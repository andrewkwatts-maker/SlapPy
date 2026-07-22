"""Formula parsing + evaluation, Arithma-backed when available.

Two execution paths share one surface:

1. **Arithma-backed.**  ``arithma.Expression.parse`` builds a symbolic
   AST that we evaluate with ``.evaluate(bindings)``. Once the Wave-3
   PyO3 wrappers land this is the fast path; until then ``Expression``
   is ``None`` and we silently fall back to (2).
2. **Sandboxed ``eval`` fallback.**  When Arithma is missing or the
   ``Expression`` wrapper has not been published yet, ``Formula``
   evaluates the source string against a locked-down sandbox: no
   ``__builtins__``, exposed names limited to the ``math`` standard
   library plus the caller's bindings. Disallowed identifiers
   (``__import__``, ``open``, ``exec``, ``eval``, ``compile``, dunders
   in general) trigger ``ValueError`` at compile time.

Both paths return Python ``float``.
"""
from __future__ import annotations

import ast as _ast
import math as _stdmath
from dataclasses import dataclass, field
from typing import Any, Callable

from ._validation import (
    validate_keyframe_list,
    validate_non_empty_str,
    validate_str,
)


# ---------------------------------------------------------------------------
# Arithma backend probe (lazy — re-evaluated each call so tests can monkey-
# patch ``pharos_engine.math._HAS_ARITHMA``)
# ---------------------------------------------------------------------------


def _arithma_expression_cls():
    """Return the live ``arithma.Expression`` class, or ``None``.

    Reads the parent ``pharos_engine.math`` module attribute lazily so a
    monkeypatch flipping ``_HAS_ARITHMA`` / ``Expression`` in tests is
    honoured.
    """
    from . import _HAS_ARITHMA, Expression  # local import — late binding
    if not _HAS_ARITHMA:
        return None
    return Expression  # may still be ``None`` until Wave-3 wrappers land


# ---------------------------------------------------------------------------
# Safe Python eval sandbox
# ---------------------------------------------------------------------------

# Whitelist of stdlib ``math`` symbols + a handful of builtins callers
# expect from a "formula" context. Everything else is rejected at compile
# time by the AST walker below.
_SAFE_MATH_NAMES = {
    name: getattr(_stdmath, name)
    for name in (
        "sin", "cos", "tan", "asin", "acos", "atan", "atan2",
        "sinh", "cosh", "tanh", "asinh", "acosh", "atanh",
        "exp", "log", "log2", "log10", "sqrt", "pow",
        "floor", "ceil", "trunc", "fabs", "copysign",
        "hypot", "fmod", "remainder",
        "degrees", "radians",
        "pi", "e", "tau", "inf", "nan",
    )
    if hasattr(_stdmath, name)
}
_SAFE_BUILTINS: dict[str, Any] = {
    "abs": abs,
    "min": min,
    "max": max,
    "round": round,
    "True": True,
    "False": False,
    "None": None,
}

# Names that are never legal inside a formula even if the caller binds them.
_FORBIDDEN_NAMES = frozenset({
    "__import__", "open", "exec", "eval", "compile",
    "globals", "locals", "vars", "getattr", "setattr",
    "delattr", "input", "exit", "quit", "help",
    "__builtins__",
})


def _ensure_safe_ast(node: _ast.AST, source: str) -> None:
    """Walk *node* and refuse anything outside the formula sub-grammar.

    Permitted: arithmetic / comparison / boolean operators, calls to
    whitelisted names, attribute access *only* through whitelisted names
    (e.g. ``math.pi`` is not used — we expose the names directly).
    Forbidden: attribute access, subscripting, lambdas, comprehensions,
    dunder identifiers, anything else.
    """
    for sub in _ast.walk(node):
        if isinstance(sub, (_ast.Attribute, _ast.Subscript, _ast.Lambda,
                            _ast.ListComp, _ast.SetComp, _ast.DictComp,
                            _ast.GeneratorExp, _ast.Starred, _ast.Yield,
                            _ast.YieldFrom, _ast.Await, _ast.IfExp,
                            _ast.NamedExpr)):
            raise ValueError(
                f"formula: unsupported syntax {type(sub).__name__!r} in {source!r}"
            )
        if isinstance(sub, _ast.Name):
            if sub.id in _FORBIDDEN_NAMES or sub.id.startswith("__"):
                raise ValueError(
                    f"formula: forbidden identifier {sub.id!r} in {source!r}"
                )
        if isinstance(sub, _ast.Call):
            # Calls must target a Name in the whitelist; nested
            # callables (``f()()``) are refused.
            if not isinstance(sub.func, _ast.Name):
                raise ValueError(
                    f"formula: only whitelisted function calls allowed in {source!r}"
                )


def _compile_sandbox(source: str) -> Callable[..., float]:
    """Compile *source* into a sandboxed callable returning ``float``."""
    validate_non_empty_str("source", "compile_formula", source)
    try:
        tree = _ast.parse(source, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"formula: parse error in {source!r}: {exc.msg}") from exc
    _ensure_safe_ast(tree, source)
    code = compile(tree, filename="<formula>", mode="eval")

    def _evaluate(**bindings: Any) -> float:
        # Refuse forbidden names in caller bindings too — closes the loophole
        # where someone passes ``__import__=...`` to smuggle access in.
        for k in bindings:
            if k in _FORBIDDEN_NAMES or k.startswith("__"):
                raise ValueError(f"formula: forbidden binding {k!r}")
        env: dict[str, Any] = {}
        env.update(_SAFE_MATH_NAMES)
        env.update(_SAFE_BUILTINS)
        env.update(bindings)
        # Hard-disable builtins inside the eval — the AST walker should have
        # caught anything dangerous, but defence in depth is cheap.
        result = eval(code, {"__builtins__": {}}, env)  # noqa: S307
        return float(result)

    return _evaluate


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


def compile_formula(source: str) -> Callable[..., float]:
    """Compile *source* once and return a callable ``(**bindings) -> float``.

    Tries the Arithma backend first; falls back to the sandboxed Python
    evaluator. Raises :class:`ValueError` on parse error or forbidden
    syntax. The returned callable is a closure — feel free to capture it
    in a hot loop, no re-parsing happens per call.
    """
    validate_non_empty_str("source", "compile_formula", source)
    Expression = _arithma_expression_cls()
    if Expression is not None:
        try:
            expr = Expression.parse(source)  # type: ignore[attr-defined]

            def _evaluate(**bindings: Any) -> float:
                return float(expr.evaluate(bindings))  # type: ignore[attr-defined]

            return _evaluate
        except Exception:  # noqa: BLE001 — fall through to sandbox
            pass
    return _compile_sandbox(source)


def evaluate(source: str, **bindings: Any) -> float:
    """Compile + evaluate *source* against ``bindings`` in one call.

    Convenience wrapper around :func:`compile_formula`. Slow path because
    every call re-parses; for hot loops compile once and reuse.
    """
    return compile_formula(source)(**bindings)


@dataclass
class Formula:
    """A parsed math expression with a fixed set of free variables.

    ``Formula("a*b + c", ["a", "b", "c"]).evaluate(a=2, b=3, c=4)`` →
    ``10.0``. The variable list is validated up front so a missing
    binding raises :class:`ValueError` at construction-time-evaluable
    point rather than producing ``NameError`` from the sandbox.

    Attributes
    ----------
    source:
        The original formula source string.
    variables:
        Declared free-variable names in evaluation order.
    """

    source: str
    variables: list[str] = field(default_factory=list)
    _compiled: Callable[..., float] | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self.source = validate_non_empty_str("source", "Formula", self.source)
        validate_keyframe_list("variables", "Formula", self.variables)
        for i, v in enumerate(self.variables):
            validate_str(f"variables[{i}]", "Formula", v, allow_empty=False)
        self._compiled = compile_formula(self.source)

    def evaluate(self, **bindings: Any) -> float:
        """Evaluate the formula against *bindings*.

        Bindings that are not in :attr:`variables` are forwarded anyway
        (e.g. ``t`` for time) so callers can keep one Formula across
        multiple per-tick contexts. Missing declared bindings raise
        :class:`ValueError`.
        """
        for v in self.variables:
            if v not in bindings:
                raise ValueError(
                    f"Formula.evaluate: missing required binding {v!r}"
                )
        assert self._compiled is not None  # nosec — set in __post_init__
        return self._compiled(**bindings)


__all__ = [
    "Formula",
    "compile_formula",
    "evaluate",
]
