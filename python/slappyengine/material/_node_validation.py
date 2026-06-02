"""Internal input-validation helpers for :mod:`slappyengine.material.node_material`.

Generic validators (``validate_finite_float``, ``validate_unit_float``,
``validate_non_empty_str``, ``validate_str``, ``validate_finite_2tuple``)
live in :mod:`slappyengine._validation` and are re-exported. Domain helpers
(``validate_name``, ``validate_positive_int`` with the ``_MAX_INT`` cap,
``validate_enum``, ``validate_output_mode``, structural validators) stay here.
"""
from __future__ import annotations

from typing import Any

from slappyengine._validation import (
    validate_finite_2tuple,
    validate_finite_float,
    validate_non_empty_str,
    validate_positive_int as _validate_positive_int_unbounded,
    validate_str,
    validate_unit_float,
)

from .graph_schema import KNOWN_NODE_TYPES, KNOWN_PORT_TYPES


# Hard cap on integer params (e.g. ``NoiseNode.octaves``, ``RayMarchNode.steps``).
_MAX_INT = 1024
_VALID_OUTPUT_MODES = frozenset({"render", "sim_write", "force", "reduce"})

_ENUM_PARAMS: dict[str, dict[str, frozenset[str]]] = {
    "noise":         {"mode": frozenset({"fbm", "worley", "perlin", "simplex", "value"})},
    "reduce_output": {"op":   frozenset({"sum", "mean", "max", "min", "product"})},
}


def validate_name(name: str, fn: str, value: Any) -> str:
    """Confirm ``value`` is a non-empty ``str`` (used for ``NodeMaterial`` name)."""
    return validate_non_empty_str(name, fn, value)


def validate_positive_int(name: str, fn: str, value: Any) -> int:
    """Confirm ``value`` is a plain ``int`` in ``[1, _MAX_INT]``."""
    return _validate_positive_int_unbounded(name, fn, value, maximum=_MAX_INT)


def validate_enum(name: str, fn: str, value: Any, allowed: frozenset[str]) -> str:
    """Confirm ``value`` is a ``str`` in ``allowed``."""
    s = validate_non_empty_str(name, fn, value)
    if s not in allowed:
        raise ValueError(
            f"{fn}: {name} must be one of {sorted(allowed)}; got {s!r}"
        )
    return s


def validate_output_mode(name: str, fn: str, value: Any) -> str:
    """Confirm ``value`` is a recognised output-mode string."""
    s = validate_non_empty_str(name, fn, value)
    if s not in _VALID_OUTPUT_MODES:
        raise ValueError(
            f"{fn}: {name} must be one of {sorted(_VALID_OUTPUT_MODES)}; "
            f"got {s!r}"
        )
    return s


def validate_node_def(name: str, fn: str, value: Any) -> Any:
    """Confirm ``value`` is a :class:`NodeDef`-shaped object."""
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
    """Confirm ``port_name`` is declared on ``node_type`` for ``direction``."""
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
    """Return True if adding ``from_id -> to_id`` would close a cycle."""
    if from_id == to_id:
        return True
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
    """Full validation pass for :meth:`NodeMaterial.connect`."""
    validate_node_def("from_node", fn, from_node)
    validate_node_def("to_node", fn, to_node)
    fp = validate_port_name("from_port", fn, from_port)
    tp = validate_port_name("to_port", fn, to_port)

    node_ids = {n.id for n in nodes}
    if from_node.id not in node_ids:
        raise ValueError(
            f"{fn}: from_node id {from_node.id!r} not in this material"
        )
    if to_node.id not in node_ids:
        raise ValueError(
            f"{fn}: to_node id {to_node.id!r} not in this material"
        )

    if _would_create_cycle(edges, from_node.id, to_node.id):
        raise ValueError(
            f"{fn}: connecting {from_node.id} -> {to_node.id} would "
            f"create a cycle (self-loops are also rejected)"
        )

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
