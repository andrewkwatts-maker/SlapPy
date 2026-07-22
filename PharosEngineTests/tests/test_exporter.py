"""Tests for pharos_engine.exporter + slap export CLI (LL6)."""
from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from pharos_engine import exporter, scaffold
from pharos_engine.exporter import (
    BinaryExporter,
    BinaryExportResult,
    BundleResult,
    DEFAULT_EXCLUDES,
    ExportResult,
    MANIFEST_FILENAME,
    ProjectManifest,
    REQUIRED_FILES,
    TARGETS,
    ZipBundler,
    detect_current_platform,
    export_project,
    get_target,
    load_manifest,
    pyinstaller_available,
)
from pharos_engine.exporter.zip_bundler import _is_excluded


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def project(tmp_path: Path) -> Path:
    proj = scaffold.create_project("exporter_probe", tmp_path, editor=False)
    # Litter the project with detritus that must not be shipped
    (proj / "__pycache__").mkdir()
    (proj / "__pycache__" / "junk.pyc").write_bytes(b"\x00\x00")
    (proj / ".git").mkdir()
    (proj / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (proj / "build").mkdir()
    (proj / "build" / "prev.txt").write_text("old build", encoding="utf-8")
    (proj / "assets").mkdir(exist_ok=True)
    (proj / "assets" / "hero.png.txt").write_text("stand-in", encoding="utf-8")
    (proj / "scenes").mkdir(exist_ok=True)
    (proj / "scenes" / "level1.yaml").write_text("name: level1\n", encoding="utf-8")
    (proj / "developer.log").write_text("noise", encoding="utf-8")
    return proj


# ---------------------------------------------------------------------------
# manifest.py
# ---------------------------------------------------------------------------


def test_manifest_defaults_populate_reasonable_values():
    m = ProjectManifest()
    assert m.name == "untitled"
    assert m.main_script == "main.py"
    assert "assets" in m.assets_dirs
    assert m.python_requires.startswith(">=")


def test_manifest_roundtrip_via_yaml():
    m = ProjectManifest(
        name="dune_defender",
        version="1.2.3",
        author="Ada",
        main_script="main.py",
        assets_dirs=["assets", "scenes", "music"],
        python_requires=">=3.11",
    )
    text = m.to_yaml()
    m2 = ProjectManifest.from_yaml(text)
    assert m2 == m


def test_manifest_from_yaml_ignores_unknown_fields():
    text = "name: foo\nversion: 0.1.0\nquantum_flux: yes\n"
    m = ProjectManifest.from_yaml(text)
    assert m.name == "foo"
    assert m.version == "0.1.0"


def test_manifest_load_synthesises_from_scaffolded_project(project: Path):
    m = load_manifest(project)
    assert isinstance(m, ProjectManifest)
    # Config name is the sanitised project name
    assert m.name
    assert "assets" in m.assets_dirs
    assert "scenes" in m.assets_dirs


def test_manifest_load_reads_slappyproject_yaml(project: Path):
    (project / MANIFEST_FILENAME).write_text(
        "name: overridden\nversion: 9.9.9\nauthor: Bob\n"
        "main_script: main.py\nassets_dirs:\n  - assets\npython_requires: '>=3.10'\n",
        encoding="utf-8",
    )
    m = load_manifest(project)
    assert m.name == "overridden"
    assert m.version == "9.9.9"
    assert m.author == "Bob"


def test_manifest_write_and_reload_roundtrip(project: Path, tmp_path: Path):
    m = ProjectManifest(name="alpha", version="0.2.0")
    m.write(project)
    m2 = load_manifest(project)
    assert m2.name == "alpha"
    assert m2.version == "0.2.0"


# ---------------------------------------------------------------------------
# platform_targets.py
# ---------------------------------------------------------------------------


def test_targets_table_has_three_entries():
    assert set(TARGETS) == {"windows", "linux", "macos"}


def test_target_windows_has_exe_extension():
    assert TARGETS["windows"]["executable_ext"] == ".exe"
    assert TARGETS["windows"]["launcher_ext"] == ".bat"


def test_target_posix_targets_have_shell_launchers():
    for key in ("linux", "macos"):
        assert TARGETS[key]["launcher_ext"] == ".sh"
        assert "bash" in TARGETS[key]["launcher_template"]


def test_get_target_auto_resolves_to_host():
    t = get_target("auto")
    assert t is TARGETS[detect_current_platform()]


def test_get_target_unknown_raises():
    with pytest.raises(ValueError):
        get_target("plan9")


# ---------------------------------------------------------------------------
# ZipBundler
# ---------------------------------------------------------------------------


def test_zip_bundler_produces_valid_zip(project: Path, tmp_path: Path):
    output = tmp_path / "bundle.zip"
    result = ZipBundler().bundle(project, output)
    assert isinstance(result, BundleResult)
    assert output.is_file()
    with zipfile.ZipFile(output) as zf:
        assert zf.testzip() is None  # None means "no bad file"


def test_zip_bundler_excludes_git_and_pycache(project: Path, tmp_path: Path):
    output = tmp_path / "bundle.zip"
    ZipBundler().bundle(project, output)
    with zipfile.ZipFile(output) as zf:
        names = zf.namelist()
    assert not any(".git" in n.split("/") for n in names)
    assert not any("__pycache__" in n for n in names)
    assert not any(n.endswith(".pyc") for n in names)


def test_zip_bundler_excludes_build_and_logs(project: Path, tmp_path: Path):
    output = tmp_path / "bundle.zip"
    ZipBundler().bundle(project, output)
    with zipfile.ZipFile(output) as zf:
        names = zf.namelist()
    assert not any(n.startswith("build/") for n in names)
    assert not any(n.endswith(".log") for n in names)


def test_zip_bundler_includes_required_files(project: Path, tmp_path: Path):
    output = tmp_path / "bundle.zip"
    ZipBundler().bundle(project, output)
    with zipfile.ZipFile(output) as zf:
        names = set(zf.namelist())
    for req in REQUIRED_FILES:
        assert req in names, f"expected required file {req!r} in bundle"


def test_zip_bundler_includes_assets_and_scenes(project: Path, tmp_path: Path):
    output = tmp_path / "bundle.zip"
    ZipBundler().bundle(project, output)
    with zipfile.ZipFile(output) as zf:
        names = zf.namelist()
    assert any(n.startswith("assets/") for n in names)
    assert any(n.startswith("scenes/") for n in names)


def test_zip_bundler_include_python_writes_launcher(project: Path, tmp_path: Path):
    output = tmp_path / "bundle.zip"
    result = ZipBundler().bundle(project, output, include_python=True)
    with zipfile.ZipFile(output) as zf:
        names = zf.namelist()
    # Launcher extension depends on host platform
    assert any(n.startswith("run_game.") for n in names)
    # Without SLAPPY_EMBED_PYTHON we fall back to instructions
    if not result.python_bundled:
        assert "PYTHON_SETUP.txt" in names
        assert any("PYTHON_SETUP" in w or "embeddable" in w for w in result.warnings)


def test_zip_bundler_accepts_custom_exclude_patterns(project: Path, tmp_path: Path):
    output = tmp_path / "bundle.zip"
    (project / "README.md").write_text("dev-only readme", encoding="utf-8")
    ZipBundler().bundle(project, output, exclude_patterns=["README.md"])
    with zipfile.ZipFile(output) as zf:
        names = zf.namelist()
    assert "README.md" not in names


def test_zip_bundler_size_reported(project: Path, tmp_path: Path):
    output = tmp_path / "bundle.zip"
    result = ZipBundler().bundle(project, output)
    assert result.size_bytes > 0
    assert result.size_bytes == output.stat().st_size


def test_zip_bundler_raises_when_project_missing(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        ZipBundler().bundle(tmp_path / "does_not_exist", tmp_path / "out.zip")


def test_is_excluded_matches_directory_names():
    assert _is_excluded("foo/__pycache__/bar.pyc", DEFAULT_EXCLUDES)
    assert _is_excluded(".git/HEAD", DEFAULT_EXCLUDES)
    assert not _is_excluded("assets/hero.png", DEFAULT_EXCLUDES)


# ---------------------------------------------------------------------------
# BinaryExporter
# ---------------------------------------------------------------------------


def test_binary_exporter_soft_skips_when_pyinstaller_missing(project: Path, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(exporter.binary_exporter, "pyinstaller_available", lambda: False)
    out = tmp_path / "binary_out"
    result = BinaryExporter().export(project, out)
    assert isinstance(result, BinaryExportResult)
    assert result.spec_path is not None
    assert result.spec_path.is_file()
    assert result.binary_path is None
    assert result.skipped_reason == "PyInstaller not installed"
    assert any("PyInstaller" in w for w in result.warnings)


def test_binary_exporter_dry_run_writes_spec_only(project: Path, tmp_path: Path):
    out = tmp_path / "binary_out"
    result = BinaryExporter().export(project, out, dry_run=True)
    assert result.spec_path is not None and result.spec_path.is_file()
    body = result.spec_path.read_text(encoding="utf-8")
    assert "Analysis" in body
    assert "EXE" in body
    # No binary produced during dry-run
    assert result.binary_path is None


def test_binary_exporter_missing_main_script_errors(tmp_path: Path):
    empty = tmp_path / "empty_project"
    empty.mkdir()
    out = tmp_path / "binary_out"
    result = BinaryExporter().export(empty, out)
    assert any("main script not found" in e for e in result.errors)


def test_binary_exporter_records_datas_for_assets(project: Path, tmp_path: Path):
    out = tmp_path / "binary_out"
    result = BinaryExporter().export(project, out, dry_run=True)
    body = result.spec_path.read_text(encoding="utf-8")
    assert "assets" in body
    assert "config.yaml" in body


def test_pyinstaller_available_returns_bool():
    assert isinstance(pyinstaller_available(), bool)


# ---------------------------------------------------------------------------
# ExportResult + export_project dispatch
# ---------------------------------------------------------------------------


def test_export_result_populated_from_zip(project: Path, tmp_path: Path):
    out = tmp_path / "ship.zip"
    result = export_project(project, out)
    assert isinstance(result, ExportResult)
    assert result.kind == "zip"
    assert result.path == out
    assert result.size_bytes > 0
    assert result.manifest is not None
    assert result.included_files, "expected included_files to be populated"
    assert result.succeeded


def test_export_result_from_binary_dry_run(project: Path, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(exporter.binary_exporter, "pyinstaller_available", lambda: False)
    out_dir = tmp_path / "binary_out"
    result = export_project(project, out_dir)
    assert result.kind == "binary"
    # Even without PyInstaller we return the spec path as `path`
    assert result.path is not None and result.path.suffix == ".spec"
    assert any("PyInstaller" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# CLI: slap export
# ---------------------------------------------------------------------------


def test_cli_export_produces_zip(project: Path, tmp_path: Path):
    out = tmp_path / "cli.zip"
    completed = subprocess.run(
        [sys.executable, "-m", "pharos_engine.cli", "export", str(project),
         "--output", str(out)],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert out.is_file()
    with zipfile.ZipFile(out) as zf:
        assert "main.py" in zf.namelist()
        assert "config.yaml" in zf.namelist()


def test_cli_export_binary_dry_run(project: Path, tmp_path: Path):
    out_dir = tmp_path / "bin_out"
    completed = subprocess.run(
        [sys.executable, "-m", "pharos_engine.cli", "export", str(project),
         "--output", str(out_dir), "--dry-run"],
        capture_output=True,
        text=True,
    )
    # dry_run + missing pyinstaller both surface via warnings but do not fail
    # unless spec generation itself fails.
    assert completed.returncode == 0, completed.stderr


def test_cli_export_help_lists_all_flags():
    completed = subprocess.run(
        [sys.executable, "-m", "pharos_engine.cli", "export", "--help"],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    for flag in ("--output", "--platform", "--include-python", "--icon", "--dry-run"):
        assert flag in completed.stdout
