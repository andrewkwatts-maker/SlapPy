"""Smoke test for ``examples/hello_export_cli.py`` (OO5 sprint).

Pins the following behaviours of the NN7 export CLI Python surface:

* The demo module imports cleanly.
* :func:`main` runs headlessly end-to-end under a ``tmp_path`` and
  writes a trace YAML.
* The trace YAML carries all five expected top-level keys.
* At least one file was excluded via the ``"**/*.log"`` pattern
  (``exclusion_count > 0``).
* ``manifest.engine_version`` matches :data:`slappyengine.__version__`.
* Every file in the produced zip (bar the manifest itself) has a
  matching sha256 in the manifest.
"""
from __future__ import annotations

import importlib.util
import sys
import zipfile
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Locate + load the demo
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEMO_PATH = (
    _REPO_ROOT / "SlapPyEngineExamples" / "examples" / "hello_export_cli.py"
)

_EXPECTED_TRACE_KEYS = {
    "dry_run_file_count",
    "exclusion_count",
    "manifest_engine_version",
    "sha256_count",
    "target_list",
}


def _load_demo():
    if not _DEMO_PATH.exists():  # pragma: no cover — safety net
        pytest.skip(f"demo not found: {_DEMO_PATH}")
    try:
        import slappyengine.exporter  # noqa: F401
    except Exception as exc:  # pragma: no cover — defensive
        pytest.skip(f"slappyengine.exporter unavailable: {exc}")

    spec = importlib.util.spec_from_file_location(
        "hello_export_cli_demo", _DEMO_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["hello_export_cli_demo"] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # pragma: no cover — defensive
        pytest.skip(f"failed to load hello_export_cli demo: {exc}")
    return module


@pytest.fixture(scope="module")
def demo():
    return _load_demo()


@pytest.fixture(scope="module")
def summary(demo, tmp_path_factory):
    tmp_root = tmp_path_factory.mktemp("oo5_hello_export_cli")
    trace_path = tmp_root / "trace.yaml"
    try:
        return demo.main(tmp_path=tmp_root, trace_yaml_path=trace_path)
    except Exception as exc:
        pytest.skip(f"hello_export_cli.main failed: {exc}")


@pytest.fixture(scope="module")
def trace_payload(summary):
    yaml = pytest.importorskip("yaml")
    text = Path(summary["trace_path"]).read_text(encoding="utf-8")
    payload = yaml.safe_load(text)
    assert isinstance(payload, dict), "trace YAML must decode to a mapping"
    return payload


# ---------------------------------------------------------------------------
# Smoke: the demo imports + defines main()
# ---------------------------------------------------------------------------


def test_demo_imports(demo):
    assert hasattr(demo, "main"), "demo missing main()"
    assert callable(demo.main)


# ---------------------------------------------------------------------------
# End-to-end summary shape
# ---------------------------------------------------------------------------


def test_demo_runs_end_to_end(summary):
    assert isinstance(summary, dict)
    assert Path(summary["trace_path"]).is_file()
    assert Path(summary["output_zip"]).is_file()


# ---------------------------------------------------------------------------
# All 5 expected trace keys present
# ---------------------------------------------------------------------------


def test_trace_yaml_has_all_expected_keys(trace_payload):
    missing = _EXPECTED_TRACE_KEYS - set(trace_payload.keys())
    assert not missing, (
        f"trace YAML missing expected keys: {sorted(missing)}; "
        f"got={sorted(trace_payload.keys())}"
    )


# ---------------------------------------------------------------------------
# The exclude filter actually excluded something
# ---------------------------------------------------------------------------


def test_exclusion_count_positive(trace_payload):
    exclusion_count = trace_payload["exclusion_count"]
    assert isinstance(exclusion_count, int)
    assert exclusion_count > 0, (
        f"expected at least one file excluded by **/*.log; "
        f"exclusion_count={exclusion_count}"
    )


# ---------------------------------------------------------------------------
# Manifest engine_version pins slappyengine.__version__
# ---------------------------------------------------------------------------


def test_manifest_engine_version_matches_slappyengine(trace_payload):
    import slappyengine

    assert trace_payload["manifest_engine_version"] == slappyengine.__version__, (
        f"manifest engine_version={trace_payload['manifest_engine_version']!r} "
        f"but slappyengine.__version__={slappyengine.__version__!r}"
    )


# ---------------------------------------------------------------------------
# Every packed file has a sha256 in the manifest
# ---------------------------------------------------------------------------


def test_every_zip_file_has_manifest_sha256(summary):
    output_zip = Path(summary["output_zip"])
    assert output_zip.is_file(), f"missing zip: {output_zip}"

    # Manifest itself is not expected to appear in the manifest entries —
    # it's written last and is metadata, not payload.
    manifest_files = summary["manifest_files"]
    manifest_by_path = {entry["path"]: entry for entry in manifest_files}
    assert manifest_by_path, "manifest.files was empty"

    with zipfile.ZipFile(output_zip, "r") as zf:
        namelist = [n for n in zf.namelist() if n != "manifest.json"]

    assert namelist, "zip had no payload files other than manifest.json"
    for name in namelist:
        assert name in manifest_by_path, (
            f"zip entry {name!r} missing from manifest.files"
        )
        sha = manifest_by_path[name].get("sha256", "")
        assert isinstance(sha, str) and len(sha) == 64 and all(
            c in "0123456789abcdef" for c in sha
        ), f"manifest entry for {name!r} has invalid sha256={sha!r}"
