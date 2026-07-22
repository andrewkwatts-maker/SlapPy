"""WGSL shader chunk loader.

A tiny library of reusable WGSL snippets lives in ``shaders/chunks/`` —
RGBA pack/unpack helpers, smoothstep falloff, integer hashes, etc.  This
module loads them on demand (with an in-process cache) so compute passes can
prepend the helpers they need instead of copy-pasting boilerplate.

This is intentionally opt-in: existing shaders continue to inline their
helpers.  New code can do::

    from pharos_engine.compute.wgsl_chunks import chunk, compose

    SRC = compose("pack_rgba", "hash", MAIN_WGSL)
"""
from __future__ import annotations

from pathlib import Path

_CHUNK_DIR = Path(__file__).parent.parent.parent.parent / "shaders" / "chunks"
_cache: dict[str, str] = {}


def chunk(name: str) -> str:
    """Return the WGSL source for chunk ``name`` (e.g. ``'pack_rgba'``).

    The chunk file ``shaders/chunks/<name>.wgsl`` is read on first access and
    cached for the lifetime of the process.
    """
    if name not in _cache:
        path = _CHUNK_DIR / f"{name}.wgsl"
        _cache[name] = path.read_text(encoding="utf-8")
    return _cache[name]


def compose(*chunks_then_main: str) -> str:
    """Concatenate chunk names + main source.

    The last argument is the main shader source; preceding arguments are
    treated as chunk names UNLESS they already look like WGSL (contain ``@``
    decorators or end with ``.wgsl``), in which case they're passed through
    verbatim.  Parts are joined with newlines.
    """
    if not chunks_then_main:
        return ""
    parts: list[str] = []
    for c in chunks_then_main[:-1]:
        if c.endswith(".wgsl") or "@" in c:  # treat as raw WGSL
            parts.append(c)
        else:
            parts.append(chunk(c))
    parts.append(chunks_then_main[-1])
    return "\n".join(parts)


__all__ = ["chunk", "compose"]
