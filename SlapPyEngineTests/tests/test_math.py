"""Tests for ``slappyengine.math`` — formula sandbox, curves, vectors.

The package is the engine's Arithma-roundtrip surface; in this test env
Arithma is *not* installed (it's an optional `[math]` extra), so the
sandbox path is the default. Where the Arithma-installed branch needs
coverage we monkeypatch ``slappyengine.math._HAS_ARITHMA`` directly.
"""
from __future__ import annotations

import importlib
import math as _stdmath
import sys

import pytest

import slappyengine.math as semath
from slappyengine.math import (
    AnimationCurve,
    Bezier,
    Catmull,
    Formula,
    Keyframe,
    Vec2,
    Vec3,
    Vec4,
    _HAS_ARITHMA,
    compile_formula,
    ease,
    evaluate,
)


# ---------------------------------------------------------------------------
# Module-level import surface
# ---------------------------------------------------------------------------


def test_module_imports_cleanly() -> None:
    # Bare ``from slappyengine.math import ...`` already succeeded at the
    # top of the file. This test pins the public surface.
    assert isinstance(semath._HAS_ARITHMA, bool)
    # In this CI env arithma is absent.
    assert semath._HAS_ARITHMA is False
    assert semath.Expression is None
    assert semath.Integer is None
    assert semath.Variable is None


def test_subpackage_resolvable_from_top_level() -> None:
    import slappyengine
    mod = slappyengine.math
    assert mod is semath
    # And the lazy resolver caches it.
    assert slappyengine.math is mod


def test_all_exports_present() -> None:
    for name in (
        "AnimationCurve", "Bezier", "Catmull", "Formula",
        "Keyframe", "Vec2", "Vec3", "Vec4",
        "compile_formula", "ease", "evaluate",
        "_HAS_ARITHMA", "Expression", "Integer", "Variable",
    ):
        assert name in semath.__all__, f"missing {name!r} in __all__"


def test_module_survives_missing_arithma() -> None:
    # Even with the import path tampered, a re-import path that fails to
    # find ``arithma`` should still succeed gracefully. We simulate by
    # injecting a stub that raises on attribute access then reload.
    saved = sys.modules.pop("arithma", None)
    sys.modules["arithma"] = None  # type: ignore[assignment]
    try:
        # Reload — degraded mode must hold.
        m = importlib.reload(semath)
        assert m._HAS_ARITHMA is False
        assert m.Expression is None
    finally:
        # Restore.
        if saved is not None:
            sys.modules["arithma"] = saved
        else:
            sys.modules.pop("arithma", None)
        importlib.reload(semath)


# ---------------------------------------------------------------------------
# Formula / evaluate / compile_formula (sandbox path)
# ---------------------------------------------------------------------------


def test_evaluate_constant() -> None:
    assert evaluate("2 + 3") == 5.0


def test_evaluate_with_binding() -> None:
    assert evaluate("x ** 2", x=4) == 16.0


def test_evaluate_uses_stdlib_math() -> None:
    # sin / cos / pi all available in the sandbox.
    assert evaluate("sin(t)", t=0.0) == 0.0
    assert evaluate("cos(0)") == 1.0
    val = evaluate("sqrt(x*x + y*y)", x=3, y=4)
    assert val == 5.0


def test_evaluate_pi_constant() -> None:
    assert evaluate("pi") == pytest.approx(_stdmath.pi)


def test_formula_dataclass_evaluate() -> None:
    f = Formula("a*b + c", ["a", "b", "c"])
    assert f.evaluate(a=2, b=3, c=4) == 10.0


def test_formula_missing_binding_raises() -> None:
    f = Formula("x + y", ["x", "y"])
    with pytest.raises(ValueError, match="missing required binding 'y'"):
        f.evaluate(x=1.0)


def test_formula_empty_source_rejected() -> None:
    with pytest.raises(ValueError):
        Formula("", ["x"])


def test_formula_rejects_non_str_source() -> None:
    with pytest.raises(TypeError):
        Formula(123, ["x"])  # type: ignore[arg-type]


def test_compile_formula_callable_reusable() -> None:
    g = compile_formula("x*x + 1")
    assert g(x=0) == 1.0
    assert g(x=2) == 5.0


def test_sandbox_rejects_dunder_import() -> None:
    with pytest.raises(ValueError):
        evaluate("__import__('os').system('echo hi')")


def test_sandbox_rejects_open() -> None:
    with pytest.raises(ValueError):
        evaluate("open('foo.txt')")


def test_sandbox_rejects_attribute_access() -> None:
    with pytest.raises(ValueError):
        evaluate("(1).bit_length()")


def test_sandbox_rejects_lambda() -> None:
    with pytest.raises(ValueError):
        evaluate("(lambda: 1)()")


def test_sandbox_rejects_forbidden_binding_name() -> None:
    g = compile_formula("x")
    # The binding ``__import__`` is refused even though the source string
    # itself is innocent — closes the smuggle loophole.
    with pytest.raises(ValueError):
        g(x=1, __import__=lambda *a, **k: None)


def test_sandbox_handles_min_max_abs() -> None:
    # abs / min / max are in the safe-builtin allow-list.
    assert evaluate("abs(-3)") == 3.0
    assert evaluate("min(2, 5)") == 2.0
    assert evaluate("max(2, 5)") == 5.0


def test_arithma_branch_falls_through_to_sandbox_when_expression_none() -> None:
    # Even with ``_HAS_ARITHMA = True`` monkeypatched on, ``Expression``
    # stays ``None`` until Wave-3 lands, so ``compile_formula`` must still
    # produce a working sandboxed callable.
    semath._HAS_ARITHMA = True
    try:
        g = compile_formula("x + 1")
        assert g(x=2) == 3.0
    finally:
        semath._HAS_ARITHMA = False


# ---------------------------------------------------------------------------
# Curves: Bezier, Catmull, AnimationCurve, ease
# ---------------------------------------------------------------------------


def test_bezier_endpoints_exact() -> None:
    b = Bezier(0, 0.3, 0.7, 1)
    assert b.sample(0.0) == 0.0
    assert b.sample(1.0) == 1.0


def test_bezier_midpoint_matches_expected() -> None:
    # Bezier(0, 0.3, 0.7, 1) at t=0.5:
    #   u3*p0 + 3u2t*p1 + 3ut2*p2 + t3*p3
    # = 0.125·0 + 0.375·0.3 + 0.375·0.7 + 0.125·1 = 0.5
    b = Bezier(0, 0.3, 0.7, 1)
    assert b.sample(0.5) == pytest.approx(0.5)


def test_bezier_clamps_out_of_range() -> None:
    b = Bezier(0, 0, 1, 1)
    assert b.sample(-1.0) == b.sample(0.0)
    assert b.sample(2.0) == b.sample(1.0)


def test_catmull_passes_through_points() -> None:
    c = Catmull([0.0, 1.0, 0.0, 1.0])
    assert c.sample(0.0) == pytest.approx(0.0)
    assert c.sample(1.0) == pytest.approx(1.0)
    assert c.sample(2.0) == pytest.approx(0.0)
    assert c.sample(3.0) == pytest.approx(1.0)


def test_catmull_clamps_outside_range() -> None:
    c = Catmull([0.0, 1.0])
    assert c.sample(-1.0) == 0.0
    assert c.sample(99.0) == 1.0


def test_catmull_requires_two_points() -> None:
    with pytest.raises(ValueError):
        Catmull([1.0])


def test_animation_curve_hermite_endpoints() -> None:
    curve = AnimationCurve([Keyframe(0.0, 1.0), Keyframe(1.0, 2.0)])
    assert curve.sample(0.0) == 1.0
    assert curve.sample(1.0) == 2.0


def test_animation_curve_clamps_outside_keyframes() -> None:
    curve = AnimationCurve([Keyframe(0.0, 0.0), Keyframe(1.0, 1.0)])
    assert curve.sample(-5.0) == 0.0
    assert curve.sample(5.0) == 1.0


def test_animation_curve_accepts_tuples() -> None:
    curve = AnimationCurve([(0.0, 0.0), (1.0, 1.0, 0.0, 0.0)])
    assert curve.sample(0.5) == pytest.approx(0.5)


def test_animation_curve_requires_keyframes() -> None:
    with pytest.raises(ValueError):
        AnimationCurve([])


def test_ease_endpoints_zero_and_one() -> None:
    for kind in ("linear", "ease_in_cubic", "ease_in_out_cubic",
                 "ease_out_quad", "ease_in_out_sine"):
        assert ease(0.0, kind) == pytest.approx(0.0, abs=1e-12)
        assert ease(1.0, kind) == pytest.approx(1.0, abs=1e-12)


def test_ease_midpoint_in_unit_range() -> None:
    v = ease(0.5, "ease_in_out_cubic")
    assert 0.0 <= v <= 1.0
    assert v == pytest.approx(0.5)


def test_ease_rejects_unknown_kind() -> None:
    with pytest.raises(ValueError, match="unknown kind"):
        ease(0.5, "ease_secret_kind")


def test_ease_clamps_input_range() -> None:
    assert ease(-1.0, "linear") == 0.0
    assert ease(2.0, "linear") == 1.0


# ---------------------------------------------------------------------------
# Vectors
# ---------------------------------------------------------------------------


def test_vec3_cross_matches_expected() -> None:
    a = Vec3(1, 2, 3)
    b = Vec3(4, 5, 6)
    c = a.cross(b)
    assert (c.x, c.y, c.z) == (-3.0, 6.0, -3.0)


def test_vec3_dot_and_length() -> None:
    v = Vec3(3, 4, 0)
    assert v.dot(Vec3(3, 4, 0)) == 25.0
    assert v.length() == 5.0
    n = v.normalized()
    assert n.length() == pytest.approx(1.0)


def test_vec3_normalized_zero_raises() -> None:
    with pytest.raises(ValueError):
        Vec3(0, 0, 0).normalized()


def test_vec3_arithmetic() -> None:
    a = Vec3(1, 2, 3)
    b = Vec3(4, 5, 6)
    assert (a + b).as_tuple() == (5.0, 7.0, 9.0)
    assert (b - a).as_tuple() == (3.0, 3.0, 3.0)
    assert (a * 2).as_tuple() == (2.0, 4.0, 6.0)
    assert (2 * a).as_tuple() == (2.0, 4.0, 6.0)


def test_vec2_basics() -> None:
    a = Vec2(3, 4)
    assert a.length() == 5.0
    assert (a + Vec2(1, 1)).as_tuple() == (4.0, 5.0)
    assert a.dot(Vec2(3, 4)) == 25.0


def test_vec4_basics() -> None:
    a = Vec4(1, 0, 0, 0)
    b = Vec4(0, 1, 0, 0)
    assert (a + b).as_tuple() == (1.0, 1.0, 0.0, 0.0)
    assert a.dot(b) == 0.0
    assert Vec4(2, 0, 0, 0).length() == 2.0


def test_vec_refuses_nan_or_inf() -> None:
    with pytest.raises(ValueError):
        Vec3(float("nan"), 0, 0)
    with pytest.raises(ValueError):
        Vec2(float("inf"), 0)


def test_vec_refuses_bool() -> None:
    # bool is a subclass of int in Python, but the shared validator
    # refuses it loudly so callers don't smuggle True into a vector.
    with pytest.raises(TypeError):
        Vec3(True, 0, 0)  # type: ignore[arg-type]


def test_vec3_to_arithma_returns_floats_in_degraded_mode() -> None:
    # Without arithma installed, ``to_arithma`` should return the raw
    # float tuple (Arithma round-trip lands once Wave-3 is published).
    v = Vec3(1, 2, 3)
    out = v.to_arithma()
    assert out == (1.0, 2.0, 3.0)


def test_vec_from_arithma_accepts_float_iterable() -> None:
    # Without Arithma installed, ``from_arithma`` should still accept a
    # plain iterable of floats (the degraded round-trip shape).
    assert Vec2.from_arithma([1.0, 2.0]) == Vec2(1, 2)
    assert Vec3.from_arithma((1, 2, 3)) == Vec3(1, 2, 3)
    assert Vec4.from_arithma([1, 2, 3, 4]) == Vec4(1, 2, 3, 4)


def test_vec_dot_cross_refuse_wrong_arity() -> None:
    with pytest.raises(TypeError):
        Vec3(1, 0, 0).dot(Vec2(1, 0))  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        Vec3(1, 0, 0).cross(Vec2(1, 0))  # type: ignore[arg-type]
