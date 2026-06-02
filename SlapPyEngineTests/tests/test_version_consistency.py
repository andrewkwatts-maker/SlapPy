"""Sprint-7 ship-readiness: lock version-string consistency across all three
declaration sites.

The version lives in three places that drift independently if you only edit
one of them by hand:

* ``pyproject.toml`` — PyPI metadata (read by ``pip install`` / ``maturin``).
* ``Cargo.toml`` — Rust crate version (read by ``cargo`` / ``maturin``).
* ``python/slappyengine/__init__.py`` — ``slappyengine.__version__`` at
  runtime (what user code sees).

These must match so the wheel users ``pip install`` reports the same string
its ``__version__`` advertises. A drift is almost always a half-finished
release bump.

Note: Rust's SemVer pre-release syntax differs from PEP 440. ``"0.3.0a0"``
in pyproject corresponds to ``"0.3.0-alpha.0"`` in Cargo. The test
normalises both to a canonical form before comparing so the legitimate
syntactic differences don't trip it.
"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

import slappyengine

_ROOT = Path(__file__).resolve().parents[2]


def _read_pyproject_version() -> str:
    data = tomllib.loads((_ROOT / "pyproject.toml").read_text())
    return data["project"]["version"]


def _read_cargo_version() -> str:
    data = tomllib.loads((_ROOT / "Cargo.toml").read_text())
    return data["package"]["version"]


def _normalize(v: str) -> str:
    """Canonicalise a version string for cross-ecosystem comparison.

    PEP 440 writes ``0.3.0a0`` for alpha-0 of 0.3.0; SemVer (Cargo) writes
    ``0.3.0-alpha.0``. They mean the same release. The canonical form here
    strips all separators (``.``, ``-``) and expands the PEP 440 short
    pre-release tags (``a`` / ``b`` / ``rc``) to their long forms so
    equivalent versions across both ecosystems land on the same string.
    """
    s = v.strip().lower()
    # Normalise PEP 440 short forms -> long forms BEFORE stripping separators
    # (otherwise "0.2.0a0" becomes "020a0" and we can't tell the "a" is a
    # pre-release tag versus part of a future hex-like version).
    s = re.sub(r"(\d)a(\d)", r"\1alpha\2", s)
    s = re.sub(r"(\d)b(\d)", r"\1beta\2", s)
    s = re.sub(r"(\d)rc(\d)", r"\1rc\2", s)
    # Now strip all separator characters. Cargo's "0.2.0-alpha.0" and
    # pyproject's "0.2.0alpha0" both reduce to "020alpha0".
    s = s.replace("-", "").replace(".", "")
    return s


def test_versions_match_across_three_files() -> None:
    """The same release must be declared in pyproject, Cargo, and __init__.

    If this fails, one of the three has been bumped without the other two.
    Reconcile manually — do NOT delete this test to make it pass.
    """
    py = _read_pyproject_version()
    rust = _read_cargo_version()
    runtime = slappyengine.__version__

    py_norm = _normalize(py)
    rust_norm = _normalize(rust)
    runtime_norm = _normalize(runtime)

    assert py_norm == rust_norm == runtime_norm, (
        f"Version drift detected:\n"
        f"  pyproject.toml       : {py!r} (normalised: {py_norm!r})\n"
        f"  Cargo.toml           : {rust!r} (normalised: {rust_norm!r})\n"
        f"  __init__.__version__ : {runtime!r} (normalised: {runtime_norm!r})\n"
        f"All three must declare the same release."
    )


def test_candidate_tag_string() -> None:
    """Compute the candidate ship-tag from pyproject and print it.

    Convention: ``v<pyproject_version>`` for finalised releases, with
    ``-candidate`` suffixed while the release is still being vetted (any
    pre-release marker — ``a``, ``b``, ``rc`` — counts as not-yet-final).
    The tag is *not* pushed by this test; it's just computed so the
    sprint-7 checklist has the exact string to use.
    """
    py = _read_pyproject_version()
    is_final = not re.search(r"(a|b|rc|alpha|beta|dev)", py.lower())
    tag = f"v{py}" if is_final else f"v{py}-candidate"
    print(f"\nCANDIDATE_TAG={tag}")
    # Sanity check: tag must start with "v" and contain the version.
    assert tag.startswith("v")
    assert py in tag
