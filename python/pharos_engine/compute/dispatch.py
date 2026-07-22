"""GPU / CPU compute dispatch chooser (Sprint 7).

Decides whether a given kernel invocation goes to the Rust CPU
Tier-10 path (``pharos_engine._core``) or the wgpu GPU compute path
(``pharos_render::compute``, dispatched via a to-be-added
``_core.gpu_dispatch`` PyO3 wrapper).

Threshold rationale
-------------------
Nova3D's Tier-11 discussion (``docs/tier_11_gpu_compute_discussion.md``)
measured GPU launch overhead at ~50-100 us on desktop-class hardware.
For small scenes the CPU Tier-10 path is already at 300-700 fps and
the GPU launch cost dominates; for large scenes (>5000 particles /
nodes) the GPU wins by 10-100x.

The default thresholds live below. Downstream apps can override via
``engine_config`` YAML::

    compute:
      dispatch:
        pbf_gpu_threshold: 5000
        softbody_gpu_threshold: 2000
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


Backend = Literal["cpu", "gpu"]


@dataclass(frozen=True)
class DispatchThresholds:
    """Particle / node count above which we prefer GPU."""

    pbf: int = 5000
    softbody: int = 2000


_DEFAULT_THRESHOLDS = DispatchThresholds()


def _load_thresholds_from_config() -> DispatchThresholds:
    """Pull overrides from ``engine_config.yaml`` if present.

    Kept as a soft-import so this module works in the pharos-engine
    wheel with no editor / config-loader plugins installed.
    """
    try:
        from pharos_engine.config import engine_config
    except Exception:
        return _DEFAULT_THRESHOLDS
    dispatch_cfg = None
    try:
        dispatch_cfg = engine_config.get("compute", {}).get("dispatch")  # type: ignore[assignment]
    except Exception:
        return _DEFAULT_THRESHOLDS
    if not dispatch_cfg:
        return _DEFAULT_THRESHOLDS
    return DispatchThresholds(
        pbf=int(dispatch_cfg.get("pbf_gpu_threshold", _DEFAULT_THRESHOLDS.pbf)),
        softbody=int(dispatch_cfg.get("softbody_gpu_threshold", _DEFAULT_THRESHOLDS.softbody)),
    )


_thresholds: DispatchThresholds | None = None


def get_thresholds() -> DispatchThresholds:
    global _thresholds
    if _thresholds is None:
        _thresholds = _load_thresholds_from_config()
    return _thresholds


def _gpu_available() -> bool:
    """Best-effort probe for a functioning GPU compute path.

    Sprint 7 lands the shader pipelines and PyO3 wrappers; until the
    ``_core.gpu_dispatch`` bindings are wired end-to-end, callers get
    the CPU path unconditionally. Flip ``PHAROS_FORCE_GPU=1`` in the
    env to opt into the GPU dispatch during development.
    """
    import os

    if os.environ.get("PHAROS_FORCE_GPU", "").lower() in ("1", "true", "yes"):
        return True
    try:
        from pharos_engine import _core  # type: ignore
    except ImportError:
        return False
    return hasattr(_core, "gpu_dispatch")


def choose_backend(kind: str, size: int) -> Backend:
    """Pick "cpu" or "gpu" for a given kernel + workload size.

    Parameters
    ----------
    kind:
        "pbf" or "softbody". Unknown kinds default to CPU.
    size:
        Particle / node / element count for this invocation.
    """
    if not _gpu_available():
        return "cpu"
    t = get_thresholds()
    thresh = getattr(t, kind, None)
    if thresh is None:
        return "cpu"
    return "gpu" if size >= thresh else "cpu"


__all__ = [
    "Backend",
    "DispatchThresholds",
    "get_thresholds",
    "choose_backend",
]
