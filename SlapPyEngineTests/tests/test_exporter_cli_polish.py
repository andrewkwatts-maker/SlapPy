"""Polish tests for ``slap export`` — NN7.

Covers the six new features layered on top of LL6/MM1:

* ``--dry-run`` for zip export (validates + lists, no zip written)
* ``--verbose`` prints per-file lines to stdout
* ``--exclude PATTERN`` (repeatable) drops matching files
* ``manifest.json`` written inside the zip with all 4 required keys
* Missing project dir surfaces a clean one-line error (no stack trace)
* Bad ``--target`` value is rejected by argparse
"""
from __future__ import annotations

import hashlib
import io
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from slappyengine import scaffold
from slappyengine.exporter import (
    MANIFEST_JSON_FILENAME,
    TARGETS,
    ZipBundler,
    build_bundle_manifest,
    export_project,
)


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A scaffolded project + typical detritus + a couple of log files."""
    proj = scaffold.create_project("polish_probe", tmp_path, editor=False)
    (proj / "__pycache__").mkdir(exist_ok=True)
    (proj / "__pycache__" / "junk.pyc").write_bytes(b"\x00\x00")
    (proj / "assets").mkdir(exist_ok=True)
    (proj / "assets" / "hero.png.txt").write_text("stand-in", encoding="utf-8")
    (proj / "developer.log").write_text("dev-only noise", encoding="utf-8")
    (proj / "notes.log").write_text("more noise", encoding="utf-8")
    (proj / "README.md").write_text("keep me", encoding="utf-8")
    return proj


# ---------------------------------------------------------------------------
# --dry-run — no zip on disk, file list still populated
# ---------------------------------------------------------------------------


def test_dry_run_via_api_produces_file_list_without_writing_zip(
    project: Path, tmp_path: Path
):
    out = tmp_path / "ship.zip"
    result = export_project(project, out, dry_run=True)
    assert not out.exists(), "dry-run must NOT write the zip"
    assert result.included_files, "dry-run must still populate included_files"
    # Detritus still filtered even in dry-run
    assert not any(n.endswith(".pyc") for n in result.included_files)
    assert not any(n.endswith(".log") for n in result.included_files)
    # main.py + config.yaml still present as they would be in a real bundle
    assert "main.py" in result.included_files
    assert "config.yaml" in result.included_files


def test_dry_run_via_cli_reports_would_export_and_no_zip(
    project: Path, tmp_path: Path
):
    out = tmp_path / "ship.zip"
    completed = subprocess.run(
        [sys.executable, "-m", "slappyengine.cli", "export", str(project),
         "--output", str(out), "--dry-run"],
        capture_output=True, text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert not out.exists(), "CLI --dry-run must NOT write the zip"
    assert "[dry-run]" in completed.stdout
    assert "would be bundled" in completed.stdout


# ---------------------------------------------------------------------------
# --verbose
# ---------------------------------------------------------------------------


def test_verbose_prints_per_file_lines_via_api(project: Path, tmp_path: Path):
    out = tmp_path / "ship.zip"
    buf = io.StringIO()
    result = export_project(
        project, out, verbose=True, verbose_stream=buf,
    )
    text = buf.getvalue()
    assert result.included_files
    # Every included file must appear on its own line, prefixed "adding:"
    assert "adding: main.py" in text
    assert "adding: config.yaml" in text
    # Manifest is written after the walk — also announced
    assert f"adding: {MANIFEST_JSON_FILENAME}" in text


def test_verbose_prints_per_file_lines_via_cli(project: Path, tmp_path: Path):
    out = tmp_path / "ship.zip"
    completed = subprocess.run(
        [sys.executable, "-m", "slappyengine.cli", "export", str(project),
         "--output", str(out), "--verbose"],
        capture_output=True, text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert "adding: main.py" in completed.stdout
    assert "adding: config.yaml" in completed.stdout


# ---------------------------------------------------------------------------
# --exclude PATTERN
# ---------------------------------------------------------------------------


def test_exclude_pattern_skips_log_files_via_api(project: Path, tmp_path: Path):
    out = tmp_path / "ship.zip"
    # *.log is already in DEFAULT_EXCLUDES — pick a non-default pattern
    # (README.md) to prove the flag actually adds new excludes.
    export_project(
        project, out, exclude_patterns=["README.md"],
    )
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
    assert "README.md" not in names


def test_exclude_pattern_skips_arbitrary_glob_via_cli(project: Path, tmp_path: Path):
    (project / "keep_me.txt").write_text("keep", encoding="utf-8")
    (project / "skip_me.tmp").write_text("skip", encoding="utf-8")
    out = tmp_path / "ship.zip"
    completed = subprocess.run(
        [sys.executable, "-m", "slappyengine.cli", "export", str(project),
         "--output", str(out), "--exclude", "*.tmp"],
        capture_output=True, text=True,
    )
    assert completed.returncode == 0, completed.stderr
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
    assert "keep_me.txt" in names
    assert "skip_me.tmp" not in names


def test_exclude_can_be_repeated(project: Path, tmp_path: Path):
    (project / "one.aa").write_text("a", encoding="utf-8")
    (project / "two.bb").write_text("b", encoding="utf-8")
    out = tmp_path / "ship.zip"
    completed = subprocess.run(
        [sys.executable, "-m", "slappyengine.cli", "export", str(project),
         "--output", str(out), "--exclude", "*.aa", "--exclude", "*.bb"],
        capture_output=True, text=True,
    )
    assert completed.returncode == 0, completed.stderr
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
    assert "one.aa" not in names
    assert "two.bb" not in names


# ---------------------------------------------------------------------------
# manifest.json inside the zip
# ---------------------------------------------------------------------------


REQUIRED_MANIFEST_KEYS = {"engine_version", "bundled_at", "targets", "files"}


def test_manifest_json_written_by_zip_bundler_has_required_keys(
    project: Path, tmp_path: Path
):
    out = tmp_path / "ship.zip"
    ZipBundler().bundle(
        project, out,
        write_manifest_json=True,
        manifest_targets=["windows", "linux"],
    )
    with zipfile.ZipFile(out) as zf:
        assert MANIFEST_JSON_FILENAME in zf.namelist()
        data = json.loads(zf.read(MANIFEST_JSON_FILENAME))
    assert REQUIRED_MANIFEST_KEYS <= set(data.keys())
    assert data["targets"] == ["linux", "windows"]  # sorted
    assert isinstance(data["files"], list) and data["files"]
    # engine_version is a non-empty string
    assert isinstance(data["engine_version"], str)
    assert data["engine_version"]
    # ISO-8601 timestamp — very loose sanity check
    assert "T" in data["bundled_at"]


def test_manifest_json_hashes_match_file_contents(project: Path, tmp_path: Path):
    out = tmp_path / "ship.zip"
    ZipBundler().bundle(project, out, write_manifest_json=True)
    with zipfile.ZipFile(out) as zf:
        data = json.loads(zf.read(MANIFEST_JSON_FILENAME))
        for entry in data["files"]:
            body = zf.read(entry["path"])
            assert hashlib.sha256(body).hexdigest() == entry["sha256"]
            assert len(body) == entry["size"]


def test_manifest_targets_all_via_cli(project: Path, tmp_path: Path):
    out = tmp_path / "ship.zip"
    completed = subprocess.run(
        [sys.executable, "-m", "slappyengine.cli", "export", str(project),
         "--output", str(out), "--target", "all"],
        capture_output=True, text=True,
    )
    assert completed.returncode == 0, completed.stderr
    with zipfile.ZipFile(out) as zf:
        data = json.loads(zf.read(MANIFEST_JSON_FILENAME))
    # --target all should fan out to every TARGETS key
    assert set(data["targets"]) == set(TARGETS.keys())


def test_manifest_single_target_via_cli(project: Path, tmp_path: Path):
    out = tmp_path / "ship.zip"
    completed = subprocess.run(
        [sys.executable, "-m", "slappyengine.cli", "export", str(project),
         "--output", str(out), "--target", "linux"],
        capture_output=True, text=True,
    )
    assert completed.returncode == 0, completed.stderr
    with zipfile.ZipFile(out) as zf:
        data = json.loads(zf.read(MANIFEST_JSON_FILENAME))
    assert data["targets"] == ["linux"]


def test_manifest_bad_target_rejected(project: Path, tmp_path: Path):
    out = tmp_path / "ship.zip"
    completed = subprocess.run(
        [sys.executable, "-m", "slappyengine.cli", "export", str(project),
         "--output", str(out), "--target", "atari"],
        capture_output=True, text=True,
    )
    assert completed.returncode != 0
    # argparse writes the error to stderr; make sure it mentions the flag
    assert "target" in completed.stderr.lower()


def test_build_bundle_manifest_helper_direct(project: Path):
    """Direct call to the public helper — hashes + targets + files."""
    manifest = build_bundle_manifest(
        project,
        ["main.py", "config.yaml"],
        targets=["windows"],
    )
    assert REQUIRED_MANIFEST_KEYS <= set(manifest.keys())
    assert manifest["targets"] == ["windows"]
    paths = {e["path"] for e in manifest["files"]}
    assert paths == {"main.py", "config.yaml"}


# ---------------------------------------------------------------------------
# Clean error when project dir is missing / not a project
# ---------------------------------------------------------------------------


def test_missing_project_dir_gives_clean_error_via_cli(tmp_path: Path):
    ghost = tmp_path / "no_such_project"
    out = tmp_path / "ship.zip"
    completed = subprocess.run(
        [sys.executable, "-m", "slappyengine.cli", "export", str(ghost),
         "--output", str(out)],
        capture_output=True, text=True,
    )
    assert completed.returncode == 1
    # No traceback (no "Traceback (most recent call last)")
    assert "Traceback" not in completed.stderr
    # Message must mention the missing dir + start with "error:"
    assert "error:" in completed.stderr
    assert "does not exist" in completed.stderr
    assert str(ghost) in completed.stderr


def test_project_without_main_or_manifest_gives_clean_error_via_cli(tmp_path: Path):
    empty = tmp_path / "empty_dir"
    empty.mkdir()
    out = tmp_path / "ship.zip"
    completed = subprocess.run(
        [sys.executable, "-m", "slappyengine.cli", "export", str(empty),
         "--output", str(out)],
        capture_output=True, text=True,
    )
    assert completed.returncode == 1
    assert "Traceback" not in completed.stderr
    assert "not a SlapPyEngine project" in completed.stderr


def test_missing_project_dir_via_api_returns_errors_not_raise(tmp_path: Path):
    ghost = tmp_path / "no_such_project"
    result = export_project(ghost, tmp_path / "ship.zip")
    assert not result.succeeded
    assert result.errors
    assert any("does not exist" in e for e in result.errors)


# ---------------------------------------------------------------------------
# Regression — help lists all polish flags
# ---------------------------------------------------------------------------


def test_export_help_lists_polish_flags():
    completed = subprocess.run(
        [sys.executable, "-m", "slappyengine.cli", "export", "--help"],
        capture_output=True, text=True,
    )
    assert completed.returncode == 0
    for flag in ("--dry-run", "--verbose", "--exclude", "--target"):
        assert flag in completed.stdout, f"help missing {flag}"
