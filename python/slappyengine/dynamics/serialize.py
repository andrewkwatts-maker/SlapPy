"""JSON round-trip serialisation for :class:`slappyengine.dynamics.World`.

Game saves need to persist a dynamics world: node arrays, bodies, joints,
solver tuning, and the overdamping-warning toggle. Pickle would be a one-liner
but is unsafe to load from disk, so this module sticks to plain JSON.

Encoding rules
--------------
* numpy arrays  →  ``{"_dtype": "<dtype>", "_shape": [..], "_b64": "<base64>"}``
* :class:`JointSpec` → ``{"kind", "node_a", "node_b", "rest_length",
  "stiffness", "damping", "params", "break_force", "enabled"}``
* :class:`Body`      → ``{"kind", "parameters", "node_offset", "node_count",
  "label"}``
* All floats are normalised to Python ``float`` (no numpy scalars).

Determinism contract
--------------------
After ``world_from_dict(world_to_dict(w))``, a single ``step(dt)`` of the
copy reproduces the original world's state to machine precision (≤ 1e-9).
"""
from __future__ import annotations

import base64
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from .body import Body
from .joint import KIND_PARAM_KEYS, JointSpec
from .world import World

# Schema version — bump when the on-disk format breaks compatibility.
SCHEMA_VERSION = 1

# Keys we require at the top level of a world dict.
_REQUIRED_WORLD_KEYS = {
    "schema_version",
    "positions",
    "prev_positions",
    "velocities",
    "inv_masses",
    "bodies",
    "joints",
    "gravity",
    "solver_iterations",
    "warn_overdamping",
    "frame",
}

# Keys we require on each serialized joint dict.
_REQUIRED_JOINT_KEYS = {
    "kind",
    "node_a",
    "node_b",
    "rest_length",
    "stiffness",
    "damping",
    "params",
    "break_force",
    "enabled",
}

# Keys we require on each serialized body dict.
_REQUIRED_BODY_KEYS = {
    "kind",
    "parameters",
    "node_offset",
    "node_count",
    "label",
}


# ---------------------------------------------------------------------------
# Primitive encoders
# ---------------------------------------------------------------------------

def _encode_array(arr: np.ndarray) -> dict[str, Any]:
    """Encode a numpy array as a JSON-friendly dict.

    The raw bytes are base64-encoded so we keep full precision without
    serialising every float as a (lossy) decimal string.
    """
    if not isinstance(arr, np.ndarray):
        arr = np.asarray(arr)
    # Force native byte order so cross-platform loads don't get surprised.
    if arr.dtype.byteorder not in ("=", "|"):
        arr = arr.astype(arr.dtype.newbyteorder("="))
    b = base64.b64encode(arr.tobytes()).decode("ascii")
    return {
        "_dtype": str(arr.dtype),
        "_shape": list(arr.shape),
        "_b64": b,
    }


def _decode_array(d: Any, *, name: str) -> np.ndarray:
    """Inverse of :func:`_encode_array`."""
    if not isinstance(d, dict):
        raise ValueError(
            f"{name}: expected an array-dict; got {type(d).__name__}"
        )
    for k in ("_dtype", "_shape", "_b64"):
        if k not in d:
            raise ValueError(
                f"{name}: array-dict missing required key {k!r}"
            )
    try:
        raw = base64.b64decode(d["_b64"].encode("ascii"))
    except Exception as exc:  # pragma: no cover - base64 error surfaces here
        raise ValueError(f"{name}: invalid base64 payload ({exc})") from exc
    try:
        arr = np.frombuffer(raw, dtype=np.dtype(d["_dtype"])).reshape(
            tuple(int(s) for s in d["_shape"])
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{name}: cannot reshape buffer to dtype={d['_dtype']!r} "
            f"shape={d['_shape']!r} ({exc})"
        ) from exc
    return np.array(arr, copy=True)  # detach from the immutable buffer


def _to_json_safe(value: Any) -> Any:
    """Recursively coerce numpy scalars/arrays inside ``params`` / ``parameters``
    into JSON-safe Python primitives."""
    if isinstance(value, np.ndarray):
        # Inline small arrays as lists; preserve dtype-encoded blob for big ones.
        if value.size <= 16:
            return [_to_json_safe(v) for v in value.tolist()]
        return _encode_array(value)
    if isinstance(value, (np.floating,)):
        f = float(value)
        if math.isnan(f):
            return "NaN"
        if math.isinf(f):
            return "Infinity" if f > 0 else "-Infinity"
        return f
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, float):
        if math.isnan(value):
            return "NaN"
        if math.isinf(value):
            return "Infinity" if value > 0 else "-Infinity"
        return value
    if isinstance(value, dict):
        return {str(k): _to_json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_json_safe(v) for v in value]
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    # Fall back to string for opaque builder objects (e.g. live spec instances).
    # The on-disk shape stays JSON, but the consumer must rebuild objects
    # using its own knowledge of the kind.
    return repr(value)


def _from_json_safe(value: Any) -> Any:
    """Inverse of :func:`_to_json_safe` for plain JSON values; leaves
    nested array-dicts as-is for caller-side rebuild if needed."""
    if isinstance(value, str):
        if value == "NaN":
            return float("nan")
        if value == "Infinity":
            return float("inf")
        if value == "-Infinity":
            return float("-inf")
        return value
    if isinstance(value, list):
        return [_from_json_safe(v) for v in value]
    if isinstance(value, dict):
        # Detect the encoded-array sentinel and rebuild it transparently.
        if {"_dtype", "_shape", "_b64"} <= set(value.keys()):
            return _decode_array(value, name="<param>")
        return {k: _from_json_safe(v) for k, v in value.items()}
    return value


# ---------------------------------------------------------------------------
# Joint / Body encoders
# ---------------------------------------------------------------------------

def _encode_joint(j: JointSpec) -> dict[str, Any]:
    bf = float(j.break_force)
    if math.isinf(bf):
        bf_enc: Any = "Infinity" if bf > 0 else "-Infinity"
    elif math.isnan(bf):
        bf_enc = "NaN"
    else:
        bf_enc = bf
    return {
        "kind": str(j.kind),
        "node_a": int(j.node_a),
        "node_b": int(j.node_b),
        "rest_length": float(j.rest_length),
        "stiffness": float(j.stiffness),
        "damping": float(j.damping),
        "params": _to_json_safe(j.params),
        "break_force": bf_enc,
        "enabled": bool(j.enabled),
    }


def _decode_joint(d: Any, *, index: int) -> JointSpec:
    if not isinstance(d, dict):
        raise ValueError(
            f"joints[{index}]: expected a dict; got {type(d).__name__}"
        )
    missing = _REQUIRED_JOINT_KEYS - set(d.keys())
    if missing:
        raise ValueError(
            f"joints[{index}]: missing required keys {sorted(missing)!r}"
        )
    kind = d["kind"]
    if not isinstance(kind, str) or kind not in KIND_PARAM_KEYS:
        raise ValueError(
            f"joints[{index}]: unknown kind {kind!r}; "
            f"expected one of {sorted(KIND_PARAM_KEYS)!r}"
        )
    bf_raw = d["break_force"]
    if isinstance(bf_raw, str):
        bf = _from_json_safe(bf_raw)
        if not isinstance(bf, float):
            raise ValueError(
                f"joints[{index}]: break_force string must be one of "
                f"'Infinity', '-Infinity', 'NaN'; got {bf_raw!r}"
            )
    else:
        bf = float(bf_raw)
    params_raw = d["params"]
    if not isinstance(params_raw, dict):
        raise ValueError(
            f"joints[{index}]: params must be a dict; "
            f"got {type(params_raw).__name__}"
        )
    params = {k: _from_json_safe(v) for k, v in params_raw.items()}
    return JointSpec(
        kind=kind,
        node_a=int(d["node_a"]),
        node_b=int(d["node_b"]),
        rest_length=float(d["rest_length"]),
        stiffness=float(d["stiffness"]),
        damping=float(d["damping"]),
        params=params,
        break_force=bf,
        enabled=bool(d["enabled"]),
    )


def _encode_body(b: Body) -> dict[str, Any]:
    return {
        "kind": str(b.kind),
        "parameters": _to_json_safe(b.parameters),
        "node_offset": int(b.node_offset),
        "node_count": int(b.node_count),
        "label": str(b.label),
    }


def _decode_body(d: Any, *, index: int) -> Body:
    if not isinstance(d, dict):
        raise ValueError(
            f"bodies[{index}]: expected a dict; got {type(d).__name__}"
        )
    missing = _REQUIRED_BODY_KEYS - set(d.keys())
    if missing:
        raise ValueError(
            f"bodies[{index}]: missing required keys {sorted(missing)!r}"
        )
    params_raw = d["parameters"]
    if not isinstance(params_raw, dict):
        raise ValueError(
            f"bodies[{index}]: parameters must be a dict; "
            f"got {type(params_raw).__name__}"
        )
    parameters = {k: _from_json_safe(v) for k, v in params_raw.items()}
    return Body(
        kind=str(d["kind"]),
        parameters=parameters,
        node_offset=int(d["node_offset"]),
        node_count=int(d["node_count"]),
        label=str(d["label"]),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def world_to_dict(world: World) -> dict[str, Any]:
    """Serialise ``world`` into a JSON-compatible dict.

    Captures every attribute needed for a deterministic ``step`` continuation:
    node arrays (positions, prev_positions, velocities, inv_masses), bodies,
    joints, gravity, solver_iterations, the overdamping-warning flag, and the
    current frame counter.

    Raises
    ------
    TypeError
        If ``world`` is not a :class:`World`.
    """
    if not isinstance(world, World):
        raise TypeError(
            f"world_to_dict: expected a World; got {type(world).__name__}"
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "positions": _encode_array(np.asarray(world.positions, dtype=np.float64)),
        "prev_positions": _encode_array(
            np.asarray(world.prev_positions, dtype=np.float64)
        ),
        "velocities": _encode_array(
            np.asarray(world.velocities, dtype=np.float64)
        ),
        "inv_masses": _encode_array(
            np.asarray(world.inv_masses, dtype=np.float64)
        ),
        "bodies": [_encode_body(b) for b in world.bodies],
        "joints": [_encode_joint(j) for j in world.joints],
        "gravity": [float(world.gravity[0]), float(world.gravity[1])],
        "solver_iterations": int(world.solver_iterations),
        "warn_overdamping": bool(world.warn_overdamping),
        "frame": int(world.frame),
    }


def world_from_dict(d: dict) -> World:
    """Reconstruct a :class:`World` from a dict produced by
    :func:`world_to_dict`.

    Raises
    ------
    ValueError
        If ``d`` is not a dict, is missing required keys, has the wrong schema
        version, or contains malformed arrays / joints / bodies.
    """
    if not isinstance(d, dict):
        raise ValueError(
            f"world_from_dict: expected a dict; got {type(d).__name__}"
        )
    missing = _REQUIRED_WORLD_KEYS - set(d.keys())
    if missing:
        raise ValueError(
            f"world_from_dict: missing required keys {sorted(missing)!r}"
        )
    schema = d["schema_version"]
    if schema != SCHEMA_VERSION:
        raise ValueError(
            f"world_from_dict: unsupported schema_version {schema!r} "
            f"(this build expects {SCHEMA_VERSION})"
        )
    positions = _decode_array(d["positions"], name="positions")
    prev_positions = _decode_array(d["prev_positions"], name="prev_positions")
    velocities = _decode_array(d["velocities"], name="velocities")
    inv_masses = _decode_array(d["inv_masses"], name="inv_masses")
    # Shape sanity — protects the solver from a malformed save corrupting
    # state mid-step.
    if positions.ndim != 2 or positions.shape[1] != 2:
        raise ValueError(
            f"world_from_dict: positions must be (N, 2); "
            f"got shape {positions.shape!r}"
        )
    n = positions.shape[0]
    if prev_positions.shape != positions.shape:
        raise ValueError(
            f"world_from_dict: prev_positions shape {prev_positions.shape!r} "
            f"does not match positions shape {positions.shape!r}"
        )
    if velocities.shape != positions.shape:
        raise ValueError(
            f"world_from_dict: velocities shape {velocities.shape!r} "
            f"does not match positions shape {positions.shape!r}"
        )
    if inv_masses.shape != (n,):
        raise ValueError(
            f"world_from_dict: inv_masses shape {inv_masses.shape!r} "
            f"does not match (N,) with N={n}"
        )

    gravity_raw = d["gravity"]
    if (
        not isinstance(gravity_raw, (list, tuple))
        or len(gravity_raw) != 2
    ):
        raise ValueError(
            f"world_from_dict: gravity must be a 2-sequence; "
            f"got {gravity_raw!r}"
        )
    try:
        gravity = (float(gravity_raw[0]), float(gravity_raw[1]))
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"world_from_dict: gravity entries must be floats; "
            f"got {gravity_raw!r}"
        ) from exc

    if not isinstance(d["bodies"], list):
        raise ValueError(
            f"world_from_dict: bodies must be a list; "
            f"got {type(d['bodies']).__name__}"
        )
    if not isinstance(d["joints"], list):
        raise ValueError(
            f"world_from_dict: joints must be a list; "
            f"got {type(d['joints']).__name__}"
        )

    w = World(gravity=gravity)
    w.positions = positions.astype(np.float64, copy=True)
    w.prev_positions = prev_positions.astype(np.float64, copy=True)
    w.velocities = velocities.astype(np.float64, copy=True)
    w.inv_masses = inv_masses.astype(np.float64, copy=True)
    w.solver_iterations = int(d["solver_iterations"])
    w.warn_overdamping = bool(d["warn_overdamping"])
    w.frame = int(d["frame"])
    w.bodies = [_decode_body(b, index=i) for i, b in enumerate(d["bodies"])]
    w.joints = [_decode_joint(j, index=i) for i, j in enumerate(d["joints"])]
    return w


def save_world(world: World, path: Path | str) -> None:
    """JSON-encode ``world`` and write it to ``path``.

    Raises
    ------
    TypeError
        If ``world`` is not a :class:`World`.
    ValueError
        If ``path`` does not end in ``.json``.
    """
    if not isinstance(world, World):
        raise TypeError(
            f"save_world: expected a World; got {type(world).__name__}"
        )
    p = Path(path)
    if p.suffix.lower() != ".json":
        raise ValueError(
            f"save_world: path must end with .json; got {str(path)!r}"
        )
    data = world_to_dict(world)
    p.write_text(json.dumps(data), encoding="utf-8")


def load_world(path: Path | str) -> World:
    """Read a JSON world file and deserialise it.

    Raises
    ------
    ValueError
        If ``path`` does not end in ``.json``, the file is not valid JSON, or
        the contents do not describe a well-formed world.
    FileNotFoundError
        If ``path`` does not exist.
    """
    p = Path(path)
    if p.suffix.lower() != ".json":
        raise ValueError(
            f"load_world: path must end with .json; got {str(path)!r}"
        )
    text = p.read_text(encoding="utf-8")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"load_world: {p} is not valid JSON ({exc.msg} at "
            f"line {exc.lineno} col {exc.colno})"
        ) from exc
    return world_from_dict(payload)


__all__ = [
    "SCHEMA_VERSION",
    "world_to_dict",
    "world_from_dict",
    "save_world",
    "load_world",
]
