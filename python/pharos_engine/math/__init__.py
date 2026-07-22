"""pharos_engine.math — Symbolic + numeric formula evaluation.

Backed by Arithma (Rust symbolic math) plus engine-specific helpers
for animation curves, particle force fields, IK targets, and
material graph compilation.

Layering
--------
* ``Formula`` / ``evaluate`` / ``compile_formula``  — parse a math
  expression into a callable. When ``arithma`` is installed
  (``pip install pharos_engine[math]``) we route through
  ``arithma.Expression``; otherwise we fall through to a locked-down
  Python eval sandbox with only stdlib ``math`` in scope.
* ``AnimationCurve`` / ``Bezier`` / ``Catmull`` / ``ease``  — pure
  Python animation primitives shared by the animation rig, particle
  field, and post-process easing chains.
* ``Vec2`` / ``Vec3`` / ``Vec4``  — small, immutable, finite-validated
  vectors with an optional ``to_arithma`` / ``from_arithma`` round-trip
  hook for callers that mix symbolic expressions into a vector
  pipeline.

Degraded mode
-------------
``pharos_engine.math`` always imports cleanly. ``_HAS_ARITHMA`` reports
whether the optional ``[math]`` extra is installed; when ``False``,
``Expression`` / ``Integer`` / ``Variable`` are ``None`` and the formula
path uses the sandbox fallback.

See ``docs/api/math.md`` for the hand-authored reference.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Arithma backend probe (graceful fallback when [math] extra is absent)
# ---------------------------------------------------------------------------
try:
    import arithma as _arithma  # type: ignore[import-not-found]
    _HAS_ARITHMA = True
    Expression = getattr(_arithma, "Expression", None)
    Integer = getattr(_arithma, "Integer", None)
    Variable = getattr(_arithma, "Variable", None)
except ImportError:
    _arithma = None  # type: ignore[assignment]
    _HAS_ARITHMA = False
    Expression = None
    Integer = None
    Variable = None

from .curves import AnimationCurve, Bezier, Catmull, Keyframe, ease  # noqa: E402
from .formula import Formula, compile_formula, evaluate  # noqa: E402
from .vector import Vec2, Vec3, Vec4  # noqa: E402


__all__ = sorted([
    "AnimationCurve",
    "Bezier",
    "Catmull",
    "Expression",
    "Formula",
    "Integer",
    "Keyframe",
    "Variable",
    "Vec2",
    "Vec3",
    "Vec4",
    "_HAS_ARITHMA",
    "compile_formula",
    "ease",
    "evaluate",
])
