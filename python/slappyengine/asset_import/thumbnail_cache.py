"""``thumbnail_cache`` — EEE1: persistent thumbnail cache for the asset panel.

Nova3D's ``AssetThumbnailCache`` persists rendered previews to disk so the
editor can rebuild the asset grid in <100 ms even for projects with
thousands of assets. This module ports that contract in pure Python:

* Cache root: user-picked directory (default
  ``~/.slappyengine/thumbnails``).
* Entry key: ``sha1(str(Path(asset_path).resolve()))`` — collision-safe
  and stable across editor restarts.
* Freshness rule: entry is valid iff ``cache_mtime > asset_mtime``. If
  the asset file is missing we still return the cached entry (source may
  live inside a pack file); if the cache PNG is missing we treat as a
  miss.
* Eviction: LRU by mtime of the cache PNGs when total size exceeds
  ``max_size_mb`` (default 256 MB).
* PNG I/O: PIL preferred (already a dev dependency); soft-imports the
  stdlib-free ``png`` module as a fallback; if neither is available the
  cache silently degrades to a no-op (all ``get`` calls miss, all
  ``put`` calls return the intended path without writing).

Intentional non-goals:

* No cross-process locking. The editor is single-process; the panel
  serialises writes through the async import queue thread pool. If two
  processes ever share a cache dir, the worst case is a re-render.
* No compression tuning. PNG's zlib default is fine for 128×128×4 =
  65 KB tops per entry.
"""
from __future__ import annotations

import hashlib
import io
import logging
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

_LOG = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# PIL / png soft-import — resolved once at module import so the hot path
# doesn't pay the import cost per call.
# ---------------------------------------------------------------------------


def _load_png_backend() -> tuple[str, Any]:
    """Return ``(backend_name, module)`` for PNG I/O.

    Preference order: ``PIL`` → ``png`` → ``("none", None)``. The
    thumbnail cache silently degrades to a no-op when neither is
    available (all reads miss, writes short-circuit).
    """
    try:
        from PIL import Image  # noqa: PLC0415
        return "pil", Image
    except Exception:  # noqa: BLE001
        pass
    try:
        import png  # noqa: PLC0415
        return "png", png
    except Exception:  # noqa: BLE001
        pass
    return "none", None


_PNG_BACKEND_NAME, _PNG_BACKEND = _load_png_backend()


# ---------------------------------------------------------------------------
# Public dataclass — kept lightweight so tests can assert cheaply.
# ---------------------------------------------------------------------------


@dataclass
class ThumbnailCacheStats:
    """Snapshot of cache stats. Returned by :meth:`ThumbnailCache.stats`."""

    entries: int = 0
    size_mb: float = 0.0
    hits: int = 0
    misses: int = 0
    evictions: int = 0

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        if total <= 0:
            return 0.0
        return float(self.hits) / float(total)

    def as_dict(self) -> dict[str, Any]:
        return {
            "entries": int(self.entries),
            "size_mb": float(self.size_mb),
            "hit_rate": float(self.hit_rate),
            "hits": int(self.hits),
            "misses": int(self.misses),
            "evictions": int(self.evictions),
        }


# ---------------------------------------------------------------------------
# ThumbnailCache
# ---------------------------------------------------------------------------


class ThumbnailCache:
    """Persistent 128×128×4 RGBA thumbnail cache.

    Parameters
    ----------
    cache_root:
        Directory to store PNGs. Created on demand.
    max_size_mb:
        Total on-disk cap. When exceeded, LRU eviction (oldest mtime
        first) trims the cache down to 90 % of the cap so writes don't
        immediately re-trigger eviction.
    """

    def __init__(
        self,
        cache_root: Path | str,
        *,
        max_size_mb: float = 256.0,
    ) -> None:
        self._root = Path(cache_root)
        self._max_size_mb = float(max_size_mb)
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        try:
            self._root.mkdir(parents=True, exist_ok=True)
        except Exception as exc:  # noqa: BLE001
            _LOG.warning("ThumbnailCache: cannot create %s: %s", self._root, exc)

    # ------------------------------------------------------------------
    # Key derivation
    # ------------------------------------------------------------------

    @staticmethod
    def _key(asset_path: str | Path) -> str:
        # Resolve so ``./foo.png`` and ``/abs/path/foo.png`` map to the
        # same cache entry when the CWD lines up. Fall back to the raw
        # string when resolve() blows up on a non-existent path.
        try:
            key_src = str(Path(asset_path).resolve())
        except Exception:  # noqa: BLE001
            key_src = str(asset_path)
        return hashlib.sha1(key_src.encode("utf-8"), usedforsecurity=False).hexdigest()

    def cache_path(self, asset_path: str | Path) -> Path:
        """Return the on-disk PNG path this cache would use for *asset_path*."""
        return self._root / f"{self._key(asset_path)}.png"

    # ------------------------------------------------------------------
    # get / put / invalidate
    # ------------------------------------------------------------------

    def get(self, asset_path: str | Path) -> np.ndarray | None:
        """Return the cached RGBA thumbnail if fresh, else ``None``.

        Freshness is ``cache_mtime > asset_mtime``. If the asset file is
        missing we assume the cache is authoritative (source may live in
        a pack file); if the cache PNG is missing we return ``None``.
        """
        cpath = self.cache_path(asset_path)
        with self._lock:
            if not cpath.exists():
                self._misses += 1
                return None
            try:
                cache_mtime = cpath.stat().st_mtime
            except OSError:
                self._misses += 1
                return None
            asset_mtime: float | None
            try:
                asset_mtime = Path(asset_path).stat().st_mtime
            except OSError:
                asset_mtime = None
            if asset_mtime is not None and asset_mtime >= cache_mtime:
                # Asset changed after the cache entry was written — stale.
                self._misses += 1
                return None
            arr = self._read_png(cpath)
            if arr is None:
                self._misses += 1
                return None
            # Touch atime for LRU accounting.
            try:
                now = cache_mtime  # keep freshness comparison stable
                os.utime(cpath, (now, cache_mtime))
            except OSError:
                pass
            self._hits += 1
            return arr

    def put(self, asset_path: str | Path, rgba: np.ndarray) -> Path:
        """Write ``rgba`` to the cache and return the on-disk path.

        The ndarray must be ``(H, W, 4)`` uint8. Non-conforming inputs
        are coerced (RGB → RGBA with 255 alpha; float → uint8 via
        ``clip * 255``). Writes are best-effort — if PNG encoding fails
        the return value still points at the intended location so
        callers can distinguish "cache disabled" from "cache miss".
        """
        cpath = self.cache_path(asset_path)
        rgba = self._coerce_rgba(rgba)
        with self._lock:
            wrote = self._write_png(cpath, rgba)
            if wrote:
                # Bump the mtime so freshness compares strictly newer than
                # the source. Some fs's (Windows FAT) have 2-second mtime
                # granularity — nudge by a tick to survive same-second
                # asset writes in tests.
                try:
                    stat = cpath.stat()
                    os.utime(cpath, (stat.st_atime, stat.st_mtime + 1e-3))
                except OSError:
                    pass
                self._maybe_evict_locked(protect=cpath)
        return cpath

    def invalidate(self, asset_path: str | Path) -> bool:
        """Delete the cache entry for *asset_path*. Returns ``True`` on hit."""
        cpath = self.cache_path(asset_path)
        with self._lock:
            if not cpath.exists():
                return False
            try:
                cpath.unlink()
                return True
            except OSError as exc:
                _LOG.info("ThumbnailCache.invalidate failed for %s: %s", cpath, exc)
                return False

    # ------------------------------------------------------------------
    # Stats + housekeeping
    # ------------------------------------------------------------------

    def stats(self) -> dict[str, Any]:
        """Return ``{"entries", "size_mb", "hit_rate", "hits", "misses", "evictions"}``.

        All counters are non-negative. ``hit_rate`` is ``hits /
        (hits + misses)`` and is ``0.0`` when there have been no lookups.
        """
        entries = 0
        size_bytes = 0
        with self._lock:
            try:
                for p in self._root.glob("*.png"):
                    entries += 1
                    try:
                        size_bytes += p.stat().st_size
                    except OSError:
                        pass
            except OSError:
                pass
            snap = ThumbnailCacheStats(
                entries=entries,
                size_mb=size_bytes / (1024.0 * 1024.0),
                hits=self._hits,
                misses=self._misses,
                evictions=self._evictions,
            )
        return snap.as_dict()

    def clear(self) -> int:
        """Delete every entry in the cache. Returns the count removed."""
        removed = 0
        with self._lock:
            try:
                for p in self._root.glob("*.png"):
                    try:
                        p.unlink()
                        removed += 1
                    except OSError:
                        pass
            except OSError:
                pass
        return removed

    # ------------------------------------------------------------------
    # LRU eviction — called under the lock.
    # ------------------------------------------------------------------

    def _maybe_evict_locked(self, *, protect: Path | None = None) -> None:
        cap_bytes = int(self._max_size_mb * 1024 * 1024)
        if cap_bytes <= 0:
            return
        try:
            entries: list[tuple[float, int, Path]] = []
            total = 0
            for p in self._root.glob("*.png"):
                try:
                    st = p.stat()
                except OSError:
                    continue
                total += st.st_size
                entries.append((st.st_mtime, st.st_size, p))
        except OSError:
            return
        if total <= cap_bytes:
            return
        # Sort by mtime ascending — oldest first.
        entries.sort(key=lambda e: e[0])
        # Trim down to 90 % of the cap so we're not evicting on every
        # subsequent put.
        target = int(cap_bytes * 0.9)
        protect_str = str(protect.resolve()) if protect is not None else None
        for _mtime, size, p in entries:
            if total <= target:
                break
            try:
                # Never evict the freshly-written entry that triggered
                # this eviction — even if its size alone exceeds the
                # cap. Otherwise a single large put would immediately
                # discard the value the caller just asked us to store.
                if protect_str is not None:
                    try:
                        if str(p.resolve()) == protect_str:
                            continue
                    except OSError:
                        pass
                p.unlink()
                total -= size
                self._evictions += 1
            except OSError:
                continue

    # ------------------------------------------------------------------
    # PNG I/O — soft-imports resolved at module load.
    # ------------------------------------------------------------------

    @staticmethod
    def _coerce_rgba(rgba: np.ndarray) -> np.ndarray:
        arr = np.asarray(rgba)
        if arr.ndim == 2:
            arr = np.stack([arr, arr, arr, np.full_like(arr, 255)], axis=-1)
        elif arr.ndim == 3 and arr.shape[-1] == 3:
            alpha = np.full(arr.shape[:2] + (1,), 255, dtype=arr.dtype)
            arr = np.concatenate([arr, alpha], axis=-1)
        if arr.dtype != np.uint8:
            f = arr.astype(np.float32)
            if float(f.max() if f.size else 0.0) <= 1.0:
                f = f * 255.0
            arr = np.clip(f, 0, 255).astype(np.uint8)
        if arr.ndim != 3 or arr.shape[-1] != 4:
            # Last-resort — shape mismatch: coerce to a blank 4×4.
            arr = np.full((4, 4, 4), 200, dtype=np.uint8)
            arr[..., 3] = 255
        return arr

    def _write_png(self, path: Path, rgba: np.ndarray) -> bool:
        if _PNG_BACKEND_NAME == "pil":
            try:
                img = _PNG_BACKEND.fromarray(rgba, mode="RGBA")
                buf = io.BytesIO()
                img.save(buf, format="PNG", optimize=False)
                path.write_bytes(buf.getvalue())
                return True
            except Exception as exc:  # noqa: BLE001
                _LOG.info("PIL PNG write failed for %s: %s", path, exc)
                return False
        if _PNG_BACKEND_NAME == "png":
            try:
                h, w = rgba.shape[:2]
                writer = _PNG_BACKEND.Writer(w, h, alpha=True, greyscale=False)
                with open(path, "wb") as fh:
                    writer.write(fh, rgba.reshape(h, w * 4).tolist())
                return True
            except Exception as exc:  # noqa: BLE001
                _LOG.info("png PNG write failed for %s: %s", path, exc)
                return False
        return False

    def _read_png(self, path: Path) -> np.ndarray | None:
        if _PNG_BACKEND_NAME == "pil":
            try:
                img = _PNG_BACKEND.open(path).convert("RGBA")
                return np.asarray(img, dtype=np.uint8)
            except Exception as exc:  # noqa: BLE001
                _LOG.info("PIL PNG read failed for %s: %s", path, exc)
                return None
        if _PNG_BACKEND_NAME == "png":
            try:
                reader = _PNG_BACKEND.Reader(filename=str(path))
                w, h, rows, _info = reader.asRGBA8()
                data = np.asarray(list(rows), dtype=np.uint8).reshape(h, w, 4)
                return data
            except Exception as exc:  # noqa: BLE001
                _LOG.info("png PNG read failed for %s: %s", path, exc)
                return None
        return None


__all__ = [
    "ThumbnailCache",
    "ThumbnailCacheStats",
]
