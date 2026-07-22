"""
pharos_engine.telemetry.sink
===========================

Per-panel telemetry sink helpers.

Editor panels (outliner, code mode, script binding editor, ...) share the
same DD4 dashboard (``NotebookTelemetryDashboard``).  Rather than have every
panel hand-craft its own :func:`pharos_engine.telemetry.emit` payloads,
this module exposes a small ergonomic API that guarantees the payload keys
match the dashboard's sniff contract:

======================  ===========================================
Emitter                 Payload keys the dashboard sniffs
======================  ===========================================
:meth:`TelemetrySink.incr`        ``count``, ``delta``, ``value``
:meth:`TelemetrySink.gauge`       ``gauge``, ``value``
:meth:`TelemetrySink.histogram`   ``bucket`` / ``histogram``, ``value``
:meth:`TelemetrySink.perf_start`  ``duration_ms``
======================  ===========================================

Layer prefixing
---------------
Each sink is bound to a ``source`` string.  :meth:`TelemetrySink.sublayer`
returns a :class:`LayerSink` whose ``source`` is dotted onto the parent
(``"editor" -> "editor.outliner" -> "editor.outliner.tree"``).  Sublayers
compose freely.

Batching
--------
Tight loops can wrap their emits in :meth:`TelemetrySink.batch` — the sink
buffers the events and fires them in bulk when the context exits, so the
dashboard's subscriber gets one burst instead of N interleaved calls.

Instrumentation helper
----------------------
:meth:`TelemetrySink.instrument_module` wraps every public function of a
module in :meth:`perf_timed` so a panel can retrofit timing onto an
existing module without editing it.  Functions carrying the
:data:`SKIP_INSTRUMENT_MARKER` attribute (``__telemetry_skip__ = True``)
are left alone — this lets a module opt out of a specific hot loop.

Null sink
---------
:func:`null_sink` returns a no-op sink for headless / testing paths that
don't want to touch the global telemetry bus.
"""
from __future__ import annotations

import contextlib
import inspect
import time
from types import ModuleType
from typing import Any, Callable, Iterator, List, Optional, Tuple

from . import emit as _emit

__all__ = [
    "SKIP_INSTRUMENT_MARKER",
    "LayerSink",
    "TelemetrySink",
    "null_sink",
]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SKIP_INSTRUMENT_MARKER: str = "__telemetry_skip__"
"""Attribute name — set to ``True`` on a function to opt out of
:meth:`TelemetrySink.instrument_module`."""


# ---------------------------------------------------------------------------
# Perf handle
# ---------------------------------------------------------------------------


class _PerfHandle:
    """Handle returned by :meth:`TelemetrySink.perf_start`.

    Calling :meth:`stop` emits a ``duration_ms`` telemetry event carrying
    the elapsed milliseconds since :meth:`TelemetrySink.perf_start` was
    called.  Calling :meth:`stop` twice is a no-op after the first call.
    """

    __slots__ = ("_sink", "_name", "_started_at", "_stopped", "duration_ms")

    def __init__(self, sink: "TelemetrySink", name: str) -> None:
        self._sink = sink
        self._name = name
        self._started_at: float = time.perf_counter()
        self._stopped: bool = False
        self.duration_ms: float = 0.0

    def stop(self, tags: Optional[dict] = None) -> float:
        """Emit the timing event and return the elapsed milliseconds.

        Parameters
        ----------
        tags : dict, optional
            Extra key/value pairs to merge into the emitted payload.  Tag
            keys collide with the reserved ``duration_ms`` / ``source`` /
            ``name`` keys only when the caller explicitly overrides them;
            in that case the caller's value wins (this keeps the API
            forgiving — a panel can override ``source`` for a burst).
        """
        if self._stopped:
            return self.duration_ms
        self._stopped = True
        self.duration_ms = (time.perf_counter() - self._started_at) * 1000.0
        payload: dict = {"duration_ms": self.duration_ms}
        if tags:
            payload.update(tags)
        self._sink._emit(self._name, payload)
        return self.duration_ms


# ---------------------------------------------------------------------------
# TelemetrySink
# ---------------------------------------------------------------------------


class TelemetrySink:
    """Emit dashboard-shaped telemetry events on behalf of a panel.

    Parameters
    ----------
    source : str
        Name shown in the dashboard's ``source`` column.  Typically the
        panel's dotted identifier (``"editor.outliner"``, ``"editor.script_binding"``).
    """

    __slots__ = ("_source", "_batch_stack")

    def __init__(self, source: str) -> None:
        if not isinstance(source, str):
            raise TypeError(
                f"TelemetrySink: source must be a str; got {type(source).__name__}"
            )
        if not source:
            raise ValueError("TelemetrySink: source must be non-empty")
        self._source: str = source
        # Stack of active batch buffers.  Nested batches append to the
        # innermost buffer; the outermost .__exit__ flushes.  Each entry
        # is a list of (name, payload) tuples.
        self._batch_stack: List[List[Tuple[str, dict]]] = []

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def source(self) -> str:
        """The source name that will be attached to every emit."""
        return self._source

    # ------------------------------------------------------------------
    # Sublayer
    # ------------------------------------------------------------------

    def sublayer(self, name: str) -> "LayerSink":
        """Return a :class:`LayerSink` scoped to ``{parent_source}.{name}``."""
        if not isinstance(name, str):
            raise TypeError(
                f"TelemetrySink.sublayer: name must be a str; got {type(name).__name__}"
            )
        if not name:
            raise ValueError("TelemetrySink.sublayer: name must be non-empty")
        return LayerSink(self, name)

    # ------------------------------------------------------------------
    # Emitters
    # ------------------------------------------------------------------

    def incr(
        self,
        name: str,
        delta: float = 1,
        tags: Optional[dict] = None,
    ) -> None:
        """Emit a counter event.

        The payload carries both ``count`` and ``delta`` — DD4 sniffs
        either key, so panels don't have to remember which one the
        dashboard prefers.
        """
        self._require_str_name(name, "incr")
        if not isinstance(delta, (int, float)) or isinstance(delta, bool):
            raise TypeError(
                f"TelemetrySink.incr: delta must be numeric; got {type(delta).__name__}"
            )
        payload: dict = {"count": float(delta), "delta": float(delta)}
        if tags:
            payload.update(tags)
        self._emit(name, payload)

    def gauge(
        self,
        name: str,
        value: float,
        tags: Optional[dict] = None,
    ) -> None:
        """Emit a gauge event carrying the latest ``value``."""
        self._require_str_name(name, "gauge")
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise TypeError(
                f"TelemetrySink.gauge: value must be numeric; got {type(value).__name__}"
            )
        payload: dict = {"gauge": float(value), "value": float(value)}
        if tags:
            payload.update(tags)
        self._emit(name, payload)

    def histogram(
        self,
        name: str,
        value: float,
        bucket_key: Optional[str] = None,
        tags: Optional[dict] = None,
    ) -> None:
        """Emit a histogram sample.

        When ``bucket_key`` is provided the event carries a ``bucket``
        payload (DD4 folds it into ``{bucket: count}``).  When it is
        omitted the sink derives a bucket label from ``value`` using
        exponential bucketing (`<1`, `<10`, `<100`, ...) so the dashboard
        can still render something useful without the caller having to
        pre-bucket.
        """
        self._require_str_name(name, "histogram")
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise TypeError(
                f"TelemetrySink.histogram: value must be numeric; "
                f"got {type(value).__name__}"
            )
        bucket_label: str
        if bucket_key is None:
            bucket_label = _auto_bucket_label(float(value))
        else:
            if not isinstance(bucket_key, str):
                raise TypeError(
                    f"TelemetrySink.histogram: bucket_key must be str; "
                    f"got {type(bucket_key).__name__}"
                )
            bucket_label = bucket_key
        payload: dict = {
            "bucket": bucket_label,
            "histogram": {bucket_label: 1},
            "value": float(value),
        }
        if tags:
            payload.update(tags)
        self._emit(name, payload)

    # ------------------------------------------------------------------
    # Perf timers
    # ------------------------------------------------------------------

    def perf_start(self, name: str) -> _PerfHandle:
        """Start a perf timer.  Call :meth:`_PerfHandle.stop` to emit."""
        self._require_str_name(name, "perf_start")
        return _PerfHandle(self, name)

    @contextlib.contextmanager
    def perf_timed(self, name: str) -> Iterator[_PerfHandle]:
        """Context manager wrapping :meth:`perf_start` / :meth:`stop`.

        Usage::

            with sink.perf_timed("outliner.rebuild"):
                rebuild()
        """
        handle = self.perf_start(name)
        try:
            yield handle
        finally:
            handle.stop()

    # ------------------------------------------------------------------
    # Batch API
    # ------------------------------------------------------------------

    @contextlib.contextmanager
    def batch(self) -> Iterator["TelemetrySink"]:
        """Context manager that buffers emits + flushes on exit.

        Nested :meth:`batch` blocks buffer into the innermost buffer; only
        the outermost block flushes to the global bus.  Exceptions raised
        inside the block still cause the buffered events to be emitted
        (best-effort — losing telemetry on a crash is worse than emitting
        it late).
        """
        buffer: List[Tuple[str, dict]] = []
        self._batch_stack.append(buffer)
        try:
            yield self
        finally:
            popped = self._batch_stack.pop()
            # Only flush at the outermost level so nested batches behave
            # like a single flush.
            if not self._batch_stack:
                for name, payload in popped:
                    _emit(name, **payload)
            else:
                # Nested batch — propagate to the parent buffer.
                self._batch_stack[-1].extend(popped)

    # ------------------------------------------------------------------
    # Module instrumentation
    # ------------------------------------------------------------------

    def instrument_module(
        self,
        module: ModuleType,
        prefix: Optional[str] = None,
    ) -> int:
        """Wrap every public function of *module* with :meth:`perf_timed`.

        Returns the number of functions actually wrapped.  Functions that
        carry :data:`SKIP_INSTRUMENT_MARKER` set to a truthy value are
        skipped; so are functions whose name starts with an underscore.

        Parameters
        ----------
        module : ModuleType
            The module to walk.  Only attributes defined in *module*
            itself are considered — imported helpers are left alone so
            the sink doesn't re-wrap the world.
        prefix : str, optional
            Prefix prepended (dotted) to each perf name.  Defaults to
            the module's ``__name__``.
        """
        if not isinstance(module, ModuleType):
            raise TypeError(
                "TelemetrySink.instrument_module: module must be a ModuleType; "
                f"got {type(module).__name__}"
            )
        actual_prefix = prefix if prefix is not None else module.__name__
        wrapped = 0
        module_name = getattr(module, "__name__", None)
        for attr_name in dir(module):
            if attr_name.startswith("_"):
                continue
            obj = getattr(module, attr_name)
            if not callable(obj):
                continue
            # Skip classes — instrumenting a class is a different feature.
            if inspect.isclass(obj):
                continue
            # Only wrap functions defined in *this* module — imported
            # helpers get skipped so we don't re-instrument shared utils.
            defined_in = getattr(obj, "__module__", None)
            if module_name is not None and defined_in is not None:
                if defined_in != module_name:
                    continue
            # Skip anything opted out.
            if getattr(obj, SKIP_INSTRUMENT_MARKER, False):
                continue
            wrapped_fn = self._wrap_callable(obj, f"{actual_prefix}.{attr_name}")
            setattr(module, attr_name, wrapped_fn)
            wrapped += 1
        return wrapped

    def _wrap_callable(
        self,
        fn: Callable[..., Any],
        perf_name: str,
    ) -> Callable[..., Any]:
        """Return *fn* wrapped in a :meth:`perf_timed` block."""
        sink = self

        def _wrapper(*args: Any, **kwargs: Any) -> Any:
            with sink.perf_timed(perf_name):
                return fn(*args, **kwargs)

        # Preserve identity metadata so debugging + repr stays readable.
        try:
            _wrapper.__name__ = getattr(fn, "__name__", "instrumented")
            _wrapper.__doc__ = getattr(fn, "__doc__", None)
            _wrapper.__wrapped__ = fn  # type: ignore[attr-defined]
            _wrapper.__module__ = getattr(fn, "__module__", None)
        except Exception:
            pass
        return _wrapper

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _emit(self, name: str, payload: dict) -> None:
        """Attach ``source`` and route through the batch buffer or bus."""
        # source is a reserved payload key — do not let a caller shadow
        # it via ``tags`` unless they explicitly passed the same key.
        if "source" not in payload:
            payload = dict(payload)
            payload["source"] = self._source
        if self._batch_stack:
            self._batch_stack[-1].append((name, payload))
        else:
            _emit(name, **payload)

    def _require_str_name(self, name: str, method: str) -> None:
        if not isinstance(name, str):
            raise TypeError(
                f"TelemetrySink.{method}: name must be a str; "
                f"got {type(name).__name__}"
            )
        if not name:
            raise ValueError(f"TelemetrySink.{method}: name must be non-empty")


# ---------------------------------------------------------------------------
# LayerSink
# ---------------------------------------------------------------------------


class LayerSink(TelemetrySink):
    """A :class:`TelemetrySink` scoped under a parent's ``source``.

    The layer's ``source`` is ``{parent.source}.{layer_name}``.  Every
    emit is routed through the parent so batches and null sinks compose
    naturally — calling :meth:`batch` on a layer buffers into the parent's
    batch stack, and a layer built on top of :func:`null_sink` inherits
    the no-op behaviour.
    """

    __slots__ = ("_parent", "_layer_name")

    def __init__(self, parent: TelemetrySink, layer_name: str) -> None:
        if not isinstance(parent, TelemetrySink):
            raise TypeError(
                "LayerSink: parent must be a TelemetrySink; "
                f"got {type(parent).__name__}"
            )
        if not isinstance(layer_name, str) or not layer_name:
            raise ValueError("LayerSink: layer_name must be a non-empty str")
        # Compose the source before delegating to the base __init__ so
        # ``self._source`` is set correctly.
        composed = f"{parent.source}.{layer_name}"
        super().__init__(composed)
        self._parent = parent
        self._layer_name = layer_name

    @property
    def parent(self) -> TelemetrySink:
        return self._parent

    @property
    def layer_name(self) -> str:
        return self._layer_name

    def _emit(self, name: str, payload: dict) -> None:
        # Force our composed source onto the payload, then delegate so
        # batch buffers + null routing are inherited.
        if "source" not in payload:
            payload = dict(payload)
            payload["source"] = self._source
        # Delegate to parent so batching composes.  We route through the
        # parent's _emit (not directly to the bus) so a batch opened on a
        # layer gets flushed by the parent's outermost batch exit.
        self._parent._emit(name, payload)


# ---------------------------------------------------------------------------
# Null sink
# ---------------------------------------------------------------------------


class _NullSink(TelemetrySink):
    """No-op sink — every emit is dropped on the floor."""

    __slots__ = ()

    def _emit(self, name: str, payload: dict) -> None:  # noqa: D401
        # Intentional no-op.
        return None


def null_sink(source: str = "null") -> TelemetrySink:
    """Return a sink whose emits are dropped.

    Handy for headless tests + tools that construct a panel but don't
    want to touch the global telemetry bus.  The returned object still
    honours the full :class:`TelemetrySink` protocol — batches,
    sublayers, perf handles all work; they just don't emit anything.
    """
    return _NullSink(source)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _auto_bucket_label(value: float) -> str:
    """Return an exponential-bucket label for *value*.

    Buckets: ``"<1"``, ``"<10"``, ``"<100"``, ``"<1000"``, ...

    Negative values land in ``"<0"``.  Non-positive zero maps to
    ``"<1"``.
    """
    if value < 0:
        return "<0"
    if value < 1.0:
        return "<1"
    threshold = 10.0
    while value >= threshold:
        threshold *= 10.0
        if threshold > 1e12:
            return ">=1e12"
    return f"<{int(threshold)}"
