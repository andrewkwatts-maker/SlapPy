from __future__ import annotations
import hashlib
import random
import string


class RoomCode:
    """
    Human-readable 6-character room code.
    Internally hashes to a 160-bit DHT key.

    Usage:
        code = RoomCode.generate()      # "X7K2MQ"
        code = RoomCode("X7K2MQ")       # join existing room
        dht_key = code.dht_key          # bytes for Kademlia lookup
    """
    _CHARS = string.ascii_uppercase + string.digits
    # Exclude confusable chars: O, 0, I, 1
    _SAFE = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

    def __init__(self, code: str) -> None:
        self.code = code.upper().strip()

    @classmethod
    def generate(cls) -> "RoomCode":
        code = "".join(random.choice(cls._SAFE) for _ in range(6))
        return cls(code)

    @property
    def dht_key(self) -> bytes:
        """160-bit DHT key derived from room code + app namespace."""
        return hashlib.sha1(b"SlapPyEngine-v1-" + self.code.encode()).digest()

    def __str__(self) -> str:
        return self.code

    def __repr__(self) -> str:
        return f"RoomCode({self.code!r})"
