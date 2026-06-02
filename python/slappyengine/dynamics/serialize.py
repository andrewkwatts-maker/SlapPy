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
from .humanoid import Humanoid
from .ik import IKChainSpec
from .joint import KIND_PARAM_KEYS, JointSpec
from .material import Material
from .motor import MotorSpec
from .ragdoll import BoneSpec, RagdollSpec
from .rope import RopeSpec
from .spring import SpringSpec
from .world import World

# Schema version — bump when the on-disk format breaks compatibility.
SCHEMA_VERSION = 1

# JSON-safe primitive types accepted inside ``JointSpec.params`` /
# ``Body.parameters`` after numpy coercion. Anything outside this set is
# rejected with a clear message at serialise time so a save file never
# captures a half-encoded blob.
_PARAMS_SCALAR_TYPES: tuple[type, ...] = (str, int, float, bool, type(None))

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


def _params_to_json_safe(value: Any, *, path: str) -> Any:
    """Strict :func:`_to_json_safe` variant for ``JointSpec.params``.

    The XPBD solver only ever stores JSON-trivial values (ints, floats,
    bools, 2-tuples of floats, strings) inside ``params``. A save that
    captured an opaque builder object would silently round-trip to a
    ``repr(...)`` string and corrupt the next load. This helper coerces
    numpy scalars to Python primitives and raises :class:`TypeError`
    with a precise ``path`` for anything outside the supported set.
    """
    if isinstance(value, np.ndarray):
        if value.size <= 16:
            return [
                _params_to_json_safe(v, path=f"{path}[{i}]")
                for i, v in enumerate(value.tolist())
            ]
        return _encode_array(value)
    if isinstance(value, np.floating):
        f = float(value)
        if math.isnan(f):
            return "NaN"
        if math.isinf(f):
            return "Infinity" if f > 0 else "-Infinity"
        return f
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, float):
        if math.isnan(value):
            return "NaN"
        if math.isinf(value):
            return "Infinity" if value > 0 else "-Infinity"
        return value
    if isinstance(value, dict):
        return {
            str(k): _params_to_json_safe(v, path=f"{path}.{k}")
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [
            _params_to_json_safe(v, path=f"{path}[{i}]")
            for i, v in enumerate(value)
        ]
    if isinstance(value, _PARAMS_SCALAR_TYPES):
        return value
    raise TypeError(
        f"JointSpec.params: cannot serialise value at {path!r} of type "
        f"{type(value).__name__}; only str/int/float/bool/None plus nested "
        f"list/tuple/dict and numpy scalars/arrays are supported."
    )


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
        "params": _params_to_json_safe(j.params, path="params"),
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


# ---------------------------------------------------------------------------
# Per-spec dict encoders for Round 1 + Round 2 types.
# Each helper mirrors the dataclass field-by-field so a payload can be
# inspected, diffed, or rebuilt in isolation (handy for editor presets and
# the unified ``slappyengine.serialize`` dispatch).
# ---------------------------------------------------------------------------


def _float_or_str(value: float) -> Any:
    """Encode +/-inf and NaN as JSON-safe strings; finite floats pass through."""
    f = float(value)
    if math.isnan(f):
        return "NaN"
    if math.isinf(f):
        return "Infinity" if f > 0 else "-Infinity"
    return f


def _decode_float(value: Any) -> float:
    """Inverse of :func:`_float_or_str` — accepts the three string sentinels
    or any int/float."""
    if isinstance(value, str):
        if value == "NaN":
            return float("nan")
        if value == "Infinity":
            return float("inf")
        if value == "-Infinity":
            return float("-inf")
        raise ValueError(
            f"_decode_float: unrecognised string sentinel {value!r}; expected "
            f"'NaN', 'Infinity', or '-Infinity'"
        )
    return float(value)


def material_to_dict(mat: Material) -> dict[str, Any]:
    """Encode a :class:`Material` as a JSON-compatible dict."""
    if not isinstance(mat, Material):
        raise TypeError(
            f"material_to_dict: expected Material; got {type(mat).__name__}"
        )
    return {
        "_kind": "Material",
        "name": str(mat.name),
        "density": float(mat.density),
        "stiffness": float(mat.stiffness),
        "damping": float(mat.damping),
        "restitution": float(mat.restitution),
        "friction": float(mat.friction),
        "breaking_strain": _float_or_str(mat.breaking_strain),
        "properties": _params_to_json_safe(mat.properties, path="properties"),
    }


def material_from_dict(d: dict[str, Any]) -> Material:
    """Inverse of :func:`material_to_dict`."""
    if not isinstance(d, dict):
        raise ValueError(
            f"material_from_dict: expected dict; got {type(d).__name__}"
        )
    return Material(
        name=str(d.get("name", "default")),
        density=float(d.get("density", 1000.0)),
        stiffness=float(d.get("stiffness", 1.0e6)),
        damping=float(d.get("damping", 0.05)),
        restitution=float(d.get("restitution", 0.2)),
        friction=float(d.get("friction", 0.5)),
        breaking_strain=_decode_float(d.get("breaking_strain", "Infinity")),
        properties={
            k: _from_json_safe(v) for k, v in d.get("properties", {}).items()
        },
    )


def body_to_dict(body: Body) -> dict[str, Any]:
    """Encode a :class:`Body` as a JSON-compatible dict."""
    if not isinstance(body, Body):
        raise TypeError(
            f"body_to_dict: expected Body; got {type(body).__name__}"
        )
    out = _encode_body(body)
    out["_kind"] = "Body"
    return out


def body_from_dict(d: dict[str, Any]) -> Body:
    """Inverse of :func:`body_to_dict`."""
    return _decode_body(d, index=0)


def joint_to_dict(joint: JointSpec) -> dict[str, Any]:
    """Encode a :class:`JointSpec` as a JSON-compatible dict."""
    if not isinstance(joint, JointSpec):
        raise TypeError(
            f"joint_to_dict: expected JointSpec; got {type(joint).__name__}"
        )
    out = _encode_joint(joint)
    out["_kind"] = "JointSpec"
    return out


def joint_from_dict(d: dict[str, Any]) -> JointSpec:
    """Inverse of :func:`joint_to_dict`."""
    return _decode_joint(d, index=0)


def spring_to_dict(spec: SpringSpec) -> dict[str, Any]:
    """Encode a :class:`SpringSpec` preset."""
    if not isinstance(spec, SpringSpec):
        raise TypeError(
            f"spring_to_dict: expected SpringSpec; got {type(spec).__name__}"
        )
    return {
        "_kind": "SpringSpec",
        "node_a": int(spec.node_a),
        "node_b": int(spec.node_b),
        "rest_length": float(spec.rest_length),
        "stiffness": float(spec.stiffness),
        "damping": float(spec.damping),
        "params": _params_to_json_safe(spec.params, path="params"),
    }


def spring_from_dict(d: dict[str, Any]) -> SpringSpec:
    """Inverse of :func:`spring_to_dict`."""
    if not isinstance(d, dict):
        raise ValueError(
            f"spring_from_dict: expected dict; got {type(d).__name__}"
        )
    return SpringSpec(
        node_a=int(d["node_a"]),
        node_b=int(d["node_b"]),
        rest_length=float(d["rest_length"]),
        stiffness=float(d.get("stiffness", 1.0e6)),
        damping=float(d.get("damping", 0.05)),
        params={k: _from_json_safe(v) for k, v in d.get("params", {}).items()},
    )


def motor_to_dict(spec: MotorSpec) -> dict[str, Any]:
    """Encode a :class:`MotorSpec` preset."""
    if not isinstance(spec, MotorSpec):
        raise TypeError(
            f"motor_to_dict: expected MotorSpec; got {type(spec).__name__}"
        )
    return {
        "_kind": "MotorSpec",
        "hub": int(spec.hub),
        "rim_a": int(spec.rim_a),
        "rim_b": int(spec.rim_b),
        "target_omega": float(spec.target_omega),
        "max_torque": float(spec.max_torque),
        "radius": float(spec.radius),
        "axis": [float(spec.axis[0]), float(spec.axis[1])],
        "stiffness": float(spec.stiffness),
        "damping": float(spec.damping),
        "params": _params_to_json_safe(spec.params, path="params"),
    }


def motor_from_dict(d: dict[str, Any]) -> MotorSpec:
    """Inverse of :func:`motor_to_dict`."""
    if not isinstance(d, dict):
        raise ValueError(
            f"motor_from_dict: expected dict; got {type(d).__name__}"
        )
    axis_raw = d.get("axis", (1.0, 0.0))
    if not hasattr(axis_raw, "__len__") or len(axis_raw) != 2:
        raise ValueError(
            f"motor_from_dict: axis must be a 2-sequence; got {axis_raw!r}"
        )
    return MotorSpec(
        hub=int(d["hub"]),
        rim_a=int(d["rim_a"]),
        rim_b=int(d["rim_b"]),
        target_omega=float(d["target_omega"]),
        max_torque=float(d["max_torque"]),
        radius=float(d.get("radius", 0.0)),
        axis=(float(axis_raw[0]), float(axis_raw[1])),
        stiffness=float(d.get("stiffness", 1.0e8)),
        damping=float(d.get("damping", 0.02)),
        params={k: _from_json_safe(v) for k, v in d.get("params", {}).items()},
    )


def rope_spec_to_dict(spec: RopeSpec) -> dict[str, Any]:
    """Encode a :class:`RopeSpec` preset."""
    if not isinstance(spec, RopeSpec):
        raise TypeError(
            f"rope_spec_to_dict: expected RopeSpec; got {type(spec).__name__}"
        )
    return {
        "_kind": "RopeSpec",
        "node_count": int(spec.node_count),
        "total_length": float(spec.total_length),
        "mass_per_node": float(spec.mass_per_node),
        "stiffness": float(spec.stiffness),
        "damping": float(spec.damping),
        "bend_stiffness": float(spec.bend_stiffness),
        "anchor_a_pinned": bool(spec.anchor_a_pinned),
        "anchor_b_pinned": bool(spec.anchor_b_pinned),
        "params": _params_to_json_safe(spec.params, path="params"),
    }


def rope_spec_from_dict(d: dict[str, Any]) -> RopeSpec:
    """Inverse of :func:`rope_spec_to_dict`."""
    if not isinstance(d, dict):
        raise ValueError(
            f"rope_spec_from_dict: expected dict; got {type(d).__name__}"
        )
    return RopeSpec(
        node_count=int(d["node_count"]),
        total_length=float(d["total_length"]),
        mass_per_node=float(d.get("mass_per_node", 0.1)),
        stiffness=float(d.get("stiffness", 1.0e6)),
        damping=float(d.get("damping", 0.05)),
        bend_stiffness=float(d.get("bend_stiffness", 0.0)),
        anchor_a_pinned=bool(d.get("anchor_a_pinned", True)),
        anchor_b_pinned=bool(d.get("anchor_b_pinned", False)),
        params={k: _from_json_safe(v) for k, v in d.get("params", {}).items()},
    )


def bone_spec_to_dict(bone: BoneSpec) -> dict[str, Any]:
    """Encode a single :class:`BoneSpec`."""
    if not isinstance(bone, BoneSpec):
        raise TypeError(
            f"bone_spec_to_dict: expected BoneSpec; got {type(bone).__name__}"
        )
    return {
        "_kind": "BoneSpec",
        "parent_idx": int(bone.parent_idx),
        "length": float(bone.length),
        "mass": float(bone.mass),
        "angle_limit": [
            float(bone.angle_limit[0]),
            float(bone.angle_limit[1]),
        ],
        "direction": [
            float(bone.direction[0]),
            float(bone.direction[1]),
        ],
        "label": str(bone.label),
    }


def bone_spec_from_dict(d: dict[str, Any]) -> BoneSpec:
    """Inverse of :func:`bone_spec_to_dict`."""
    if not isinstance(d, dict):
        raise ValueError(
            f"bone_spec_from_dict: expected dict; got {type(d).__name__}"
        )
    al = d.get("angle_limit", (-math.pi, math.pi))
    di = d.get("direction", (0.0, -1.0))
    return BoneSpec(
        parent_idx=int(d.get("parent_idx", -1)),
        length=float(d.get("length", 1.0)),
        mass=float(d.get("mass", 1.0)),
        angle_limit=(float(al[0]), float(al[1])),
        direction=(float(di[0]), float(di[1])),
        label=str(d.get("label", "")),
    )


def ragdoll_spec_to_dict(spec: RagdollSpec) -> dict[str, Any]:
    """Encode a :class:`RagdollSpec` preset (bones + extra joints)."""
    if not isinstance(spec, RagdollSpec):
        raise TypeError(
            f"ragdoll_spec_to_dict: expected RagdollSpec; "
            f"got {type(spec).__name__}"
        )
    return {
        "_kind": "RagdollSpec",
        "bones": [bone_spec_to_dict(b) for b in spec.bones],
        "joints": [_encode_joint(j) for j in spec.joints],
        "stiffness": float(spec.stiffness),
        "damping": float(spec.damping),
    }


def ragdoll_spec_from_dict(d: dict[str, Any]) -> RagdollSpec:
    """Inverse of :func:`ragdoll_spec_to_dict`."""
    if not isinstance(d, dict):
        raise ValueError(
            f"ragdoll_spec_from_dict: expected dict; got {type(d).__name__}"
        )
    bones_raw = d.get("bones", [])
    if not isinstance(bones_raw, list):
        raise ValueError(
            f"ragdoll_spec_from_dict: bones must be a list; "
            f"got {type(bones_raw).__name__}"
        )
    joints_raw = d.get("joints", [])
    if not isinstance(joints_raw, list):
        raise ValueError(
            f"ragdoll_spec_from_dict: joints must be a list; "
            f"got {type(joints_raw).__name__}"
        )
    return RagdollSpec(
        bones=[bone_spec_from_dict(b) for b in bones_raw],
        joints=[_decode_joint(j, index=i) for i, j in enumerate(joints_raw)],
        stiffness=float(d.get("stiffness", 5.0e6)),
        damping=float(d.get("damping", 0.05)),
    )


def ik_chain_to_dict(spec: IKChainSpec) -> dict[str, Any]:
    """Encode an :class:`IKChainSpec`."""
    if not isinstance(spec, IKChainSpec):
        raise TypeError(
            f"ik_chain_to_dict: expected IKChainSpec; "
            f"got {type(spec).__name__}"
        )
    return {
        "_kind": "IKChainSpec",
        "node_indices": [int(i) for i in spec.node_indices],
        "target": [float(spec.target[0]), float(spec.target[1])],
        "fixed_root": bool(spec.fixed_root),
        "params": _params_to_json_safe(spec.params, path="params"),
    }


def ik_chain_from_dict(d: dict[str, Any]) -> IKChainSpec:
    """Inverse of :func:`ik_chain_to_dict`."""
    if not isinstance(d, dict):
        raise ValueError(
            f"ik_chain_from_dict: expected dict; got {type(d).__name__}"
        )
    tgt = d.get("target", (0.0, 0.0))
    return IKChainSpec(
        node_indices=[int(i) for i in d["node_indices"]],
        target=(float(tgt[0]), float(tgt[1])),
        fixed_root=bool(d.get("fixed_root", True)),
        params={k: _from_json_safe(v) for k, v in d.get("params", {}).items()},
    )


def humanoid_to_dict(humanoid: Humanoid) -> dict[str, Any]:
    """Encode a :class:`Humanoid` handle.

    Captures every named bone node index, the bone/beam slices and body id,
    the cached bone-length table, and the flesh-layer node/beam slices added
    by :func:`wrap_in_flesh`. The host softbody world (the SoA arrays
    themselves) is *not* serialised here — pair this with the host world's
    own save format.
    """
    if not isinstance(humanoid, Humanoid):
        raise TypeError(
            f"humanoid_to_dict: expected Humanoid; got {type(humanoid).__name__}"
        )
    return {
        "_kind": "Humanoid",
        "pelvis": int(humanoid.pelvis),
        "neck": int(humanoid.neck),
        "head": int(humanoid.head),
        "shoulder_l": int(humanoid.shoulder_l),
        "elbow_l": int(humanoid.elbow_l),
        "wrist_l": int(humanoid.wrist_l),
        "shoulder_r": int(humanoid.shoulder_r),
        "elbow_r": int(humanoid.elbow_r),
        "wrist_r": int(humanoid.wrist_r),
        "hip_l": int(humanoid.hip_l),
        "knee_l": int(humanoid.knee_l),
        "ankle_l": int(humanoid.ankle_l),
        "hip_r": int(humanoid.hip_r),
        "knee_r": int(humanoid.knee_r),
        "ankle_r": int(humanoid.ankle_r),
        "node_slice": [int(humanoid.node_slice[0]), int(humanoid.node_slice[1])],
        "beam_slice": [int(humanoid.beam_slice[0]), int(humanoid.beam_slice[1])],
        "body_id": int(humanoid.body_id),
        "bone_lengths": {str(k): float(v) for k, v in humanoid.bone_lengths.items()},
        "flesh_node_slices": {
            str(k): [int(v[0]), int(v[1])]
            for k, v in humanoid.flesh_node_slices.items()
        },
        "flesh_beam_slices": {
            str(k): [int(v[0]), int(v[1])]
            for k, v in humanoid.flesh_beam_slices.items()
        },
    }


def humanoid_from_dict(d: dict[str, Any]) -> Humanoid:
    """Inverse of :func:`humanoid_to_dict`."""
    if not isinstance(d, dict):
        raise ValueError(
            f"humanoid_from_dict: expected dict; got {type(d).__name__}"
        )
    ns = d.get("node_slice", (0, 0))
    bs = d.get("beam_slice", (0, 0))
    return Humanoid(
        pelvis=int(d.get("pelvis", -1)),
        neck=int(d.get("neck", -1)),
        head=int(d.get("head", -1)),
        shoulder_l=int(d.get("shoulder_l", -1)),
        elbow_l=int(d.get("elbow_l", -1)),
        wrist_l=int(d.get("wrist_l", -1)),
        shoulder_r=int(d.get("shoulder_r", -1)),
        elbow_r=int(d.get("elbow_r", -1)),
        wrist_r=int(d.get("wrist_r", -1)),
        hip_l=int(d.get("hip_l", -1)),
        knee_l=int(d.get("knee_l", -1)),
        ankle_l=int(d.get("ankle_l", -1)),
        hip_r=int(d.get("hip_r", -1)),
        knee_r=int(d.get("knee_r", -1)),
        ankle_r=int(d.get("ankle_r", -1)),
        node_slice=(int(ns[0]), int(ns[1])),
        beam_slice=(int(bs[0]), int(bs[1])),
        body_id=int(d.get("body_id", 0)),
        bone_lengths={
            str(k): float(v) for k, v in d.get("bone_lengths", {}).items()
        },
        flesh_node_slices={
            str(k): (int(v[0]), int(v[1]))
            for k, v in d.get("flesh_node_slices", {}).items()
        },
        flesh_beam_slices={
            str(k): (int(v[0]), int(v[1]))
            for k, v in d.get("flesh_beam_slices", {}).items()
        },
    )


__all__ = [
    "SCHEMA_VERSION",
    "world_to_dict",
    "world_from_dict",
    "save_world",
    "load_world",
    "body_to_dict",
    "body_from_dict",
    "joint_to_dict",
    "joint_from_dict",
    "spring_to_dict",
    "spring_from_dict",
    "motor_to_dict",
    "motor_from_dict",
    "rope_spec_to_dict",
    "rope_spec_from_dict",
    "bone_spec_to_dict",
    "bone_spec_from_dict",
    "ragdoll_spec_to_dict",
    "ragdoll_spec_from_dict",
    "ik_chain_to_dict",
    "ik_chain_from_dict",
    "humanoid_to_dict",
    "humanoid_from_dict",
    "material_to_dict",
    "material_from_dict",
]
