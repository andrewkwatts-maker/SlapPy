<!-- handauthored: do not regenerate -->
# pharos_engine.math — API Reference

> Hand-written reference for the `math` subpackage — symbolic + numeric
> formula evaluation backed by [Arithma](https://github.com/andrewkwatts-maker/Arithma)
> when the optional `[math]` extra is installed, with a Python eval
> sandbox fallback so the module always imports.
> Companion design notes for the animation surface live in
> [`animation.md`](animation.md); the lower-level Poisson / multigrid
> kernel sits in [`numerics.md`](numerics.md).

## Overview

`pharos_engine.math` exposes three layers of math primitives the rest of
the engine reaches for over and over:

1. **Formulas.** `Formula`, `evaluate`, and `compile_formula` turn a
   user-supplied math string ("`a*b + sin(t)`") into a callable. When
   the `[math]` extra is installed (`pip install pharos_engine[math]`)
   we route through `arithma.Expression` — Arithma's Rust-backed
   symbolic AST gives consistent precision and shared simplification
   with material graph compilation. When the extra is missing, the
   same surface drops to a locked-down Python `eval` sandbox: no
   `__builtins__`, only stdlib `math` symbols plus the caller's
   bindings, with `__import__` / `open` / `exec` / `eval` / `compile`
   and any dunder identifier refused at compile time by an AST
   walker.
2. **Animation curves.** `AnimationCurve` (piecewise cubic Hermite
   through `Keyframe` controls), `Bezier`, `Catmull` (uniform
   Catmull-Rom), and a roster of named easing functions under `ease`.
   All pure Python — no numpy — so they import cleanly in the degraded
   mode and are cheap to use from hot animation paths.
3. **Vectors.** `Vec2`, `Vec3`, `Vec4` immutable dataclasses with
   operator overloads (`+ - * dot`), `length` / `normalized`, and a
   `to_arithma` / `from_arithma` round-trip hook so material and IK
   graphs can flow values into and out of Arithma's symbolic surface.

Degraded mode is the *default* until somebody installs the `[math]`
extra. The package always imports; `_HAS_ARITHMA` reports whether the
Arithma backend is live, and `Expression` / `Integer` / `Variable`
re-export the live Arithma wrappers (or `None` when the extra is
missing or before Wave-3 wrappers land in Arithma itself).

## Public surface

```python
from pharos_engine.math import (
    Formula,
    evaluate,
    compile_formula,
    AnimationCurve,
    Keyframe,
    Bezier,
    Catmull,
    ease,
    Vec2, Vec3, Vec4,
    _HAS_ARITHMA,
    Expression, Integer, Variable,
)
```

* **Formula surface** — `Formula`, `evaluate`, `compile_formula`.
* **Animation surface** — `AnimationCurve`, `Keyframe`, `Bezier`,
  `Catmull`, `ease`.
* **Vector surface** — `Vec2`, `Vec3`, `Vec4`.
* **Arithma re-exports** — `Expression`, `Integer`, `Variable`. The
  first two are `None` until Arithma ships its PyO3 wrappers.
* **Capability flag** — `_HAS_ARITHMA`. Use this in production-side
  feature detection rather than `try: import arithma`.

## Classes

### `Formula`

_class | dataclass — defined in `pharos_engine.math.formula`_

A parsed math expression plus a declared list of free variables.
Construction validates the source string and pre-compiles the
expression so subsequent `evaluate(**bindings)` calls are O(formula
nodes) with no re-parse overhead. Missing declared bindings raise
`ValueError` at call time; extra bindings are forwarded through so
callers can keep one `Formula` instance across many per-tick contexts
that share an unchanging time variable.

#### Constructor signature

```python
Formula(source: str, variables: list[str] = []) -> None
```

#### Methods

- `evaluate(self, **bindings: Any) -> float` — bind the declared
  `variables` and evaluate. Raises `ValueError` for missing bindings or
  forbidden identifiers when the sandbox path is in use.

### `AnimationCurve`

_class | dataclass — defined in `pharos_engine.math.curves`_

Piecewise cubic Hermite curve through a sequence of `Keyframe` records
(or raw `(t, v)` / `(t, v, in_tan, out_tan)` tuples). Keyframes are
sorted by `t` at construction. Sampling outside the keyframe time range
*clamps* to the endpoint values — no extrapolation — matching what
animation rigs expect downstream.

#### Constructor signature

```python
AnimationCurve(keyframes: list[Keyframe | tuple]) -> None
```

#### Methods

- `sample(self, t: float) -> float` — Hermite-interpolated value at
  time `t`. Tangents are scaled by segment length so values compose
  cleanly across irregular keyframe spacing.

### `Keyframe`

_frozen dataclass — defined in `pharos_engine.math.curves`_

Hermite control point: `t`, `value`, optional `in_tan` / `out_tan`
(default 0). All fields are finite-validated at construction time.

### `Bezier`

_frozen dataclass — defined in `pharos_engine.math.curves`_

Cubic Bezier curve through `(p0, p1, p2, p3)`. `sample(t)` evaluates
the standard Bernstein form on `[0, 1]`; out-of-range `t` is clamped.

### `Catmull`

_class | dataclass — defined in `pharos_engine.math.curves`_

Catmull-Rom spline through arbitrary 1-D points (uniform
parameterisation). End-tangents are mirrored from the first / last
interior segment so the spline still behaves at the endpoints without
phantom controls from the caller. `sample(t)` accepts `t` in
`[0, len(points) - 1]` and clamps outside.

### `Vec2`, `Vec3`, `Vec4`

_frozen dataclass — defined in `pharos_engine.math.vector`_

Immutable, finite-validated vectors with operator overloads and the
shared method roster:

| Method | Vec2 | Vec3 | Vec4 |
|---|---|---|---|
| `+ - *` | ✓ | ✓ | ✓ |
| `dot(other)` | ✓ | ✓ | ✓ |
| `cross(other)` |   | ✓ |   |
| `length()` | ✓ | ✓ | ✓ |
| `normalized()` | ✓ | ✓ | ✓ |
| `as_tuple()` | ✓ | ✓ | ✓ |
| `from_arithma(seq)` | ✓ | ✓ | ✓ |
| `to_arithma()` | ✓ | ✓ | ✓ |

`normalized()` raises `ValueError` on a zero-length input. `dot` and
`cross` raise `TypeError` if the argument is not the same vector
arity.

## Functions

### `evaluate(source: str, **bindings) -> float`

_defined in `pharos_engine.math.formula`_

Parse and evaluate `source` against `bindings` in one call. Slow path
because every call re-parses; for hot loops compile once with
`compile_formula` and reuse the returned callable. Raises `ValueError`
on parse error, forbidden syntax, or a forbidden binding name (anything
in the sandbox's `_FORBIDDEN_NAMES` set, or any dunder identifier).

### `compile_formula(source: str) -> Callable[..., float]`

_defined in `pharos_engine.math.formula`_

Compile `source` once and return a callable `(**bindings) -> float`.
Tries Arithma first; falls back to the sandbox on any parse error or
when `_HAS_ARITHMA` is `False`. The returned callable is a closure —
safe to capture in a hot loop.

### `ease(t: float, kind: str = "ease_in_out_cubic") -> float`

_defined in `pharos_engine.math.curves`_

Common easing functions on `[0, 1] → [0, 1]`. Inputs outside `[0, 1]`
are clamped. Unknown `kind` raises `ValueError` with the legal kinds
enumerated:

```
linear, ease_in_quad, ease_out_quad, ease_in_out_quad,
ease_in_cubic, ease_out_cubic, ease_in_out_cubic,
ease_in_sine, ease_out_sine, ease_in_out_sine
```

## Constants

### `_HAS_ARITHMA`

_bool — defined in `pharos_engine.math`_

`True` iff `import arithma` succeeded at package load time. Reflects
whether the optional `[math]` extra is installed.

### `Expression`, `Integer`, `Variable`

_re-exports from `arithma` — defined in `pharos_engine.math`_

Live Arithma PyO3 wrappers when present. Today (Arithma 2.0.2) these
are `None` until the Wave-3 wrappers land — degraded-mode is the only
production code path even with the extra installed. The flag still
flips `_HAS_ARITHMA = True` so callers can probe for the Arithma
backend separately from the wrapper readiness.

## Inner modules

- `pharos_engine.math.formula` — `Formula` / `evaluate` /
  `compile_formula` + Arithma probe + Python sandbox.
- `pharos_engine.math.curves`  — `AnimationCurve`, `Keyframe`,
  `Bezier`, `Catmull`, `ease`.
- `pharos_engine.math.vector`  — `Vec2`, `Vec3`, `Vec4` + Arithma
  round-trip helper.
- `pharos_engine.math._validation` — shared input validators that
  delegate to `pharos_engine._validation` for the generic checks and
  add `validate_finite_sequence` / `validate_keyframe_list` for the
  domain shapes.

## Conventions

- **Lazy Arithma probe.** The Arithma `Expression` class is resolved
  lazily via `_arithma_expression_cls()` so tests can monkeypatch
  `pharos_engine.math._HAS_ARITHMA` / `Expression` to exercise both
  branches without reloading the module.
- **Sandbox forbidden list.** The sandbox refuses identifiers in
  `_FORBIDDEN_NAMES` (`__import__`, `open`, `exec`, `eval`, `compile`,
  `globals`, `locals`, `vars`, `getattr`, `setattr`, `delattr`,
  `input`, `exit`, `quit`, `help`, `__builtins__`) *and* any dunder
  identifier. Refused both in the formula source AST and in the
  caller's bindings dict, closing the smuggle-via-binding loophole.
- **Vector frozen-ness.** `Vec2` / `Vec3` / `Vec4` are frozen
  dataclasses; mutation is a `dataclasses.FrozenInstanceError`. Use
  the operator overloads or rebuild with `Vec3(...)`.
- **Float normalisation.** Every value entering the package is
  funnelled through `validate_finite_float` — NaN / ±inf are refused
  with `ValueError` rather than poisoning downstream curves.

## See also

- [`animation.md`](animation.md) — `ProceduralRig` / `AnimationGraph`
  consume `AnimationCurve` and `Bezier` outputs.
- [`material.md`](material.md) — `NodeMaterial` will route through
  `Formula` for user-authored shader-input formulas once Wave-3 lands.
- [`numerics.md`](numerics.md) — lower-level Poisson / multigrid
  numerical kernels (no symbolic surface, no Arithma).
