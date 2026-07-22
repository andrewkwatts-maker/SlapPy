"""hello_rust_bypass — direct-to-Rust bypass demo (PP7 sprint, 2026-07-07).

Codifies the 2026-07-05 architectural directive:

    "ensure framework is PY PYPI Lib, wrapping a Rust Accellerated
     backend, users should be able to bypass the py lib if they want."

This demo shows a power user how to **skip the Python wrapper stack**
and call the compiled Rust kernels in :mod:`pharos_engine._core`
directly.  It covers three concrete comparisons on kernels that ship in
every wheel build (no `--features 3d,gi,ibl` required):

* :func:`_core.convex_hull` vs the pure-Python fallback in
  :mod:`pharos_engine.compute.spatial`.
* :func:`_core.compute_bone_lengths` vs a hand-rolled numpy euclidean
  distance loop.
* :func:`_core.lz4_compress` vs :func:`zlib.compress` at the default
  compression level (a rough stand-in for "the wrapper does more work
  than a raw Rust call").

For every comparison the demo records ``(bypass_seconds, wrapper_seconds,
speedup)`` and writes the roll-up to ``hello_rust_bypass_trace.yaml`` so
downstream tests and the docs generator can consume the numbers.

The demo also enumerates every logical Rust sub-module reachable at
runtime — the count matches ``len(_core_facade.list_rust_functions())``
so it's a live inventory of what the local wheel actually shipped.

Run
---

::

    python PharosEngineExamples/examples/hello_rust_bypass.py

Headless-safe; no window, no wgpu, no audio backend.  If the compiled
``_core`` extension is missing (source install without maturin) the
demo prints a helpful pointer and writes an empty-timings trace so the
smoke test can still assert on the trace shape.
"""
from __future__ import annotations

import math
import os
import time
import zlib
from pathlib import Path
from typing import Any, Dict, List, Tuple


# ---------------------------------------------------------------------------
# Paths / constants
# ---------------------------------------------------------------------------

_THIS_DIR = Path(__file__).resolve().parent
_DEFAULT_TRACE_YAML = _THIS_DIR / "hello_rust_bypass_trace.yaml"

# Repeat counts tuned so each kernel runs long enough (~1 ms+) that
# time.perf_counter() resolution isn't the dominant factor.  Kept
# module-level so tests can override for a fast smoke run.
DEFAULT_HULL_POINTS: int = 512
DEFAULT_HULL_REPEATS: int = 200
DEFAULT_BONE_JOINTS: int = 64
DEFAULT_BONE_REPEATS: int = 500
DEFAULT_LZ4_BYTES: int = 4096
DEFAULT_LZ4_REPEATS: int = 200


# ---------------------------------------------------------------------------
# Bench harness helpers
# ---------------------------------------------------------------------------


def _bench(fn, repeats: int) -> float:
    """Return the *median* per-call seconds for ``fn`` over ``repeats`` runs.

    Median (not mean) so a single OS scheduling hiccup doesn't skew the
    result. ``repeats`` should be tuned per-kernel so the total wall
    time stays under ~50 ms per call site.
    """
    if repeats < 1:
        raise ValueError(f"repeats must be >= 1 (got {repeats})")
    samples: List[float] = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        fn()
        samples.append(time.perf_counter() - t0)
    samples.sort()
    return samples[len(samples) // 2]


def _speedup(bypass_s: float, wrapper_s: float) -> float:
    """Return ``wrapper / bypass`` with a tiny-denominator guard.

    A speedup of 1.0 means "no difference"; > 1.0 means the bypass is
    faster than the wrapper.  Guards against divide-by-zero when the
    bypass path measures at the perf_counter noise floor.
    """
    if bypass_s <= 0.0:
        return float("inf")
    return wrapper_s / bypass_s


# ---------------------------------------------------------------------------
# Fixture builders — deterministic input for repeatable timings
# ---------------------------------------------------------------------------


def _make_hull_points(n: int) -> List[Tuple[float, float]]:
    """Points on / near a unit circle — non-trivial hull, no duplicates."""
    pts: List[Tuple[float, float]] = []
    for i in range(n):
        theta = 2.0 * math.pi * i / n
        # Perturb the radius slightly so some points fall inside the
        # eventual hull and the algorithm actually has to reject them.
        r = 1.0 + 0.02 * math.sin(7.0 * theta)
        pts.append((r * math.cos(theta), r * math.sin(theta)))
    return pts


def _make_bone_chain(n_joints: int) -> List[Tuple[float, float]]:
    """A straight bone chain of ``n_joints`` joints along ``+X``."""
    return [(float(i), 0.0) for i in range(n_joints)]


def _make_lz4_payload(n_bytes: int) -> bytes:
    """A repeat-friendly payload so LZ4 finds long matches (realistic)."""
    # 32-byte pattern repeated to ``n_bytes``.  Matches the kind of
    # tile-map / voxel data the .slap container actually compresses.
    pattern = b"pharos_engine-bypass-demo-payload"
    return (pattern * ((n_bytes // len(pattern)) + 1))[:n_bytes]


# ---------------------------------------------------------------------------
# Python-side wrapper equivalents (for the "wrapper vs bypass" comparison)
# ---------------------------------------------------------------------------


def _python_convex_hull(
    points: List[Tuple[float, float]],
) -> List[Tuple[float, float]]:
    """Andrew's monotone chain in pure Python.

    Mirrors :func:`pharos_engine.compute.spatial._python_convex_hull` so
    the comparison is against the same algorithm the wrapper would use
    on a machine without ``_core``.
    """
    if len(points) < 3:
        return list(points)
    pts = sorted(points)

    def _cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list = []
    for p in pts:
        while len(lower) >= 2 and _cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper: list = []
    for p in reversed(pts):
        while len(upper) >= 2 and _cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def _python_bone_lengths(
    joints: List[Tuple[float, float]],
) -> List[float]:
    """Reference implementation of ``_core.compute_bone_lengths``."""
    out: List[float] = []
    for a, b in zip(joints, joints[1:]):
        dx = b[0] - a[0]
        dy = b[1] - a[1]
        out.append(math.sqrt(dx * dx + dy * dy))
    return out


# ---------------------------------------------------------------------------
# YAML writer — same graceful-degradation pattern as hello_positional_audio
# ---------------------------------------------------------------------------


def _write_trace_yaml(payload: Dict[str, Any], path: Path) -> Path:
    try:
        import yaml
    except Exception:  # pragma: no cover — pyyaml is a regular dep
        path.write_text(repr(payload), encoding="utf-8")
        return path
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Enumerate what's reachable at runtime
# ---------------------------------------------------------------------------


def _enumerate_core_submodules() -> Dict[str, List[str]]:
    """Return a ``{submodule: [symbol, ...]}`` map from the live ``_core``.

    Uses :func:`pharos_engine._core_facade.list_rust_functions` — which
    filters :data:`RUST_MODULE_MAP` against actual ``hasattr(_core, ...)``
    presence — so the returned dict reflects the shipping wheel, not
    the theoretical maximum surface.
    """
    from pharos_engine import _core_facade

    if not _core_facade.has_native():
        return {}
    return _core_facade.list_rust_functions()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(
    *,
    hull_points: int = DEFAULT_HULL_POINTS,
    hull_repeats: int = DEFAULT_HULL_REPEATS,
    bone_joints: int = DEFAULT_BONE_JOINTS,
    bone_repeats: int = DEFAULT_BONE_REPEATS,
    lz4_bytes: int = DEFAULT_LZ4_BYTES,
    lz4_repeats: int = DEFAULT_LZ4_REPEATS,
    trace_yaml_path: str | Path | None = None,
) -> Dict[str, Any]:
    """Run the bypass demo and return a summary dict.

    Parameters
    ----------
    hull_points, hull_repeats:
        Convex-hull benchmark input size and repeat count.
    bone_joints, bone_repeats:
        Bone-length benchmark input size and repeat count.
    lz4_bytes, lz4_repeats:
        LZ4 compress benchmark payload size and repeat count.
    trace_yaml_path:
        Where to write the YAML trace.  ``None`` -> next to the demo.
    """
    from pharos_engine import _core_facade

    submodules = _enumerate_core_submodules()
    has_native = _core_facade.has_native()

    print("=== hello_rust_bypass ===")
    print(f"  has_native: {has_native}")
    print(f"  _core submodules present: {len(submodules)}")
    for mod, syms in sorted(submodules.items()):
        print(f"    {mod}: {len(syms)} symbol(s) -> {syms}")

    timings: List[Dict[str, Any]] = []

    if has_native:
        # We import the flat _core module directly.  Users who prefer
        # the sub-module views can do ``from pharos_engine._core import
        # hull, ik_solver, slap_format`` — both work; the sub-module
        # views are attribute-level aliases installed by _core_facade.
        from pharos_engine import _core

        # --- 1. Convex hull ------------------------------------------------
        hull_pts = _make_hull_points(hull_points)
        # Warm-up so the first call's allocator dance doesn't dominate.
        _core.convex_hull(hull_pts)
        bypass_hull_s = _bench(lambda: _core.convex_hull(hull_pts), hull_repeats)
        wrapper_hull_s = _bench(
            lambda: _python_convex_hull(hull_pts), hull_repeats
        )
        timings.append({
            "name": "convex_hull",
            "rust_module": "hull",
            "input_size": hull_points,
            "repeats": hull_repeats,
            "bypass_seconds": bypass_hull_s,
            "wrapper_seconds": wrapper_hull_s,
            "speedup": _speedup(bypass_hull_s, wrapper_hull_s),
        })

        # --- 2. compute_bone_lengths --------------------------------------
        bones = _make_bone_chain(bone_joints)
        _core.compute_bone_lengths(bones)
        bypass_bone_s = _bench(
            lambda: _core.compute_bone_lengths(bones), bone_repeats
        )
        wrapper_bone_s = _bench(
            lambda: _python_bone_lengths(bones), bone_repeats
        )
        timings.append({
            "name": "compute_bone_lengths",
            "rust_module": "ik_solver",
            "input_size": bone_joints,
            "repeats": bone_repeats,
            "bypass_seconds": bypass_bone_s,
            "wrapper_seconds": wrapper_bone_s,
            "speedup": _speedup(bypass_bone_s, wrapper_bone_s),
        })

        # --- 3. lz4_compress vs zlib --------------------------------------
        payload = _make_lz4_payload(lz4_bytes)
        _core.lz4_compress(payload)
        bypass_lz4_s = _bench(lambda: _core.lz4_compress(payload), lz4_repeats)
        # zlib.compress is a rough stand-in for "the wrapper does more
        # work (e.g. add a container header, choose a level)" — its
        # timing profile is comparable at default level 6.
        wrapper_lz4_s = _bench(lambda: zlib.compress(payload), lz4_repeats)
        timings.append({
            "name": "lz4_compress",
            "rust_module": "slap_format",
            "input_size": lz4_bytes,
            "repeats": lz4_repeats,
            "bypass_seconds": bypass_lz4_s,
            "wrapper_seconds": wrapper_lz4_s,
            "speedup": _speedup(bypass_lz4_s, wrapper_lz4_s),
        })
    else:  # pragma: no cover — demo is exercised on a build with _core
        print(
            "  (skipping timings — build the wheel with "
            "``maturin develop --release`` to enable the bypass path)"
        )

    payload: Dict[str, Any] = {
        "has_native": has_native,
        "submodule_count": len(submodules),
        "submodules": submodules,
        "timings": timings,
        "notes": [
            "Bypass path: `from pharos_engine import _core` then call the "
            "kernel directly on the same argument tuple/list.",
            "Wrapper path: pure-Python reference implementation matching "
            "what pharos_engine falls back to when _core is missing.",
            "Speedup > 1.0 means the Rust kernel is faster than the "
            "equivalent Python fallback.",
        ],
    }

    out_path = (
        Path(trace_yaml_path) if trace_yaml_path is not None else _DEFAULT_TRACE_YAML
    )
    _write_trace_yaml(payload, out_path)

    for t in timings:
        print(
            f"  {t['name']:>22s}  bypass={t['bypass_seconds']*1e6:8.2f} us  "
            f"wrapper={t['wrapper_seconds']*1e6:8.2f} us  "
            f"speedup={t['speedup']:6.2f}x"
        )
    print(f"  trace written: {out_path}")

    return {
        "has_native": has_native,
        "submodule_count": len(submodules),
        "timing_count": len(timings),
        "trace_path": str(out_path),
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _honour_headless_env() -> None:
    """Respect ``SLAPPY_HEADLESS=1`` as an env-flag override."""
    if os.environ.get("SLAPPY_HEADLESS", "").strip() in ("", "0"):
        os.environ.setdefault("SLAPPY_HEADLESS", "1")


if __name__ == "__main__":
    _honour_headless_env()
    main()
