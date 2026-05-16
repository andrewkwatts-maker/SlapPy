from __future__ import annotations
import asyncio
import enum
import time
from dataclasses import dataclass, field


class PeerState(enum.Enum):
    CONNECTING = "connecting"
    HOLE_PUNCHING = "hole_punching"
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    FAILED = "failed"


@dataclass
class Peer:
    """
    Represents one remote player in the session.

    peer_id: unique integer (assigned by session host or hash of external IP:port)
    external_addr: (ip, port) from STUN discovery
    state: connection state
    rtt_ms: estimated round-trip time in milliseconds
    """
    peer_id: int
    external_addr: tuple[str, int]
    local_addr: tuple[str, int] | None = None
    state: PeerState = PeerState.CONNECTING
    rtt_ms: float = 0.0
    last_seen: float = field(default_factory=time.monotonic)
    _send_seq: int = 0
    _recv_seq: int = -1

    def is_alive(self, timeout: float = 5.0) -> bool:
        return (time.monotonic() - self.last_seen) < timeout

    def mark_seen(self) -> None:
        self.last_seen = time.monotonic()
