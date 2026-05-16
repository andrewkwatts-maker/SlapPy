from __future__ import annotations
import asyncio
import logging
import socket
import time
from dataclasses import dataclass, field
from typing import Callable

from .room import RoomCode
from .peer import Peer, PeerState
from .sync import LockstepSync, InputFrame
from .discovery import get_external_address, discover_peers_dht, discover_peers_lan

logger = logging.getLogger(__name__)


@dataclass
class SessionConfig:
    tick_rate: int = 30             # simulation ticks per second
    timeout_ms: float = 100.0       # per-tick wait for peer inputs
    max_players: int = 8
    use_lan_discovery: bool = True  # also check LAN peers
    use_dht_discovery: bool = True  # use internet DHT
    udp_port: int = 0               # 0 = OS-assigned


class GameSession:
    """
    High-level multiplayer session. Handles peer discovery, connection,
    and provides a simple tick-based input synchronization interface.

    All network operations are async. If you are integrating with a synchronous
    engine loop (e.g. wgpu's canvas.request_draw), drive the async methods with
    asyncio.get_event_loop().run_until_complete() or run the entire game loop
    inside asyncio.run().

    Usage (host a new game):
        session = await GameSession.host(player_id=0, cfg=SessionConfig())
        print(f"Room code: {session.room_code}")

    Usage (join existing game):
        session = await GameSession.join("X7K2MQ", player_id=1)

    Game loop integration:
        # Each frame, for lockstep:
        local_inputs = InputFrame(tick=session.sync.tick, player_id=0,
                                  actions={"fire": True}, axes={"move_x": 0.5})
        all_inputs = await session.sync.tick_async(local_inputs, session.broadcast)
        for inp in all_inputs:
            apply_inputs(inp.player_id, inp)
    """

    def __init__(
        self,
        room_code: RoomCode,
        local_player_id: int,
        cfg: SessionConfig,
    ) -> None:
        self.room_code = room_code
        self.local_player_id = local_player_id
        self.cfg = cfg
        self.peers: dict[int, Peer] = {}
        self.sync: LockstepSync | None = None
        self._sock: socket.socket | None = None
        self._external_addr: tuple[str, int] | None = None
        self._local_addr: tuple[str, int] | None = None
        self._running = False
        self._on_player_joined: list[Callable] = []
        self._on_player_left: list[Callable] = []

    # ── Lifecycle ──────────────────────────────────────────────────────────

    @classmethod
    async def host(
        cls,
        player_id: int = 0,
        cfg: SessionConfig | None = None,
    ) -> "GameSession":
        """
        Host a new multiplayer room.

        Generates a fresh RoomCode, opens a UDP socket, discovers the external
        address via STUN, and begins listening for incoming peers.
        Share session.room_code with other players so they can join.
        """
        cfg = cfg or SessionConfig()
        room = RoomCode.generate()
        session = cls(room, player_id, cfg)
        await session._start()
        logger.info(f"Hosting room: {room}")
        return session

    @classmethod
    async def join(
        cls,
        room_code: str,
        player_id: int = 1,
        cfg: SessionConfig | None = None,
    ) -> "GameSession":
        """
        Join an existing room by 6-character room code.

        Runs peer discovery (LAN multicast and/or DHT) and initiates
        UDP hole-punching with each discovered peer.
        """
        cfg = cfg or SessionConfig()
        room = RoomCode(room_code)
        session = cls(room, player_id, cfg)
        await session._start()
        await session._discover_peers()
        return session

    async def _start(self) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setblocking(False)
        self._sock.bind(("", self.cfg.udp_port))
        self._local_addr = self._sock.getsockname()
        self._external_addr = await get_external_address(self._local_addr[1])
        if self._external_addr:
            logger.info(f"External address: {self._external_addr[0]}:{self._external_addr[1]}")
        self._running = True
        asyncio.ensure_future(self._recv_loop())

    async def _discover_peers(self) -> None:
        found = []
        if self.cfg.use_lan_discovery:
            lan_peers = await discover_peers_lan(str(self.room_code))
            found.extend(lan_peers)
        if self.cfg.use_dht_discovery:
            dht_peers = await discover_peers_dht(
                self.room_code.dht_key,
                self._local_addr,
                self._external_addr,
                on_peer_found=lambda ip, port: logger.info(f"DHT peer: {ip}:{port}"),
            )
            found.extend(dht_peers)
        for addr in found:
            await self._punch_hole(addr)

    async def _punch_hole(self, remote_addr: tuple[str, int]) -> None:
        """
        UDP hole punching: send 3 packets to open NAT mapping, wait for reply.

        Works for cone NATs (full cone, address-restricted, port-restricted).
        Symmetric NATs (some corporate firewalls) require a relay server, which
        is out of scope for v1.
        """
        HELLO = b"\x00SlapPyEngine-Hello"
        loop = asyncio.get_event_loop()
        for _ in range(3):
            await loop.sock_sendto(self._sock, HELLO, remote_addr)
            await asyncio.sleep(0.1)

    async def _recv_loop(self) -> None:
        loop = asyncio.get_event_loop()
        while self._running:
            try:
                data, addr = await asyncio.wait_for(
                    loop.sock_recvfrom(self._sock, 4096), timeout=1.0
                )
                await self._handle_packet(data, addr)
            except asyncio.TimeoutError:
                self._prune_dead_peers()
            except Exception as e:
                logger.debug(f"recv error: {e}")

    async def _handle_packet(self, data: bytes, addr: tuple[str, int]) -> None:
        if data.startswith(b"\x00SlapPyEngine-Hello"):
            # Register new peer
            peer_id = hash(addr) % 100000
            if peer_id not in self.peers:
                peer = Peer(peer_id=peer_id, external_addr=addr, state=PeerState.CONNECTED)
                self.peers[peer_id] = peer
                logger.info(f"Peer connected: {addr[0]}:{addr[1]}")
                for cb in self._on_player_joined:
                    cb(peer_id)
            # Update last_seen on the known peer
            if peer_id in self.peers:
                self.peers[peer_id].mark_seen()
            # Send hello back
            loop = asyncio.get_event_loop()
            await loop.sock_sendto(self._sock, b"\x00SlapPyEngine-Hello-ACK", addr)
        elif data.startswith(b"\x01"):
            # Input frame
            if self.sync:
                try:
                    frame = InputFrame.from_bytes(data[1:])
                    self.sync.receive_frame(frame)
                except Exception as e:
                    logger.debug(f"Bad input frame: {e}")

    def _prune_dead_peers(self) -> None:
        dead = [pid for pid, p in self.peers.items() if not p.is_alive()]
        for pid in dead:
            self.peers.pop(pid)
            for cb in self._on_player_left:
                cb(pid)

    async def broadcast(self, data: bytes) -> None:
        """Send data to all connected peers (unreliable, fire-and-forget)."""
        loop = asyncio.get_event_loop()
        packet = b"\x01" + data
        for peer in self.peers.values():
            if peer.state == PeerState.CONNECTED:
                try:
                    await loop.sock_sendto(self._sock, packet, peer.external_addr)
                except Exception:
                    pass

    def enable_lockstep(self, num_players: int | None = None) -> LockstepSync:
        """
        Enable deterministic lockstep sync and return the LockstepSync object.

        Call this after all players have joined, or pass num_players explicitly.
        The returned sync object is also accessible via session.sync.
        """
        n = num_players or (len(self.peers) + 1)
        self.sync = LockstepSync(
            local_player_id=self.local_player_id,
            num_players=n,
            tick_rate=self.cfg.tick_rate,
            timeout_ms=self.cfg.timeout_ms,
        )
        return self.sync

    def on_player_joined(self, fn: Callable) -> Callable:
        """Decorator/callback: called with peer_id when a new peer connects."""
        self._on_player_joined.append(fn)
        return fn

    def on_player_left(self, fn: Callable) -> Callable:
        """Decorator/callback: called with peer_id when a peer times out."""
        self._on_player_left.append(fn)
        return fn

    @property
    def connected_player_ids(self) -> list[int]:
        return [p.peer_id for p in self.peers.values() if p.state == PeerState.CONNECTED]

    async def close(self) -> None:
        """Shut down the session and close the UDP socket."""
        self._running = False
        if self._sock:
            self._sock.close()
