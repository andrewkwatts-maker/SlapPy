"""GI (Global Illumination) subpackage — radiance cascades, ReSTIR, SVGF.

Sprint 2 deprecation: the CPU-side GI kernels are moving to
``pharos_engine.render.native`` (wgpu-backed Renderer + VCR pipeline).
This subpackage keeps its symbols for now but emits a one-shot
DeprecationWarning on first import so downstream code can migrate.
"""
import warnings as _warnings

_DEPRECATION = (
    "pharos_engine.gi is deprecated in v0.3.0 and will retire in v0.4. "
    "Use pharos_engine.render.native (Renderer + VcrPipeline) for the "
    "wgpu-backed GPU path; radiance cascades / ReSTIR / SVGF now live "
    "inside the Rust render backend."
)
_warnings.warn(_DEPRECATION, DeprecationWarning, stacklevel=2)

# Soft-import the native replacement so callers can reach the new API
# through pharos_engine.gi.native if they need a transition alias.
try:
    from pharos_engine.render import native  # noqa: F401
except Exception:  # native extension not built — keep the pure-Python surface.
    native = None  # type: ignore[assignment]

from .cascade import RadianceCascadeSystem
from .restir import ReSTIRSystem
from .svgf import SVGFDenoiser

__all__ = ["RadianceCascadeSystem", "ReSTIRSystem", "SVGFDenoiser", "native"]
