"""Wavefront .mtl material resolution — companion to :mod:`obj_importer`.

The HH5 OBJ importer records ``mtllib`` and ``usemtl`` references, but
does not resolve them into real materials. This module fills that gap:

* :class:`MtlMaterialDef` — a plain-dataclass representation of a
  single MTL material.
* :func:`parse_mtl` — parse a ``.mtl`` file into
  ``{name: MtlMaterialDef}``.
* :func:`mtl_to_material` — convert an :class:`MtlMaterialDef` into an
  HH4 :class:`slappyengine.render.material.Material`, using a
  Blinn-Phong ``Ns``-to-roughness heuristic.
* :func:`resolve_mtl_references` — take an :class:`ImportResult` from
  :func:`import_obj`, walk its ``mtllib`` metadata, and return
  ``{name: Material}``.
* :func:`import_obj_with_materials` — one-shot: run
  :func:`import_obj` **and** attach real materials to the result.

The Material import is *soft* — if :mod:`slappyengine.render.material`
cannot be imported (headless test env), :func:`mtl_to_material` falls
back to a lightweight dict with the same field names, so the resolver
never crashes just because wgpu is unavailable.

MTL spec references
-------------------
* ``Ka r g b``   — ambient colour  (RGB 0..1)
* ``Kd r g b``   — diffuse colour  (RGB 0..1)
* ``Ks r g b``   — specular colour (RGB 0..1)
* ``Ke r g b``   — emissive colour (extension, common)
* ``Ns f``       — Blinn-Phong specular exponent (0..1000, higher = sharper)
* ``Ni f``       — index of refraction (parsed, kept as raw float)
* ``d f``        — dissolve (0 = fully transparent, 1 = fully opaque)
* ``Tr f``       — transparency (1 - d); some exporters emit both
* ``illum n``    — illumination model 0..10
* ``map_Kd``     — diffuse texture
* ``map_Ks``     — specular texture
* ``map_Bump`` / ``bump`` — normal map
* ``map_Ns``     — roughness / specular-exponent map
* ``map_d``      — opacity map
* ``refl``       — reflection cube map
"""
from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .import_result import ImportResult
from .obj_importer import import_obj

_LOG = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class MtlMaterialDef:
    """Parsed .mtl material.

    Colours default to sensible values so partially-populated MTL files
    (e.g. only ``Kd`` present) still produce usable materials.
    """

    name: str
    ka: tuple[float, float, float] = (0.2, 0.2, 0.2)
    kd: tuple[float, float, float] = (0.8, 0.8, 0.8)
    ks: tuple[float, float, float] = (0.0, 0.0, 0.0)
    ke: tuple[float, float, float] = (0.0, 0.0, 0.0)
    ns: float = 0.0
    ni: float = 1.0
    d: float = 1.0
    tr: float = 0.0
    illum: int = 2
    map_kd: Path | None = None
    map_ks: Path | None = None
    map_bump: Path | None = None
    map_ns: Path | None = None
    map_d: Path | None = None
    refl: Path | None = None

    # Free-form metadata bag for extra tags we don't model natively.
    extras: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _parse_rgb(parts: list[str], fallback: tuple[float, float, float]) -> tuple[float, float, float]:
    """Parse ``r g b`` (or ``r`` = grey) from an MTL token list.

    MTL also allows ``spectral`` and ``xyz`` forms; we ignore those and
    return the fallback so the parser keeps going instead of raising.
    """
    if not parts:
        return fallback
    if parts[0] in ("spectral", "xyz"):
        return fallback
    try:
        vals = [float(p) for p in parts[:3]]
    except ValueError:
        return fallback
    if len(vals) == 1:
        return (vals[0], vals[0], vals[0])
    if len(vals) == 2:
        return (vals[0], vals[1], 0.0)
    return (vals[0], vals[1], vals[2])


def _parse_texture_token(parts: list[str], base_dir: Path) -> Path | None:
    """Parse a ``map_*`` token — strip options, return an absolute path.

    Options like ``-o u v w``, ``-s u v w``, ``-mm base gain``,
    ``-clamp on`` prefix the filename in MTL. We skip them and take
    the last token as the filename.
    """
    if not parts:
        return None
    # Skip -flag / value pairs. Everything without a leading dash is
    # potentially the filename; the actual filename is always the *last*
    # non-option token in practice.
    i = 0
    filename: str | None = None
    while i < len(parts):
        tok = parts[i]
        if tok.startswith("-"):
            # -clamp on, -blendu on, -mm base gain, -o u v w, -s u v w, -t u v w
            # Consume the flag then advance past its arguments.
            flag = tok
            i += 1
            # Heuristic: consume up to 3 following non-flag tokens for
            # numeric options; consume 1 for on/off options.
            if flag in ("-o", "-s", "-t"):
                # up to 3 floats
                consumed = 0
                while i < len(parts) and consumed < 3:
                    try:
                        float(parts[i])
                        i += 1
                        consumed += 1
                    except ValueError:
                        break
            elif flag in ("-mm",):
                consumed = 0
                while i < len(parts) and consumed < 2:
                    try:
                        float(parts[i])
                        i += 1
                        consumed += 1
                    except ValueError:
                        break
            elif flag in ("-clamp", "-blendu", "-blendv", "-cc"):
                if i < len(parts) and parts[i] in ("on", "off"):
                    i += 1
            elif flag in ("-imfchan", "-texres", "-bm"):
                if i < len(parts):
                    i += 1
            # else: unknown flag — skip only itself.
            continue
        filename = tok
        i += 1
    if filename is None:
        return None
    p = Path(filename)
    if not p.is_absolute():
        p = (base_dir / p).resolve()
    return p


def parse_mtl(path: str | Path) -> dict[str, MtlMaterialDef]:
    """Parse a Wavefront .mtl file.

    Returns
    -------
    dict[str, MtlMaterialDef]
        Empty if the file is empty or has no ``newmtl`` blocks.
        Malformed lines emit warnings and are skipped; a partial dict is
        still returned so downstream code can proceed.
    """
    path = Path(path)
    if not path.exists():
        warnings.warn(f"mtl file not found: {path}", stacklevel=2)
        return {}

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        warnings.warn(f"could not read mtl {path}: {e}", stacklevel=2)
        return {}

    base_dir = path.parent
    materials: dict[str, MtlMaterialDef] = {}
    current: MtlMaterialDef | None = None

    for line_no, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        tag = parts[0].lower()
        args = parts[1:]

        if tag == "newmtl":
            if not args:
                warnings.warn(
                    f"{path.name}:{line_no}: newmtl with no name",
                    stacklevel=2,
                )
                current = None
                continue
            name = args[0]
            current = MtlMaterialDef(name=name)
            materials[name] = current
            continue

        if current is None:
            # Stray property before any newmtl — record on a synthetic
            # default material so we don't lose data.
            warnings.warn(
                f"{path.name}:{line_no}: property {tag!r} before newmtl; "
                "attaching to '__default__'",
                stacklevel=2,
            )
            current = MtlMaterialDef(name="__default__")
            materials["__default__"] = current

        try:
            if tag == "ka":
                current.ka = _parse_rgb(args, current.ka)
            elif tag == "kd":
                current.kd = _parse_rgb(args, current.kd)
            elif tag == "ks":
                current.ks = _parse_rgb(args, current.ks)
            elif tag == "ke":
                current.ke = _parse_rgb(args, current.ke)
            elif tag == "ns":
                current.ns = float(args[0]) if args else current.ns
            elif tag == "ni":
                current.ni = float(args[0]) if args else current.ni
            elif tag == "d":
                if args:
                    # `d -halo f` variant — skip the flag.
                    val_tok = args[-1] if args[0] == "-halo" else args[0]
                    current.d = float(val_tok)
                    # d and tr are two views of the same thing; keep them
                    # consistent unless tr was explicitly set later.
                    current.tr = 1.0 - current.d
            elif tag == "tr":
                current.tr = float(args[0]) if args else current.tr
                current.d = 1.0 - current.tr
            elif tag == "illum":
                current.illum = int(float(args[0])) if args else current.illum
            elif tag == "map_kd":
                current.map_kd = _parse_texture_token(args, base_dir)
            elif tag == "map_ks":
                current.map_ks = _parse_texture_token(args, base_dir)
            elif tag in ("map_bump", "bump"):
                current.map_bump = _parse_texture_token(args, base_dir)
            elif tag == "map_ns":
                current.map_ns = _parse_texture_token(args, base_dir)
            elif tag == "map_d":
                current.map_d = _parse_texture_token(args, base_dir)
            elif tag == "refl":
                current.refl = _parse_texture_token(args, base_dir)
            else:
                current.extras[tag] = " ".join(args)
        except (ValueError, IndexError) as e:
            warnings.warn(
                f"{path.name}:{line_no}: could not parse {tag!r}: {e}",
                stacklevel=2,
            )

    return materials


# ---------------------------------------------------------------------------
# Conversion — MTL → Material
# ---------------------------------------------------------------------------

def _soft_material_types() -> tuple[Any, Any]:
    """Return (Material, TextureHandle) — real classes if available, else fakes."""
    try:
        from slappyengine.render.material import (  # noqa: PLC0415
            Material,
            TextureHandle,
        )
        return Material, TextureHandle
    except Exception:  # pragma: no cover - only in stripped test env
        # Lightweight fallbacks that mirror the field names so
        # downstream code can still inspect the same attributes.
        @dataclass
        class _FakeTextureHandle:
            id: int = 0
            width: int = 0
            height: int = 0
            format: str = "rgba8unorm"
            gpu_texture: Any | None = None
            source_path: Path | None = None

        @dataclass
        class _FakeMaterial:
            name: str = "default"
            base_color: tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0)
            metallic: float = 0.0
            roughness: float = 0.5
            emissive: tuple[float, float, float] = (0.0, 0.0, 0.0)
            alpha_mode: str = "opaque"
            alpha_cutoff: float = 0.5
            base_color_texture: Any | None = None
            normal_texture: Any | None = None
            double_sided: bool = False

        return _FakeMaterial, _FakeTextureHandle


def _ns_to_roughness(ns: float) -> float:
    """Blinn-Phong specular exponent → linear roughness.

    Heuristic: roughness = clip(1 - min(ns / 900, 1), 0.05, 1.0).

    * ``ns = 0``    → roughness ≈ 1.0 (fully matte)
    * ``ns = 900``  → roughness ≈ 0.05 (mirror-ish)
    * ``ns > 900``  → clipped to 0.05 (avoids a perfectly smooth PBR
      surface, which behaves poorly with IBL).
    """
    if ns < 0:
        ns = 0.0
    r = 1.0 - min(ns / 900.0, 1.0)
    if r < 0.05:
        return 0.05
    if r > 1.0:
        return 1.0
    return r


def _make_texture_handle(TextureHandleCls: Any, path: Path | None) -> Any:
    """Wrap ``path`` in a deferred-load TextureHandle stub, or return None.

    The handle is *unresolved* — width/height/gpu_texture are 0/None
    until a later pass actually loads the file. We stash the source
    path so downstream code knows where to fetch the pixels from.
    """
    if path is None:
        return None
    handle = TextureHandleCls(
        id=0,
        width=0,
        height=0,
        format="rgba8unorm",
        gpu_texture=None,
    )
    # Attach the source path as an attribute even if the dataclass
    # doesn't declare it — HH4 TextureHandle uses default init and
    # accepts arbitrary attrs after construction.
    try:
        object.__setattr__(handle, "source_path", path)
    except AttributeError:
        pass
    return handle


def mtl_to_material(mtl_def: MtlMaterialDef) -> Any:
    """Convert a parsed :class:`MtlMaterialDef` into an HH4 ``Material``.

    Conversion rules
    ----------------
    * ``base_color = (*kd, 1 - tr)`` (RGBA, alpha from transparency).
    * ``metallic = 0.0`` — OBJ is not PBR; the classic assumption.
    * ``roughness = _ns_to_roughness(ns)``.
    * ``emissive = ka`` — Ka approximates emissive for legacy MTLs.
      If ``ke`` (extension) is non-zero we prefer it.
    * ``alpha_mode = "blend" if tr > 0 or d < 1 else "opaque"``.
    * ``alpha_cutoff = 0.5``.
    * ``map_kd`` → ``base_color_texture`` (deferred).
    * ``map_bump`` → ``normal_texture`` (deferred).
    """
    Material, TextureHandle = _soft_material_types()

    # Clip Kd to [0, 1] so the Material validator is happy.
    def _clip3(rgb: tuple[float, float, float]) -> tuple[float, float, float]:
        return (
            max(0.0, min(1.0, rgb[0])),
            max(0.0, min(1.0, rgb[1])),
            max(0.0, min(1.0, rgb[2])),
        )

    kd = _clip3(mtl_def.kd)
    alpha = max(0.0, min(1.0, 1.0 - mtl_def.tr))
    # If dissolve is explicit and non-1, honour it.
    if mtl_def.d < 1.0:
        alpha = max(0.0, min(1.0, mtl_def.d))
    base_color = (kd[0], kd[1], kd[2], alpha)

    metallic = 0.0
    roughness = _ns_to_roughness(mtl_def.ns)

    # Prefer explicit Ke if present; else fall back to Ka approximation.
    if any(v > 0.0 for v in mtl_def.ke):
        emissive = _clip3(mtl_def.ke)
    else:
        emissive = _clip3(mtl_def.ka)

    alpha_mode = "blend" if (mtl_def.tr > 0.0 or mtl_def.d < 1.0) else "opaque"

    base_color_texture = _make_texture_handle(TextureHandle, mtl_def.map_kd)
    normal_texture = _make_texture_handle(TextureHandle, mtl_def.map_bump)

    return Material(
        name=mtl_def.name,
        base_color=base_color,
        metallic=metallic,
        roughness=roughness,
        emissive=emissive,
        alpha_mode=alpha_mode,
        alpha_cutoff=0.5,
        base_color_texture=base_color_texture,
        normal_texture=normal_texture,
    )


# ---------------------------------------------------------------------------
# Resolver — walk ImportResult metadata
# ---------------------------------------------------------------------------

def _iter_mtllib_paths(obj_result: ImportResult, obj_path: Path) -> list[Path]:
    """Collect .mtl file paths referenced by an ImportResult."""
    base_dir = obj_path.parent
    refs: list[str] = []

    top = obj_result.metadata.get("mtllib")
    if isinstance(top, str) and top:
        refs.append(top)
    elif isinstance(top, (list, tuple)):
        refs.extend(str(x) for x in top if x)

    # OBJ files can carry mtllib per-material too (older exporters).
    for mat in obj_result.materials:
        if not isinstance(mat, dict):
            continue
        mref = mat.get("mtllib")
        if isinstance(mref, str) and mref and mref not in refs:
            refs.append(mref)

    resolved: list[Path] = []
    for ref in refs:
        p = Path(ref)
        if not p.is_absolute():
            p = (base_dir / p).resolve()
        if p not in resolved:
            resolved.append(p)
    return resolved


def resolve_mtl_references(
    obj_result: ImportResult,
    obj_path: str | Path,
) -> dict[str, Any]:
    """Resolve every ``mtllib`` reference in ``obj_result``.

    Parameters
    ----------
    obj_result
        Result of :func:`import_obj`.
    obj_path
        Path to the .obj file (used to resolve sibling .mtl paths).

    Returns
    -------
    dict[str, Material]
        Mapping ``material_name → Material``. Empty if the OBJ had no
        ``mtllib`` reference or the .mtl files could not be found.
    """
    obj_path = Path(obj_path)
    mtl_paths = _iter_mtllib_paths(obj_result, obj_path)
    if not mtl_paths:
        return {}

    all_defs: dict[str, MtlMaterialDef] = {}
    for mtl_path in mtl_paths:
        if not mtl_path.exists():
            warnings.warn(
                f"mtllib references missing file: {mtl_path}",
                stacklevel=2,
            )
            continue
        parsed = parse_mtl(mtl_path)
        # Later refs win on collision — matches OBJ resolution order.
        all_defs.update(parsed)

    return {name: mtl_to_material(mdef) for name, mdef in all_defs.items()}


# ---------------------------------------------------------------------------
# End-to-end helper
# ---------------------------------------------------------------------------

def import_obj_with_materials(path: str | Path) -> ImportResult:
    """:func:`import_obj` + MTL resolution in one call.

    The returned :class:`ImportResult`:

    * ``materials`` — replaced with the resolved ``Material`` instances
      (in the order they appear in the .mtl file). If no .mtl file is
      found, the original name-only entries are preserved.
    * ``metadata["materials_by_name"]`` — dict view for random access.
    * ``metadata["resolved_material_count"]`` — count of real materials
      produced.
    """
    path = Path(path)
    result = import_obj(path)

    resolved = resolve_mtl_references(result, path)
    if resolved:
        # Preserve the original mesh↔material association order by
        # emitting resolved materials in the order they were referenced
        # via `usemtl`. Fall back to insertion order for unused ones.
        used_names: list[str] = []
        seen: set[str] = set()
        for m in result.materials:
            if isinstance(m, dict):
                nm = m.get("name")
                if nm and nm not in seen and nm in resolved:
                    used_names.append(nm)
                    seen.add(nm)
        # Add any resolved names not referenced via usemtl.
        for nm in resolved:
            if nm not in seen:
                used_names.append(nm)
                seen.add(nm)

        result.materials = [resolved[nm] for nm in used_names]
        result.metadata["materials_by_name"] = resolved
        result.metadata["resolved_material_count"] = len(resolved)
    else:
        result.metadata["resolved_material_count"] = 0

    return result


__all__ = [
    "MtlMaterialDef",
    "parse_mtl",
    "mtl_to_material",
    "resolve_mtl_references",
    "import_obj_with_materials",
]
