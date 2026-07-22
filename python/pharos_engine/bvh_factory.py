"""Python-side factories for BVH and SDF acceleration structures.

These thin wrappers exist so that mobile builds can opt out of expensive
structure construction by flipping module-level flags in
:mod:`pharos_engine.config`.

Pattern
-------
The Rust BVH (in ``src/bvh.rs``) is not yet exposed to Python — it is
consumed internally by the physics broad-phase, with O(n²) fallback noted in
``src/physics.rs``.  This module is the gating point for any future
Python-facing BVH construction call.  Today it returns ``None`` when the
flag is set, and otherwise returns a placeholder dict so callers can
exercise the API surface.

The SDF wrapper, by contrast, is wired through to the real Rust
``_core.SdfScene`` when the flag is False — primitives are passed through
unchanged.  Mobile builds get ``None`` and must treat that as "no SDF".

Usage::

    from pharos_engine.bvh_factory import build_bvh, make_sdf_scene
    from pharos_engine import config as cfg

    cfg.MOBILE_DISABLE_BVH = True
    assert build_bvh([...]) is None

    cfg.MOBILE_DISABLE_SDF = True
    assert make_sdf_scene() is None
"""
from __future__ import annotations

from typing import Any, Iterable, Optional


def build_bvh(primitives: Iterable[Any]) -> Optional[Any]:
    """Build a BVH over *primitives*, or return ``None`` on the mobile profile.

    Parameters
    ----------
    primitives:
        Any iterable of primitive descriptors.  When the Rust BVH grows a
        Python-exposed builder this signature will tighten to match it; for
        now we accept anything so call sites can integrate the gate ahead of
        the Rust binding work.

    Returns
    -------
    object or None
        ``None`` when :data:`pharos_engine.config.MOBILE_DISABLE_BVH` is True
        (mobile opt-out).  Otherwise returns a placeholder structure
        wrapping the materialised primitive list — callers that already
        treat ``None`` as "no acceleration structure" continue to work
        unchanged.
    """
    # Module-level import so runtime flips are honoured per call.
    from pharos_engine import config as _cfg
    if _cfg.MOBILE_DISABLE_BVH:
        return None

    # Try the Rust _core.bvh when available; fall back to a tagged list so
    # downstream code can still iterate over primitives in pure Python.
    try:
        from pharos_engine import _core  # noqa: F401
        _bvh_mod = getattr(_core, "bvh", None)
        if _bvh_mod is not None and hasattr(_bvh_mod, "build"):
            return _bvh_mod.build(list(primitives))
    except ImportError:
        pass

    # Pure-Python placeholder — preserves the input so callers can still
    # iterate.  Replace with the real Rust binding once exposed.
    return {"kind": "bvh", "primitives": list(primitives)}


def make_sdf_scene() -> Optional[Any]:
    """Construct an :class:`_core.SdfScene`, or ``None`` on the mobile profile.

    Returns
    -------
    SdfScene or None
        ``None`` when :data:`pharos_engine.config.MOBILE_DISABLE_SDF` is True.
        Otherwise an empty :class:`SdfScene` ready for ``.add(prim)`` calls.
        If the Rust ``_core`` extension is unavailable, returns ``None`` and
        the caller should treat that as "no SDF" as well.
    """
    from pharos_engine import config as _cfg
    if _cfg.MOBILE_DISABLE_SDF:
        return None

    try:
        from pharos_engine._core import SdfScene  # type: ignore[attr-defined]
    except (ImportError, AttributeError):
        return None
    return SdfScene()
