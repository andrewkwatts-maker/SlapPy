"""Batch WGSL shader compile-validator (DD6).

This module walks every shader source shipped by the engine — the three
built-in notebook theme libraries (washi tape, page linings, edge
strokes) plus every ``*.wgsl`` file that lives inside a handful of
well-known subtrees — and runs each source through the AA6
:func:`~pharos_engine.ui.theme.shader_lint.lint_wgsl` linter (which
optionally piggybacks on a real :mod:`wgpu` compile).

The output is a structured :class:`ValidationSummary` plus a
human-readable Markdown report that can be dropped straight into CI
artefacts.

Design constraints
------------------

* **Read-only sweep** — the validator never mutates a shader source
  file. All AA6 read-only library modules stay untouched.
* **wgpu-optional** — if :mod:`wgpu` cannot be imported the walker
  degrades to the source-only lint path. This is signalled by the
  :attr:`ValidationSummary.by_library` payload
  (``wgpu_available: False``).
* **Missing subtrees are silently skipped** — the target directories
  under ``gi/`` and ``post_process/`` may or may not contain WGSL
  files depending on the engine build; a missing directory must not
  crash the sweep.
* **Timing budget** — the sweep records its own wall-clock time and
  short-circuits when a per-file check would push the total past the
  caller-supplied ``timeout_s`` limit. The limit is a soft budget;
  files already in flight always finish so partial results remain
  well-defined.

The CLI entrypoint runs the whole sweep, prints a one-line summary,
and drops ``shader_validation_report.md`` into the current working
directory.
"""
from __future__ import annotations

import io
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from pharos_engine.ui.theme.shader_lint import (
    SHADER_CONTRACTS,
    WGSLLintResult,
    lint_wgsl,
    wgpu_available,
)


# ---------------------------------------------------------------------------
# Public dataclass
# ---------------------------------------------------------------------------


@dataclass
class ValidationSummary:
    """Aggregate result of :func:`validate_all_shaders`.

    Attributes
    ----------
    total:
        Number of shader sources considered.
    passed:
        Sources whose lint / compile came back error-free.
    failed:
        Sources with at least one hard error.
    by_library:
        Mapping from library name (``"washi_tape"``, ``"page_linings"``,
        ``"edge_strokes"``, ``"hello_examples"``, ``"baked_wgsl"``, ...)
        to a per-library dict::

            {
                "total": int,
                "passed": int,
                "failed": int,
                "wgpu_available": bool,
                "results": [ {source_id, size_bytes, errors, warnings,
                              parseable, entry_point_name}, ... ],
            }

    failing_ids:
        Fully-qualified identifiers (``"<library>::<source_id>"``) of
        every failing source, in walk order.
    wall_seconds:
        End-to-end wall-clock time of the sweep in seconds.
    """

    total: int = 0
    passed: int = 0
    failed: int = 0
    by_library: dict[str, dict[str, Any]] = field(default_factory=dict)
    failing_ids: list[str] = field(default_factory=list)
    wall_seconds: float = 0.0


# ---------------------------------------------------------------------------
# Directory targets
# ---------------------------------------------------------------------------


def _repo_root() -> Path:
    """Locate the SlapPyEngine repo root by walking up from this file."""
    here = Path(__file__).resolve()
    # ui/theme/ -> ui/ -> pharos_engine/ -> python/ -> repo root.
    for parent in here.parents:
        if (parent / "python" / "pharos_engine").is_dir():
            return parent
    # Fallback: three levels up.
    return here.parents[4]


def _package_root() -> Path:
    """Locate the ``python/pharos_engine`` directory on disk."""
    return _repo_root() / "python" / "pharos_engine"


#: Directories whose ``*.wgsl`` files get validated by the sweep.
#: Each entry is ``(library_name, relative_path)``. Paths are resolved
#: relative to the ``python/pharos_engine`` package root except where
#: noted.
WGSL_SEARCH_DIRS: list[tuple[str, str]] = [
    ("theme_wgsl", "ui/theme"),
    ("gi_wgsl", "gi"),
    ("post_process_wgsl", "post_process"),
]


HELLO_EXAMPLES_REL = "SlapPyEngineExamples/examples"


# Contract used for free-form ``*.wgsl`` files that were not authored to
# any specific library contract. It relaxes the byte budget (some
# compute kernels are large), keeps the entry-point requirement lenient,
# and does not enforce any uniform list.
_FREEFORM_CONTRACT: Mapping[str, Any] = {
    "max_bytes": 64_000,
    "entry_point": "fs_main",
    "required_uniforms": (),
    "require_location_0": False,
    "forbid_deprecated": True,
}


# ---------------------------------------------------------------------------
# Library iterators
# ---------------------------------------------------------------------------


def _iter_theme_library_sources() -> Iterable[tuple[str, str, str, Mapping[str, Any]]]:
    """Yield ``(library_name, source_id, source, contract)`` for AA6 libs.

    Falls back gracefully if any of the three library modules fail to
    import — we log the failure into the result set instead of raising.
    """
    try:
        from pharos_engine.ui.theme.washi_tape.library import WASHI_TAPES

        for sid, style in WASHI_TAPES.items():
            yield (
                "washi_tape",
                sid,
                style.wgsl_source,
                SHADER_CONTRACTS["washi_tape"],
            )
    except Exception:  # pragma: no cover - defensive
        pass

    try:
        from pharos_engine.ui.theme.page_linings.library import PAGE_LININGS

        for sid, style in PAGE_LININGS.items():
            yield (
                "page_linings",
                sid,
                style.source,
                SHADER_CONTRACTS["page_linings"],
            )
    except Exception:  # pragma: no cover - defensive
        pass

    try:
        from pharos_engine.ui.theme.edge_strokes.library import EDGE_STROKES

        for sid, style in EDGE_STROKES.items():
            yield (
                "edge_strokes",
                sid,
                style.wgsl_source,
                SHADER_CONTRACTS["edge_strokes"],
            )
    except Exception:  # pragma: no cover - defensive
        pass


def _iter_wgsl_files(
    root: Path,
    library_name: str,
) -> Iterable[tuple[str, str, str, Mapping[str, Any]]]:
    """Yield ``(library_name, source_id, source, contract)`` for ``root``.

    ``root`` may be missing; in that case we yield nothing. Files that
    fail to decode as UTF-8 are yielded with an empty source so the
    downstream linter records a hard error against them.
    """
    if not root.is_dir():
        return
    for path in sorted(root.rglob("*.wgsl")):
        try:
            source = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            source = ""
        source_id = path.stem
        yield (library_name, source_id, source, _FREEFORM_CONTRACT)


def _iter_hello_examples() -> Iterable[tuple[str, str, str, Mapping[str, Any]]]:
    """Yield ``(library_name, source_id, source, contract)`` for CC2 examples."""
    examples_root = _repo_root() / HELLO_EXAMPLES_REL
    if not examples_root.is_dir():
        return
    for path in sorted(examples_root.glob("*.wgsl")):
        try:
            source = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            source = ""
        yield ("hello_examples", path.stem, source, _FREEFORM_CONTRACT)


def _iter_baked_wgsl() -> Iterable[tuple[str, str, str, Mapping[str, Any]]]:
    """Yield any ``*.wgsl`` files sitting under ``post_process/baked_chains``."""
    baked_root = _package_root() / "post_process" / "baked_chains"
    if not baked_root.is_dir():
        return
    for path in sorted(baked_root.rglob("*.wgsl")):
        try:
            source = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            source = ""
        yield ("baked_wgsl", path.stem, source, _FREEFORM_CONTRACT)


# ---------------------------------------------------------------------------
# Sweep entrypoint
# ---------------------------------------------------------------------------


def _lint_one(
    library_name: str,
    source_id: str,
    source: str,
    contract: Mapping[str, Any],
) -> WGSLLintResult:
    """Run ``lint_wgsl`` guarded against empty / degenerate sources."""
    if not source:
        return WGSLLintResult(
            source_id=source_id,
            size_bytes=0,
            has_entry_point=False,
            entry_point_name="",
            uniforms=[],
            errors=[(0, "empty or unreadable source file")],
            warnings=[],
            parseable=False,
        )
    try:
        return lint_wgsl(source_id, source, contract=contract)
    except Exception as exc:  # pragma: no cover - defensive
        return WGSLLintResult(
            source_id=source_id,
            size_bytes=len(source.encode("utf-8", errors="ignore")),
            has_entry_point=False,
            entry_point_name="",
            uniforms=[],
            errors=[(0, f"linter raised {type(exc).__name__}: {exc}")],
            warnings=[],
            parseable=False,
        )


def _result_to_dict(result: WGSLLintResult) -> dict[str, Any]:
    """Serialise a :class:`WGSLLintResult` for the summary payload."""
    return {
        "source_id": result.source_id,
        "size_bytes": result.size_bytes,
        "entry_point_name": result.entry_point_name,
        "has_entry_point": result.has_entry_point,
        "uniforms": list(result.uniforms),
        "errors": [list(pair) for pair in result.errors],
        "warnings": [list(pair) for pair in result.warnings],
        "parseable": result.parseable,
    }


def validate_all_shaders(
    *,
    include_hello_examples: bool = True,
    include_baked: bool = True,
    timeout_s: float = 30.0,
    clock: Callable[[], float] | None = None,
) -> ValidationSummary:
    """Walk every registered WGSL corpus and lint each source.

    Parameters
    ----------
    include_hello_examples:
        If ``True`` (default), the sweep also inspects
        ``SlapPyEngineExamples/examples/*.wgsl`` — the CC2
        hello-material-graph fixtures.
    include_baked:
        If ``True`` (default), any ``*.wgsl`` files that live under the
        post-process ``baked_chains`` folder are folded into the sweep
        as the ``baked_wgsl`` library.
    timeout_s:
        Soft wall-clock budget in seconds. If the sweep passes this
        budget while iterating, any *remaining* sources are recorded as
        skipped (they surface with a ``skipped: timeout`` warning) and
        the walk exits. In-flight files always finish.
    clock:
        Optional monotonic clock callable — mainly for tests. Defaults
        to :func:`time.perf_counter`.

    Returns
    -------
    :class:`ValidationSummary`
        Aggregate counts + per-library payload + failing-id list.

    Raises
    ------
    TypeError
        If ``timeout_s`` is not a positive real number.
    """
    if not isinstance(include_hello_examples, bool):
        raise TypeError(
            "validate_all_shaders: include_hello_examples must be bool; "
            f"got {type(include_hello_examples).__name__}"
        )
    if not isinstance(include_baked, bool):
        raise TypeError(
            "validate_all_shaders: include_baked must be bool; "
            f"got {type(include_baked).__name__}"
        )
    if not isinstance(timeout_s, (int, float)) or isinstance(timeout_s, bool):
        raise TypeError(
            "validate_all_shaders: timeout_s must be int or float; "
            f"got {type(timeout_s).__name__}"
        )
    if timeout_s <= 0:
        raise ValueError(
            f"validate_all_shaders: timeout_s must be positive; got {timeout_s!r}"
        )

    clk = clock if clock is not None else time.perf_counter
    start = clk()

    summary = ValidationSummary()
    have_wgpu = wgpu_available()

    def _ensure_library(name: str) -> dict[str, Any]:
        bucket = summary.by_library.get(name)
        if bucket is None:
            bucket = {
                "total": 0,
                "passed": 0,
                "failed": 0,
                "skipped": 0,
                "wgpu_available": have_wgpu,
                "results": [],
            }
            summary.by_library[name] = bucket
        return bucket

    # Assemble the walk. The order matters — CI reports read left-to-right.
    walks: list[Iterable[tuple[str, str, str, Mapping[str, Any]]]] = [
        _iter_theme_library_sources(),
    ]
    pkg_root = _package_root()
    for library_name, rel in WGSL_SEARCH_DIRS:
        walks.append(_iter_wgsl_files(pkg_root / rel, library_name))
    if include_hello_examples:
        walks.append(_iter_hello_examples())
    if include_baked:
        walks.append(_iter_baked_wgsl())

    timed_out = False
    for walk in walks:
        for library_name, source_id, source, contract in walk:
            if timed_out or (clk() - start) > timeout_s:
                timed_out = True
                bucket = _ensure_library(library_name)
                bucket["skipped"] += 1
                bucket["results"].append(
                    {
                        "source_id": source_id,
                        "size_bytes": len(source.encode("utf-8", errors="ignore")),
                        "entry_point_name": "",
                        "has_entry_point": False,
                        "uniforms": [],
                        "errors": [],
                        "warnings": [[0, "skipped: timeout"]],
                        "parseable": False,
                    }
                )
                continue

            result = _lint_one(library_name, source_id, source, contract)
            bucket = _ensure_library(library_name)
            bucket["total"] += 1
            bucket["results"].append(_result_to_dict(result))
            summary.total += 1
            if result.parseable and not result.errors:
                bucket["passed"] += 1
                summary.passed += 1
            else:
                bucket["failed"] += 1
                summary.failed += 1
                summary.failing_ids.append(f"{library_name}::{source_id}")

    summary.wall_seconds = float(clk() - start)
    return summary


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def generate_report(summary: ValidationSummary) -> str:
    """Render *summary* as a Markdown report.

    The report contains:

    * A one-line headline with pass / fail counts and wall time.
    * A per-library table (library, total, passed, failed).
    * A per-source table showing every failing shader with its first
      error message.
    * A per-library appendix listing every source, its byte size, and
      its top-level status glyph.

    Returns
    -------
    str
        The full Markdown text. Always ends with a trailing newline.
    """
    if not isinstance(summary, ValidationSummary):
        raise TypeError(
            "generate_report: summary must be a ValidationSummary; "
            f"got {type(summary).__name__}"
        )

    out = io.StringIO()
    out.write("# WGSL Shader Batch Validation Report\n\n")
    out.write(
        f"Total: {summary.total} | "
        f"Passed: {summary.passed} | "
        f"Failed: {summary.failed} | "
        f"Wall: {summary.wall_seconds:.3f}s\n\n"
    )

    # Per-library summary table.
    out.write("## Per-library summary\n\n")
    out.write("| Library | Total | Passed | Failed | Skipped | wgpu |\n")
    out.write("|---|---:|---:|---:|---:|:---:|\n")
    for name, bucket in summary.by_library.items():
        out.write(
            f"| `{name}` | "
            f"{bucket.get('total', 0)} | "
            f"{bucket.get('passed', 0)} | "
            f"{bucket.get('failed', 0)} | "
            f"{bucket.get('skipped', 0)} | "
            f"{'yes' if bucket.get('wgpu_available') else 'no'} |\n"
        )
    out.write("\n")

    # Failing-source table.
    out.write("## Failing sources\n\n")
    if not summary.failing_ids:
        out.write("_No failures — every source passed lint + wgpu compile._\n\n")
    else:
        out.write("| ID | First error |\n")
        out.write("|---|---|\n")
        for full_id in summary.failing_ids:
            library, source_id = full_id.split("::", 1)
            first_err = ""
            bucket = summary.by_library.get(library, {})
            for entry in bucket.get("results", []):
                if entry.get("source_id") == source_id:
                    if entry.get("errors"):
                        line, issue = entry["errors"][0]
                        first_err = f"(L{line}) {issue}"
                    elif entry.get("warnings"):
                        line, issue = entry["warnings"][0]
                        first_err = f"warn (L{line}) {issue}"
                    break
            # Escape pipes so the Markdown table stays intact.
            safe_err = first_err.replace("|", "\\|")
            out.write(f"| `{full_id}` | {safe_err} |\n")
        out.write("\n")

    # Per-library appendix.
    out.write("## Per-source detail\n\n")
    for name, bucket in summary.by_library.items():
        out.write(f"### `{name}`\n\n")
        results = bucket.get("results", [])
        if not results:
            out.write("_No sources in this library._\n\n")
            continue
        out.write("| Source ID | Bytes | Entry | Status |\n")
        out.write("|---|---:|---|:---:|\n")
        for entry in results:
            status = "PASS" if entry.get("parseable") and not entry.get("errors") else "FAIL"
            entry_name = entry.get("entry_point_name") or "-"
            out.write(
                f"| `{entry.get('source_id', '?')}` | "
                f"{entry.get('size_bytes', 0)} | "
                f"`{entry_name}` | "
                f"{status} |\n"
            )
        out.write("\n")

    return out.getvalue()


def write_report(summary: ValidationSummary, out_path: str | Path) -> Path:
    """Write :func:`generate_report` output to *out_path*.

    Parameters
    ----------
    summary:
        The :class:`ValidationSummary` to render.
    out_path:
        Filesystem path (``str`` or :class:`pathlib.Path`). Parent
        directories are created on demand.

    Returns
    -------
    :class:`pathlib.Path`
        The resolved output path.

    Raises
    ------
    TypeError
        If *out_path* is not a string or :class:`Path`.
    """
    if not isinstance(out_path, (str, Path)):
        raise TypeError(
            "write_report: out_path must be str or Path; "
            f"got {type(out_path).__name__}"
        )
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(generate_report(summary), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# YAML manifest for CI tracking
# ---------------------------------------------------------------------------


def _collect_wgsl_manifest_entries() -> list[dict[str, Any]]:
    """Return one manifest entry per WGSL file on disk + built-in shader.

    Each entry has ``library`` (str), ``source_id`` (str),
    ``origin`` (either ``"embedded"`` or a filesystem path relative to
    the repo root), and ``size_bytes`` (int).
    """
    entries: list[dict[str, Any]] = []
    repo_root = _repo_root()

    # Embedded library sources.
    for library, source_id, source, _contract in _iter_theme_library_sources():
        entries.append(
            {
                "library": library,
                "source_id": source_id,
                "origin": "embedded",
                "size_bytes": len(source.encode("utf-8")),
            }
        )

    pkg_root = _package_root()
    for library_name, rel in WGSL_SEARCH_DIRS:
        root = pkg_root / rel
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.wgsl")):
            try:
                size = path.stat().st_size
            except OSError:  # pragma: no cover - defensive
                size = 0
            try:
                rel_path = path.relative_to(repo_root).as_posix()
            except ValueError:  # pragma: no cover
                rel_path = path.as_posix()
            entries.append(
                {
                    "library": library_name,
                    "source_id": path.stem,
                    "origin": rel_path,
                    "size_bytes": size,
                }
            )

    # Hello examples.
    examples_root = repo_root / HELLO_EXAMPLES_REL
    if examples_root.is_dir():
        for path in sorted(examples_root.glob("*.wgsl")):
            try:
                size = path.stat().st_size
            except OSError:  # pragma: no cover - defensive
                size = 0
            try:
                rel_path = path.relative_to(repo_root).as_posix()
            except ValueError:  # pragma: no cover
                rel_path = path.as_posix()
            entries.append(
                {
                    "library": "hello_examples",
                    "source_id": path.stem,
                    "origin": rel_path,
                    "size_bytes": size,
                }
            )

    return entries


def save_shader_manifest(out_path: str | Path) -> Path:
    """Write a YAML manifest of every WGSL source known to the engine.

    The manifest is intended for CI tracking — downstream jobs can diff
    the file across commits to spot new / removed shaders and byte-size
    regressions without needing to import the engine.

    Falls back to JSON (a strict YAML 1.2 superset) if :mod:`yaml` is
    not importable, matching the pattern already used by
    :mod:`pharos_engine.autosave`.

    Parameters
    ----------
    out_path:
        Filesystem path (``str`` or :class:`pathlib.Path`). Parent
        directories are created on demand.

    Returns
    -------
    :class:`pathlib.Path`
        The resolved output path.

    Raises
    ------
    TypeError
        If *out_path* is not a string or :class:`Path`.
    """
    if not isinstance(out_path, (str, Path)):
        raise TypeError(
            "save_shader_manifest: out_path must be str or Path; "
            f"got {type(out_path).__name__}"
        )
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    entries = _collect_wgsl_manifest_entries()
    payload = {
        "schema": "pharos_engine.shader_manifest",
        "version": 1,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "wgpu_available": wgpu_available(),
        "count": len(entries),
        "shaders": entries,
    }

    try:
        import yaml  # type: ignore[import-not-found]

        text = yaml.safe_dump(
            payload,
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
        )
    except Exception:  # pragma: no cover - env-dependent
        # JSON is a strict subset of YAML 1.2 so any real YAML reader
        # still ingests the fallback.
        text = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False)

    path.write_text(text, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------


def _cli(argv: list[str] | None = None) -> int:
    """Command-line entrypoint. Returns the exit code."""
    summary = validate_all_shaders()
    report_path = Path.cwd() / "shader_validation_report.md"
    write_report(summary, report_path)
    manifest_path = Path.cwd() / "shader_manifest.yaml"
    save_shader_manifest(manifest_path)
    sys.stdout.write(
        f"[shader-batch] total={summary.total} "
        f"passed={summary.passed} "
        f"failed={summary.failed} "
        f"wall={summary.wall_seconds:.3f}s "
        f"report={report_path}\n"
    )
    if summary.failing_ids:
        sys.stdout.write(
            "[shader-batch] failing ids:\n"
        )
        for full_id in summary.failing_ids:
            sys.stdout.write(f"  - {full_id}\n")
    return 0 if summary.failed == 0 else 1


__all__ = [
    "HELLO_EXAMPLES_REL",
    "SHADER_CONTRACTS",
    "ValidationSummary",
    "WGSL_SEARCH_DIRS",
    "generate_report",
    "save_shader_manifest",
    "validate_all_shaders",
    "write_report",
]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli(sys.argv[1:]))
