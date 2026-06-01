"""Internal input-validation helpers for :mod:`slappyengine.material.node_material`.

Shared rejection logic for :class:`NodeMaterial` (``__init__`` / ``node`` /
``connect``) and the 18 node-factory functions (``ReadFieldNode`` /
``WriteFieldNode`` / ``SampleSimFieldNode`` / ``SinNode`` / ``CosNode`` /
``PowNode`` / etc.).

Engineering policy: validate at the public boundary; the Rust ``_core``
backend trusts inputs. O(1) checks only — the cycle-check is bounded by
the current edge count (``connect`` is amortised O(E+V) but typical
graphs are small). Don't silently coerce: a NaN ``exponent`` on
``PowNode`` would silently NaN-poison the entire material at first GPU
dispatch, where the traceback is lost in WGSL.

Notable silent-acceptance bug this catches: ``NodeMaterial.connect`` was
appending edges without any cycle / self-loop / id-existence check, so a
caller could build a graph whose topological sort fails inside the Rust
compiler — only seen as an unhelpful "ShaderCompileError" with no
authoring-site context.
"""
from __future__ import annotations

import math
from typing import Any

from .graph_schema import KNOWN_NODE_TYPES, KNOWN_PORT_TYPES


# Hard cap on integer params (e.g. ``NoiseNode.octaves``, ``RayMarchNode.steps``)
# — anything beyond this is almost certainly a typo and would blow up GPU
# memory / shader compile time before any visible output.
_MAX_INT = 1024
# Output-mode strings the engine recognises (mirrors ``_TERMINAL_MODES``
# values in :mod:`node_material`). The current constructor doesn't take an
# ``output_mode`` kwarg explicitly, but several callers pass it via
# ``from_json`` round-trips; reserve the constant here for the future.
_VALID_OUTPUT_MODES = frozenset({"render", "sim_write", "force", "reduce"})

# Allowed string param values, keyed by node-type → param name.
_ENUM_PARAMS: dict[str, dict[str, frozenset[str]]] = {
    "noise":         {"mode": frozenset({"fbm", "worley", "perlin", "simplex", "value"})},
    "reduce_output": {"op":   frozenset({"sum", "mean", "max", "min", "product"})},
}


# ---------------------------------------------------------------------------
# Scalar / primitive validators
# ---------------------------------------------------------------------------


def validate_name(name: str, fn: str, value: Any) -> str:
    """Confirm ``value`` is a non-empty ``str`` (used for ``NodeMaterial`` name).

    Raises
    ------
    TypeError
        If ``value`` is not a ``str``.
    ValueError
        If ``value`` is empty.
    """
    if not isinstance(value, str):
        raise TypeError(
            f"{fn}: {name} must be a str; got {type(value).__name__}"
        )
    if not value:
        raise ValueError(f"{fn}: {name} must be a non-empty string")
    return value


def validate_finite_float(name: str, fn: str, value: Any) -> float:
    """Confirm ``value`` is a finite real number (bool refused, NaN/inf refused).

    A NaN ``exponent`` on :func:`PowNode` would silently NaN-poison the
    entire material at first GPU dispatch.

    Raises
    ------
    TypeError
        If ``value`` is not a real number (bool refused).
    ValueError
        If ``value`` is NaN/inf.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(
            f"{fn}: {name} must be a real number; got {type(value).__name__}"
        )
    v = float(value)
    if not math.isfinite(v):
        raise ValueError(f"{fn}: {name} must be finite; got {v!r}")
    return v


def validate_unit_float(name: str, fn: str, value: Any) -> float:
    """Confirm ``value`` is a finite real number in ``[0, 1]``.

    Used for ``AccumulateNode.decay``.
    """
    v = validate_finite_float(name, fn, value)
    if v < 0.0 or v > 1.0:
        raise ValueError(f"{fn}: {name} must be in [0, 1]; got {v}")
    return v


def validate_positive_int(name: str, fn: str, value: Any) -> int:
    """Confirm ``value`` is a plain ``int`` in ``[1, _MAX_INT]``.

    Used for ``NoiseNode.octaves`` and ``RayMarchNode.steps``. A ``bool``
    silently becoming ``octaves=1`` would mute the noise — refuse it.

    Raises
    ------
    TypeError
        If ``value`` is not an ``int``.
    ValueError
        If ``value < 1`` or ``value > _MAX_INT``.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(
            f"{fn}: {name} must be an int; got {type(value).__name__}"
        )
    if value < 1:
        raise ValueError(f"{fn}: {name} must be >= 1; got {value}")
    if value > _MAX_INT:
        raise ValueError(
            f"{fn}: {name} must be <= {_MAX_INT}; got {value}"
        )
    return value


def validate_non_empty_str(name: str, fn: str, value: Any) -> str:
    """Confirm ``value`` is a non-empty ``str``.

    Used for required string params (``ReadFieldNode.field``,
    ``WriteFieldNode.field``, ``PixelChannelNode.channel``).
    """
    if not isinstance(value, str):
        raise TypeError(
            f"{fn}: {name} must be a str; got {type(value).__name__}"
        )
    if not value:
        raise ValueError(f"{fn}: {name} must be a non-empty string")
    return value


def validate_str(name: str, fn: str, value: Any) -> str:
    """Confirm ``value`` is a ``str`` (empty allowed).

    Used for optional string params (``SampleSimFieldNode.field_ref``,
    ``SampleSimFieldNode.channel``, ``ReduceOutputNode.field``).
    """
    if not isinstance(value, str):
        raise TypeError(
            f"{fn}: {name} must be a str; got {type(value).__name__}"
        )
    return value


def validate_enum(name: str, fn: str, value: Any, allowed: frozenset[str]) -> str:
    """Confirm ``value`` is a ``str`` in ``allowed``.

    Used for ``NoiseNode.mode`` and ``ReduceOutputNode.op``.
    """
    s = validate_non_empty_str(name, fn, value)
    if s not in allowed:
        raise ValueError(
            f"{fn}: {name} must be one of {sorted(allowed)}; got {s!r}"
        )
    return s


def validate_finite_2tuple(name: str, fn: str, value: Any) -> tuple[float, float]:
    """Confirm ``value`` is a 2-element sequence of finite real numbers.

    Used for ``RayMarchNode.direction``.
    """
    if isinstance(value, (str, bytes)) or not hasattr(value, "__len__"):
        raise TypeError(
            f"{fn}: {name} must be a 2-tuple of floats; "
            f"got {type(value).__name__}"
        )
    if len(value) != 2:
        raise ValueError(
            f"{fn}: {name} must have length 2; got length {len(value)}"
        )
    x = validate_finite_float(f"{name}[0]", fn, value[0])
    y = validate_finite_float(f"{name}[1]", fn, value[1])
    return (x, y)


def validate_output_mode(name: str, fn: str, value: Any) -> str:
    """Confirm ``value`` is a recognised output-mode string."""
    s = validate_non_empty_str(name, fn, value)
    if s not in _VALID_OUTPUT_MODES:
        raise ValueError(
            f"{fn}: {name} must be one of {sorted(_VALID_OUTPUT_MODES)}; "
            f"got {s!r}"
        )
    return s


# ---------------------------------------------------------------------------
# NodeDef / NodeMaterial structural validators
# ---------------------------------------------------------------------------


def validate_node_def(name: str, fn: str, value: Any) -> Any:
    """Confirm ``value`` is a :class:`NodeDef`-shaped object.

    We check duck-typing (``node_type`` is a known str, ``id`` is a non-empty
    str, ``params`` is a dict) rather than ``isinstance(NodeDef)`` because
    importing :class:`NodeDef` here would create a cycle.

    Raises
    ------
    TypeError
        If ``value`` is None or lacks the required attributes.
    ValueError
        If ``node_type`` is empty / unknown, or ``id`` is empty.
    """
    if value is None:
        raise TypeError(f"{fn}: {name} must be a NodeDef; got None")
    if not hasattr(value, "node_type") or not hasattr(value, "id") \
       or not hasattr(value, "params"):
        raise TypeError(
            f"{fn}: {name} must be a NodeDef; got {type(value).__name__}"
        )
    if not isinstance(value.node_type, str) or not value.node_type:
        raise ValueError(
            f"{fn}: {name}.node_type must be a non-empty str; "
            f"got {value.node_type!r}"
        )
    if value.node_type not in KNOWN_NODE_TYPES:
        raise ValueError(
            f"{fn}: {name}.node_type {value.node_type!r} is not in "
            f"KNOWN_NODE_TYPES"
        )
    if not isinstance(value.id, str) or not value.id:
        raise ValueError(
            f"{fn}: {name}.id must be a non-empty str; got {value.id!r}"
        )
    if not isinstance(value.params, dict):
        raise TypeError(
            f"{fn}: {name}.params must be a dict; "
            f"got {type(value.params).__name__}"
        )
    return value


def validate_port_name(name: str, fn: str, value: Any) -> str:
    """Confirm ``value`` is a non-empty ``str`` and not whitespace-only."""
    s = validate_non_empty_str(name, fn, value)
    if not s.strip():
        raise ValueError(f"{fn}: {name} must be a non-whitespace string")
    return s


def validate_port_exists(
    node_type: str, port_name: str, direction: str, fn: str
) -> None:
    """Confirm ``port_name`` is declared on ``node_type`` for ``direction``.

    Only checked when :data:`KNOWN_PORT_TYPES` declares the node — many
    factories (``SinNode`` / ``CosNode`` / ``ReadFieldNode``) have no
    port-table entry yet, so we skip silently for those.

    Parameters
    ----------
    direction
        ``"out"`` (look in the node's ``outputs``) or ``"in"`` (look in
        ``inputs``).
    """
    spec = KNOWN_PORT_TYPES.get(node_type)
    if spec is None:
        return
    if direction == "out":
        ports = spec.get("outputs", [])
        which = "outputs"
    else:
        ports = spec.get("inputs", [])
        which = "inputs"
    if port_name not in ports:
        raise ValueError(
            f"{fn}: port {port_name!r} not in {node_type} {which}={ports}"
        )


def _would_create_cycle(
    edges: list[dict], from_id: str, to_id: str
) -> bool:
    """Return True if adding ``from_id -> to_id`` would close a cycle.

    Implementation: DFS from ``to_id`` following existing forward edges; if
    we ever reach ``from_id`` then adding the proposed edge closes a loop.

    Self-loops (``from_id == to_id``) are also a cycle and reported here.
    """
    if from_id == to_id:
        return True
    # adjacency: from_node -> [to_node, ...]
    adj: dict[str, list[str]] = {}
    for e in edges:
        adj.setdefault(e["from_node"], []).append(e["to_node"])
    stack = [to_id]
    seen: set[str] = set()
    while stack:
        cur = stack.pop()
        if cur == from_id:
            return True
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(adj.get(cur, []))
    return False


def validate_connect(
    fn: str,
    nodes: list[Any],
    edges: list[dict],
    from_node: Any,
    from_port: Any,
    to_node: Any,
    to_port: Any,
) -> tuple[str, str]:
    """Full validation pass for :meth:`NodeMaterial.connect`.

    Returns the validated ``(from_port, to_port)`` strings. Mutation of
    the edge list is left to the caller.

    Raises
    ------
    TypeError / ValueError
        On any of: non-NodeDef arguments, unknown port names, endpoints
        not present in ``nodes``, self-loops, or a cycle that the new
        edge would close.
    """
    validate_node_def("from_node", fn, from_node)
    validate_node_def("to_node", fn, to_node)
    fp = validate_port_name("from_port", fn, from_port)
    tp = validate_port_name("to_port", fn, to_port)

    # Endpoints must be members of the current material.
    node_ids = {n.id for n in nodes}
    if from_node.id not in node_ids:
        raise ValueError(
            f"{fn}: from_node id {from_node.id!r} not in this material"
        )
    if to_node.id not in node_ids:
        raise ValueError(
            f"{fn}: to_node id {to_node.id!r} not in this material"
        )

    # Cycle / self-loop check first — structural errors are more useful to
    # report than per-port typos.
    if _would_create_cycle(edges, from_node.id, to_node.id):
        raise ValueError(
            f"{fn}: connecting {from_node.id} -> {to_node.id} would "
            f"create a cycle (self-loops are also rejected)"
        )

    # Port-existence is best-effort: only enforced when the schema knows
    # the node-type.
    validate_port_exists(from_node.node_type, fp, "out", fn)
    validate_port_exists(to_node.node_type, tp, "in", fn)

    return fp, tp


__all__ = [
    "validate_name",
    "validate_finite_float",
    "validate_unit_float",
    "validate_positive_int",
    "validate_non_empty_str",
    "validate_str",
    "validate_enum",
    "validate_finite_2tuple",
    "validate_output_mode",
    "validate_node_def",
    "validate_port_name",
    "validate_port_exists",
    "validate_connect",
    "_ENUM_PARAMS",
    "_MAX_INT",
    "_VALID_OUTPUT_MODES",
]
