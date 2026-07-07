<!-- handauthored: do not regenerate -->
# slappyengine.net — API Reference

> Hand-written reference for the SlapPyEngine peer-to-peer multiplayer
> stack. Owns the deterministic lockstep sync layer, the UDP transport
> with STUN + DHT + LAN peer discovery, and the human-readable room
> code / DHT-key derivation. Sibling reference:
> [`telemetry.md`](telemetry.md) is where per-tick net events surface
> (peer join / leave, RTT gauges).

## Overview

`slappyengine.net` is the shipped multiplayer transport for SlapPyEngine
games. It targets 2–8 player cooperative and competitive sessions over
consumer NATs and exposes exactly one deterministic sync model —
**frame-accurate lockstep** with input prediction across timeout windows.

The top-level entry points are :class:`GameSession.host` and
:class:`GameSession.join`. Both return a :class:`GameSession` with an
opened UDP socket, a STUN-discovered external address, and a running
receive loop; games then call :meth:`GameSession.enable_lockstep` to
mint a :class:`LockstepSync` and drive it once per simulation tick with
:meth:`LockstepSync.tick_async`.

Peer discovery is dual-path: LAN multicast for same-network play, DHT
(Kademlia) for internet play behind cone NATs. Symmetric-NAT relay is
out of scope for v1 — sessions that fall through to symmetric on both
ends fail cleanly via :attr:`Peer.state` = `PeerState.FAILED`.

All :class:`GameSession` operations are `async`; games that drive a
synchronous engine loop should either wrap the tick in
`asyncio.get_event_loop().run_until_complete(...)` or wire the entire
loop inside `asyncio.run`.

## Public surface

```python
from slappyengine.net import (
    GameSession,
    InputFrame,
    LockstepSync,
    Peer,
    PeerState,
    RoomCode,
    SessionConfig,
)
```

- **Session** — `GameSession` + `SessionConfig` (top-level entry point).
- **Sync** — `LockstepSync` + `InputFrame` (per-tick determinism).
- **Peer bookkeeping** — `Peer` + `PeerState` (connection state machine).
- **Room addressing** — `RoomCode` (6-character user-facing code that
  hashes into a 160-bit DHT key).

## Classes

### `GameSession`

_class — defined in `slappyengine.net.session`_

High-level session object. Constructs a UDP socket, runs peer discovery,
performs hole-punching, and holds the :class:`LockstepSync` once enabled.

Prefer the two classmethod constructors:

```python
GameSession.host(player_id: int = 0, cfg: SessionConfig | None = None) -> GameSession   # async
GameSession.join(room_code: str, player_id: int = 1, cfg: SessionConfig | None = None) -> GameSession   # async
```

Both return an initialised, receive-loop-running session; `host`
generates a fresh :class:`RoomCode`, `join` accepts one from the
inviting host.

#### Key methods

- `enable_lockstep(num_players: int | None = None) -> LockstepSync` —
  mint and attach a :class:`LockstepSync` once all peers have joined
  (or pass `num_players` explicitly to seed early).
- `broadcast(data: bytes) -> None` — fire-and-forget unreliable send to
  every connected peer.
- `on_player_joined(fn)` / `on_player_left(fn)` — callback registration
  (usable as decorators); called with `peer_id`.
- `close() -> None` — stop the receive loop and close the UDP socket.

#### Key attributes

- `room_code: RoomCode` — the session's addressing token.
- `local_player_id: int` — this player's id (host = 0 by default).
- `peers: dict[int, Peer]` — the current peer map.
- `sync: LockstepSync | None` — set by :meth:`enable_lockstep`.
- `connected_player_ids: list[int]` — property returning peer ids
  currently in `PeerState.CONNECTED`.

### `SessionConfig`

_dataclass — defined in `slappyengine.net.session`_

| Field | Type | Default | Notes |
|---|---|---|---|
| `tick_rate` | `int` | `30` | Simulation ticks per second. |
| `timeout_ms` | `float` | `100.0` | Per-tick wait for peer inputs before falling back to prediction. |
| `max_players` | `int` | `8` | Session capacity. |
| `use_lan_discovery` | `bool` | `True` | Enable LAN multicast discovery. |
| `use_dht_discovery` | `bool` | `True` | Enable Kademlia DHT discovery. |
| `udp_port` | `int` | `0` | `0` = OS-assigned. |

### `LockstepSync`

_class — defined in `slappyengine.net.sync`_

Deterministic lockstep synchronisation. Each tick:

1. Local player submits their :class:`InputFrame`.
2. Frame is broadcast to all peers.
3. Waits until all peers' frames for the tick arrive, or `timeout_ms`
   elapses.
4. Returns the full per-player :class:`InputFrame` list; missing peers'
   frames are extrapolated from their most recent known input (input
   prediction) for up to `max_prediction_ticks` ticks before the sync
   stalls to let stragglers catch up.

#### Constructor signature

```python
LockstepSync(local_player_id: int, num_players: int,
             tick_rate: int = 30, timeout_ms: float = 100.0,
             max_prediction_ticks: int = 8) -> None
```

#### Key methods

- `receive_frame(frame: InputFrame) -> None` — called by the transport
  layer when a peer's frame arrives.
- `tick_async(local_frame: InputFrame, send_fn) -> list[InputFrame]` —
  submit the local frame, broadcast via `send_fn`, wait for peers,
  return all frames for the tick.

### `InputFrame`

_dataclass — defined in `slappyengine.net.sync`_

One player's inputs for one simulation tick.

| Field | Type | Notes |
|---|---|---|
| `tick` | `int` | Simulation tick index. |
| `player_id` | `int` | Owning player. |
| `actions` | `dict[str, bool]` | Named button state. |
| `axes` | `dict[str, float]` | Named axis in `[-1, 1]`. |
| `timestamp` | `float` | `time.monotonic()` at construction. |

Serialises via `to_bytes()` (2-byte length prefix + JSON payload) and
`from_bytes(data)` for on-wire transmission.

### `Peer`

_dataclass — defined in `slappyengine.net.peer`_

Per-peer connection bookkeeping.

| Field | Type | Notes |
|---|---|---|
| `peer_id` | `int` | Stable id (session-assigned or `hash(addr)`). |
| `external_addr` | `tuple[str, int]` | STUN-discovered `(ip, port)`. |
| `local_addr` | `tuple[str, int] \| None` | LAN address, if known. |
| `state` | `PeerState` | Connection state machine. |
| `rtt_ms` | `float` | Estimated round-trip time. |
| `last_seen` | `float` | Monotonic timestamp of last packet. |

- `is_alive(timeout: float = 5.0) -> bool` — has this peer sent
  something within `timeout` seconds?
- `mark_seen() -> None` — reset the `last_seen` clock.

### `PeerState`

_enum — defined in `slappyengine.net.peer`_

`CONNECTING` → `HOLE_PUNCHING` → `CONNECTED` (happy path); or
`DISCONNECTED` / `FAILED` on symmetric-NAT collision or timeout.

### `RoomCode`

_class — defined in `slappyengine.net.room`_

Human-readable 6-character room code that internally hashes into a
160-bit DHT key. Character alphabet excludes confusables (`O`, `0`,
`I`, `1`).

- `RoomCode.generate() -> RoomCode` — mint a fresh code.
- `RoomCode(code: str)` — parse an existing code.
- `dht_key: bytes` — 160-bit Kademlia lookup key (SHA-1 of a namespaced
  code).

## Usage

```python
import asyncio
from slappyengine.net import (
    GameSession, InputFrame, RoomCode, SessionConfig,
)

async def host_a_game():
    session = await GameSession.host(
        player_id=0,
        cfg=SessionConfig(tick_rate=30, timeout_ms=100.0),
    )
    print(f"Share this code: {session.room_code}")
    sync = session.enable_lockstep(num_players=2)

    # One simulation tick:
    local = InputFrame(
        tick=sync.tick, player_id=0,
        actions={"fire": True}, axes={"move_x": 0.5},
    )
    all_frames = await sync.tick_async(local, session.broadcast)
    for frame in all_frames:
        print(f"player {frame.player_id}: actions={frame.actions}")

    await session.close()

# RoomCode round-trip — no network required.
code = RoomCode.generate()
assert len(str(code)) == 6
assert len(code.dht_key) == 20  # 160 bits
```

## Skip the wrapper

`slappyengine.net` is pure Python (asyncio + stdlib `socket` + SHA-1 in
`hashlib`). Grep of `slappyengine._core_facade.RUST_MODULE_MAP` shows
**no** `net` entry — the subpackage is I/O-bound (UDP + STUN + DHT) and
throughput is dominated by network round-trip time, not CPU work. A Rust
port would move no measurable frame-time needle.

Callers who want to bypass :class:`GameSession` and drive a bespoke
transport (WebRTC, TCP, in-process test fixture) can still reuse
:class:`LockstepSync` directly — it is transport-agnostic and only
requires a `send_fn` callable + `receive_frame` calls to drive the
determinism model.

## Conventions

- **Async by default.** Every transport method on :class:`GameSession`
  and :meth:`LockstepSync.tick_async` is `async`. Synchronous engine
  loops must bridge via `run_until_complete` or wrap the whole loop in
  `asyncio.run`.
- **Unreliable + deterministic.** :meth:`GameSession.broadcast` is
  fire-and-forget UDP. Determinism is enforced above the transport by
  :class:`LockstepSync` waiting for every peer's frame each tick (or
  extrapolating from prediction).
- **Cone-NAT only.** Hole-punching supports full-cone,
  address-restricted, and port-restricted NATs; symmetric NAT on both
  ends fails cleanly (no relay ships in v1).

## See also

- [`telemetry.md`](telemetry.md) — per-tick net events (peer join / leave,
  RTT gauges) surface through the telemetry ring buffer.
- [`../rust_migration_plan.md`](../rust_migration_plan.md) — Rust ROI
  reference; `slappyengine.net` is intentionally not on the migration
  roadmap (I/O-bound).
