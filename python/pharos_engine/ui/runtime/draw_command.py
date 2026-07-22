"""Draw commands emitted by :class:`ImmediateUI` — renderer-agnostic.

An :class:`ImmediateUI` frame is a list of :class:`DrawCommand` records.
The HH4 renderer (or any back-end) walks the list and turns each entry
into the corresponding draw call. Keeping widgets → commands → renderer
decoupled is what lets the exact same widget code run inside DPG (via
:mod:`.dpg_bridge`) and inside a pure-Python game loop.

The dataclass is intentionally minimal — the six fields cover every
widget kind the runtime layer emits (rect, text, line, circle,
textured_quad). More exotic primitives are expressed as multiple
commands, not by extending the schema.
"""
from __future__ import annotations

from dataclasses import dataclass


_VALID_KINDS: frozenset[str] = frozenset(
    {"rect", "text", "line", "circle", "textured_quad"}
)


@dataclass
class DrawCommand:
    """A single renderer-agnostic draw instruction.

    Parameters
    ----------
    kind:
        One of ``"rect"``, ``"text"``, ``"line"``, ``"circle"``,
        ``"textured_quad"``. Extending the runtime with a new primitive
        means adding an entry here.
    position:
        Screen-space ``(x, y)`` of the primitive's top-left (rects,
        textured quads, text) or first endpoint (lines, circles).
    size:
        Screen-space ``(w, h)`` of the primitive. For a line this is the
        vector to the second endpoint; for a circle this encodes the
        bounding box (so a ``size`` of ``(24, 24)`` is a 12-pixel radius).
    color:
        RGBA in ``[0.0, 1.0]``. Text commands use this as the ink colour.
    text:
        Payload for ``kind == "text"``; ``None`` for other kinds.
    texture_id:
        Renderer-side handle for ``kind == "textured_quad"``; ``None``
        otherwise.
    z_order:
        Sort key; higher values draw on top. Panels typically sit at
        ``z_order=10``, panel content at ``20``, hover state at ``30``,
        toasts at ``100``.
    """

    kind: str
    position: tuple[float, float]
    size: tuple[float, float]
    color: tuple[float, float, float, float]
    text: str | None = None
    texture_id: int | None = None
    z_order: int = 0

    def __post_init__(self) -> None:
        fn = "DrawCommand"
        if not isinstance(self.kind, str) or self.kind not in _VALID_KINDS:
            raise ValueError(
                f"{fn}: kind must be one of {sorted(_VALID_KINDS)}; "
                f"got {self.kind!r}"
            )
        self.position = _to_pair("position", fn, self.position)
        self.size = _to_pair("size", fn, self.size)
        self.color = _to_rgba("color", fn, self.color)
        if self.text is not None and not isinstance(self.text, str):
            raise TypeError(
                f"{fn}: text must be str or None; got {type(self.text).__name__}"
            )
        if self.texture_id is not None and not isinstance(self.texture_id, int):
            raise TypeError(
                f"{fn}: texture_id must be int or None; "
                f"got {type(self.texture_id).__name__}"
            )
        if not isinstance(self.z_order, int):
            raise TypeError(
                f"{fn}: z_order must be int; got {type(self.z_order).__name__}"
            )


def _to_pair(name: str, fn: str, value) -> tuple[float, float]:
    if not hasattr(value, "__len__") or len(value) != 2:
        raise TypeError(f"{fn}: {name} must be a 2-sequence; got {value!r}")
    return (float(value[0]), float(value[1]))


def _to_rgba(name: str, fn: str, value) -> tuple[float, float, float, float]:
    if not hasattr(value, "__len__") or len(value) != 4:
        raise TypeError(f"{fn}: {name} must be a 4-sequence; got {value!r}")
    return (float(value[0]), float(value[1]), float(value[2]), float(value[3]))


__all__ = ["DrawCommand"]
