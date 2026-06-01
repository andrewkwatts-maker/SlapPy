"""Generate per-subpackage API reference docs under ``docs/api/``.

Each target subpackage is introspected at runtime and rendered to a
self-contained Markdown file that an LLM-driven user can paste into a
prompt to get accurate signatures + Raises sections. The top-level
``docs/engine_surface_v030.md`` index links out to these per-subpackage
files instead of duplicating their content.

Usage::

    PYTHONPATH=python python scripts/gen_subpackage_api_docs.py

The generator is the single source of truth — no hand-written entries.
Re-running it produces byte-identical output if no source has changed
(members are sorted lexicographically and no timestamps are emitted).
"""

from __future__ import annotations

import dataclasses
import importlib
import inspect
import pkgutil
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Iterable

# ---------------------------------------------------------------------------
# Locate the engine package
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[1]
PY_ROOT = REPO_ROOT / "python"
if str(PY_ROOT) not in sys.path:
    sys.path.insert(0, str(PY_ROOT))

DOC_DIR = REPO_ROOT / "docs" / "api"

# Subpackages we generate API references for. Stable contract — order is
# preserved in the index doc.
TARGET_SUBPACKAGES: tuple[str, ...] = (
    "dynamics",
    "zones",
    "topology",
    "numerics",
    "thermal",
    "iso",
    "telemetry",
    "testing",
    "tools",
)

# Names we never document, even if they appear in ``dir(module)``.
SKIP_NAMES: frozenset[str] = frozenset({"annotations"})
SKIP_MODULE_SUFFIXES: tuple[str, ...] = ("_validation",)

# Hand-authored docs opt out of regeneration by including this marker
# anywhere in the file (we check the first ~10 lines so it must live at
# the top). The generator preserves the on-disk file byte-for-byte when
# the marker is present.
HANDAUTHORED_MARKER: str = "<!-- handauthored: do not regenerate -->"
HANDAUTHORED_HEAD_LINES: int = 10


def _is_handauthored(path: Path) -> bool:
    """Return ``True`` if ``path`` carries the hand-authored opt-out marker.

    Only the first ``HANDAUTHORED_HEAD_LINES`` lines are inspected so the
    marker cannot be smuggled in by, e.g., a stale comment buried inside
    a code block deep in the doc.
    """
    if not path.exists():
        return False
    try:
        with path.open("r", encoding="utf-8") as fh:
            head = "".join(next(fh, "") for _ in range(HANDAUTHORED_HEAD_LINES))
    except OSError:
        return False
    return HANDAUTHORED_MARKER in head


# ---------------------------------------------------------------------------
# Introspection helpers
# ---------------------------------------------------------------------------


def _is_skippable_name(name: str) -> bool:
    """Private members and ``annotations`` futures import leak get filtered."""
    if name.startswith("_"):
        return True
    if name in SKIP_NAMES:
        return True
    return False


def _is_skippable_submodule(name: str) -> bool:
    """Skip ``_validation`` shims and any private submodule."""
    if name.startswith("_"):
        return True
    for suffix in SKIP_MODULE_SUFFIXES:
        if name == suffix or name.endswith("." + suffix):
            return True
    return False


def _signature_text(value: Any) -> str:
    """Render ``inspect.signature(value)`` or empty string if unavailable."""
    try:
        sig = inspect.signature(value)
    except (TypeError, ValueError):
        return ""
    return str(sig)


def _first_doc_line(obj: Any) -> str:
    """First non-empty line of the cleaned docstring, or empty string."""
    doc = inspect.getdoc(obj) or ""
    for line in doc.splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def _first_paragraph(obj: Any) -> str:
    """First paragraph of the cleaned docstring (blank-line terminated)."""
    doc = inspect.getdoc(obj) or ""
    paragraph: list[str] = []
    for line in doc.splitlines():
        if not line.strip():
            if paragraph:
                break
            continue
        paragraph.append(line.strip())
    return " ".join(paragraph)


# Parses NumPy-style ``Raises`` / ``Raises:`` sections. The grammar we
# accept:
#
#   Raises
#   ------
#   ExceptionType
#       Reason text continued on
#       multiple indented lines.
#   OtherException
#       ...
#
# and the Google-style equivalent:
#
#   Raises:
#       ExceptionType: Reason text.
#       OtherException: Reason text continued
#           on multiple lines.
_RAISES_HEADER = re.compile(
    r"^[ \t]*Raises[ \t]*[:]?[ \t]*$",
    re.MULTILINE,
)


def _extract_raises(doc: str) -> list[tuple[str, str]]:
    """Return ``[(exception_name, reason), ...]`` parsed from ``doc``.

    Tolerates both numpydoc and google-style sections. Stops at the
    next un-indented section header or blank-followed-by-unindented line.
    """
    if not doc:
        return []
    match = _RAISES_HEADER.search(doc)
    if not match:
        return []
    rest = doc[match.end():]

    # Drop leading blanks and the optional numpy-style underline ('------').
    lines = rest.splitlines()
    while lines and not lines[0].strip():
        lines = lines[1:]
    if lines and set(lines[0].strip()) == {"-"}:
        lines = lines[1:]

    out: list[tuple[str, str]] = []
    current_name: str | None = None
    current_body: list[str] = []

    def _flush() -> None:
        nonlocal current_name, current_body
        if current_name is not None:
            reason = " ".join(s.strip() for s in current_body if s.strip())
            out.append((current_name, reason))
        current_name = None
        current_body = []

    base_indent: int | None = None
    for raw in lines:
        if not raw.strip():
            # Allow blank lines inside a multi-line reason; only break on
            # blank + un-indented next line. We approximate that by
            # treating consecutive blank as end-of-section.
            current_body.append("")
            if len(current_body) >= 2 and current_body[-1] == current_body[-2] == "":
                break
            continue
        indent = len(raw) - len(raw.lstrip())
        if base_indent is None:
            base_indent = indent
        if indent < base_indent:
            # Un-indented line ends the Raises block.
            break
        stripped = raw.strip()

        # google-style: "ExceptionType: reason..."
        if indent == base_indent:
            _flush()
            if ":" in stripped:
                head, _, tail = stripped.partition(":")
                current_name = head.strip()
                current_body = [tail.strip()] if tail.strip() else []
            else:
                # numpy-style: exception name on its own line.
                current_name = stripped
                current_body = []
        else:
            # Continuation of the current reason.
            current_body.append(stripped)
    _flush()

    # Drop empties — e.g. a header with no body.
    return [(name, body) for name, body in out if name]


def _public_attrs(module: ModuleType) -> list[str]:
    """Return the module's documented public attribute names.

    Prefers ``module.__all__`` when present (the explicit author contract);
    otherwise falls back to ``dir(module)`` with the standard filters.
    """
    explicit = getattr(module, "__all__", None)
    if explicit:
        return sorted({name for name in explicit if not _is_skippable_name(name)})
    return sorted(
        name for name in dir(module)
        if not _is_skippable_name(name)
        and not inspect.ismodule(getattr(module, name, None))
    )


def _walk_inner_modules(pkg: ModuleType) -> list[str]:
    """Return sorted dotted paths for every non-private inner module."""
    if not hasattr(pkg, "__path__"):
        return []
    prefix = pkg.__name__ + "."
    out: list[str] = []
    for info in pkgutil.walk_packages(pkg.__path__, prefix=prefix):
        short = info.name[len(prefix):]
        if any(_is_skippable_submodule(part) for part in short.split(".")):
            continue
        out.append(info.name)
    return sorted(out)


# ---------------------------------------------------------------------------
# Categorisation
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class _Entry:
    name: str
    value: Any
    qualname: str  # dotted path to the defining module


def _classify(entries: Iterable[_Entry]) -> tuple[list[_Entry], list[_Entry], list[_Entry]]:
    """Bucket entries into (classes, functions, constants), each sorted."""
    classes: list[_Entry] = []
    functions: list[_Entry] = []
    constants: list[_Entry] = []
    for entry in entries:
        v = entry.value
        if inspect.isclass(v):
            classes.append(entry)
        elif inspect.isfunction(v) or inspect.isbuiltin(v) or inspect.ismethod(v):
            functions.append(entry)
        elif callable(v) and not inspect.ismodule(v):
            functions.append(entry)
        elif inspect.ismodule(v):
            # Modules are listed separately in the Inner modules section.
            continue
        else:
            constants.append(entry)
    classes.sort(key=lambda e: e.name)
    functions.sort(key=lambda e: e.name)
    constants.sort(key=lambda e: e.name)
    return classes, functions, constants


# ---------------------------------------------------------------------------
# Member harvesting from classes (for the Methods sub-list)
# ---------------------------------------------------------------------------


def _public_methods(cls: type) -> list[tuple[str, str, str]]:
    """Return ``[(method_name, signature, first_doc_line), ...]`` for the class.

    Filters out dunder methods, private members, and anything inherited
    from ``object``. Methods are sorted lexicographically.
    """
    out: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for name, member in inspect.getmembers(cls):
        if name in seen:
            continue
        if _is_skippable_name(name):
            continue
        if name in {"__init__", "__post_init__"}:
            # Constructor is rendered separately.
            continue
        # Skip object-level dunders and helpers.
        if getattr(object, name, None) is member:
            continue
        if not callable(member):
            continue
        # Heuristic: if the attribute was not defined on the class itself
        # or any of its non-object bases, skip — keeps the output focused
        # on the type's own surface.
        defining = None
        for base in cls.__mro__:
            if base is object:
                continue
            if name in vars(base):
                defining = base
                break
        if defining is None:
            continue
        # Skip methods that come from a built-in base (e.g. ``int`` /
        # ``IntEnum`` give us ``bit_length``, ``as_integer_ratio``, …).
        if getattr(defining, "__module__", "") == "builtins":
            continue
        seen.add(name)
        sig = _signature_text(member)
        doc = _first_doc_line(member)
        out.append((name, sig, doc))
    out.sort(key=lambda row: row[0])
    return out


def _constructor_signature(cls: type) -> str:
    """Render the constructor signature for ``cls``.

    For dataclasses, the synthesised ``__init__`` already carries the
    full field signature, so we just use ``inspect.signature(cls)``.
    """
    return _signature_text(cls)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


HEADER_TEMPLATE = (
    "# slappyengine.{subpackage} — API Reference\n"
    "\n"
    "> Auto-generated. Re-run `python scripts/gen_subpackage_api_docs.py`.\n"
    "> Do not hand-edit — every entry below comes from runtime introspection\n"
    "> (`inspect.signature`, `inspect.getdoc`, `dataclasses.fields`).\n"
)


def _render_subpackage(subpackage: str) -> str:
    """Render the full Markdown document for one subpackage.

    Returns a string that always ends with a single trailing newline so
    re-generation is byte-identical when nothing has changed.
    """
    lines: list[str] = []
    lines.append(HEADER_TEMPLATE.format(subpackage=subpackage))

    try:
        module = importlib.import_module(f"slappyengine.{subpackage}")
    except Exception as exc:
        lines.append("")
        lines.append(
            f"_Could not import `slappyengine.{subpackage}`: "
            f"`{type(exc).__name__}: {exc}`._"
        )
        lines.append("")
        return "\n".join(lines) + "\n"

    # Top-level module docstring (first paragraph) for context.
    mod_para = _first_paragraph(module) or ""
    if mod_para:
        lines.append("")
        lines.append(mod_para)

    # Discover everything reachable from the package's surface.
    public_names = _public_attrs(module)
    entries: list[_Entry] = []
    for name in public_names:
        value = getattr(module, name, None)
        if value is None:
            continue
        qualname = getattr(value, "__module__", "") or ""
        entries.append(_Entry(name=name, value=value, qualname=qualname))

    classes, functions, constants = _classify(entries)

    # --- Classes ----------------------------------------------------------
    lines.append("")
    lines.append("## Classes")
    if not classes:
        lines.append("")
        lines.append("_(none)_")
    for entry in classes:
        cls = entry.value
        is_dc = dataclasses.is_dataclass(cls)
        lines.append("")
        lines.append(f"### `{entry.name}`")
        kind_tag = "dataclass" if is_dc else "class"
        lines.append("")
        lines.append(f"_{kind_tag} — defined in `{entry.qualname}`_")
        doc = _first_doc_line(cls)
        if doc:
            lines.append("")
            lines.append(doc)
        sig = _constructor_signature(cls)
        if sig:
            lines.append("")
            lines.append("#### Constructor signature")
            lines.append("")
            lines.append("```python")
            lines.append(f"{entry.name}{sig}")
            lines.append("```")
        if is_dc:
            fields = dataclasses.fields(cls)
            if fields:
                lines.append("")
                lines.append("#### Fields")
                lines.append("")
                for f in sorted(fields, key=lambda x: x.name):
                    type_str = f.type if isinstance(f.type, str) else getattr(f.type, "__name__", repr(f.type))
                    default = ""
                    if f.default is not dataclasses.MISSING:
                        default = f" — default `{f.default!r}`"
                    elif f.default_factory is not dataclasses.MISSING:  # type: ignore[misc]
                        default = " — default factory"
                    lines.append(f"- `{f.name}: {type_str}`{default}")
        methods = _public_methods(cls)
        if methods:
            lines.append("")
            lines.append("#### Methods")
            lines.append("")
            for mname, msig, mdoc in methods:
                doc_suffix = f" — {mdoc}" if mdoc else ""
                lines.append(f"- `{mname}{msig}`{doc_suffix}")
        # Class-level Raises (typically attached to __init__/__post_init__).
        raises = _extract_raises(inspect.getdoc(cls) or "")
        init_doc = inspect.getdoc(getattr(cls, "__init__", None)) or ""
        post_init_doc = inspect.getdoc(getattr(cls, "__post_init__", None)) or ""
        for extra in (init_doc, post_init_doc):
            raises.extend(_extract_raises(extra))
        if raises:
            lines.append("")
            lines.append("#### Raises")
            lines.append("")
            # De-dupe while preserving order.
            seen: set[tuple[str, str]] = set()
            for name, reason in raises:
                key = (name, reason)
                if key in seen:
                    continue
                seen.add(key)
                reason_text = f" — {reason}" if reason else ""
                lines.append(f"- `{name}`{reason_text}")

    # --- Functions --------------------------------------------------------
    lines.append("")
    lines.append("## Functions")
    if not functions:
        lines.append("")
        lines.append("_(none)_")
    for entry in functions:
        fn = entry.value
        sig = _signature_text(fn)
        lines.append("")
        lines.append(f"### `{entry.name}{sig}`")
        lines.append("")
        lines.append(f"_defined in `{entry.qualname}`_")
        para = _first_paragraph(fn)
        if para:
            lines.append("")
            lines.append(para)
        raises = _extract_raises(inspect.getdoc(fn) or "")
        if raises:
            lines.append("")
            lines.append("#### Raises")
            lines.append("")
            for name, reason in raises:
                reason_text = f" — {reason}" if reason else ""
                lines.append(f"- `{name}`{reason_text}")

    # --- Constants --------------------------------------------------------
    lines.append("")
    lines.append("## Constants")
    if not constants:
        lines.append("")
        lines.append("_(none)_")
    for entry in constants:
        value = entry.value
        # Normalise machine-specific paths so the doc is portable across
        # checkouts (otherwise an absolute path in a BASELINES_DIR-style
        # constant would change byte-by-byte per machine, breaking the
        # idempotency promise on first regeneration).
        if isinstance(value, Path):
            try:
                rel = value.resolve().relative_to(REPO_ROOT)
                repr_text = f"<repo>/{rel.as_posix()}"
            except (ValueError, OSError):
                repr_text = value.name or repr(value)
        else:
            try:
                repr_text = repr(value)
            except Exception:
                repr_text = f"<{type(value).__name__}>"
        if len(repr_text) > 80:
            repr_text = repr_text[:77] + "..."
        type_name = type(value).__name__
        lines.append("")
        lines.append(f"### `{entry.name}`")
        lines.append("")
        lines.append(f"_{type_name} — defined in `{entry.qualname or 'slappyengine.' + subpackage}`_")
        # Suppress docstrings for built-in / stdlib primitives whose
        # ``__doc__`` is the type's help text (e.g. ``int.__doc__`` is
        # ``"int([x]) -> integer"``, ``Path.__doc__`` describes the class).
        suppress_doc_modules = {"builtins", "pathlib", "pathlib._local"}
        if type(value).__module__ not in suppress_doc_modules:
            doc = _first_doc_line(value)
            if doc:
                lines.append("")
                lines.append(doc)
        lines.append("")
        lines.append(f"Value: `{repr_text}`")

    # --- Inner modules ----------------------------------------------------
    inner = _walk_inner_modules(module)
    lines.append("")
    lines.append("## Inner modules")
    if not inner:
        lines.append("")
        lines.append("_(none)_")
    else:
        lines.append("")
        for path in inner:
            lines.append(f"- `{path}`")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Index update (top-level engine_surface_v030.md)
# ---------------------------------------------------------------------------


INDEX_DOC = REPO_ROOT / "docs" / "engine_surface_v030.md"

# Sentinel pair so re-runs don't duplicate or stale-out the linked block.
INDEX_BLOCK_BEGIN = "<!-- BEGIN: AUTO-GENERATED SUBPACKAGE API LINKS -->"
INDEX_BLOCK_END = "<!-- END: AUTO-GENERATED SUBPACKAGE API LINKS -->"


def _render_index_block() -> str:
    lines = [
        INDEX_BLOCK_BEGIN,
        "",
        "## Per-subpackage API references",
        "",
        (
            "The following per-subpackage reference docs are auto-generated "
            "by `scripts/gen_subpackage_api_docs.py`. Each one lists every "
            "public class / function / constant with full signatures and "
            "parsed `Raises:` sections — paste one into an LLM prompt to get "
            "accurate context for that subpackage."
        ),
        "",
    ]
    for sub in TARGET_SUBPACKAGES:
        lines.append(f"- [`slappyengine.{sub}`](api/{sub}.md)")
    lines.append("")
    lines.append(INDEX_BLOCK_END)
    return "\n".join(lines)


def _update_index() -> None:
    """Insert / refresh the per-subpackage link block in the top-level doc."""
    if not INDEX_DOC.exists():
        # No top-level doc yet — nothing to update. (The dedicated generator
        # for that doc lives in scripts/gen_engine_surface_doc.py.)
        return
    text = INDEX_DOC.read_text(encoding="utf-8")
    block = _render_index_block()
    if INDEX_BLOCK_BEGIN in text and INDEX_BLOCK_END in text:
        # Replace existing block.
        pattern = re.compile(
            re.escape(INDEX_BLOCK_BEGIN) + r".*?" + re.escape(INDEX_BLOCK_END),
            re.DOTALL,
        )
        new_text = pattern.sub(block, text)
    else:
        # Append at end with a separator.
        sep = "" if text.endswith("\n") else "\n"
        new_text = text + sep + "\n" + block + "\n"
    if new_text != text:
        INDEX_DOC.write_text(new_text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def write_all() -> list[Path]:
    """Generate every target subpackage doc. Returns the list of paths written.

    Files carrying the :data:`HANDAUTHORED_MARKER` in their first
    :data:`HANDAUTHORED_HEAD_LINES` lines are left untouched — the path is
    still returned so callers can see what was considered, but the
    on-disk bytes are not modified. This is how the per-subpackage hand-
    written references under ``docs/api/`` survive across regenerations.
    """
    DOC_DIR.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for sub in TARGET_SUBPACKAGES:
        path = DOC_DIR / f"{sub}.md"
        # Hand-authored opt-out: never touch the file.
        if _is_handauthored(path):
            written.append(path)
            continue
        body = _render_subpackage(sub)
        # Only rewrite if content changed — keeps mtimes stable for caches.
        if path.exists() and path.read_text(encoding="utf-8") == body:
            written.append(path)
            continue
        path.write_text(body, encoding="utf-8")
        written.append(path)
    _update_index()
    return written


def main() -> None:
    paths = write_all()
    for p in paths:
        rel = p.relative_to(REPO_ROOT)
        print(f"wrote {rel} ({p.stat().st_size} bytes)")
    print(f"total: {len(paths)} subpackage API docs")


if __name__ == "__main__":
    main()
