"""Spring-flavoured :class:`JointSpec` builder.

Springs reuse the distance projection in :mod:`pharos_engine.dynamics.joint`
with author-tuned softer defaults so the same backend can express both stiff
welds and bouncy suspension.
"""
import math
from dataclasses import dataclass, field
from typing import Any

from .joint import JointSpec


@dataclass
class SpringSpec:
    """Pure-data record for a spring; resolves to ``JointSpec(kind='spring')``.

    Useful as a serialisable preset; the :func:`make_spring` builder unpacks
    one of these into a :class:`JointSpec` for the solver.
    """
    node_a: int
    node_b: int
    rest_length: float
    stiffness: float = 1.0e6
    damping: float = 0.05
    params: dict[str, Any] = field(default_factory=dict)


def _check_node_index(fn: str, name: str, value: Any) -> int:
    try:
        v = int(value)
    except (TypeError, ValueError) as exc:
        raise TypeError(
            f"{fn}: {name} must be int-coercible; got {value!r}"
        ) from exc
    if v < 0:
        raise ValueError(
            f"{fn}: {name} must be non-negative; got {value!r}"
        )
    return v


def make_spring(
    node_a: int,
    node_b: int,
    rest_length: float,
    stiffness: float = 1.0e6,
    damping: float = 0.05,
) -> JointSpec:
    """Build a spring constraint between two nodes.

    Raises
    ------
    TypeError
        If ``node_a`` or ``node_b`` is not int-coercible.
    ValueError
        If indices are negative or equal, ``rest_length < 0``,
        ``stiffness <= 0``, or ``damping`` is outside ``[0, 1]``.
    """
    a = _check_node_index("make_spring", "node_a", node_a)
    b = _check_node_index("make_spring", "node_b", node_b)
    if a == b:
        raise ValueError(
            f"make_spring: node_a and node_b must differ; both are {a}"
        )
    rl = float(rest_length)
    if not math.isfinite(rl) or rl < 0.0:
        raise ValueError(
            f"make_spring: rest_length must be finite and >= 0; "
            f"got {rest_length!r}"
        )
    k = float(stiffness)
    if not math.isfinite(k) or k <= 0.0:
        raise ValueError(
            f"make_spring: stiffness must be finite and > 0; "
            f"got {stiffness!r}"
        )
    d = float(damping)
    if math.isnan(d) or not (0.0 <= d <= 1.0):
        raise ValueError(
            f"make_spring: damping must be in [0, 1]; got {damping!r}"
        )
    return JointSpec(
        kind="spring",
        node_a=a,
        node_b=b,
        rest_length=rl,
        stiffness=k,
        damping=d,
        params={},
    )


__all__ = ["SpringSpec", "make_spring"]
