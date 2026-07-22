"""``async_import_queue`` — EEE1: non-blocking asset import queue.

Nova3D's ``AssetBrowser`` fires imports on a background worker pool so a
5 MB glTF drop doesn't stall the editor. This module ports that shape:

* ``AsyncImportQueue.submit(path, callback)`` schedules the type-router
  invocation on a :class:`concurrent.futures.ThreadPoolExecutor`.
* Completions are drained from the editor tick via
  :meth:`poll_completions`, which pulls done futures off a thread-safe
  deque and returns their :class:`ImportRouteResult` payloads to the
  caller.
* Started / completed events are published on
  :mod:`pharos_engine.event_bus` so telemetry / progress HUDs / listener-
  leak sentinels can observe the flow without wiring into the panel.

Threading contract:

* :meth:`submit` is thread-safe. Multiple threads may call it
  concurrently.
* Callbacks fire on the *worker* thread — do NOT touch DPG or numpy
  writable-view state from inside them. Editor code should use
  :meth:`poll_completions` from the render tick instead.
* :meth:`cancel_all` calls ``Future.cancel()`` on every not-yet-started
  task and clears the pending queue. Already-running imports are not
  interrupted (matches Nova3D's contract — importers are not
  restartable).
"""
from __future__ import annotations

import logging
import threading
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from pharos_engine import event_bus as _event_bus_mod

from .type_router import ImportRouteResult, import_by_extension

_LOG = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public result envelope (aliases ImportRouteResult but named to match
# the Nova3D contract — makes the intent obvious at the panel call
# site).
# ---------------------------------------------------------------------------


@dataclass
class ImportResult:
    """Envelope returned by :meth:`AsyncImportQueue.poll_completions`.

    ``route`` is the raw :class:`ImportRouteResult` from
    :func:`import_by_extension`. ``elapsed_s`` is the wall-clock time
    the worker spent on the import — surfaced so the editor status
    strip can report ``"Imported foo.png in 12ms"``.
    """

    path: Path
    route: ImportRouteResult
    elapsed_s: float = 0.0
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.error == "" and self.route.kind not in ("error", "unsupported")


# ---------------------------------------------------------------------------
# AsyncImportQueue
# ---------------------------------------------------------------------------


class AsyncImportQueue:
    """Bounded thread-pool queue for asset imports.

    Parameters
    ----------
    max_workers:
        Thread-pool size. Nova3D uses 4; that's the default here too —
        matches typical desktop core counts on the low end and stays
        below the disk-IO saturation point for asset drops.
    router:
        Optional override for :func:`import_by_extension`. Tests pass a
        fake callable to avoid touching real importers.
    bus:
        Event bus instance. Defaults to the module-level default bus so
        events reach the global subscribers Ochema Circuit / Bullet
        Strata / editor HUDs use.
    """

    EVT_STARTED = "asset_import.started"
    EVT_COMPLETED = "asset_import.completed"

    def __init__(
        self,
        max_workers: int = 4,
        *,
        router: Callable[[str | Path], ImportRouteResult] = import_by_extension,
        bus: Any = None,
    ) -> None:
        self._max_workers = max(1, int(max_workers))
        self._router = router
        self._bus = bus if bus is not None else _event_bus_mod.get_default_bus()
        self._executor: ThreadPoolExecutor | None = ThreadPoolExecutor(
            max_workers=self._max_workers,
            thread_name_prefix="slappy-asset-import",
        )
        self._pending: set[Future] = set()
        self._completed: deque[ImportResult] = deque()
        self._lock = threading.Lock()
        self._submitted_total: int = 0
        self._completed_total: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def submit(
        self,
        path: str | Path,
        callback: Callable[[ImportResult], None] | None = None,
    ) -> Future:
        """Schedule an import of *path*. Returns the underlying Future.

        The optional ``callback`` fires on the worker thread once the
        import completes (successfully or not) with an
        :class:`ImportResult`. Editor UI code should prefer polling via
        :meth:`poll_completions` from the render tick so callbacks stay
        on the main thread.

        A ``asset_import.started`` event is published on the bus with
        ``path`` set; a ``asset_import.completed`` event is published
        after the import finishes with ``path``, ``kind``, ``ok``,
        ``elapsed_s`` and ``error`` fields.
        """
        p = Path(path)
        if self._executor is None:
            # Queue has been shut down — return a resolved Future with an
            # error result so callers can uniformly branch on the
            # ``.ok`` field.
            fut: Future = Future()
            err = ImportResult(
                path=p,
                route=ImportRouteResult(
                    kind="error", handle=None, path=p, error="queue shut down",
                ),
                error="queue shut down",
            )
            fut.set_result(err)
            if callback is not None:
                try:
                    callback(err)
                except Exception as exc:  # noqa: BLE001
                    _LOG.info("submit callback raised: %s", exc)
            return fut

        try:
            self._bus.publish(self.EVT_STARTED, path=str(p))
        except Exception as exc:  # noqa: BLE001
            _LOG.debug("EVT_STARTED publish failed: %s", exc)

        fut = self._executor.submit(self._run_import, p)
        with self._lock:
            self._pending.add(fut)
            self._submitted_total += 1

        def _on_done(f: Future) -> None:
            try:
                result: ImportResult = f.result()
            except Exception as exc:  # noqa: BLE001
                result = ImportResult(
                    path=p,
                    route=ImportRouteResult(
                        kind="error", handle=None, path=p, error=str(exc),
                    ),
                    error=str(exc),
                )
            with self._lock:
                self._pending.discard(f)
                self._completed.append(result)
                self._completed_total += 1
            try:
                self._bus.publish(
                    self.EVT_COMPLETED,
                    path=str(result.path),
                    kind=result.route.kind,
                    ok=result.ok,
                    elapsed_s=result.elapsed_s,
                    error=result.error,
                )
            except Exception as exc:  # noqa: BLE001
                _LOG.debug("EVT_COMPLETED publish failed: %s", exc)
            if callback is not None:
                try:
                    callback(result)
                except Exception as exc:  # noqa: BLE001
                    _LOG.info("submit callback raised: %s", exc)

        fut.add_done_callback(_on_done)
        return fut

    def poll_completions(self) -> list[ImportResult]:
        """Drain completed results. Safe to call every editor tick."""
        with self._lock:
            drained = list(self._completed)
            self._completed.clear()
        return drained

    def pending_count(self) -> int:
        """Return the number of futures still queued or running."""
        with self._lock:
            return len(self._pending)

    def cancel_all(self) -> int:
        """Attempt to cancel every pending future. Returns cancelled count."""
        cancelled = 0
        with self._lock:
            for f in list(self._pending):
                if f.cancel():
                    cancelled += 1
                    self._pending.discard(f)
        return cancelled

    def wait(self, timeout: float | None = None) -> None:
        """Block until every submitted future completes.

        Intended for tests + shutdown; the editor tick uses
        :meth:`poll_completions` instead. Uses busy-poll under the lock
        so cancelled futures don't leak into the wait.
        """
        with self._lock:
            futures = list(self._pending)
        for f in futures:
            try:
                f.result(timeout=timeout)
            except Exception:  # noqa: BLE001
                pass

    def shutdown(self, wait: bool = True) -> None:
        """Tear down the underlying executor. Idempotent."""
        exe = self._executor
        self._executor = None
        if exe is not None:
            try:
                exe.shutdown(wait=wait, cancel_futures=True)
            except TypeError:
                # Older Python without cancel_futures kwarg.
                exe.shutdown(wait=wait)

    def stats(self) -> dict[str, Any]:
        """Return submission / completion counters."""
        with self._lock:
            return {
                "max_workers": self._max_workers,
                "pending": len(self._pending),
                "completed_ready": len(self._completed),
                "submitted_total": self._submitted_total,
                "completed_total": self._completed_total,
            }

    # ------------------------------------------------------------------
    # Worker body
    # ------------------------------------------------------------------

    def _run_import(self, path: Path) -> ImportResult:
        import time as _time

        start = _time.perf_counter()
        try:
            route = self._router(path)
        except Exception as exc:  # noqa: BLE001
            elapsed = _time.perf_counter() - start
            return ImportResult(
                path=path,
                route=ImportRouteResult(
                    kind="error", handle=None, path=path, error=str(exc),
                ),
                elapsed_s=elapsed,
                error=f"{type(exc).__name__}: {exc}",
            )
        elapsed = _time.perf_counter() - start
        return ImportResult(
            path=path,
            route=route,
            elapsed_s=elapsed,
            error=route.error if route.kind == "error" else "",
        )


__all__ = [
    "AsyncImportQueue",
    "ImportResult",
]
