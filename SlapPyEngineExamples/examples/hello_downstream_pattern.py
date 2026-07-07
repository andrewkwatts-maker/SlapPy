"""hello_downstream_pattern — VV5 subclass-pattern smoke demo.

This 30-frame demo exercises the exact "subclass-in-external-code"
pattern that downstream games (Ochema Circuit's ``VehicleEntity``,
Bullet Strata's ``PlayerEntity``) rely on but that engine-side tests
historically never covered — the class of gap that leaked 6+ silent
backwards-incompatible breaks past CI over the F1 -> TT6 window.

The demo defines a ``PlayerVehicle(Observable, Asset)`` inside the
example file (mimicking a downstream game class), constructs two
instances, and drives a small pub/sub loop through the module-level
``global_bus``.  Any ``AttributeError`` raised along the way is
captured and dumped to the trace YAML so tests can pin ``== 0``.

Behaviour contract
------------------

* ``PlayerVehicle`` mixes :class:`Observable` first, :class:`Asset`
  second. This is the exact MRO shape TT1 caught regressing.
* The subclass ``__init__`` calls ``super().__init__()`` and THEN adds
  three layers (``chassis``, ``weapon``, ``hud``) via ``add_layer``.
  The pre-super variant is deliberately not exercised here — the
  backcompat harness (UU7) owns that — but the post-super happy-path
  must remain green.
* Reads :attr:`CacheMode.OFFSCREEN_SERIALIZE` to pin the legacy enum
  alias downstream games depend on.
* Publishes 5 events per frame through
  ``global_bus.publish("player.pos", ...)`` for 30 frames = 150 total
  events. A second ``PlayerVehicle`` subscribes and counts deliveries.
* Uses :func:`slappyengine.launch` for the tick loop when the App
  subsystem is available; falls back to a plain loop if launch()
  cannot boot headless.

Output
------

Writes ``hello_downstream_pattern_trace.yaml`` next to this file (or
the caller-supplied ``trace_yaml_path``) with:

* ``mro``                 — string names in the ``PlayerVehicle`` MRO.
* ``layers_added``        — list of layer names attached to instance A.
* ``events_published``    — total publish() calls (target 150).
* ``events_delivered``    — total subscriber invocations (target 150).
* ``attribute_errors``    — count of AttributeError caught (target 0).
* ``cache_mode_value``    — string value of ``CacheMode.OFFSCREEN_SERIALIZE``.
* ``frame_count``         — final frame count from the tick loop.

Run
---

::

    python SlapPyEngineExamples/examples/hello_downstream_pattern.py

Returns a summary dict.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List


# ---------------------------------------------------------------------------
# Paths / constants
# ---------------------------------------------------------------------------

_THIS_DIR = Path(__file__).resolve().parent
_DEFAULT_TRACE_YAML = _THIS_DIR / "hello_downstream_pattern_trace.yaml"

DEFAULT_MAX_FRAMES: int = 30
EVENTS_PER_FRAME: int = 5
EVENT_TOPIC: str = "player.pos"


# ---------------------------------------------------------------------------
# Downstream-style subclass definition
# ---------------------------------------------------------------------------
#
# NOTE: These imports intentionally live at module top so that the demo
# fails loudly at import time if the engine drops Observable / Asset /
# CacheMode / global_bus. Downstream games do the same — a silent
# ``ImportError`` at ``import slappyengine`` is the fastest signal that
# a rename happened.
from slappyengine.asset import Asset
from slappyengine.event_bus import Observable, global_bus
from slappyengine.layer import Layer
from slappyengine.residency.manager import CacheMode


class PlayerVehicle(Observable, Asset):
    """Downstream-style entity mixing Observable + Asset.

    Mirrors Ochema Circuit's ``VehicleEntity`` and Bullet Strata's
    ``PlayerEntity``: Observable-first MRO so ``notify()`` reaches the
    module-level bus, Asset-second so the layer stack is available for
    chassis / weapon / hud sprites.

    The constructor deliberately follows the "call super, then add
    layers, then wire subscriptions" ordering that TT1 pinned as the
    supported downstream pattern.
    """

    def __init__(self, name: str = "player") -> None:
        # super().__init__() is the entry point that must NOT swallow
        # the Asset side of the MRO. Observable.__init__ forwards via
        # cooperative super() (see event_bus.py) so this single line
        # boots BOTH mixins.
        super().__init__()
        # Asset gives us self.layers via RenderTarget.__init__. If a
        # future refactor breaks the cooperative chain, the next line
        # AttributeErrors and the trace records it — that's the whole
        # point of this demo.
        self.name = name
        self.add_layer(Layer(name="chassis"))
        self.add_layer(Layer(name="weapon"))
        self.add_layer(Layer(name="hud"))
        # Legacy enum access — Ochema Circuit stores this on the
        # instance to drive its own eviction policy.
        self.cache_mode = CacheMode.OFFSCREEN_SERIALIZE


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _headless_config() -> Any:
    """Build a headless :class:`AppConfig` if the App subsystem is present."""
    import slappyengine

    return slappyengine.AppConfig(
        window_title="hello_downstream_pattern",
        window_size=(320, 240),
        enable_gpu=False,
        renderer_backend="stub",
        clear_color=(0.05, 0.05, 0.08, 1.0),
        enable_editor=False,
        enable_telemetry=False,
        enable_audio=False,
        target_fps=60,
    )


def _write_trace_yaml(payload: Dict[str, Any], path: Path) -> Path:
    """Dump the trace payload to YAML; falls back to ``repr`` if pyyaml missing."""
    try:
        import yaml
    except Exception:  # pragma: no cover — pyyaml is a regular dep
        path.write_text(repr(payload), encoding="utf-8")
        return path
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(
    *,
    max_frames: int = DEFAULT_MAX_FRAMES,
    trace_yaml_path: str | Path | None = None,
) -> Dict[str, Any]:
    """Boot the 30-frame downstream-subclass demo.

    Parameters
    ----------
    max_frames:
        Frame cap for the tick loop (default 30).
    trace_yaml_path:
        Where to persist the summary YAML. ``None`` writes next to the
        demo module.
    """
    if max_frames < 1:
        raise ValueError(f"max_frames must be >= 1 (got {max_frames})")

    # ---- Mutable state shared across lifecycle callbacks ------------------
    state: Dict[str, Any] = {
        "events_published": 0,
        "events_delivered": 0,
        "attribute_errors": 0,
        "attribute_error_notes": [],
        "frame_count": 0,
        "player_a": None,
        "player_b": None,
        "layers_added": [],
    }

    # ---- Build the two subclass instances (main body of the demo) --------
    # Reset the module-level bus so we start with a clean listener set
    # regardless of prior test-suite runs sharing this process.
    global_bus.clear(EVENT_TOPIC)

    try:
        player_a = PlayerVehicle(name="player_a")
        player_b = PlayerVehicle(name="player_b")
    except AttributeError as exc:
        # This is the TT1-class regression path: capture and continue
        # so the trace still ends up on disk for post-mortem.
        state["attribute_errors"] += 1
        state["attribute_error_notes"].append(f"PlayerVehicle.__init__: {exc!r}")
        state["frame_count"] = 0
        payload = _build_payload(state, max_frames)
        out_path = (
            Path(trace_yaml_path) if trace_yaml_path is not None
            else _DEFAULT_TRACE_YAML
        )
        _write_trace_yaml(payload, out_path)
        return _build_summary(state, out_path)

    state["player_a"] = player_a
    state["player_b"] = player_b
    state["layers_added"] = [layer.name for layer in player_a.layers]

    def _delivery_listener(payload: dict) -> None:
        # Simulate what a real downstream subscriber would do: touch
        # sender + position without exploding on shape drift.
        try:
            _ = payload.get("sender")
            _ = payload.get("x")
            _ = payload.get("y")
            state["events_delivered"] += 1
        except AttributeError as exc:  # pragma: no cover — defensive
            state["attribute_errors"] += 1
            state["attribute_error_notes"].append(
                f"delivery listener: {exc!r}"
            )

    global_bus.subscribe(EVENT_TOPIC, _delivery_listener)

    # ---- Tick loop --------------------------------------------------------
    def _tick_body(frame: int) -> None:
        # Publish EVENTS_PER_FRAME events per frame. Each carries a
        # sender + position payload matching the downstream game shape.
        for i in range(EVENTS_PER_FRAME):
            try:
                global_bus.publish(
                    EVENT_TOPIC,
                    sender=player_a.name,
                    x=float(frame),
                    y=float(i),
                )
                state["events_published"] += 1
            except AttributeError as exc:  # pragma: no cover — defensive
                state["attribute_errors"] += 1
                state["attribute_error_notes"].append(
                    f"publish frame={frame} i={i}: {exc!r}"
                )
        state["frame_count"] = frame + 1

    # Preferred path: use slappyengine.launch() for the tick loop.
    launch_used = False
    try:
        import slappyengine

        def on_tick(a: Any, dt: float) -> None:
            _tick_body(int(a.frame_count))

        app = slappyengine.launch(
            on_tick=on_tick,
            max_frames=max_frames,
            config=_headless_config(),
        )
        state["frame_count"] = int(app.frame_count)
        launch_used = True
    except Exception:
        # Fallback: run the loop directly. Keeps the demo useful even
        # when the App subsystem is missing dependencies in the
        # current env.
        for frame in range(max_frames):
            _tick_body(frame)

    # ---- Cleanup ---------------------------------------------------------
    global_bus.unsubscribe(EVENT_TOPIC, _delivery_listener)

    # ---- Build + persist trace ------------------------------------------
    payload = _build_payload(state, max_frames, launch_used=launch_used)
    out_path = (
        Path(trace_yaml_path) if trace_yaml_path is not None
        else _DEFAULT_TRACE_YAML
    )
    _write_trace_yaml(payload, out_path)

    summary = _build_summary(state, out_path, launch_used=launch_used)

    print("=== hello_downstream_pattern summary ===")
    for key, value in summary.items():
        print(f"  {key}: {value}")

    return summary


def _build_payload(
    state: Dict[str, Any],
    max_frames: int,
    *,
    launch_used: bool = False,
) -> Dict[str, Any]:
    """Compose the YAML-serialisable trace payload."""
    mro_names: List[str] = [cls.__name__ for cls in PlayerVehicle.__mro__]
    return {
        "mro": mro_names,
        "layers_added": list(state["layers_added"]),
        "layer_count": len(state["layers_added"]),
        "events_published": int(state["events_published"]),
        "events_delivered": int(state["events_delivered"]),
        "events_per_frame": int(EVENTS_PER_FRAME),
        "attribute_errors": int(state["attribute_errors"]),
        "attribute_error_notes": list(state["attribute_error_notes"]),
        "cache_mode_value": str(CacheMode.OFFSCREEN_SERIALIZE.value),
        "frame_count": int(state["frame_count"]),
        "max_frames": int(max_frames),
        "launch_used": bool(launch_used),
    }


def _build_summary(
    state: Dict[str, Any],
    trace_path: Path,
    *,
    launch_used: bool = False,
) -> Dict[str, Any]:
    """Compose the small dict returned to the caller."""
    return {
        "mro": [cls.__name__ for cls in PlayerVehicle.__mro__],
        "layer_count": len(state["layers_added"]),
        "events_published": int(state["events_published"]),
        "events_delivered": int(state["events_delivered"]),
        "attribute_errors": int(state["attribute_errors"]),
        "frame_count": int(state["frame_count"]),
        "launch_used": bool(launch_used),
        "trace_path": str(trace_path),
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _honour_headless_env() -> None:
    """Respect ``SLAPPY_HEADLESS=1`` as an env-flag override."""
    if os.environ.get("SLAPPY_HEADLESS", "").strip() in ("", "0"):
        os.environ.setdefault("SLAPPY_HEADLESS", "1")


if __name__ == "__main__":
    _honour_headless_env()
    main()
