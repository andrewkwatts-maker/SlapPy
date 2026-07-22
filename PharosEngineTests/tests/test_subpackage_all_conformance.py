"""Subpackage ``__all__`` conformance tripwire.

After two weeks of agents adding exports incrementally, every
``python/pharos_engine/<subpkg>/__init__.py`` should:

* declare a non-empty ``__all__`` (unless the file is an empty marker —
  ``assets``, ``build``, ``tools``, ``tests`` are intentionally empty);
* keep ``__all__`` alphabetised (a sorted list is grep-friendly and
  diff-stable when symbols are added);
* expose nothing whose name begins with ``_`` (private symbols are not
  part of the public surface — the lone exception is the ``_compat``
  shim which is itself private);
* have every name in ``__all__`` actually resolve via ``getattr(pkg, name)``.

This test pins those four invariants per subpackage so a future agent
extending an export list cannot silently drift back into the
un-alphabetised state.

The list of subpackages below is intentionally hard-coded — discovering
it dynamically via ``pkgutil.iter_modules`` would skip the ``ext/``
shims because they re-export and the resulting test would be opaque if
a new subpackage was added without anyone updating this file.
"""
from __future__ import annotations

import importlib
from typing import Sequence

import pytest


# Subpackages with a non-empty ``__all__``. Each is a top-level package
# under ``pharos_engine.*`` (or, for ``ui.editor`` / ``ui.widgets``, a
# documented nested subpackage). Empty marker packages (``assets``,
# ``build``, ``tests``, ``tools``) are listed separately below.
_SUBPACKAGES_WITH_ALL: tuple[str, ...] = (
    "pharos_engine.ai",
    "pharos_engine.animation",
    "pharos_engine.compute",
    "pharos_engine.dynamics",
    "pharos_engine.ext",
    "pharos_engine.gi",
    "pharos_engine.gpu",
    "pharos_engine.input",
    "pharos_engine.iso",
    "pharos_engine.material",
    "pharos_engine.modules",
    "pharos_engine.net",
    "pharos_engine.numerics",
    "pharos_engine.physics",
    "pharos_engine.post_process",
    "pharos_engine.residency",
    "pharos_engine.telemetry",
    "pharos_engine.testing",
    "pharos_engine.thermal",
    "pharos_engine.topology",
    "pharos_editor.ui",
    "pharos_editor.ui.editor",
    "pharos_editor.ui.widgets",
    "pharos_engine.zones",
)


# Empty marker packages — intentionally empty ``__init__.py`` files.
# They exist to make the directory importable as a Python package
# (``pharos_engine.assets`` holds ``database.py``, ``pharos_engine.tools``
# holds individual CLI helpers, etc.) without re-exporting anything.
_EMPTY_MARKER_SUBPACKAGES: tuple[str, ...] = (
    "pharos_engine.assets",
    "pharos_engine.build",
    "pharos_engine.tools",
)


def _import(pkg_name: str):
    """Import the named subpackage and return the module object."""
    return importlib.import_module(pkg_name)


@pytest.mark.parametrize("pkg_name", _SUBPACKAGES_WITH_ALL)
def test_all_exists_and_nonempty(pkg_name: str) -> None:
    """Every listed subpackage must declare a non-empty ``__all__``."""
    pkg = _import(pkg_name)
    assert hasattr(pkg, "__all__"), (
        f"{pkg_name}.__all__ is missing — every public subpackage "
        f"must declare its public surface explicitly."
    )
    names: Sequence[str] = pkg.__all__  # type: ignore[assignment]
    assert isinstance(names, (list, tuple)), (
        f"{pkg_name}.__all__ must be a list or tuple; got {type(names).__name__}"
    )
    assert len(names) > 0, (
        f"{pkg_name}.__all__ is empty — drop it entirely or add the "
        f"package to ``_EMPTY_MARKER_SUBPACKAGES`` in this test."
    )


@pytest.mark.parametrize("pkg_name", _SUBPACKAGES_WITH_ALL)
def test_all_is_sorted(pkg_name: str) -> None:
    """``__all__`` must be alphabetised (case-sensitive ASCII sort).

    Sorted lists keep diffs minimal when symbols are added and make it
    obvious whether a candidate name already exists.
    """
    pkg = _import(pkg_name)
    names = list(pkg.__all__)
    expected = sorted(names)
    assert names == expected, (
        f"{pkg_name}.__all__ is not alphabetised.\n"
        f"  current : {names!r}\n"
        f"  expected: {expected!r}"
    )


@pytest.mark.parametrize("pkg_name", _SUBPACKAGES_WITH_ALL)
def test_all_names_resolve(pkg_name: str) -> None:
    """Every name in ``__all__`` must resolve via ``getattr(pkg, name)``.

    This catches the common drift where a symbol is added to ``__all__``
    but the matching ``_LAZY_MAP`` entry is forgotten — or vice versa.

    ``pharos_engine.ext`` is a special case: its ``__all__`` enumerates
    *submodules* (``ai``, ``lighting``, ...), not symbols. Submodules
    become attributes on the parent package only after they're imported.
    We give that single subpackage a one-shot import + retry rather than
    plumbing an exception around every other check.
    """
    pkg = _import(pkg_name)
    missing: list[str] = []
    for name in pkg.__all__:
        try:
            getattr(pkg, name)
        except AttributeError:
            # Retry once — for ``ext`` the name is a submodule that
            # needs an explicit ``import_module`` to attach.
            try:
                importlib.import_module(f"{pkg_name}.{name}")
                getattr(pkg, name)
            except (AttributeError, ImportError) as exc:  # noqa: PERF203
                missing.append(f"{name} ({type(exc).__name__}: {exc})")
        except ImportError as exc:  # noqa: PERF203
            missing.append(f"{name} ({type(exc).__name__}: {exc})")
    assert not missing, (
        f"{pkg_name}: names listed in __all__ failed to resolve:\n  "
        + "\n  ".join(missing)
    )


@pytest.mark.parametrize("pkg_name", _SUBPACKAGES_WITH_ALL)
def test_no_leading_underscore_exports(pkg_name: str) -> None:
    """No name in ``__all__`` may begin with ``_``.

    Leading-underscore symbols are private by convention; exposing them
    in ``__all__`` defeats the convention and leaks internal helpers.
    """
    pkg = _import(pkg_name)
    leaked = [name for name in pkg.__all__ if name.startswith("_")]
    assert not leaked, (
        f"{pkg_name}.__all__ exposes leading-underscore symbols (which "
        f"are private by convention): {leaked!r}"
    )


@pytest.mark.parametrize("pkg_name", _EMPTY_MARKER_SUBPACKAGES)
def test_empty_marker_subpackages_have_no_all(pkg_name: str) -> None:
    """Empty marker packages must not declare ``__all__``.

    These directories are intentionally bare so importing them does not
    pull in heavy submodules. If a future change adds an ``__all__`` to
    one of them, it must also move out of this list into
    ``_SUBPACKAGES_WITH_ALL`` so the alphabetisation / no-underscore
    invariants apply.
    """
    pkg = _import(pkg_name)
    # ``__all__`` may exist as an attribute via inheritance / dunder
    # default; the marker invariant is that it isn't defined in the
    # package's own ``__init__.py`` namespace.
    own_all = pkg.__dict__.get("__all__")
    assert own_all is None, (
        f"{pkg_name} is listed as an empty marker but defines __all__ = "
        f"{own_all!r}. Move it into ``_SUBPACKAGES_WITH_ALL`` so the "
        f"sort / resolve / no-underscore invariants apply."
    )


def test_ext_shim_inherits_canonical_all() -> None:
    """``ext.<sub>`` shims must propagate ``__all__`` from the canonical home.

    The six ``ext/*`` shims (``ai``, ``animation``, ``input``, ``iso``,
    ``net``, ``ui``) use ``from <canonical> import __all__`` so the two
    import paths expose an identical surface. This pins that identity.
    """
    pairs = (
        ("pharos_engine.ext.ai", "pharos_engine.ai"),
        ("pharos_engine.ext.animation", "pharos_engine.animation"),
        ("pharos_engine.ext.input", "pharos_engine.input"),
        ("pharos_engine.ext.iso", "pharos_engine.iso"),
        ("pharos_engine.ext.net", "pharos_engine.net"),
        ("pharos_engine.ext.ui", "pharos_editor.ui"),
    )
    for shim_name, canonical_name in pairs:
        shim = _import(shim_name)
        canonical = _import(canonical_name)
        assert list(shim.__all__) == list(canonical.__all__), (
            f"{shim_name}.__all__ drifted from {canonical_name}.__all__:\n"
            f"  shim     : {list(shim.__all__)!r}\n"
            f"  canonical: {list(canonical.__all__)!r}"
        )


def test_top_level_all_resolves() -> None:
    """Every name in ``pharos_engine.__all__`` must be resolvable.

    The top-level package uses PEP 562 ``__getattr__`` over a
    ``_LAZY_MAP`` so this is the strongest single-line check that no
    entry has been left dangling after the recent flurry of additions.
    """
    pkg = _import("pharos_engine")
    missing: list[str] = []
    for name in pkg.__all__:
        try:
            getattr(pkg, name)
        except (AttributeError, ImportError) as exc:  # noqa: PERF203
            missing.append(f"{name} ({type(exc).__name__}: {exc})")
    assert not missing, (
        "pharos_engine.__all__ entries failed to resolve:\n  "
        + "\n  ".join(missing)
    )
