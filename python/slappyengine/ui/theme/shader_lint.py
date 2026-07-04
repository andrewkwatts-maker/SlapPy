"""WGSL shader validation suite for the notebook theme system.

This module lints every WGSL fragment shader shipped by the three
notebook theme libraries — washi tape, page linings, and edge strokes —
against a small but rigorous set of rules:

* **Byte budget** — every source must fit inside a 1000-byte envelope
  so the whole library stays cheap to embed in a wheel.
* **Fragment entry point** — every source must declare a ``@fragment``
  function named ``fs_main`` (or the contract's override) returning an
  ``@location(0)`` colour.
* **Uniform contract** — every source must reference the uniform names
  its library contract requires. The three libraries have slightly
  different contracts (see :data:`SHADER_CONTRACTS`).
* **Encoding hygiene** — no stray backticks, smart quotes, or
  non-ASCII glyphs that would trip WGSL parsers on some drivers.
* **Deprecated syntax** — warnings fire when a shader still uses
  ``[[block]]`` or ``[[binding(0)]]`` attribute syntax.
* **Real parse (soft)** — when :mod:`wgpu` is importable and a device
  can be created, the linter attempts an actual shader-module compile
  and captures any error text.

The suite is intentionally source-only (it does *not* execute the
shaders); the goal is fast pre-flight validation that runs on every
CI ticket without needing a GPU.

Design constraints
------------------

* No writes to the shader libraries themselves — those files are
  read-only inputs owned by other agents.
* No hard dependency on wgpu; if the module is unimportable the linter
  degrades gracefully to source-only checks and records the fact via
  :func:`wgpu_available`.
* Every check that *fails* is recorded as either an ``error`` or a
  ``warning`` on the :class:`WGSLLintResult`. Callers can decide how
  strict to be.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence


# ---------------------------------------------------------------------------
# Public exceptions + result dataclass
# ---------------------------------------------------------------------------


class WGSLLintError(Exception):
    """Raised for structural violations that the caller opted in to fail on.

    Parameters
    ----------
    source_id:
        The library-relative identifier of the offending shader (e.g.
        ``"tape_pink_dots"`` or ``"ruled_paper"``).
    line:
        1-based line number in the source, or ``0`` if the issue is
        global (byte budget, missing entry point, etc.).
    issue:
        Short human-readable description.
    """

    def __init__(self, source_id: str, line: int, issue: str) -> None:
        if not isinstance(source_id, str) or not source_id:
            raise ValueError(
                "WGSLLintError: source_id must be non-empty str; "
                f"got {source_id!r}"
            )
        if not isinstance(line, int) or line < 0:
            raise ValueError(
                f"WGSLLintError: line must be non-negative int; got {line!r}"
            )
        if not isinstance(issue, str) or not issue:
            raise ValueError(
                f"WGSLLintError: issue must be non-empty str; got {issue!r}"
            )
        self.source_id = source_id
        self.line = line
        self.issue = issue
        super().__init__(f"[{source_id}:{line}] {issue}")


@dataclass
class WGSLLintResult:
    """The output of :func:`lint_wgsl` for a single shader source.

    Attributes
    ----------
    source_id:
        The library-relative identifier.
    size_bytes:
        UTF-8 byte length of the source.
    has_entry_point:
        ``True`` if a ``@fragment`` function was found. Its name is in
        :attr:`entry_point_name`.
    entry_point_name:
        The detected fragment entry-point name, or ``""`` if none.
    uniforms:
        The list of ``var<uniform>`` binding names + the field names of
        any wrapping struct that were extracted from the source. Field
        names carry the same prefix as the source (e.g. ``u_time``).
    errors:
        A list of ``(line, issue)`` tuples describing hard violations.
        Populated even when :attr:`parseable` is ``True`` — callers
        should inspect the list before promoting.
    warnings:
        A list of ``(line, issue)`` tuples describing soft violations
        (deprecated syntax, cosmetic issues).
    parseable:
        ``True`` iff the source has no hard errors and, if wgpu is
        importable, its ``create_shader_module`` call returned without
        raising. ``False`` otherwise.
    """

    source_id: str
    size_bytes: int
    has_entry_point: bool
    entry_point_name: str
    uniforms: list[str] = field(default_factory=list)
    errors: list[tuple[int, str]] = field(default_factory=list)
    warnings: list[tuple[int, str]] = field(default_factory=list)
    parseable: bool = True


# ---------------------------------------------------------------------------
# Regexes reused across checks
# ---------------------------------------------------------------------------


# ``@fragment\s+fn\s+<name>`` — captures the fragment entry-point name.
_ENTRY_POINT_RE = re.compile(
    r"@fragment\s+fn\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\("
)

# ``var<uniform>\s+<name>\s*:`` — captures the binding-slot name.
_UNIFORM_RE = re.compile(
    r"var\s*<\s*uniform\s*>\s*(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*:"
)

# Struct field discovery: matches ``struct <Name> { ... }`` blocks and
# yields each field name inside.
_STRUCT_RE = re.compile(
    r"struct\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\{(?P<body>[^}]*)\}",
    re.DOTALL,
)
_STRUCT_FIELD_RE = re.compile(
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*:\s*[^,;]+[,;]"
)

# Deprecated ``[[attribute]]`` syntax (WGSL predecessor spelling).
_DEPRECATED_ATTR_RE = re.compile(r"\[\[\s*(block|binding|location|group)")

# Any run of non-ASCII bytes / smart quotes / stray backticks.
_SMART_QUOTE_CHARS = "‘’“”–—…"
_BACKTICK = "`"


# ---------------------------------------------------------------------------
# wgpu soft-import shim
# ---------------------------------------------------------------------------


_WGPU_CACHE: dict[str, Any] = {}


def wgpu_available() -> bool:
    """Return ``True`` iff :mod:`wgpu` is importable at runtime.

    Result is cached so repeated calls are cheap.
    """
    if "checked" in _WGPU_CACHE:
        return bool(_WGPU_CACHE.get("module") is not None)
    try:
        import wgpu  # type: ignore[import-not-found]

        _WGPU_CACHE["module"] = wgpu
    except Exception:  # pragma: no cover - env-dependent
        _WGPU_CACHE["module"] = None
    _WGPU_CACHE["checked"] = True
    return _WGPU_CACHE["module"] is not None


def _get_wgpu_device() -> Any:
    """Return a cached wgpu ``Device`` or ``None`` if unavailable.

    We only need a device to test-compile shader modules. Errors on
    adapter/device creation are swallowed and the linter falls back to
    source-only checks.
    """
    if "device_checked" in _WGPU_CACHE:
        return _WGPU_CACHE.get("device")
    if not wgpu_available():
        _WGPU_CACHE["device_checked"] = True
        _WGPU_CACHE["device"] = None
        return None
    wgpu = _WGPU_CACHE["module"]
    try:  # pragma: no cover - env-dependent
        adapter = wgpu.gpu.request_adapter_sync(power_preference="low-power")
        if adapter is None:
            _WGPU_CACHE["device"] = None
        else:
            _WGPU_CACHE["device"] = adapter.request_device_sync()
    except Exception:  # pragma: no cover - env-dependent
        _WGPU_CACHE["device"] = None
    _WGPU_CACHE["device_checked"] = True
    return _WGPU_CACHE["device"]


# ---------------------------------------------------------------------------
# Core linter
# ---------------------------------------------------------------------------


def _extract_uniforms(source: str) -> list[str]:
    """Return the union of ``var<uniform>`` names and their struct fields.

    We treat *both* the binding-slot name and every field name of any
    ``struct`` referenced by that slot as recognised uniforms. That way
    the contract can name either the binding (``u``) or a well-known
    field (``u_time``, ``u_size``) and the linter will accept it.
    """
    binding_names: list[str] = []
    struct_types: dict[str, str] = {}
    for m in _UNIFORM_RE.finditer(source):
        binding_names.append(m.group("name"))
        # Try to also grab the type token that follows the ':'.
        tail = source[m.end() :].lstrip()
        type_m = re.match(r"([A-Za-z_][A-Za-z0-9_]*)", tail)
        if type_m is not None:
            struct_types[m.group("name")] = type_m.group(1)
    field_names: list[str] = []
    struct_bodies: dict[str, str] = {}
    for sm in _STRUCT_RE.finditer(source):
        struct_bodies[sm.group("name")] = sm.group("body")
    for binding, type_name in struct_types.items():
        body = struct_bodies.get(type_name)
        if body is None:
            continue
        for fm in _STRUCT_FIELD_RE.finditer(body):
            fname = fm.group("name")
            # Ignore trivial padding fields.
            if fname.startswith("_"):
                continue
            field_names.append(fname)
    # Preserve order but drop dupes.
    seen: set[str] = set()
    out: list[str] = []
    for n in binding_names + field_names:
        if n in seen:
            continue
        seen.add(n)
        out.append(n)
    return out


def _find_line(source: str, needle: str) -> int:
    """Return the 1-based line number of ``needle`` in ``source`` (or 0)."""
    idx = source.find(needle)
    if idx < 0:
        return 0
    return source.count("\n", 0, idx) + 1


def lint_wgsl(
    source_id: str,
    source: str,
    contract: Mapping[str, Any] | None = None,
) -> WGSLLintResult:
    """Lint a single WGSL fragment shader against ``contract``.

    Parameters
    ----------
    source_id:
        The library-relative identifier of this shader.
    source:
        The full WGSL source string. Must be non-empty.
    contract:
        Optional dict describing the library's contract. Supported keys:

        * ``max_bytes`` (int, default 1000) — byte budget.
        * ``entry_point`` (str, default ``"fs_main"``).
        * ``required_uniforms`` (list[str]) — uniform-slot **or**
          struct-field names that must appear in the source. Empty by
          default (matches the page-linings library that hard-codes
          colours).
        * ``require_location_0`` (bool, default ``True``) — enforce
          the ``@location(0)`` return attribute.
        * ``forbid_deprecated`` (bool, default ``True``) — warn on
          ``[[block]]`` / ``[[binding(0)]]`` syntax.

    Returns
    -------
    :class:`WGSLLintResult`
        Populated with all detected errors and warnings. The
        :attr:`~WGSLLintResult.parseable` flag reflects whether the
        source passed *all* structural checks *and* survived the
        optional wgpu compile.

    Raises
    ------
    TypeError
        If ``source_id`` or ``source`` are not strings.
    ValueError
        If ``source`` is empty.
    """
    if not isinstance(source_id, str) or not source_id:
        raise TypeError(
            f"lint_wgsl: source_id must be non-empty str; got {source_id!r}"
        )
    if not isinstance(source, str):
        raise TypeError(
            f"lint_wgsl: source must be str; got {type(source).__name__}"
        )
    if not source:
        raise ValueError("lint_wgsl: source must be non-empty")
    if contract is not None and not isinstance(contract, Mapping):
        raise TypeError(
            "lint_wgsl: contract must be a Mapping or None; "
            f"got {type(contract).__name__}"
        )

    contract = dict(contract) if contract else {}
    max_bytes = int(contract.get("max_bytes", 1000))
    entry_point = str(contract.get("entry_point", "fs_main"))
    required_uniforms: Sequence[str] = tuple(contract.get("required_uniforms", ()))
    require_location_0 = bool(contract.get("require_location_0", True))
    forbid_deprecated = bool(contract.get("forbid_deprecated", True))

    size_bytes = len(source.encode("utf-8"))
    errors: list[tuple[int, str]] = []
    warnings: list[tuple[int, str]] = []

    # 1. Byte-budget check.
    if size_bytes > max_bytes:
        errors.append(
            (0, f"exceeds byte budget: {size_bytes} > {max_bytes}")
        )

    # 2. Entry-point discovery.
    entry_match = _ENTRY_POINT_RE.search(source)
    has_entry_point = entry_match is not None
    entry_point_name = entry_match.group("name") if entry_match else ""
    if not has_entry_point:
        errors.append((0, "missing @fragment entry point"))
    elif entry_point_name != entry_point:
        errors.append(
            (
                _find_line(source, "@fragment"),
                f"entry point named {entry_point_name!r}, "
                f"contract requires {entry_point!r}",
            )
        )

    # 3. @location(0) return attribute.
    if require_location_0 and has_entry_point:
        # Look at the entry-point signature only; that's where
        # ``@location(0)`` must appear.
        sig_slice = source[entry_match.start() :]
        # Find matching brace to get the signature region.
        brace = sig_slice.find("{")
        if brace < 0:
            errors.append(
                (_find_line(source, "@fragment"), "malformed entry-point signature")
            )
        else:
            sig = sig_slice[:brace]
            if "@location(0)" not in sig.replace(" ", ""):
                errors.append(
                    (
                        _find_line(source, "@fragment"),
                        "entry point missing @location(0) return attribute",
                    )
                )

    # 4. Uniform contract.
    uniforms = _extract_uniforms(source)
    uniform_set = set(uniforms)
    for u in required_uniforms:
        if u not in uniform_set:
            errors.append(
                (0, f"missing required uniform / struct field {u!r}")
            )

    # 5. Encoding hygiene.
    if _BACKTICK in source:
        line = _find_line(source, _BACKTICK)
        errors.append((line, "stray backtick in source"))
    for ch in _SMART_QUOTE_CHARS:
        if ch in source:
            line = _find_line(source, ch)
            errors.append((line, f"smart-quote / dash character U+{ord(ch):04X}"))
    # Also flag any non-ASCII bytes.
    try:
        source.encode("ascii")
    except UnicodeEncodeError as exc:
        line = source.count("\n", 0, exc.start) + 1
        # Skip if already reported as smart-quote above.
        if source[exc.start] not in _SMART_QUOTE_CHARS:
            errors.append(
                (
                    line,
                    f"non-ASCII character U+{ord(source[exc.start]):04X}",
                )
            )

    # 6. Deprecated attribute syntax → warning.
    if forbid_deprecated:
        for m in _DEPRECATED_ATTR_RE.finditer(source):
            line = source.count("\n", 0, m.start()) + 1
            warnings.append(
                (line, f"deprecated attribute syntax {m.group(0)!r}")
            )

    # 7. Real wgpu parse (soft — only if importable + device available).
    if not errors:
        device = _get_wgpu_device()
        if device is not None:  # pragma: no branch - env-dependent
            try:  # pragma: no cover - GPU env-dependent
                device.create_shader_module(code=source)
            except Exception as exc:  # pragma: no cover
                errors.append((0, f"wgpu parse failed: {exc}"))

    parseable = not errors

    return WGSLLintResult(
        source_id=source_id,
        size_bytes=size_bytes,
        has_entry_point=has_entry_point,
        entry_point_name=entry_point_name,
        uniforms=uniforms,
        errors=errors,
        warnings=warnings,
        parseable=parseable,
    )


# ---------------------------------------------------------------------------
# Per-library contracts
# ---------------------------------------------------------------------------


SHADER_CONTRACTS: dict[str, dict[str, Any]] = {
    "washi_tape": {
        "max_bytes": 1000,
        "entry_point": "fs_main",
        # Washi tapes bind ``u`` to a struct holding these fields.
        "required_uniforms": [
            "u",
            "u_time",
            "u_size",
            "u_theme_color_1",
            "u_theme_color_2",
        ],
        "require_location_0": True,
        "forbid_deprecated": True,
    },
    "page_linings": {
        "max_bytes": 1000,
        "entry_point": "fs_main",
        # Page linings hard-code their palette; no uniforms required.
        "required_uniforms": [],
        "require_location_0": True,
        "forbid_deprecated": True,
    },
    "edge_strokes": {
        "max_bytes": 1000,
        "entry_point": "fs_main",
        "required_uniforms": [
            "u",
            "u_size",
            "u_theme_color_1",
            "u_theme_color_2",
        ],
        "require_location_0": True,
        "forbid_deprecated": True,
    },
}


# ---------------------------------------------------------------------------
# Whole-library sweep
# ---------------------------------------------------------------------------


def _iter_washi_sources() -> list[tuple[str, str]]:
    """Return ``[(style_id, wgsl_source), ...]`` for the washi library."""
    from slappyengine.ui.theme.washi_tape.library import WASHI_TAPES

    return [(sid, style.wgsl_source) for sid, style in WASHI_TAPES.items()]


def _iter_lining_sources() -> list[tuple[str, str]]:
    """Return ``[(style_id, wgsl_source), ...]`` for the linings library."""
    from slappyengine.ui.theme.page_linings.library import PAGE_LININGS

    return [(sid, style.source) for sid, style in PAGE_LININGS.items()]


def _iter_edge_stroke_sources() -> list[tuple[str, str]]:
    """Return ``[(style_id, wgsl_source), ...]`` for the edge-stroke library."""
    from slappyengine.ui.theme.edge_strokes.library import EDGE_STROKES

    return [(sid, style.wgsl_source) for sid, style in EDGE_STROKES.items()]


_LIBRARY_ITERATORS = {
    "washi_tape": _iter_washi_sources,
    "page_linings": _iter_lining_sources,
    "edge_strokes": _iter_edge_stroke_sources,
}


def lint_all_shaders() -> dict[str, list[WGSLLintResult]]:
    """Walk every registered theme library and lint every shader in it.

    Returns
    -------
    dict[str, list[WGSLLintResult]]
        Mapping from library name (``"washi_tape"``, ``"page_linings"``,
        ``"edge_strokes"``) to the list of per-shader lint results, in
        library iteration order.
    """
    results: dict[str, list[WGSLLintResult]] = {}
    for library_name, iterator in _LIBRARY_ITERATORS.items():
        contract = SHADER_CONTRACTS[library_name]
        results[library_name] = [
            lint_wgsl(source_id, source, contract=contract)
            for source_id, source in iterator()
        ]
    return results


def raise_on_error(result: WGSLLintResult) -> None:
    """Raise :class:`WGSLLintError` iff *result* has any hard errors.

    Utility for callers that prefer exception-flow over inspecting the
    ``errors`` list on the result.
    """
    if not result.errors:
        return
    line, issue = result.errors[0]
    raise WGSLLintError(result.source_id, line, issue)


__all__ = [
    "SHADER_CONTRACTS",
    "WGSLLintError",
    "WGSLLintResult",
    "lint_all_shaders",
    "lint_wgsl",
    "raise_on_error",
    "wgpu_available",
]
