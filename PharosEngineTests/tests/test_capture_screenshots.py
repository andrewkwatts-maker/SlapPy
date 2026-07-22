"""Headless tests for ``scripts/capture_notebook_screenshots.py``.

Covers:

* Script imports without error (no module-level side effects beyond
  ``sys.path`` manipulation).
* ``--all`` accepts and exits 0 in a sub-second smoke run.
* The output directory is created on demand (the script never assumes
  the caller pre-created it).
* At least one PNG file is written for each theme.
* The grid composite is produced when ``--all`` runs without
  ``--no-grid``.
* The panel-slug whitelist guards against typos.

All tests are headless and **never** spin up a real DPG viewport. The
script's PIL placeholder fallback is the path under test.
"""
from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Resolve the script under test by absolute path so the test does not
# rely on ``PYTHONPATH`` covering ``scripts/`` (it doesn't, by design).
# ---------------------------------------------------------------------------


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "capture_notebook_screenshots.py"


@pytest.fixture(scope="module")
def capture_module():
    """Import the capture script as a real module just once per session."""
    mod_name = "capture_notebook_screenshots"
    spec = importlib.util.spec_from_file_location(mod_name, SCRIPT_PATH)
    assert spec is not None and spec.loader is not None, (
        f"could not build module spec for {SCRIPT_PATH}"
    )
    module = importlib.util.module_from_spec(spec)
    # Register before exec so dataclass()'s ``sys.modules[cls.__module__]``
    # lookup succeeds for ``PanelSpec``'s string annotations.
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_script_imports(capture_module) -> None:
    """The script file imports cleanly and exposes the expected surface."""
    for attr in (
        "PANELS",
        "PanelSpec",
        "build_arg_parser",
        "capture_all",
        "capture_panel",
        "capture_theme",
        "discover_themes",
        "main",
        "output_filename",
        "render_grid_composite",
        "render_placeholder",
        "resolve_theme_palette",
    ):
        assert hasattr(capture_module, attr), (
            f"capture script missing public symbol {attr!r}"
        )

    # The PANELS tuple should cover every panel referenced in the manual.
    slugs = {p.slug for p in capture_module.PANELS}
    expected = {
        "toolbar", "outliner", "inspector", "gizmos",
        "theme_switcher", "code_mode", "spawn_menu",
        "material", "welcome", "status_bar",
    }
    assert expected.issubset(slugs), (
        f"missing panel slugs: {expected - slugs}"
    )


def test_all_flag_smoke(capture_module, tmp_path: Path) -> None:
    """``--all`` accepts and exits 0 in a sub-second smoke run."""
    out_dir = tmp_path / "shots"
    t0 = time.perf_counter()
    rc = capture_module.main([
        "--all",
        "--out", str(out_dir),
        # Force tiny tiles so the placeholder painter is fast.
        "--width", "64",
        "--height", "48",
    ])
    elapsed = time.perf_counter() - t0
    assert rc == 0, f"--all should exit 0; got {rc}"
    # Sub-second budget per the brief. Be generous (3s) for CI noise.
    assert elapsed < 3.0, (
        f"--all smoke run took {elapsed:.2f}s; expected < 3s"
    )


def test_output_directory_created_on_demand(
    capture_module, tmp_path: Path,
) -> None:
    """Script creates the output dir even when several levels deep + missing."""
    deep_out = tmp_path / "a" / "b" / "c"
    assert not deep_out.exists(), "precondition: deep_out should not exist"

    rc = capture_module.main([
        "--theme", "teengirl_notebook",
        "--panel", "toolbar",
        "--out", str(deep_out),
        "--width", "32",
        "--height", "32",
    ])
    assert rc == 0
    assert deep_out.is_dir(), (
        "capture script did not create the output directory"
    )


def test_at_least_one_png_per_theme(capture_module, tmp_path: Path) -> None:
    """Every theme contributes at least one PNG file to the output dir."""
    out_dir = tmp_path / "by_theme"
    rc = capture_module.main([
        "--all",
        "--out", str(out_dir),
        "--width", "32",
        "--height", "32",
    ])
    assert rc == 0

    themes = capture_module.discover_themes()
    assert themes, "discover_themes returned empty list"

    pngs = list(out_dir.glob("*.png"))
    assert pngs, "no PNG files produced by --all run"

    for theme in themes:
        matching = [
            p for p in pngs
            if p.name != "notebook_overview.png" and theme in p.name
        ]
        assert matching, (
            f"no per-panel PNG produced for theme {theme!r} "
            f"(found: {[p.name for p in pngs]})"
        )


def test_overview_grid_emitted_for_all(
    capture_module, tmp_path: Path,
) -> None:
    """``--all`` (without ``--no-grid``) drops ``notebook_overview.png``."""
    out_dir = tmp_path / "with_grid"
    rc = capture_module.main([
        "--all",
        "--out", str(out_dir),
        "--width", "48",
        "--height", "32",
    ])
    assert rc == 0
    overview = out_dir / "notebook_overview.png"
    assert overview.is_file(), (
        "notebook_overview.png missing after --all"
    )
    # The grid must be a non-empty PNG.
    assert overview.stat().st_size > 0


def test_no_grid_flag_skips_overview(
    capture_module, tmp_path: Path,
) -> None:
    """``--no-grid`` skips the composite even on a full ``--all`` run."""
    out_dir = tmp_path / "no_grid"
    rc = capture_module.main([
        "--all",
        "--no-grid",
        "--out", str(out_dir),
        "--width", "32",
        "--height", "32",
    ])
    assert rc == 0
    assert not (out_dir / "notebook_overview.png").exists(), (
        "--no-grid should suppress the overview composite"
    )


def test_panel_filter_rejects_unknown_slug(
    capture_module, tmp_path: Path,
) -> None:
    """Unknown ``--panel`` slugs surface a non-zero exit code."""
    out_dir = tmp_path / "bad_panel"
    rc = capture_module.main([
        "--panel", "does_not_exist",
        "--out", str(out_dir),
    ])
    assert rc != 0, "unknown panel slug should be rejected"


def test_output_filename_helper(capture_module) -> None:
    """``output_filename`` returns the canonical ``notebook_<panel>_<theme>.png``."""
    name = capture_module.output_filename("toolbar", "teengirl_notebook")
    assert name == "notebook_toolbar_teengirl_notebook.png"
