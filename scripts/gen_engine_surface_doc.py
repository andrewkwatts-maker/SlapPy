"""Generate ``docs/engine_surface_v030.md`` by introspecting :mod:`slappyengine`.

This script is the single source of truth for the v0.3 engine-surface reference.
It walks ``slappyengine.__all__`` plus the ``_subpackages`` set inside
``__init__.__getattr__`` and emits a categorised Markdown document. Re-run it
whenever the public surface changes so the doc stays accurate.

Usage::

    PYTHONPATH=python python scripts/gen_engine_surface_doc.py

The generator never hand-types names — every entry is derived from runtime
introspection (``getattr``, ``inspect.signature``, ``dataclasses.fields``,
``pkgutil.iter_modules``).
"""

from __future__ import annotations

import ast
import dataclasses
import importlib
import inspect
import pkgutil
import sys
from pathlib import Path
from textwrap import shorten
from types import ModuleType
from typing import Any, Iterable

# ---------------------------------------------------------------------------
# Locate the engine package
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[1]
PY_ROOT = REPO_ROOT / "python"
if str(PY_ROOT) not in sys.path:
    sys.path.insert(0, str(PY_ROOT))

import slappyengine  # noqa: E402  (after sys.path tweak)

DOC_PATH = REPO_ROOT / "docs" / "engine_surface_v030.md"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _first_doc_line(obj: Any) -> str:
    """Return the first non-empty line of ``obj.__doc__`` or empty string."""
    doc = inspect.getdoc(obj) or ""
    for line in doc.splitlines():
        line = line.strip()
        if line:
            return shorten(line, width=110, placeholder="...")
    return ""


def _kind_of(value: Any) -> str:
    """Classify a top-level attribute as class / function / constant."""
    if inspect.isclass(value):
        if dataclasses.is_dataclass(value):
            return "dataclass"
        return "class"
    if inspect.isfunction(value) or inspect.isbuiltin(value):
        return "function"
    if inspect.ismodule(value):
        return "module"
    if callable(value):
        return "callable"
    return "constant"


def _signature_or_blank(value: Any) -> str:
    """Return a short ``inspect.signature`` rendering or ``""`` if unavailable."""
    try:
        sig = inspect.signature(value)
    except (TypeError, ValueError):
        return ""
    text = str(sig)
    if len(text) > 90:
        text = text[:87] + "..."
    return text


def _module_of(value: Any) -> str:
    mod = getattr(value, "__module__", None)
    if not mod:
        return ""
    if mod.startswith("slappyengine."):
        return mod[len("slappyengine."):]
    if mod == "slappyengine":
        return "(top-level)"
    return mod


# ---------------------------------------------------------------------------
# Discover subpackages from ``__init__.__getattr__``
# ---------------------------------------------------------------------------


def discover_subpackages() -> list[str]:
    """Parse ``python/slappyengine/__init__.py`` to read the ``_subpackages`` set
    literal inside ``__getattr__``. This avoids running the lazy loader and
    keeps the doc honest about the declared subpackages."""
    init_src = (PY_ROOT / "slappyengine" / "__init__.py").read_text(encoding="utf-8-sig")
    tree = ast.parse(init_src)
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != "__getattr__":
            continue
        for stmt in ast.walk(node):
            if isinstance(stmt, ast.Assign):
                for tgt in stmt.targets:
                    if isinstance(tgt, ast.Name) and tgt.id == "_subpackages":
                        if isinstance(stmt.value, (ast.Set, ast.Tuple, ast.List)):
                            return sorted(
                                elt.value
                                for elt in stmt.value.elts
                                if isinstance(elt, ast.Constant)
                                and isinstance(elt.value, str)
                            )
    return []


# ---------------------------------------------------------------------------
# Section bucketing for top-level names
# ---------------------------------------------------------------------------


# Module-prefix -> category. Order matters: first match wins.
SECTION_RULES: list[tuple[str, str]] = [
    ("engine",                "Core (entity / scene / engine)"),
    ("entity",                "Core (entity / scene / engine)"),
    ("scene",                 "Core (entity / scene / engine)"),
    ("camera",                "Core (entity / scene / engine)"),
    ("config",                "Core (entity / scene / engine)"),
    ("script",                "Scripting"),
    ("components",            "Components"),
    ("data_component",        "Components"),
    ("event_bus",             "Events & data"),
    ("collision",             "Physics & collision"),
    ("modules.physics",       "Physics & collision"),
    ("modules.pixel_physics", "Physics & collision"),
    ("fluid_sim",             "Fluid simulation"),
    ("lighting",              "Lighting"),
    ("layer",                 "Layers"),
    ("landscape",             "Landscape & tiles"),
    ("residency",             "Asset residency & streaming"),
    ("assets",                "Assets"),
    ("asset",                 "Assets"),
    ("cube_array",            "Rendering"),
    ("render_target",         "Rendering"),
    ("post_process",          "Post-processing"),
    ("ui",                    "UI"),
    ("animation",             "Animation"),
    ("material",              "Materials"),
    ("sdf_shapes",            "SDF & 3D"),
    ("gpu",                   "SDF & 3D"),
    ("angle_sprite",          "Angle sprites"),
    ("input",                 "Input"),
    ("split_screen",          "Split-screen"),
]


def _category_for(name: str, value: Any) -> str:
    mod = _module_of(value)
    for prefix, label in SECTION_RULES:
        if mod == prefix or mod.startswith(prefix + ".") or mod.startswith(prefix):
            return label
    return "Other"


# ---------------------------------------------------------------------------
# Top-level surface
# ---------------------------------------------------------------------------


def collect_top_level() -> dict[str, list[tuple[str, str, str, str, str]]]:
    """Return ``{section: [(name, kind, module, signature, doc), ...]}`` sorted."""
    buckets: dict[str, list[tuple[str, str, str, str, str]]] = {}
    for name in sorted(slappyengine.__all__):
        value = getattr(slappyengine, name)
        kind = _kind_of(value)
        module = _module_of(value)
        sig = _signature_or_blank(value) if kind in {"class", "dataclass", "function", "callable"} else ""
        doc = _first_doc_line(value)
        if not doc and kind == "constant":
            # Show the literal for constants when no docstring is available.
            doc = f"value: ``{value!r}``" if not isinstance(value, ModuleType) else ""
        section = _category_for(name, value)
        buckets.setdefault(section, []).append((name, kind, module, sig, doc))
    for entries in buckets.values():
        entries.sort(key=lambda row: row[0])
    return buckets


def collect_unresolved() -> list[tuple[str, str]]:
    """Report any ``__all__`` entry that fails to resolve via ``getattr``."""
    failures: list[tuple[str, str]] = []
    for name in sorted(slappyengine.__all__):
        try:
            getattr(slappyengine, name)
        except Exception as exc:  # pragma: no cover - diagnostic only
            failures.append((name, f"{type(exc).__name__}: {exc}"))
    return failures


# ---------------------------------------------------------------------------
# Subpackage surface
# ---------------------------------------------------------------------------


def collect_subpackages(names: Iterable[str]) -> list[tuple[str, str, list[str], list[str]]]:
    """Return ``[(name, doc, public_attrs, inner_modules), ...]``."""
    out: list[tuple[str, str, list[str], list[str]]] = []
    for name in sorted(names):
        try:
            module = importlib.import_module(f"slappyengine.{name}")
        except Exception as exc:
            out.append((name, f"(import failed: {type(exc).__name__}: {exc})", [], []))
            continue
        attrs = [
            n for n in sorted(dir(module))
            if not n.startswith("_") and n != "annotations"
        ]
        inner: list[str] = []
        if hasattr(module, "__path__"):
            inner = sorted(info.name for info in pkgutil.iter_modules(module.__path__))
        out.append((name, _first_doc_line(module), attrs, inner))
    return out


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


HEADER = """# SlapPyEngine v0.3 — Engine Surface Reference

> Auto-generated from runtime introspection of `slappyengine.__all__` and the
> `_subpackages` set declared in `python/slappyengine/__init__.py`.
> **Do not hand-edit.** Re-run `python scripts/gen_engine_surface_doc.py` to
> refresh after surface changes.

v0.3 is the first "Rust engine, Python wrapper" release. Hot paths are
native; Python is glue, ergonomics, and config. Ships on PyPI as
`slappy-engine`.

* Engine version (runtime): `{version}`
* Native `_core` available: `{has_native}`
* Top-level names in `__all__`: **{n_top}**
* Declared subpackages: **{n_subs}**

"""

UNRESOLVED_HEADER = """## Unresolved names

The following entries appear in `__all__` but failed to resolve via
`getattr(slappyengine, name)`. They need fixing or removal from `_LAZY_MAP`.

"""


def render() -> str:
    subpackage_names = discover_subpackages()
    unresolved = collect_unresolved()
    buckets = collect_top_level()
    sub_rows = collect_subpackages(subpackage_names)

    lines: list[str] = []
    lines.append(HEADER.format(
        version=slappyengine.__version__,
        has_native=slappyengine.HAS_NATIVE,
        n_top=len(slappyengine.__all__),
        n_subs=len(subpackage_names),
    ))

    if unresolved:
        lines.append(UNRESOLVED_HEADER)
        for name, err in unresolved:
            lines.append(f"- `{name}` — {err}")
        lines.append("")

    # --- Top-level surface ----------------------------------------------------
    lines.append("## Top-level surface (`import slappyengine`)\n")
    lines.append(
        "Every name below is reachable as `slappyengine.<Name>`. Module column "
        "is relative to `slappyengine.`. Signatures shown where introspectable."
    )
    lines.append("")

    # Preserve a stable section order: rules order, then "Other" last.
    section_order: list[str] = []
    seen: set[str] = set()
    for _, label in SECTION_RULES:
        if label not in seen and label in buckets:
            section_order.append(label)
            seen.add(label)
    for label in buckets:
        if label not in seen:
            section_order.append(label)
            seen.add(label)

    for section in section_order:
        rows = buckets[section]
        lines.append(f"### {section}\n")
        lines.append("| Name | Kind | Module | Signature | Description |")
        lines.append("|---|---|---|---|---|")
        for name, kind, module, sig, doc in rows:
            sig_md = f"`{sig}`" if sig else ""
            mod_md = f"`{module}`" if module else ""
            lines.append(
                f"| `{name}` | {kind} | {mod_md} | {sig_md} | {doc} |"
            )
        lines.append("")

    # --- Subpackages ----------------------------------------------------------
    lines.append("## Subpackages\n")
    lines.append(
        "These are the modules exposed via `slappyengine.__getattr__` — accessing "
        "`slappyengine.<name>` lazy-imports them. Each row lists the public "
        "attributes currently exposed by the subpackage and its inner modules."
    )
    lines.append("")
    for name, doc, attrs, inner in sub_rows:
        lines.append(f"### `slappyengine.{name}`\n")
        if doc:
            lines.append(f"{doc}\n")
        if attrs:
            lines.append("**Public attributes:** " + ", ".join(f"`{a}`" for a in attrs))
        else:
            lines.append("**Public attributes:** _(none exposed at package level)_")
        lines.append("")
        if inner:
            lines.append("**Inner modules:** " + ", ".join(f"`{m}`" for m in inner))
            lines.append("")

    # --- Stability ------------------------------------------------------------
    lines.append("## Stability notes\n")
    lines.append("### Stable (v0.3 — committed contract)\n")
    lines.append(
        f"- The {len(slappyengine.__all__)} top-level lazy exports listed above."
    )
    lines.append(
        f"- The {len(subpackage_names)} declared subpackages: "
        + ", ".join(f"`{n}`" for n in subpackage_names)
        + "."
    )
    lines.append("")
    lines.append("### Beta (may evolve)\n")
    lines.append(
        "- Anything inside a subpackage that is **not** re-exported at the top "
        "level. Subpackage internals may move between point releases; pin a "
        "specific `slappy-engine` version if you rely on them directly."
    )
    lines.append(
        "- `slappyengine.ext.*` — back-compat shim namespace; superseded by "
        "the top-level lazy exports."
    )
    lines.append("")
    lines.append("### Deprecated (kept for back-compat, will be removed)\n")
    lines.append(
        "- Anything not present in `__all__` or `_subpackages`. Old modules "
        "live on disk for migration but are not part of the contract."
    )
    lines.append("")

    # --- Getting started ------------------------------------------------------
    lines.append("## Getting started\n")
    lines.append("```python")
    lines.append("import slappyengine as sle")
    lines.append("")
    lines.append('engine = sle.Engine(title="My Game", width=640, height=360)')
    lines.append('layer = engine.add_layer("world", sle.Layer2D(tile_size=16))')
    lines.append("engine.run()")
    lines.append("```")
    lines.append("")
    lines.append(
        "See the `examples/` directory for runnable scenes that exercise the "
        "surface above (hello world, lighting, physics, layered character, "
        "multiplayer, HUD, landscape, baking, 3D layers, editor)."
    )
    lines.append("")

    # --- Tripwires ------------------------------------------------------------
    lines.append("## Game integration tripwires\n")
    lines.append(
        "Downstream games (e.g. Ochema Circuit, Bullet Strata) pin the names "
        "they import from this engine. When a game ships against a new engine "
        "name, add a tripwire test that asserts the name remains importable — "
        "removing any locked name breaks that game.\n"
    )
    lines.append(
        "Today the locked names are simply everything in "
        "`slappyengine.__all__` plus the declared subpackages, both of which "
        "are exercised by `tests/test_docs_engine_surface_complete.py`."
    )
    lines.append("")

    return "\n".join(lines)


def main() -> None:
    DOC_PATH.parent.mkdir(parents=True, exist_ok=True)
    DOC_PATH.write_text(render(), encoding="utf-8")
    print(f"wrote {DOC_PATH.relative_to(REPO_ROOT)} ({DOC_PATH.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
