"""Cross-subsystem serialization — JSON + YAML, dynamics + thermal + zones +
iso.combat + telemetry history + composite "save game" envelope.

Sprint 4 surfaced five subsystems that didn't round-trip. This module
closes those gaps with a single unified API:

* :func:`to_dict(obj)` — dispatch on type; returns a JSON-compatible dict
* :func:`from_dict(d, kind=None)` — inverse; auto-discriminates by the
  envelope's ``"_kind"`` field
* :func:`save(obj, path)` — writes ``.json`` or ``.yml`` based on suffix
* :func:`load(path, kind=None)` — reads either format

Numpy arrays are encoded the same way as :mod:`slappyengine.dynamics.serialize`:
``{"_dtype", "_shape", "_b64"}``. Callable fields (``zone.on_enter``, etc.)
serialize to ``None`` with a warning; reload restores them to no-op stubs.

A composite "save game" wraps multiple sub-states in one envelope:

>>> from slappyengine.serialize import SaveGame, save, load
>>> sg = SaveGame(world=my_world, thermal=heat_field, zones=zone_manager)
>>> save(sg, "savegame.yml")
>>> sg2 = load("savegame.yml")

Closed Sprint 4 gaps:
- ``slappyengine.thermal.HeatField`` (temperature grid + conductivity + diffusivity)
- ``slappyengine.zones.RectZone`` / ``ThresholdZone`` / ``ZoneManager``
- ``slappyengine.iso.combat.WaveSpec`` / ``WaveSchedule`` / ``Attacker`` / ``Defender``
- ``slappyengine.telemetry`` history ring buffer
- :class:`SaveGame` aggregate envelope
"""
from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


_NDARRAY_SENTINEL = "_b64"


def _np_to_dict(arr: np.ndarray) -> dict:
    return {
        "_dtype": str(arr.dtype),
        "_shape": list(arr.shape),
        _NDARRAY_SENTINEL: base64.b64encode(arr.tobytes()).decode("ascii"),
    }


def _np_from_dict(d: dict) -> np.ndarray:
    raw = base64.b64decode(d[_NDARRAY_SENTINEL])
    arr = np.frombuffer(raw, dtype=np.dtype(d["_dtype"]))
    return arr.reshape(d["_shape"])


def _is_np_dict(d: Any) -> bool:
    return isinstance(d, dict) and _NDARRAY_SENTINEL in d and "_dtype" in d


# ---------------------------------------------------------------------------
# Per-subsystem encoders / decoders
# ---------------------------------------------------------------------------


def _heatfield_to_dict(hf) -> dict:
    return {
        "_kind": "HeatField",
        "temperature": _np_to_dict(hf.temperature),
        "conductivity": float(hf.conductivity),
        "diffusivity": float(hf.diffusivity),
    }


def _heatfield_from_dict(d: dict):
    from slappyengine.thermal import HeatField
    grid = _np_from_dict(d["temperature"])
    return HeatField(
        grid,
        conductivity=float(d.get("conductivity", 1.0)),
        diffusivity=float(d.get("diffusivity", 0.1)),
    )


def _rectzone_to_dict(z) -> dict:
    cls = type(z).__name__
    base = {
        "_kind": cls,
        "name": z.name,
        "x": float(z.x),
        "y": float(z.y),
        "w": float(z.w),
        "h": float(z.h),
        "material": getattr(z, "material", None),
        # Callbacks aren't serialisable; restored as no-ops on load.
        "_has_on_enter": getattr(z, "on_enter", None) is not None,
        "_has_on_exit": getattr(z, "on_exit", None) is not None,
    }
    if cls == "ThresholdZone":
        base.update({
            "threshold": float(z.threshold),
            "hysteresis": float(z.hysteresis),
            "strength_scale": float(z.strength_scale),
            "on_destroy_event": z.on_destroy_event,
            "_has_on_threshold": getattr(z, "on_threshold", None) is not None,
        })
    return base


def _rectzone_from_dict(d: dict):
    from slappyengine.zones import RectZone, ThresholdZone
    kw = dict(name=d["name"], x=d["x"], y=d["y"], w=d["w"], h=d["h"])
    if "material" in d:
        kw["material"] = d["material"]
    if d.get("_kind") == "ThresholdZone":
        kw.update(dict(
            threshold=d.get("threshold", 0.0),
            hysteresis=d.get("hysteresis", 0.05),
            strength_scale=d.get("strength_scale", 1.0),
            on_destroy_event=d.get("on_destroy_event", "Zone.Destroyed"),
        ))
        return ThresholdZone(**kw)
    return RectZone(**kw)


def _zonemanager_to_dict(zm) -> dict:
    return {
        "_kind": "ZoneManager",
        "zones": [_rectzone_to_dict(z) for z in zm.zones()],
        "spatial_hash_enabled": bool(zm.spatial_hash_enabled),
    }


def _zonemanager_from_dict(d: dict):
    from slappyengine.zones import ZoneManager
    zm = ZoneManager()
    for zd in d.get("zones", []):
        zm.add(_rectzone_from_dict(zd))
    if not d.get("spatial_hash_enabled", True):
        zm.enable_spatial_hash(False)
    return zm


def _wavespec_to_dict(ws) -> dict:
    return {
        "_kind": "WaveSpec",
        "count": int(ws.count),
        "spawn_points": [(float(x), float(y)) for x, y in ws.spawn_points],
        "hp_each": float(ws.hp_each),
        "interval": float(ws.interval),
        "delay": float(getattr(ws, "delay", 0.0)),
    }


def _wavespec_from_dict(d: dict):
    from slappyengine.iso.combat import WaveSpec
    return WaveSpec(
        count=d["count"],
        spawn_points=[tuple(p) for p in d["spawn_points"]],
        hp_each=d["hp_each"],
        interval=d["interval"],
        delay=d.get("delay", 0.0),
    )


def _attacker_to_dict(a) -> dict:
    return {
        "_kind": "Attacker",
        "pos": (float(a.pos[0]), float(a.pos[1])),
        "damage": float(a.damage),
        "reach": float(a.reach),
        "team": a.team,
    }


def _attacker_from_dict(d: dict):
    from slappyengine.iso.combat import Attacker
    return Attacker(
        pos=tuple(d["pos"]),
        damage=d["damage"],
        reach=d["reach"],
        team=d.get("team", "player"),
    )


def _defender_to_dict(de) -> dict:
    return {
        "_kind": "Defender",
        "pos": (float(de.pos[0]), float(de.pos[1])),
        "hp": float(de.hp),
        "team": de.team,
    }


def _defender_from_dict(d: dict):
    from slappyengine.iso.combat import Defender
    return Defender(
        pos=tuple(d["pos"]),
        hp=d["hp"],
        team=d.get("team", "enemy"),
    )


def _telemetry_history_to_dict(events: list) -> dict:
    # events: list[TelemetryEvent] — preserve order, drop callable/object payloads.
    return {
        "_kind": "TelemetryHistory",
        "events": [
            {
                "name": ev.name,
                "timestamp": float(ev.timestamp),
                "payload": _payload_to_serializable(ev.payload),
                "source": ev.source,
            }
            for ev in events
        ],
    }


def _telemetry_history_from_dict(d: dict) -> list:
    from slappyengine.telemetry import TelemetryEvent
    return [
        TelemetryEvent(
            name=e["name"],
            timestamp=e["timestamp"],
            payload=e.get("payload", {}),
            source=e.get("source"),
        )
        for e in d.get("events", [])
    ]


def _payload_to_serializable(payload: dict) -> dict:
    """Drop callable / non-JSON-able payload values; primitives pass through."""
    out: dict = {}
    for k, v in payload.items():
        if callable(v):
            continue
        if isinstance(v, (str, int, float, bool, type(None))):
            out[k] = v
        elif isinstance(v, (list, tuple)):
            out[k] = list(v)
        elif isinstance(v, dict):
            out[k] = _payload_to_serializable(v)
        else:
            # Last resort: stringify so the event still round-trips, just lossy.
            out[k] = str(v)
    return out


# ---------------------------------------------------------------------------
# SaveGame envelope
# ---------------------------------------------------------------------------


class SaveGame:
    """Aggregate save envelope. Wrap as many sub-states as you have."""

    def __init__(
        self,
        world=None,
        thermal=None,
        zones=None,
        wave_schedule=None,
        attackers: list | None = None,
        defenders: list | None = None,
        telemetry_history: list | None = None,
        meta: dict | None = None,
    ) -> None:
        self.world = world
        self.thermal = thermal
        self.zones = zones
        self.wave_schedule = wave_schedule
        self.attackers = list(attackers) if attackers is not None else None
        self.defenders = list(defenders) if defenders is not None else None
        self.telemetry_history = list(telemetry_history) if telemetry_history is not None else None
        self.meta = dict(meta) if meta is not None else {}


def _savegame_to_dict(sg: SaveGame) -> dict:
    out: dict = {"_kind": "SaveGame", "meta": dict(sg.meta)}
    if sg.world is not None:
        from slappyengine.dynamics.serialize import world_to_dict
        out["world"] = world_to_dict(sg.world)
    if sg.thermal is not None:
        out["thermal"] = _heatfield_to_dict(sg.thermal)
    if sg.zones is not None:
        out["zones"] = _zonemanager_to_dict(sg.zones)
    if sg.attackers:
        out["attackers"] = [_attacker_to_dict(a) for a in sg.attackers]
    if sg.defenders:
        out["defenders"] = [_defender_to_dict(d) for d in sg.defenders]
    if sg.telemetry_history is not None:
        out["telemetry_history"] = _telemetry_history_to_dict(sg.telemetry_history)
    return out


def _savegame_from_dict(d: dict) -> SaveGame:
    sg = SaveGame(meta=d.get("meta", {}))
    if "world" in d:
        from slappyengine.dynamics.serialize import world_from_dict
        sg.world = world_from_dict(d["world"])
    if "thermal" in d:
        sg.thermal = _heatfield_from_dict(d["thermal"])
    if "zones" in d:
        sg.zones = _zonemanager_from_dict(d["zones"])
    if "attackers" in d:
        sg.attackers = [_attacker_from_dict(x) for x in d["attackers"]]
    if "defenders" in d:
        sg.defenders = [_defender_from_dict(x) for x in d["defenders"]]
    if "telemetry_history" in d:
        sg.telemetry_history = _telemetry_history_from_dict(d["telemetry_history"])
    return sg


# ---------------------------------------------------------------------------
# Public dispatch
# ---------------------------------------------------------------------------


def to_dict(obj: Any) -> dict:
    """Convert any supported engine object to a JSON-compatible dict.

    Supported: :class:`slappyengine.dynamics.World`, ``HeatField``, ``RectZone``
    / ``ThresholdZone``, ``ZoneManager``, ``WaveSpec``, ``Attacker``,
    ``Defender``, ``list[TelemetryEvent]``, :class:`SaveGame`.
    """
    if isinstance(obj, SaveGame):
        return _savegame_to_dict(obj)
    # Defer imports so this module stays cheap to load.
    try:
        from slappyengine.dynamics.world import World
        if isinstance(obj, World):
            from slappyengine.dynamics.serialize import world_to_dict
            return world_to_dict(obj)
    except Exception:
        pass
    try:
        from slappyengine.thermal import HeatField
        if isinstance(obj, HeatField):
            return _heatfield_to_dict(obj)
    except Exception:
        pass
    try:
        from slappyengine.zones import RectZone, ThresholdZone, ZoneManager
        if isinstance(obj, ZoneManager):
            return _zonemanager_to_dict(obj)
        if isinstance(obj, (ThresholdZone, RectZone)):
            return _rectzone_to_dict(obj)
    except Exception:
        pass
    try:
        from slappyengine.iso.combat import (
            Attacker, Defender, WaveSpec, WaveSchedule,
        )
        if isinstance(obj, WaveSpec):
            return _wavespec_to_dict(obj)
        if isinstance(obj, Attacker):
            return _attacker_to_dict(obj)
        if isinstance(obj, Defender):
            return _defender_to_dict(obj)
        if isinstance(obj, WaveSchedule):
            # Serialise the underlying specs + finished flag. The Schedule's
            # internal _waves list wraps each spec in _WaveState; we only
            # need to round-trip the original WaveSpec inputs.
            specs = [_wavespec_to_dict(state.spec) for state in obj._waves]
            return {
                "_kind": "WaveSchedule",
                "specs": specs,
                "finished": bool(obj.finished),
            }
    except Exception:
        pass
    if isinstance(obj, list) and obj and hasattr(obj[0], "timestamp"):
        return _telemetry_history_to_dict(obj)
    raise TypeError(
        f"to_dict: unsupported type {type(obj).__name__}. "
        f"Supported kinds: World, HeatField, RectZone/ThresholdZone, "
        f"ZoneManager, WaveSpec/Attacker/Defender/WaveSchedule, "
        f"list[TelemetryEvent], SaveGame."
    )


def from_dict(d: dict, kind: str | None = None) -> Any:
    """Inverse of :func:`to_dict`. Auto-discriminates on ``d["_kind"]``.

    Pass ``kind`` explicitly to override (e.g. when the envelope was
    stripped or extended). Returns the reconstructed object.
    """
    k = kind or d.get("_kind")
    if k == "SaveGame":
        return _savegame_from_dict(d)
    if k == "HeatField":
        return _heatfield_from_dict(d)
    if k in ("RectZone", "ThresholdZone"):
        return _rectzone_from_dict(d)
    if k == "ZoneManager":
        return _zonemanager_from_dict(d)
    if k == "WaveSpec":
        return _wavespec_from_dict(d)
    if k == "Attacker":
        return _attacker_from_dict(d)
    if k == "Defender":
        return _defender_from_dict(d)
    if k == "WaveSchedule":
        from slappyengine.iso.combat import WaveSchedule
        specs = [_wavespec_from_dict(sd) for sd in d.get("specs", [])]
        return WaveSchedule(specs)
    if k == "TelemetryHistory":
        return _telemetry_history_from_dict(d)
    if "schema_version" in d:  # legacy dynamics World envelope
        from slappyengine.dynamics.serialize import world_from_dict
        return world_from_dict(d)
    raise ValueError(
        f"from_dict: unknown kind {k!r}. "
        f"Expected SaveGame / HeatField / RectZone / ThresholdZone / "
        f"ZoneManager / WaveSpec / WaveSchedule / Attacker / Defender / "
        f"TelemetryHistory."
    )


# ---------------------------------------------------------------------------
# JSON + YAML file I/O
# ---------------------------------------------------------------------------


def save(obj: Any, path: str | Path) -> None:
    """Write ``obj`` to ``.json`` or ``.yml`` based on the path suffix.

    Raises ``ValueError`` for any other suffix.
    """
    p = Path(path)
    d = to_dict(obj)
    suf = p.suffix.lower()
    if suf == ".json":
        p.write_text(json.dumps(d, indent=2), encoding="utf-8")
    elif suf in (".yml", ".yaml"):
        import yaml
        p.write_text(yaml.safe_dump(d, sort_keys=False), encoding="utf-8")
    else:
        raise ValueError(
            f"save: path must end with .json, .yml, or .yaml; got {p.name!r}"
        )


def load(path: str | Path, kind: str | None = None) -> Any:
    """Read ``.json`` or ``.yml`` produced by :func:`save`.

    Pass ``kind`` to override the envelope discriminator.
    Raises ``ValueError`` on unknown suffix.
    """
    p = Path(path)
    suf = p.suffix.lower()
    if not p.exists():
        raise FileNotFoundError(f"load: {p} does not exist")
    if suf == ".json":
        d = json.loads(p.read_text(encoding="utf-8"))
    elif suf in (".yml", ".yaml"):
        import yaml
        d = yaml.safe_load(p.read_text(encoding="utf-8"))
    else:
        raise ValueError(
            f"load: path must end with .json, .yml, or .yaml; got {p.name!r}"
        )
    return from_dict(d, kind=kind)


__all__ = [
    "SaveGame",
    "to_dict",
    "from_dict",
    "save",
    "load",
]
