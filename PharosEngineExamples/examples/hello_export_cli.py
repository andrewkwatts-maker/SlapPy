"""hello_export_cli — programmatic ``slap export`` workflow showcase (OO5).

Companion to the NN7 sprint that polished ``slap export`` with
``--dry-run``, ``--verbose``, ``--exclude PATTERN``, ``--target``, and
``manifest.json`` inclusion.  This demo drives the *Python* face of that
CLI — :func:`pharos_engine.exporter.export_project` — end-to-end so a
tooling author can copy-paste a reference workflow.

Scene
-----

1. Materialise a synthetic project tree under a temp directory::

       proj/
         main.py
         pharosproject.yaml
         assets/
           hero.txt
           enemy.txt
         debug.log            # excluded by --exclude "**/*.log"
         assets/asset.log     # excluded by --exclude "**/*.log"

2. Call :func:`export_project` with ``dry_run=True`` + ``verbose=True``
   and capture the "would add:" listing to stdout — no zip written.
3. Call :func:`export_project` for real with the ``.log`` exclude and
   ``target="all"``; produce a bundled ``manifest.json`` with sha256
   hashes for every packed file.
4. Re-open the produced zip via :mod:`zipfile`, parse the embedded
   ``manifest.json``, print it, and verify that *no* ``.log`` file made
   it in.
5. Write a trace YAML (:file:`hello_export_cli_trace.yaml` next to the
   demo) capturing::

       dry_run_file_count: int
       exclusion_count:    int
       manifest_engine_version: str
       sha256_count:       int
       target_list:        list[str]

The trace is small on purpose — the smoke test only asserts those five
keys plus a couple of derived invariants.

Run
---

::

    python PharosEngineExamples/examples/hello_export_cli.py

No GPU, no game loop, no external services — safe on air-gapped CI.
"""
from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Dict, List


# ---------------------------------------------------------------------------
# Paths / constants
# ---------------------------------------------------------------------------

_THIS_DIR = Path(__file__).resolve().parent
_DEFAULT_TRACE_YAML = _THIS_DIR / "hello_export_cli_trace.yaml"

DEFAULT_TARGET: str = "all"
DEFAULT_EXCLUDE_PATTERNS: tuple[str, ...] = ("**/*.log",)


# ---------------------------------------------------------------------------
# Synthetic project fixture
# ---------------------------------------------------------------------------


def _make_synthetic_project(root: Path) -> Path:
    """Materialise a tiny scaffolded project under *root* and return its dir."""
    proj = root / "hello_export_cli_project"
    proj.mkdir(parents=True, exist_ok=True)

    (proj / "main.py").write_text(
        '"""Synthetic entry point for the hello_export_cli demo."""\n'
        "def main() -> None:\n"
        "    print('hello from exported project')\n"
        "\n"
        "if __name__ == '__main__':\n"
        "    main()\n",
        encoding="utf-8",
    )

    # The exporter loads pharosproject.yaml if present; we also drop a
    # minimal config.yaml so the manifest.name reads back sensibly.
    (proj / "pharosproject.yaml").write_text(
        "name: hello_export_cli\n"
        "version: 0.1.0\n"
        "author: OO5\n"
        "main_script: main.py\n"
        "assets_dirs:\n"
        "  - assets\n"
        "python_requires: '>=3.10'\n",
        encoding="utf-8",
    )
    (proj / "config.yaml").write_text(
        "project:\n"
        "  name: hello_export_cli\n"
        "  version: 0.1.0\n",
        encoding="utf-8",
    )

    assets = proj / "assets"
    assets.mkdir(exist_ok=True)
    (assets / "hero.txt").write_text("hero asset payload\n", encoding="utf-8")
    (assets / "enemy.txt").write_text("enemy asset payload\n", encoding="utf-8")

    # Noise that we expect the --exclude "**/*.log" filter to strip.
    (proj / "debug.log").write_text("debug noise\n", encoding="utf-8")
    (assets / "asset.log").write_text("asset build noise\n", encoding="utf-8")

    return proj


# ---------------------------------------------------------------------------
# Trace writing
# ---------------------------------------------------------------------------


def _write_trace_yaml(payload: Dict[str, Any], path: Path) -> Path:
    """Serialise *payload* to *path* — falls back to ``repr()`` if pyyaml missing."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import yaml
    except Exception:  # pragma: no cover — pyyaml is a hard dep
        path.write_text(repr(payload), encoding="utf-8")
        return path
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Main workflow
# ---------------------------------------------------------------------------


def main(
    *,
    tmp_path: str | Path | None = None,
    trace_yaml_path: str | Path | None = None,
    exclude_patterns: List[str] | None = None,
    target: str = DEFAULT_TARGET,
) -> Dict[str, Any]:
    """Drive the NN7 exporter API end-to-end and return a summary dict.

    Parameters
    ----------
    tmp_path:
        Optional pre-created temp directory. When ``None`` the demo
        provisions one via :func:`tempfile.mkdtemp` and *does not* clean
        it up — the caller (usually a test) owns the lifecycle.
    trace_yaml_path:
        Explicit destination for the trace YAML. Defaults to
        ``hello_export_cli_trace.yaml`` next to this demo.
    exclude_patterns:
        Optional override for the real-export exclude patterns. Defaults
        to ``["**/*.log"]``.
    target:
        Value passed through to ``manifest_targets``. Defaults to
        ``"all"``.
    """
    from pharos_engine import __version__ as engine_version
    from pharos_engine.exporter import export_project

    if exclude_patterns is None:
        exclude_patterns = list(DEFAULT_EXCLUDE_PATTERNS)

    owns_tmp = tmp_path is None
    if tmp_path is None:
        tmp_path = Path(tempfile.mkdtemp(prefix="hello_export_cli_"))
    else:
        tmp_path = Path(tmp_path)
        tmp_path.mkdir(parents=True, exist_ok=True)

    project_dir = _make_synthetic_project(tmp_path)
    output_zip = tmp_path / "hello_export_cli.zip"

    # ---- Step 1: dry run ------------------------------------------------
    # Capture the "would add:" listing into a buffer so we can echo it
    # AND include it in the summary without polluting stdout uncontrollably.
    dry_stream = io.StringIO()
    dry_result = export_project(
        project_dir,
        output_zip,
        dry_run=True,
        verbose=True,
        verbose_stream=dry_stream,
        write_manifest_json=True,
        manifest_targets=[target],
    )
    dry_listing = dry_stream.getvalue()
    dry_run_file_count = len(dry_result.included_files)

    print("=== hello_export_cli: dry-run listing ===")
    print(dry_listing.rstrip() or "(empty)")
    print(f"(dry-run: would add {dry_run_file_count} files)")

    # ---- Step 2: real export -------------------------------------------
    real_result = export_project(
        project_dir,
        output_zip,
        exclude_patterns=exclude_patterns,
        write_manifest_json=True,
        manifest_targets=[target],
    )
    if not real_result.succeeded:
        raise RuntimeError(
            f"real export failed: errors={real_result.errors} "
            f"warnings={real_result.warnings}"
        )
    assert output_zip.is_file(), f"expected zip at {output_zip}"

    # ---- Step 3: inspect zip + parse manifest.json ---------------------
    with zipfile.ZipFile(output_zip, "r") as zf:
        namelist = zf.namelist()
        with zf.open("manifest.json") as fh:
            manifest = json.load(fh)

    print("=== hello_export_cli: manifest.json ===")
    print(json.dumps(manifest, indent=2, sort_keys=True))

    # ---- Step 4: exclusion sanity --------------------------------------
    log_files_in_zip = [name for name in namelist if name.endswith(".log")]
    if log_files_in_zip:
        raise AssertionError(
            f"exclude pattern failed: {log_files_in_zip} present in zip"
        )
    exclusion_count = len(real_result.included_files) and len(
        # `excluded_files` isn't projected onto ExportResult; the reliable
        # signal is: how many .log files did the fixture create, minus
        # how many made it in? Since none should make it in, count the
        # fixture's .log seeds directly.
        [p for p in project_dir.rglob("*.log") if p.is_file()]
    )

    # ---- Step 5: manifest hash summary --------------------------------
    manifest_files: List[Dict[str, Any]] = list(manifest.get("files", []))
    sha256_count = sum(1 for entry in manifest_files if entry.get("sha256"))
    manifest_engine_version = str(manifest.get("engine_version", ""))
    target_list = list(manifest.get("targets", []))

    # ---- Step 6: write trace YAML -------------------------------------
    trace_payload: Dict[str, Any] = {
        "dry_run_file_count": int(dry_run_file_count),
        "exclusion_count": int(exclusion_count),
        "manifest_engine_version": manifest_engine_version,
        "sha256_count": int(sha256_count),
        "target_list": target_list,
    }
    out_trace = (
        Path(trace_yaml_path)
        if trace_yaml_path is not None
        else _DEFAULT_TRACE_YAML
    )
    _write_trace_yaml(trace_payload, out_trace)

    summary: Dict[str, Any] = {
        **trace_payload,
        "engine_version": engine_version,
        "project_dir": str(project_dir),
        "output_zip": str(output_zip),
        "trace_path": str(out_trace),
        "zip_namelist": namelist,
        "manifest_files": manifest_files,
        "dry_listing": dry_listing,
        "owns_tmp": owns_tmp,
        "tmp_root": str(tmp_path),
    }

    print("=== hello_export_cli summary ===")
    for key in (
        "dry_run_file_count",
        "exclusion_count",
        "manifest_engine_version",
        "sha256_count",
        "target_list",
        "output_zip",
        "trace_path",
    ):
        print(f"  {key}: {summary[key]}")

    return summary


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _honour_headless_env() -> None:
    """Respect ``SLAPPY_HEADLESS=1`` as an env-flag override for parity."""
    if os.environ.get("SLAPPY_HEADLESS", "").strip() in ("", "0"):
        os.environ.setdefault("SLAPPY_HEADLESS", "1")


if __name__ == "__main__":
    _honour_headless_env()
    main()
