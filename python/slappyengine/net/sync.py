from __future__ import annotations
import asyncio
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class InputFrame:
    """One player's inputs for one simulation tick."""
    tick: int
    player_id: int
    actions: dict[str, bool]    # action_name -> pressed
    axes: dict[str, float]      # axis_name -> value (-1..1)
    timestamp: float = field(default_factory=time.monotonic)

    def to_bytes(self) -> bytes:
        """Compact binary encoding for network transmission."""
        import struct, json
        payload = json.dumps({
            "t": self.tick,
            "p": self.player_id,
            "a": {k: int(v) for k, v in self.actions.items()},
            "x": {k: round(v, 3) for k, v in self.axes.items()},
        }, separators=(',', ':')).encode()
        return struct.pack("!H", len(payload)) + payload

    @classmethod
    def from_bytes(cls, data: bytes) -> "InputFrame":
        import struct, json
        length = struct.unpack("!H", data[:2])[0]
        obj = json.loads(data[2:2+length])
        return cls(
            tick=obj["t"], player_id=obj["p"],
            actions={k: bool(v) for k, v in obj["a"].items()},
            axes={k: float(v) for k, v in obj["x"].items()},
        )


class LockstepSync:
    """
    Deterministic lockstep synchronization.

    Each tick:
    1. Local player submits their InputFrame
    2. Send it to all peers
    3. Wait until all peers' InputFrames for this tick arrive (or timeout)
    4. Return all InputFrames so game can simulate tick

    If a peer's frame doesn't arrive within timeout_ms, use their last known
    inputs (input prediction). After max_prediction_ticks, stall until caught up.

    Usage:
        sync = LockstepSync(local_player_id=0, num_players=2, tick_rate=30)

        # Each game tick:
        local_frame = InputFrame(tick=sync.tick, player_id=0,
                                 actions={"fire": True}, axes={"move_x": 0.5})
        all_frames = await sync.tick_async(local_frame, send_fn=session.broadcast)
        for frame in all_frames:
            simulate_player(frame.player_id, frame.actions, frame.axes)
    """

    def __init__(
        self,
        local_player_id: int,
        num_players: int,
        tick_rate: int = 30,
        timeout_ms: float = 100.0,
        max_prediction_ticks: int = 8,
    ) -> None:
        self.local_player_id = local_player_id
        self.num_players = num_players
        self.tick_rate = tick_rate
        self.timeout_ms = timeout_ms
        self.max_prediction_ticks = max_prediction_ticks
        self.tick: int = 0
        self._pending: dict[int, dict[int, InputFrame]] = {}  # tick -> {player_id: frame}
        self._last_frames: dict[int, InputFrame] = {}         # last known frame per player
        self._events: asyncio.Queue = asyncio.Queue()

    def receive_frame(self, frame: InputFrame) -> None:
        """Called by transport layer when a remote peer's frame arrives."""
        self._pending.setdefault(frame.tick, {})[frame.player_id] = frame
        self._last_frames[frame.player_id] = frame
        self._events.put_nowait(frame)

    async def tick_async(
        self,
        local_frame: InputFrame,
        send_fn,
    ) -> list[InputFrame]:
        """
        Submit local frame, broadcast it, wait for all peers, return all frames.
        Returns list of InputFrame (one per player) for this tick.
        """
        self._pending.setdefault(self.tick, {})[self.local_player_id] = local_frame
        self._last_frames[self.local_player_id] = local_frame
        await send_fn(local_frame.to_bytes())

        deadline = time.monotonic() + self.timeout_ms / 1000.0
        while len(self._pending.get(self.tick, {})) < self.num_players:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break  # timeout — use prediction for missing peers
            try:
                await asyncio.wait_for(self._events.get(), timeout=remaining)
            except asyncio.TimeoutError:
                break

        frames = {}
        for pid in range(self.num_players):
            tick_frames = self._pending.get(self.tick, {})
            if pid in tick_frames:
                frames[pid] = tick_frames[pid]
            elif pid in self._last_frames:
                # Predict: use last known frame with updated tick
                last = self._last_frames[pid]
                frames[pid] = InputFrame(self.tick, pid, last.actions.copy(),
                                         last.axes.copy())
            else:
                frames[pid] = InputFrame(self.tick, pid, {}, {})

        # Cleanup old ticks
        self._pending.pop(self.tick - 4, None)
        self.tick += 1
        return list(frames.values())
