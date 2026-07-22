"""Tests for the Rust-backend bypass facade (II1, 2026-07-05).

Pins the surface documented in ``docs/rust_bypass_2026_07_05.md``
against the actual :mod:`pharos_engine._core_facade` module.

Tests that require the compiled ``_core`` extension soft-skip when the
extension is absent (headless CI without maturin).  Tests that check
the *contract* (RUST_MODULE_MAP shape, doc/facade cross-check, source
file existence) are hard assertions and run everywhere.
"""
from __future__ import annotations

import importlib
import os
import re
from pathlib import Path

import pytest

from pharos_engine import _core_facade
from pharos_engine._core_facade import (
    RUST_MODULE_MAP,
    _NullCore,
    has_native,
    list_rust_functions,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = REPO_ROOT / "src"
DOC_PATH = REPO_ROOT / "docs" / "rust_bypass_2026_07_05.md"


def _rust_source_files() -> list[str]:
    """Return every ``src/*.rs`` filename except ``lib.rs``.

    ``lib.rs`` is the pymodule entry point and never appears in
    ``RUST_MODULE_MAP``.
    """
    if not SRC_DIR.exists():
        return []
    return sorted(
        p.name
        for p in SRC_DIR.glob("*.rs")
        if p.name != "lib.rs"
    )


# ---------------------------------------------------------------------------
# 1. Facade contract (runs everywhere)
# ---------------------------------------------------------------------------


def test_has_native_returns_bool():
    """`has_native()` must return a plain ``bool``."""
    result = has_native()
    assert isinstance(result, bool)


def test_has_native_when_extension_built():
    """When the compiled ``_core`` is importable, ``has_native()`` is ``True``.

    Soft-skips when the extension isn't built — the point is to verify the
    facade correctly reflects reality, not to require the extension.
    """
    try:
        importlib.import_module("pharos_engine._core")
    except ImportError:
        pytest.skip("pharos_engine._core not compiled — expected on headless CI")
    assert has_native() is True


def test_list_rust_functions_returns_dict():
    """`list_rust_functions()` returns a dict.  Non-empty iff extension built."""
    surface = list_rust_functions()
    assert isinstance(surface, dict)
    if has_native():
        assert surface, "expected non-empty surface with compiled _core"
        for mod, syms in surface.items():
            assert isinstance(mod, str)
            assert isinstance(syms, list)
            assert syms, f"module {mod!r} listed with empty symbol list"
            assert all(isinstance(s, str) for s in syms)
    else:
        assert surface == {}


def test_rust_module_map_shape():
    """Every ``RUST_MODULE_MAP`` entry must have ``src`` / ``symbols`` / ``summary``."""
    assert RUST_MODULE_MAP, "RUST_MODULE_MAP must not be empty"
    for mod, meta in RUST_MODULE_MAP.items():
        assert isinstance(mod, str) and mod, f"bad module key {mod!r}"
        assert set(meta) >= {"src", "symbols", "summary"}, (
            f"module {mod!r} missing required keys, has {set(meta)}"
        )
        assert isinstance(meta["src"], str) and meta["src"].startswith("src/")
        assert meta["src"].endswith(".rs")
        assert isinstance(meta["symbols"], list) and meta["symbols"]
        assert all(isinstance(s, str) and s for s in meta["symbols"])
        assert isinstance(meta["summary"], str) and meta["summary"]


# ---------------------------------------------------------------------------
# 2. Null-core stub semantics (runs everywhere)
# ---------------------------------------------------------------------------


def test_null_core_stub_raises_helpful():
    """`_NullCore.<anything>` must raise ``RuntimeError`` with build hint."""
    stub = _NullCore()
    with pytest.raises(RuntimeError) as excinfo:
        _ = stub.some_missing_attribute
    msg = str(excinfo.value)
    assert "some_missing_attribute" in msg
    assert "maturin" in msg  # points user at the build command


def test_null_core_repr_is_informative():
    """`repr(_NullCore())` must mention that the extension isn't compiled."""
    stub = _NullCore()
    r = repr(stub)
    assert "_NullCore" in r or "unavailable" in r


# ---------------------------------------------------------------------------
# 3. Per-module importability (runs only when extension built)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mod_name", sorted(RUST_MODULE_MAP.keys()))
def test_each_module_importable(mod_name: str):
    """For every module in RUST_MODULE_MAP that's present at runtime,
    ``import pharos_engine._core.<mod_name>`` must work and expose the
    documented symbols."""
    if not has_native():
        pytest.skip("_core not built")
    surface = list_rust_functions()
    if mod_name not in surface:
        pytest.skip(
            f"module {mod_name!r} not present in this wheel "
            "(feature-gated or orphan not baked)"
        )
    # Importing the shim sub-module should not raise.
    shim = importlib.import_module(f"pharos_engine._core.{mod_name}")
    assert shim is not None
    # Every documented symbol must be on the shim.
    for sym in surface[mod_name]:
        assert hasattr(shim, sym), (
            f"symbol {sym!r} promised for module {mod_name!r} "
            "but missing on the sub-module view"
        )


# ---------------------------------------------------------------------------
# 4. Doc / facade cross-check (runs everywhere)
# ---------------------------------------------------------------------------


def test_facade_has_all_documented_modules():
    """Every module named in ``docs/rust_bypass_2026_07_05.md`` §3 must be
    present in ``RUST_MODULE_MAP`` (and vice versa)."""
    if not DOC_PATH.exists():
        pytest.skip(f"doc not found at {DOC_PATH}")
    text = DOC_PATH.read_text(encoding="utf-8")
    # Doc §3 subsection headings are of the form: "### 3.N `<module>` — ..."
    heading_re = re.compile(r"^###\s+3\.\d+\s+`([A-Za-z_][A-Za-z0-9_]*)`", re.M)
    doc_modules = set(heading_re.findall(text))
    facade_modules = set(RUST_MODULE_MAP.keys())
    missing_in_facade = doc_modules - facade_modules
    missing_in_doc = facade_modules - doc_modules
    assert not missing_in_facade, (
        f"doc §3 names modules not in RUST_MODULE_MAP: {missing_in_facade}"
    )
    assert not missing_in_doc, (
        f"RUST_MODULE_MAP has modules not documented in doc §3: {missing_in_doc}"
    )


def test_every_module_map_src_file_exists():
    """`RUST_MODULE_MAP[<mod>]['src']` must point at an existing file."""
    if not SRC_DIR.exists():
        pytest.skip(f"src/ not found at {SRC_DIR}")
    for mod, meta in RUST_MODULE_MAP.items():
        src_rel = meta["src"]
        # Strip the leading "src/" prefix
        assert src_rel.startswith("src/")
        rust_file = REPO_ROOT / src_rel
        assert rust_file.exists(), (
            f"module {mod!r} promises src at {rust_file} but file missing"
        )


def test_every_src_rs_file_has_module_map_entry():
    """Every ``src/*.rs`` file (except ``lib.rs``) must be represented in
    ``RUST_MODULE_MAP``."""
    rust_sources = _rust_source_files()
    if not rust_sources:
        pytest.skip(f"no src/*.rs files found under {SRC_DIR}")
    mapped_srcs = {meta["src"] for meta in RUST_MODULE_MAP.values()}
    for rs in rust_sources:
        expected = f"src/{rs}"
        assert expected in mapped_srcs, (
            f"Rust source {expected} has no entry in RUST_MODULE_MAP — "
            "either add it or exclude explicitly"
        )


# ---------------------------------------------------------------------------
# 5. Sub-module view registration (runs only when extension built)
# ---------------------------------------------------------------------------


def test_submodule_views_have_docstrings():
    """Each registered sub-module view must carry a docstring pointing at
    the Rust source file."""
    if not has_native():
        pytest.skip("_core not built")
    surface = list_rust_functions()
    for mod_name in surface:
        shim = importlib.import_module(f"pharos_engine._core.{mod_name}")
        assert shim.__doc__, f"sub-module {mod_name!r} missing docstring"
        assert "src/" in shim.__doc__, (
            f"sub-module {mod_name!r} docstring must reference src/"
        )


def test_submodule_views_expose_dunder_all():
    """Each registered sub-module view has a populated ``__all__``."""
    if not has_native():
        pytest.skip("_core not built")
    surface = list_rust_functions()
    for mod_name, syms in surface.items():
        shim = importlib.import_module(f"pharos_engine._core.{mod_name}")
        assert hasattr(shim, "__all__"), (
            f"sub-module {mod_name!r} missing __all__"
        )
        assert set(shim.__all__) == set(syms), (
            f"__all__ mismatch for {mod_name!r}: "
            f"{shim.__all__} vs list_rust_functions {syms}"
        )


# ---------------------------------------------------------------------------
# 6. Bypass matches wrapper — behavioural cross-check
# ---------------------------------------------------------------------------


def test_bypass_matches_wrapper_convex_hull():
    """Calling ``_core.hull.convex_hull`` directly must produce the same
    hull as the Python wrapper's high-level path.

    This is the load-bearing invariant of the whole facade design: the
    Python wrapper and the direct bypass agree on inputs and outputs.
    """
    if not has_native():
        pytest.skip("_core not built")
    surface = list_rust_functions()
    if "hull" not in surface or "convex_hull" not in surface["hull"]:
        pytest.skip("hull.convex_hull not present in this wheel")
    hull_mod = importlib.import_module("pharos_engine._core.hull")
    # Direct bypass path.
    pts = [(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0), (1.0, 1.0)]
    direct = hull_mod.convex_hull(pts)
    # Wrapper path — compute.spatial has a private ``_python_convex_hull``
    # fallback that mirrors the Rust kernel's algorithm; use it as the
    # ground-truth comparison target.
    try:
        from pharos_engine.compute import spatial as spatial_wrap
    except ImportError:  # pragma: no cover - defensive
        pytest.skip("compute.spatial wrapper not importable")
    py_fallback = getattr(spatial_wrap, "_python_convex_hull", None)
    if py_fallback is None:
        pytest.skip("compute.spatial has no _python_convex_hull fallback")
    wrapped = py_fallback(pts)
    # Both paths should produce the same set of hull vertices (order may
    # differ due to starting-vertex convention, so compare as sets of
    # rounded tuples).
    def _norm(seq):
        return {(round(x, 5), round(y, 5)) for x, y in seq}
    assert _norm(direct) == _norm(wrapped)


def test_bypass_lz4_roundtrip():
    """Direct ``_core.slap_format`` compress/decompress round-trip."""
    if not has_native():
        pytest.skip("_core not built")
    surface = list_rust_functions()
    if "slap_format" not in surface:
        pytest.skip("slap_format not present in this wheel")
    slap = importlib.import_module("pharos_engine._core.slap_format")
    payload = (b"SlapPyEngine bypass smoke " * 64)
    blob = bytes(slap.lz4_compress(payload))
    assert blob != payload  # compression actually did something
    back = bytes(slap.lz4_decompress(blob))
    assert back == payload


def test_bypass_bounding_box_matches_min_max():
    """`_core.hull.bounding_box` must agree with pure-python min/max."""
    if not has_native():
        pytest.skip("_core not built")
    surface = list_rust_functions()
    if "hull" not in surface or "bounding_box" not in surface["hull"]:
        pytest.skip("hull.bounding_box not present in this wheel")
    hull_mod = importlib.import_module("pharos_engine._core.hull")
    pts = [(1.0, 2.0), (-3.0, 4.0), (5.0, -6.0), (0.5, 0.5)]
    xmin, ymin, xmax, ymax = hull_mod.bounding_box(pts)
    assert xmin == pytest.approx(min(p[0] for p in pts))
    assert ymin == pytest.approx(min(p[1] for p in pts))
    assert xmax == pytest.approx(max(p[0] for p in pts))
    assert ymax == pytest.approx(max(p[1] for p in pts))


# ---------------------------------------------------------------------------
# 7. `core` attribute and namespace hygiene
# ---------------------------------------------------------------------------


def test_facade_exposes_core_attribute():
    """`_core_facade.core` must be either the real ``_core`` or ``_NullCore``."""
    core_obj = _core_facade.core
    if has_native():
        # Real _core module — check for at least one known symbol from a
        # tracked module.
        assert hasattr(core_obj, "convex_hull") or hasattr(core_obj, "solve_ik")
    else:
        assert isinstance(core_obj, _NullCore)


def test_facade_module_all_is_populated():
    """`_core_facade.__all__` must list the public API."""
    assert set(_core_facade.__all__) >= {
        "has_native",
        "list_rust_functions",
        "core",
        "_NullCore",
        "RUST_MODULE_MAP",
    }


# ---------------------------------------------------------------------------
# 8. Doc file lives at the expected path (fails loudly if the II1 doc
#    is removed / renamed without updating this test)
# ---------------------------------------------------------------------------


def test_bypass_doc_exists_and_is_nontrivial():
    """The doc this test file pins must exist and be non-trivial."""
    assert DOC_PATH.exists(), (
        f"bypass doc missing at {DOC_PATH} — "
        "either add it or update this test's DOC_PATH"
    )
    text = DOC_PATH.read_text(encoding="utf-8")
    assert len(text.splitlines()) >= 100, (
        f"bypass doc suspiciously short: {DOC_PATH}"
    )
    # Section headings we depend on.
    assert "## 3." in text, "doc missing §3 module surface"
    assert "## 7." in text, "doc missing §7 full inventory table"
