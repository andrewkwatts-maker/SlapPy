from __future__ import annotations

class TagRegistry:
    def __init__(self, max_bits: int = 32):
        self._max_bits = max_bits
        self._tags: dict[str, int] = {}          # name -> bit index (0-based)
        self._masks: dict[str, int] = {}         # name -> bitmask (2^bit)
        self._next_bit: int = 0

    def define(self, name: str, bit: int | None = None) -> int:
        if name in self._tags:
            return self._masks[name]
        b = bit if bit is not None else self._next_bit
        if b >= self._max_bits:
            raise ValueError(f"Tag bit {b} exceeds max_bits={self._max_bits}")
        self._tags[name] = b
        self._masks[name] = 1 << b
        self._next_bit = max(self._next_bit, b + 1)
        return self._masks[name]

    def mask(self, *names: str) -> int:
        result = 0
        for n in names:
            if n not in self._masks:
                raise KeyError(f"Tag '{n}' not defined. Call TagRegistry.define() first.")
            result |= self._masks[n]
        return result

    def name_for_bit(self, bit: int) -> str | None:
        for name, b in self._tags.items():
            if b == bit:
                return name
        return None

    def __getitem__(self, name: str) -> int:
        return self._masks[name]

    def __contains__(self, name: str) -> bool:
        return name in self._masks

    def all_tags(self) -> dict[str, int]:
        return dict(self._masks)
