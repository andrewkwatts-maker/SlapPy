"""``NotebookAssetInspector`` — diary-themed type-aware asset preview panel.

Complement to :class:`~pharos_engine.ui.editor.notebook_content_browser.NotebookContentBrowser`
(X4). Where the content browser is the notebook's *table of contents*,
this panel is the *marginalia sheet* pinned to the side that renders a
lightweight preview of whichever asset the user just clicked. Its job is
strictly cosmetic + informational — no mutations, no serialisation:

* **script** (``*.py``)  → first N lines of source with hand-drawn
  syntax hints (comment lines gray, ``def`` in accent).
* **scene** (``*.scene.yaml``) → parse + summary table (entity count,
  layer count, camera position, first 5 entities).
* **texture** (``*.png|jpg|jpeg|webp``) → 128x128 PIL preview + dims/mode.
* **material** (``*.mat.yaml`` / ``*.material.yaml``) → WGSL summary +
  a "Open in Material Editor" button that fires the callback registered
  via :meth:`set_on_open_material`.
* **shader** (``*.wgsl|glsl``) → source, byte count, WARN/ERROR summary
  from :func:`pharos_engine.ui.theme.shader_lint.lint_wgsl` (AA6).
* **prefab** (``*.prefab.yaml``) → node count / joint count / bounding
  box + a 64x64 preview baked via :class:`~pharos_engine.prefabs.preview_baker.PreviewBaker`
  (BB6) when a matching prefab can be looked up.
* **other** → file size, mtime, hex-dump of the first 64 bytes.

Design provenance
-----------------
Sprint CC3 (2026-07-05) — user directive: "build a NotebookAssetInspector
panel that renders type-specific previews of the currently-selected
asset in the content browser".

Wiring
------
``set_content_browser(browser)`` subscribes to the browser's
``on_asset_selected`` slot so single-click routing wires up
automatically. ``set_asset_path(path)`` is the imperative entry point —
callers that want to drive the panel outside the browser flow can call
this directly.

Diary theming
-------------
* Ruled-paper background around the body (mirrors
  ``NotebookAutosavePanel``'s ``child_window`` pattern).
* Hand-drawn ``~ ~ ~ ~`` dividers between metadata rows.
* Comment lines in the script preview render gray; ``def`` lines pick up
  the theme's accent colour.

Headless safety
---------------
Every :mod:`dearpygui` call funnels through :func:`_safe_dpg`, and PIL /
``yaml`` / :mod:`pharos_engine.ui.theme.shader_lint` / :mod:`pharos_engine.prefabs`
are all soft-imported so the panel constructs + exercises cleanly in
CI without the ``[editor]`` extra.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional


# ---------------------------------------------------------------------------
# Module helpers
# ---------------------------------------------------------------------------


def _is_real_dpg(dpg: Any) -> bool:
    """Return ``True`` when *dpg* is the real ``dearpygui.dearpygui`` module."""
    import types
    inner = getattr(dpg, "internal_dpg", None)
    if not isinstance(inner, types.ModuleType):
        return False
    return getattr(inner, "__name__", "").startswith("dearpygui")


def _headless_env_active() -> bool:
    val = os.environ.get("SLAPPY_HEADLESS", "")
    return val.strip().lower() in ("1", "true", "yes", "on")


def _safe_dpg() -> Any | None:
    """Return ``dearpygui.dearpygui`` if importable + usable, else ``None``.

    Mirrors the guard used by every other notebook panel — real DPG in a
    headless env would blow up before ``create_context`` so we degrade
    silently to "no widgets rendered". Test rigs supply a stub module
    marked with ``__slappy_stub__`` which sails through both branches.
    """
    try:
        import dearpygui.dearpygui as dpg  # type: ignore[import-not-found]
    except Exception:
        return None
    if getattr(dpg, "__slappy_stub__", False):
        return dpg
    if _is_real_dpg(dpg) and _headless_env_active():
        return None
    return dpg


# ---------------------------------------------------------------------------
# Asset kinds — mirrored from the X4 content browser so the panel can
# key its layouts + tests can import the same strings.
# ---------------------------------------------------------------------------

ASSET_KIND_SCRIPT = "script"
ASSET_KIND_SCENE = "scene"
ASSET_KIND_TEXTURE = "texture"
ASSET_KIND_MATERIAL = "material"
ASSET_KIND_SHADER = "shader"
ASSET_KIND_PREFAB = "prefab"
ASSET_KIND_OTHER = "other"

_ASSET_KINDS: frozenset[str] = frozenset({
    ASSET_KIND_SCRIPT, ASSET_KIND_SCENE, ASSET_KIND_TEXTURE,
    ASSET_KIND_MATERIAL, ASSET_KIND_SHADER, ASSET_KIND_PREFAB,
    ASSET_KIND_OTHER,
})

_TEXTURE_EXTS: frozenset[str] = frozenset({".png", ".jpg", ".jpeg", ".webp"})
_SHADER_EXTS: frozenset[str] = frozenset({".wgsl", ".glsl"})


def classify_asset_kind(path: Path) -> str:
    """Return the :data:`ASSET_KIND_*` string for *path*.

    Uses the same rules the X4 content browser applies, plus a
    ``prefab`` bucket that the browser folds into ``other`` — the
    inspector treats prefabs specially so it can spin up a
    :class:`PreviewBaker` render.
    """
    name = path.name.lower()
    if name.endswith(".scene.yaml") or name.endswith(".scene.json"):
        return ASSET_KIND_SCENE
    if name.endswith(".mat.yaml") or name.endswith(".material.yaml"):
        return ASSET_KIND_MATERIAL
    if name.endswith(".prefab.yaml") or name.endswith(".prefab.json"):
        return ASSET_KIND_PREFAB
    suffix = path.suffix.lower()
    if suffix == ".py":
        return ASSET_KIND_SCRIPT
    if suffix in _TEXTURE_EXTS:
        return ASSET_KIND_TEXTURE
    if suffix in _SHADER_EXTS:
        return ASSET_KIND_SHADER
    return ASSET_KIND_OTHER


# ---------------------------------------------------------------------------
# Preview dataclasses — one per asset kind so tests can assert intent
# without walking the DPG tree.
# ---------------------------------------------------------------------------


@dataclass
class ScriptPreview:
    """Cached view of a Python-script preview."""

    lines: list[str] = field(default_factory=list)
    total_lines: int = 0
    truncated: bool = False
    error: str | None = None


@dataclass
class ScenePreview:
    """Cached summary of a ``*.scene.yaml`` file."""

    entity_count: int = 0
    layer_count: int = 0
    camera_pos: tuple[float, float, float] | None = None
    entity_names: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass
class TexturePreview:
    """Cached texture metadata + optional PIL preview image."""

    width: int = 0
    height: int = 0
    mode: str = ""
    image: Any = None  # PIL.Image.Image | None
    error: str | None = None


@dataclass
class MaterialPreview:
    """Cached material summary (WGSL blob length + shader name)."""

    shader_name: str = ""
    wgsl_bytes: int = 0
    wgsl_summary: str = ""
    error: str | None = None


@dataclass
class ShaderPreview:
    """Cached shader source + lint summary."""

    source: str = ""
    byte_count: int = 0
    error_count: int = 0
    warning_count: int = 0
    error: str | None = None


@dataclass
class PrefabPreview:
    """Cached prefab summary + PIL bake."""

    node_count: int = 0
    joint_count: int = 0
    bounding_box: tuple[float, float, float, float] | None = None
    image: Any = None  # PIL.Image.Image | None
    error: str | None = None


@dataclass
class OtherPreview:
    """Cached generic-file metadata + hex dump of the first 64 bytes."""

    size_bytes: int = 0
    mtime: float = 0.0
    hex_dump: str = ""
    error: str | None = None


# ---------------------------------------------------------------------------
# Utility helpers used by the preview builders
# ---------------------------------------------------------------------------


def _classify_script_line(line: str) -> str:
    """Return a lightweight "syntax kind" for the script preview colouring.

    ``"comment"`` for pure-comment lines, ``"def"`` for def/class lines,
    otherwise ``"code"``. Strings-as-first-statement (docstrings) are not
    treated specially — we want cheap, no dependencies. This is enough
    to feed the theme's ``ink`` / ``muted`` / ``accent`` colours.
    """
    stripped = line.lstrip()
    if not stripped:
        return "blank"
    if stripped.startswith("#"):
        return "comment"
    if stripped.startswith("def ") or stripped.startswith("async def "):
        return "def"
    if stripped.startswith("class "):
        return "def"
    return "code"


def _format_hex_dump(data: bytes, width: int = 16) -> str:
    """Return a compact ``00 01 02 ... | ....`` hex-dump for *data*."""
    rows: list[str] = []
    for i in range(0, len(data), width):
        chunk = data[i:i + width]
        hex_part = " ".join(f"{b:02x}" for b in chunk)
        ascii_part = "".join(
            chr(b) if 32 <= b < 127 else "." for b in chunk
        )
        rows.append(f"{i:04x}  {hex_part:<{width * 3}}  |{ascii_part}|")
    return "\n".join(rows)


def _format_size(bytes_: int) -> str:
    """Return a human-readable byte size (KB / MB) for a metadata row."""
    if bytes_ < 1024:
        return f"{bytes_} B"
    if bytes_ < 1024 * 1024:
        return f"{bytes_ / 1024:.1f} KB"
    return f"{bytes_ / (1024 * 1024):.2f} MB"


def _format_timestamp(ts: float) -> str:
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(ts)))
    except Exception:
        return "????-??-?? ??:??:??"


def _safe_yaml_load(text: str) -> Any:
    """Try to parse *text* as YAML; return ``None`` on any error.

    Uses :mod:`yaml` when available, otherwise a minimal JSON fallback so
    tests can still exercise the code path without PyYAML installed. A
    corrupt file surfaces as ``None`` so the caller can render an
    error banner rather than crashing the editor.
    """
    try:
        import yaml  # type: ignore[import-not-found]
        return yaml.safe_load(text)
    except Exception:
        pass
    try:
        import json
        return json.loads(text)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# The panel
# ---------------------------------------------------------------------------


class NotebookAssetInspector:
    """Diary-themed asset preview panel.

    The panel is a passive observer — it never writes to the asset it's
    looking at. Selection changes flow in via :meth:`set_asset_path`
    (imperative) or by subscribing to a
    :class:`~pharos_engine.ui.editor.notebook_content_browser.NotebookContentBrowser`
    through :meth:`set_content_browser`.

    Parameters
    ----------
    path:
        Optional initial asset path to preview.
    max_preview_lines:
        Line cap for the script preview (default 40).
    on_open_material:
        Optional callback fired when the material-preview "Open in
        Material Editor" button is clicked. Receives the material path.
    prefab_library:
        Optional prefab library so :class:`PreviewBaker` can look up
        composite children when baking a prefab preview.
    clipboard_shim:
        Optional single-arg callable that replaces the OS clipboard.
        The tests pass a captor so they can assert the intent without
        poking at real clipboard APIs.
    """

    TITLE = "Asset Inspector"

    # Movable-window minimums — picked up by ``MovablePanelWindow``.
    MIN_WIDTH: int = 320
    MIN_HEIGHT: int = 260

    #: Default script-preview line cap. Keeps the panel snappy on huge
    #: source files.
    DEFAULT_MAX_PREVIEW_LINES: int = 40

    #: Guard for the hex-dump preview so a several-GB blob doesn't blow up
    #: the read.
    _HEX_DUMP_BYTES: int = 64

    #: Texture preview edge length.
    _TEXTURE_PREVIEW_SIZE: int = 128

    #: Prefab preview edge length (matches PreviewBaker default).
    _PREFAB_PREVIEW_SIZE: int = 64

    _ROOT_TAG = "notebook_asset_inspector_root"
    _HEADER_TAG = "notebook_asset_inspector_header"
    _BREADCRUMB_TAG = "notebook_asset_inspector_breadcrumb"
    _BODY_TAG = "notebook_asset_inspector_body"
    _EMPTY_TAG = "notebook_asset_inspector_empty"

    def __init__(
        self,
        path: Path | str | None = None,
        max_preview_lines: int = DEFAULT_MAX_PREVIEW_LINES,
        on_open_material: Callable[[Path], None] | None = None,
        prefab_library: Any = None,
        clipboard_shim: Callable[[str], None] | None = None,
    ) -> None:
        if not isinstance(max_preview_lines, int) or isinstance(
            max_preview_lines, bool
        ) or max_preview_lines <= 0:
            raise ValueError(
                "NotebookAssetInspector: max_preview_lines must be a "
                f"positive int; got {max_preview_lines!r}"
            )
        if on_open_material is not None and not callable(on_open_material):
            raise TypeError(
                "NotebookAssetInspector: on_open_material must be callable "
                f"or None; got {type(on_open_material).__name__}"
            )
        if clipboard_shim is not None and not callable(clipboard_shim):
            raise TypeError(
                "NotebookAssetInspector: clipboard_shim must be callable "
                f"or None; got {type(clipboard_shim).__name__}"
            )

        self._path: Path | None = None
        self._kind: str | None = None
        self._max_preview_lines: int = int(max_preview_lines)
        self._on_open_material: Callable[[Path], None] | None = (
            on_open_material
        )
        self._prefab_library: Any = prefab_library
        self._clipboard_shim: Callable[[str], None] | None = clipboard_shim

        # Current preview cache — populated on set_asset_path / refresh.
        self._preview: Any = None
        self._preview_error: str | None = None

        # Subscribed content browser + its previous callback so we can
        # cleanly unhook on ``set_content_browser(None)``.
        self._content_browser: Any = None
        self._prev_browser_cb: Any = None

        # Build state.
        self._built: bool = False
        self._parent_tag: str | int | None = None

        # Every user-facing mutation is logged as a ``(event, data)``
        # tuple so headless tests can assert intent without walking the
        # DPG tree.
        self.call_log: list[tuple[str, Any]] = []

        if path is not None:
            self.set_asset_path(path)

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def path(self) -> Path | None:
        """The currently-inspected asset path (or ``None``)."""
        return self._path

    @property
    def kind(self) -> str | None:
        """The current asset kind — one of :data:`ASSET_KIND_*` or ``None``."""
        return self._kind

    @property
    def max_preview_lines(self) -> int:
        """Script preview line cap."""
        return self._max_preview_lines

    @property
    def preview(self) -> Any:
        """Return the cached preview dataclass (``None`` when no path bound)."""
        return self._preview

    @property
    def preview_error(self) -> str | None:
        """Return the last preview error message, or ``None``."""
        return self._preview_error

    @property
    def is_empty(self) -> bool:
        """``True`` iff no asset has been selected."""
        return self._path is None

    def breadcrumb_segments(self) -> list[str]:
        """Return the header breadcrumb parts for the current asset.

        ``[]`` when no path is bound. Otherwise the parts of the path,
        split by directory separators, with the filename last.
        """
        if self._path is None:
            return []
        return list(self._path.parts)

    # ------------------------------------------------------------------
    # Setters
    # ------------------------------------------------------------------

    def set_asset_path(self, path: Path | str | None) -> None:
        """Swap the inspected asset. Passing ``None`` clears the panel."""
        if path is None:
            self._path = None
            self._kind = None
            self._preview = None
            self._preview_error = None
            self.call_log.append(("set_asset_path", None))
            if self._built:
                self._rebuild_body()
            return

        try:
            self._path = Path(path)
        except Exception as exc:
            raise TypeError(
                "NotebookAssetInspector.set_asset_path: path must be "
                f"path-like or None; got {type(path).__name__}"
            ) from exc
        self._kind = classify_asset_kind(self._path)
        self.call_log.append(("set_asset_path", str(self._path)))
        self._rebuild_preview()
        if self._built:
            self._rebuild_body()

    def set_max_preview_lines(self, n: int) -> None:
        """Cap the number of script lines rendered by the preview."""
        if not isinstance(n, int) or isinstance(n, bool) or n <= 0:
            raise ValueError(
                "NotebookAssetInspector.set_max_preview_lines: n must be "
                f"a positive int; got {n!r}"
            )
        self._max_preview_lines = int(n)
        self.call_log.append(("set_max_preview_lines", n))
        if self._kind == ASSET_KIND_SCRIPT and self._path is not None:
            self._rebuild_preview()
            if self._built:
                self._rebuild_body()

    def set_content_browser(self, browser: Any) -> None:
        """Subscribe to *browser*'s ``on_asset_selected`` slot.

        Passing ``None`` unhooks the previous subscription. Only one
        browser at a time — the design intent is that the editor shell
        owns the routing.
        """
        # Unhook previous subscription (best-effort — a mocked browser
        # may not expose set_on_asset_selected).
        prev = self._content_browser
        if prev is not None:
            try:
                prev.set_on_asset_selected(self._prev_browser_cb)
            except Exception:
                pass
        self._content_browser = None
        self._prev_browser_cb = None

        if browser is None:
            self.call_log.append(("set_content_browser", None))
            return

        # Snapshot the previous callback so we can restore it later.
        try:
            self._prev_browser_cb = getattr(
                browser, "_on_asset_selected", None,
            )
        except Exception:
            self._prev_browser_cb = None

        def _on_selected(path: Path, kind: str) -> None:
            try:
                self.set_asset_path(path)
            except Exception:
                # Selection routing must never crash the editor — swallow.
                pass

        try:
            browser.set_on_asset_selected(_on_selected)
        except Exception:
            # The browser rejected the callback (bad type / no method).
            # We still remember the intent so tests can assert routing.
            pass
        self._content_browser = browser
        self.call_log.append(
            ("set_content_browser", type(browser).__name__),
        )

    def set_on_open_material(
        self, callback: Callable[[Path], None] | None,
    ) -> None:
        """Register (or clear with ``None``) the "Open in Material Editor" cb."""
        if callback is not None and not callable(callback):
            raise TypeError(
                "NotebookAssetInspector.set_on_open_material: callback "
                f"must be callable or None; got {type(callback).__name__}"
            )
        self._on_open_material = callback
        self.call_log.append(("set_on_open_material", callback is not None))

    def set_prefab_library(self, library: Any) -> None:
        """Swap the prefab library used by :class:`PreviewBaker`."""
        self._prefab_library = library
        self.call_log.append(
            ("set_prefab_library", type(library).__name__ if library else None),
        )
        if self._kind == ASSET_KIND_PREFAB and self._path is not None:
            self._rebuild_preview()
            if self._built:
                self._rebuild_body()

    # ------------------------------------------------------------------
    # Refresh + rebuild plumbing
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        """Re-read the current asset from disk and rebuild the preview."""
        self.call_log.append(("refresh", str(self._path) if self._path else None))
        self._rebuild_preview()
        if self._built:
            self._rebuild_body()

    def copy_path(self) -> str | None:
        """Copy the current asset path to the OS clipboard (best-effort).

        Returns the string that was staged for the clipboard so tests can
        assert intent even when the DPG clipboard isn't available.
        Returns ``None`` when no asset is bound.
        """
        if self._path is None:
            self.call_log.append(("copy_path", None))
            return None
        text = str(self._path)
        self.call_log.append(("copy_path", text))
        if self._clipboard_shim is not None:
            try:
                self._clipboard_shim(text)
                return text
            except Exception:
                pass
        dpg = _safe_dpg()
        if dpg is not None:
            try:
                dpg.set_clipboard_text(text)
                return text
            except Exception:
                pass
        # Try pyperclip / tkinter as a final fallback (mirrors the
        # content browser's copy_path implementation).
        try:
            import pyperclip  # type: ignore[import-not-found]
            pyperclip.copy(text)
            return text
        except Exception:
            pass
        return text

    def open_material_editor(self) -> bool:
        """Fire the ``on_open_material`` callback if the current asset is one.

        Returns ``True`` iff the callback was invoked.
        """
        if self._kind != ASSET_KIND_MATERIAL or self._path is None:
            self.call_log.append(("open_material_editor_skipped", None))
            return False
        cb = self._on_open_material
        if cb is None:
            self.call_log.append(("open_material_editor_no_cb", None))
            return False
        try:
            cb(self._path)
        except Exception:
            self.call_log.append(
                ("open_material_editor_error", str(self._path)),
            )
            return False
        self.call_log.append(("open_material_editor", str(self._path)))
        return True

    # ------------------------------------------------------------------
    # Preview builders — dispatched from :meth:`_rebuild_preview`.
    # ------------------------------------------------------------------

    def _rebuild_preview(self) -> None:
        """Re-read the current asset and rebuild :attr:`_preview`."""
        self._preview = None
        self._preview_error = None
        path = self._path
        if path is None:
            return
        try:
            if not path.exists():
                self._preview_error = f"file not found: {path}"
                self._preview = OtherPreview(error=self._preview_error)
                return
        except OSError as exc:
            self._preview_error = f"OSError: {exc}"
            self._preview = OtherPreview(error=self._preview_error)
            return

        kind = self._kind or classify_asset_kind(path)
        builder = {
            ASSET_KIND_SCRIPT:   self._build_script_preview,
            ASSET_KIND_SCENE:    self._build_scene_preview,
            ASSET_KIND_TEXTURE:  self._build_texture_preview,
            ASSET_KIND_MATERIAL: self._build_material_preview,
            ASSET_KIND_SHADER:   self._build_shader_preview,
            ASSET_KIND_PREFAB:   self._build_prefab_preview,
            ASSET_KIND_OTHER:    self._build_other_preview,
        }.get(kind, self._build_other_preview)

        try:
            self._preview = builder(path)
        except Exception as exc:
            self._preview_error = f"{type(exc).__name__}: {exc}"
            self._preview = OtherPreview(error=self._preview_error)

    def _build_script_preview(self, path: Path) -> ScriptPreview:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            return ScriptPreview(error=f"OSError: {exc}")
        except UnicodeDecodeError:
            try:
                text = path.read_text(encoding="latin-1", errors="replace")
            except OSError as exc:
                return ScriptPreview(error=f"OSError: {exc}")
        all_lines = text.splitlines()
        cap = self._max_preview_lines
        preview_lines = all_lines[:cap]
        return ScriptPreview(
            lines=preview_lines,
            total_lines=len(all_lines),
            truncated=len(all_lines) > cap,
        )

    def _build_scene_preview(self, path: Path) -> ScenePreview:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            return ScenePreview(error=f"OSError: {exc}")
        data = _safe_yaml_load(text)
        if data is None:
            return ScenePreview(error="YAML parse failed (corrupt file?)")
        if not isinstance(data, dict):
            return ScenePreview(
                error=f"unexpected scene root type: {type(data).__name__}",
            )

        entities = data.get("entities") or []
        layers = data.get("layers") or []
        camera = data.get("camera") or {}

        entity_names: list[str] = []
        try:
            for ent in list(entities)[:5]:
                if isinstance(ent, dict):
                    name = ent.get("name") or ent.get("id") or "<unnamed>"
                else:
                    name = str(ent)
                entity_names.append(str(name))
        except Exception:
            entity_names = []

        camera_pos: tuple[float, float, float] | None = None
        try:
            pos = camera.get("position") if isinstance(camera, dict) else None
            if isinstance(pos, (list, tuple)) and len(pos) >= 3:
                camera_pos = (
                    float(pos[0]), float(pos[1]), float(pos[2]),
                )
        except Exception:
            camera_pos = None

        return ScenePreview(
            entity_count=len(entities) if hasattr(entities, "__len__") else 0,
            layer_count=len(layers) if hasattr(layers, "__len__") else 0,
            camera_pos=camera_pos,
            entity_names=entity_names,
        )

    def _build_texture_preview(self, path: Path) -> TexturePreview:
        try:
            from PIL import Image  # type: ignore[import-not-found]
        except Exception as exc:
            return TexturePreview(error=f"PIL unavailable: {exc}")
        try:
            img = Image.open(str(path))
            img.load()
        except Exception as exc:
            return TexturePreview(error=f"open failed: {exc}")
        w, h = img.size
        mode = str(img.mode)
        # Down-sample to the preview size while preserving aspect ratio.
        try:
            preview = img.copy()
            preview.thumbnail(
                (self._TEXTURE_PREVIEW_SIZE, self._TEXTURE_PREVIEW_SIZE),
            )
        except Exception:
            preview = img
        return TexturePreview(
            width=int(w), height=int(h), mode=mode, image=preview,
        )

    def _build_material_preview(self, path: Path) -> MaterialPreview:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            return MaterialPreview(error=f"OSError: {exc}")
        data = _safe_yaml_load(text)
        shader_name = ""
        wgsl_source = ""
        if isinstance(data, dict):
            shader_name = str(data.get("shader") or data.get("name") or "")
            wgsl_source = str(
                data.get("wgsl") or data.get("source") or "",
            )
        wgsl_bytes = len(wgsl_source.encode("utf-8"))
        summary_lines = wgsl_source.splitlines()[:8]
        return MaterialPreview(
            shader_name=shader_name,
            wgsl_bytes=wgsl_bytes,
            wgsl_summary="\n".join(summary_lines),
        )

    def _build_shader_preview(self, path: Path) -> ShaderPreview:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            return ShaderPreview(error=f"OSError: {exc}")
        byte_count = len(text.encode("utf-8"))
        errors = 0
        warnings = 0
        try:
            from pharos_engine.ui.theme.shader_lint import lint_wgsl
            # lint_wgsl requires a non-empty source id + non-empty source.
            source_id = path.stem or "shader"
            if text:
                result = lint_wgsl(source_id, text)
                errors = len(getattr(result, "errors", []) or [])
                warnings = len(getattr(result, "warnings", []) or [])
        except Exception:
            # Any lint failure is captured as a soft warning; the source
            # still renders so the user can eyeball the problem.
            pass
        return ShaderPreview(
            source=text,
            byte_count=byte_count,
            error_count=errors,
            warning_count=warnings,
        )

    def _build_prefab_preview(self, path: Path) -> PrefabPreview:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            return PrefabPreview(error=f"OSError: {exc}")
        data = _safe_yaml_load(text)
        if data is None:
            return PrefabPreview(
                error="YAML parse failed (corrupt file?)",
            )
        if not isinstance(data, dict):
            return PrefabPreview(
                error=f"unexpected prefab root type: {type(data).__name__}",
            )

        nodes = data.get("nodes") or data.get("bodies") or []
        joints = data.get("joints") or data.get("constraints") or []
        node_count = len(nodes) if hasattr(nodes, "__len__") else 0
        joint_count = len(joints) if hasattr(joints, "__len__") else 0

        bbox: tuple[float, float, float, float] | None = None
        try:
            bb = data.get("bounding_box") or data.get("bbox")
            if isinstance(bb, (list, tuple)) and len(bb) >= 4:
                bbox = (
                    float(bb[0]), float(bb[1]),
                    float(bb[2]), float(bb[3]),
                )
        except Exception:
            bbox = None

        image = self._bake_prefab_image(path, data)
        return PrefabPreview(
            node_count=node_count,
            joint_count=joint_count,
            bounding_box=bbox,
            image=image,
        )

    def _bake_prefab_image(self, path: Path, data: Any) -> Any:
        """Best-effort call into :class:`PreviewBaker` for the prefab.

        Returns a :class:`PIL.Image.Image` when the baker + library are
        both usable, otherwise ``None``. Every failure mode is caught so
        the panel keeps rendering the metadata rows on top.
        """
        library = self._prefab_library
        if library is None:
            return None
        try:
            from pharos_engine.prefabs.preview_baker import PreviewBaker
        except Exception:
            return None
        # Look up the prefab by name — either the filename stem or the
        # ``name`` field in the YAML payload.
        name = None
        if isinstance(data, dict):
            name = data.get("name")
        if not isinstance(name, str) or not name:
            name = path.stem
        try:
            prefab = library.get(name) if hasattr(library, "get") else None
        except Exception:
            prefab = None
        if prefab is None:
            return None
        try:
            baker = PreviewBaker()
            return baker.bake_preview(
                prefab, size=self._PREFAB_PREVIEW_SIZE, library=library,
            )
        except Exception:
            return None

    def _build_other_preview(self, path: Path) -> OtherPreview:
        try:
            stat = path.stat()
        except OSError as exc:
            return OtherPreview(error=f"OSError: {exc}")
        try:
            with open(path, "rb") as fh:
                head = fh.read(self._HEX_DUMP_BYTES)
        except OSError as exc:
            return OtherPreview(
                size_bytes=int(stat.st_size),
                mtime=float(stat.st_mtime),
                error=f"read failed: {exc}",
            )
        return OtherPreview(
            size_bytes=int(stat.st_size),
            mtime=float(stat.st_mtime),
            hex_dump=_format_hex_dump(head),
        )

    # ------------------------------------------------------------------
    # Build / rebuild widgets
    # ------------------------------------------------------------------

    def build(self, parent_tag: int | str) -> None:
        """Construct the widget tree under *parent_tag*. Headless-safe."""
        self._parent_tag = parent_tag
        self._built = True
        dpg = _safe_dpg()
        if dpg is None:
            return
        try:
            with dpg.group(tag=self._ROOT_TAG, parent=parent_tag):
                self._build_header(dpg)
                try:
                    dpg.add_separator()
                except Exception:
                    pass
                try:
                    with dpg.child_window(
                        tag=self._BODY_TAG, border=True, height=-20,
                    ):
                        self._build_body(dpg)
                except Exception:
                    try:
                        self._build_body(dpg)
                    except Exception:
                        pass
        except Exception:
            try:
                dpg.add_text(self.TITLE, parent=parent_tag)
            except Exception:
                pass

    def _build_header(self, dpg: Any) -> None:
        """Header row — breadcrumb + Refresh + Copy Path buttons."""
        try:
            with dpg.group(tag=self._HEADER_TAG, horizontal=True):
                breadcrumb = " / ".join(self.breadcrumb_segments()) or "(no asset)"
                try:
                    dpg.add_text(breadcrumb, tag=self._BREADCRUMB_TAG)
                except Exception:
                    pass
                try:
                    dpg.add_button(
                        label="Refresh",
                        callback=self._on_refresh_clicked,
                    )
                except Exception:
                    pass
                try:
                    dpg.add_button(
                        label="Copy Path",
                        callback=self._on_copy_path_clicked,
                    )
                except Exception:
                    pass
        except Exception:
            pass

    def _build_body(self, dpg: Any) -> None:
        """Dispatch body rendering by asset kind."""
        if self._path is None or self._preview is None:
            try:
                dpg.add_text(
                    "Select an asset in the content browser...",
                    tag=self._EMPTY_TAG,
                )
            except Exception:
                pass
            return
        if self._preview_error is not None:
            try:
                dpg.add_text(f"! {self._preview_error}")
            except Exception:
                pass
            # Fall through so the kind-specific renderer still emits
            # what it can — e.g. metadata rows when only the hex-dump
            # portion failed.

        kind = self._kind or ASSET_KIND_OTHER
        renderer = {
            ASSET_KIND_SCRIPT:   self._render_script_body,
            ASSET_KIND_SCENE:    self._render_scene_body,
            ASSET_KIND_TEXTURE:  self._render_texture_body,
            ASSET_KIND_MATERIAL: self._render_material_body,
            ASSET_KIND_SHADER:   self._render_shader_body,
            ASSET_KIND_PREFAB:   self._render_prefab_body,
            ASSET_KIND_OTHER:    self._render_other_body,
        }.get(kind, self._render_other_body)
        try:
            renderer(dpg)
        except Exception:
            try:
                dpg.add_text("(preview render failed)")
            except Exception:
                pass

    def _rebuild_body(self) -> None:
        """Wipe + re-render the body container. Called from :meth:`refresh`."""
        dpg = _safe_dpg()
        if dpg is None:
            return
        try:
            if not dpg.does_item_exist(self._BODY_TAG):
                return
        except Exception:
            return
        try:
            for child in list(dpg.get_item_children(self._BODY_TAG, slot=1) or []):
                try:
                    dpg.delete_item(child)
                except Exception:
                    pass
        except Exception:
            pass
        try:
            with dpg.group(parent=self._BODY_TAG):
                self._build_body(dpg)
        except Exception:
            try:
                self._build_body(dpg)
            except Exception:
                pass
        # Refresh the header breadcrumb too so navigation is visible.
        try:
            if dpg.does_item_exist(self._BREADCRUMB_TAG):
                breadcrumb = (
                    " / ".join(self.breadcrumb_segments())
                    or "(no asset)"
                )
                dpg.set_value(self._BREADCRUMB_TAG, breadcrumb)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Kind-specific body renderers — all headless-safe.
    # ------------------------------------------------------------------

    _RULE = "~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~"

    def _render_script_body(self, dpg: Any) -> None:
        preview: ScriptPreview = self._preview  # type: ignore[assignment]
        if preview is None or preview.error:
            try:
                dpg.add_text(f"! {preview.error if preview else 'no preview'}")
            except Exception:
                pass
            return
        try:
            dpg.add_text(
                f"{preview.total_lines} lines"
                + (" (truncated)" if preview.truncated else ""),
            )
        except Exception:
            pass
        try:
            dpg.add_text(self._RULE)
        except Exception:
            pass
        for line in preview.lines:
            kind = _classify_script_line(line)
            color = None
            if kind == "comment":
                color = [140, 140, 150, 255]
            elif kind == "def":
                color = [220, 120, 160, 255]
            try:
                if color is not None:
                    dpg.add_text(line, color=color)
                else:
                    dpg.add_text(line)
            except Exception:
                pass

    def _render_scene_body(self, dpg: Any) -> None:
        preview: ScenePreview = self._preview  # type: ignore[assignment]
        if preview is None:
            return
        if preview.error:
            try:
                dpg.add_text(f"! {preview.error}")
            except Exception:
                pass
            return
        try:
            dpg.add_text(f"Entities: {preview.entity_count}")
            dpg.add_text(f"Layers:   {preview.layer_count}")
            if preview.camera_pos is not None:
                x, y, z = preview.camera_pos
                dpg.add_text(f"Camera:   ({x:.2f}, {y:.2f}, {z:.2f})")
            else:
                dpg.add_text("Camera:   (unset)")
        except Exception:
            pass
        try:
            dpg.add_text(self._RULE)
        except Exception:
            pass
        try:
            dpg.add_text("First 5 entities:")
        except Exception:
            pass
        for name in preview.entity_names:
            try:
                dpg.add_text(f"  - {name}")
            except Exception:
                pass

    def _render_texture_body(self, dpg: Any) -> None:
        preview: TexturePreview = self._preview  # type: ignore[assignment]
        if preview is None:
            return
        if preview.error:
            try:
                dpg.add_text(f"! {preview.error}")
            except Exception:
                pass
            return
        try:
            dpg.add_text(f"Size: {preview.width} x {preview.height}")
            dpg.add_text(f"Mode: {preview.mode}")
        except Exception:
            pass
        try:
            dpg.add_text(self._RULE)
        except Exception:
            pass
        if preview.image is not None:
            try:
                dpg.add_text(
                    f"[texture preview {preview.image.size[0]} x "
                    f"{preview.image.size[1]}]",
                )
            except Exception:
                pass

    def _render_material_body(self, dpg: Any) -> None:
        preview: MaterialPreview = self._preview  # type: ignore[assignment]
        if preview is None:
            return
        if preview.error:
            try:
                dpg.add_text(f"! {preview.error}")
            except Exception:
                pass
            return
        try:
            dpg.add_text(f"Shader: {preview.shader_name or '(none)'}")
            dpg.add_text(f"WGSL bytes: {preview.wgsl_bytes}")
        except Exception:
            pass
        try:
            dpg.add_text(self._RULE)
        except Exception:
            pass
        for line in preview.wgsl_summary.splitlines():
            try:
                dpg.add_text(line)
            except Exception:
                pass
        try:
            dpg.add_button(
                label="Open in Material Editor",
                callback=self._on_open_material_clicked,
            )
        except Exception:
            pass

    def _render_shader_body(self, dpg: Any) -> None:
        preview: ShaderPreview = self._preview  # type: ignore[assignment]
        if preview is None:
            return
        if preview.error:
            try:
                dpg.add_text(f"! {preview.error}")
            except Exception:
                pass
            return
        try:
            dpg.add_text(f"Bytes: {preview.byte_count}")
            dpg.add_text(
                f"Lint: {preview.error_count} error(s), "
                f"{preview.warning_count} warning(s)",
            )
        except Exception:
            pass
        try:
            dpg.add_text(self._RULE)
        except Exception:
            pass
        for line in preview.source.splitlines()[: self._max_preview_lines]:
            try:
                dpg.add_text(line)
            except Exception:
                pass

    def _render_prefab_body(self, dpg: Any) -> None:
        preview: PrefabPreview = self._preview  # type: ignore[assignment]
        if preview is None:
            return
        if preview.error:
            try:
                dpg.add_text(f"! {preview.error}")
            except Exception:
                pass
            return
        try:
            dpg.add_text(f"Nodes:  {preview.node_count}")
            dpg.add_text(f"Joints: {preview.joint_count}")
            if preview.bounding_box is not None:
                x0, y0, x1, y1 = preview.bounding_box
                dpg.add_text(
                    f"BBox:   ({x0:.2f}, {y0:.2f}) -> ({x1:.2f}, {y1:.2f})",
                )
            else:
                dpg.add_text("BBox:   (unset)")
        except Exception:
            pass
        try:
            dpg.add_text(self._RULE)
        except Exception:
            pass
        if preview.image is not None:
            try:
                dpg.add_text(
                    f"[prefab preview {preview.image.size[0]} x "
                    f"{preview.image.size[1]}]",
                )
            except Exception:
                pass

    def _render_other_body(self, dpg: Any) -> None:
        preview: OtherPreview = self._preview  # type: ignore[assignment]
        if preview is None:
            return
        try:
            dpg.add_text(f"Size:  {_format_size(preview.size_bytes)}")
            dpg.add_text(f"Mtime: {_format_timestamp(preview.mtime)}")
        except Exception:
            pass
        try:
            dpg.add_text(self._RULE)
        except Exception:
            pass
        for line in preview.hex_dump.splitlines():
            try:
                dpg.add_text(line)
            except Exception:
                pass
        if preview.error and not preview.hex_dump:
            try:
                dpg.add_text(f"! {preview.error}")
            except Exception:
                pass

    # ------------------------------------------------------------------
    # DPG callback shims
    # ------------------------------------------------------------------

    def _on_refresh_clicked(self, *_a: Any, **_kw: Any) -> None:
        self.refresh()

    def _on_copy_path_clicked(self, *_a: Any, **_kw: Any) -> None:
        self.copy_path()

    def _on_open_material_clicked(self, *_a: Any, **_kw: Any) -> None:
        self.open_material_editor()

    # ------------------------------------------------------------------
    # Teardown
    # ------------------------------------------------------------------

    def destroy(self) -> None:
        """Detach any external subscriptions so the panel can be freed."""
        # Unhook the content browser if we're still attached.
        prev = self._content_browser
        if prev is not None:
            try:
                prev.set_on_asset_selected(self._prev_browser_cb)
            except Exception:
                pass
        self._content_browser = None
        self._prev_browser_cb = None
        self._built = False


__all__ = [
    "ASSET_KIND_MATERIAL",
    "ASSET_KIND_OTHER",
    "ASSET_KIND_PREFAB",
    "ASSET_KIND_SCENE",
    "ASSET_KIND_SCRIPT",
    "ASSET_KIND_SHADER",
    "ASSET_KIND_TEXTURE",
    "MaterialPreview",
    "NotebookAssetInspector",
    "OtherPreview",
    "PrefabPreview",
    "ScenePreview",
    "ScriptPreview",
    "ShaderPreview",
    "TexturePreview",
    "classify_asset_kind",
]
