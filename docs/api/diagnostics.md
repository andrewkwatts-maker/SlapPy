<!-- handauthored: do not regenerate -->
# slappyengine.diagnostics — API Reference

> Hand-written reference for the OO6 runtime diagnostics aggregator plus
> the QQ4 :class:`~slappyengine.App` façade methods that bind it to the
> app lifecycle. Sibling references:
> [`hud_overlay.md`](hud_overlay.md) documents the compact HUD widget
> (:func:`slappyengine.hud_bridge.add_diagnostics_widget`) that surfaces
> collector state in-viewport; [`telemetry.md`](telemetry.md) is the
> structured-event bus for domain telemetry — diagnostics is the
> passive listener for the stdlib `logging` warnings + errors emitted
> by every ``slappyengine.*`` subsystem.

## Overview

`slappyengine.diagnostics` was landed in OO6 to solve one problem: MM1
sprinkled `_LOG = logging.getLogger(__name__)` warnings across 13
subsystem files (audio_3d, capture, exporter, physics3_bridge,
render/ssao|skybox|instanced, text, asset_import/*, …), but those
warnings just spammed stderr and disappeared. This module attaches a
`logging.Handler` to the `slappyengine` root logger, keeps a rolling
buffer of :class:`DiagnosticEvent` records, and exposes structured
counts + filters the HUD widget and downstream tooling can consume.

Contract highlights:

* **Passive.** The collector does *not* modify any existing call site
  — subsystems keep using ``_LOG.warning(...)`` as before.
* **Thread-safe.** Every buffer mutation is guarded by an internal
  `threading.RLock` so audio / GPU-upload workers cannot clobber the
  ring buffer.
* **Level-respecting.** :meth:`install` widens the root logger's
  effective level only when it is unset — a stricter user config is
  preserved.
* **Process-wide singleton.** :func:`get_global_collector` lazily
  constructs one collector per process; the HUD widget in
  :mod:`slappyengine.hud_bridge` uses the same singleton so the
  running frame surfaces the same events the tooling sees.

The QQ4 :class:`~slappyengine.App` façade methods
(:meth:`~slappyengine.App.enable_diagnostics`,
:meth:`~slappyengine.App.disable_diagnostics`,
:meth:`~slappyengine.App.get_diagnostics`,
:meth:`~slappyengine.App.diagnostics_events`,
:meth:`~slappyengine.App.diagnostics_stats`) are thin one-liners over
this module; they exist so `App`-level users never have to import
`slappyengine.diagnostics` directly.

## Public surface

```python
from slappyengine.diagnostics import (
    DiagnosticEvent,
    DiagnosticsCollector,
    get_global_collector,
)
```

Plus the :class:`App` façade methods (see the "App integration" section
below).

## Classes

### `DiagnosticEvent`

_dataclass (frozen) — defined in `slappyengine.diagnostics`_

One captured logging record, distilled for HUD / tooling display.

| Field | Type | Notes |
|-------|------|-------|
| `level` | `str` | Upper-case level name (`"WARNING"`, `"ERROR"`, ...). |
| `subsystem` | `str` | Derived from `record.name`; `slappyengine.render.ssao` → `"render"`, `slappyengine.audio_3d` → `"audio_3d"`, foreign loggers keep their top-level module. |
| `message` | `str` | Fully-formatted log message (`record.getMessage()`). |
| `timestamp` | `float` | Wall-clock seconds since epoch (`time.time()` at capture). |
| `exc_info` | `str \| None` | Formatted traceback when the log carried `exc_info=True`. |

### `DiagnosticsCollector`

_class — defined in `slappyengine.diagnostics`_

Rolling-buffer aggregator for `slappyengine.*` log records.

```python
DiagnosticsCollector(
    max_events: int = 500,
    min_level: str = "WARNING",
)
```

Raises `ValueError` when `max_events <= 0` or *min_level* is an
unknown log level name / number.

Install / uninstall:

- `install() -> None` — attach the capture handler. Idempotent.
- `uninstall() -> None` — detach. Idempotent.
- `is_installed() -> bool`

Buffer ops:

- `events() -> list[DiagnosticEvent]` — snapshot copy, oldest first.
- `clear() -> None`
- `stats() -> dict[str, int]` — flat dict with two namespaces so HUD
  widgets can consume it directly:
  - `level:WARNING` / `level:ERROR` / `level:CRITICAL` / ...
  - `subsystem:render` / `subsystem:audio_3d` / ...
  - plus a `total` key with the event count.
- `filter_by_subsystem(name) -> list[DiagnosticEvent]` — prefix match
  so `"render"` catches both `render` and any future `render.ssao`
  sub-tag.

## Functions

### `get_global_collector() -> DiagnosticsCollector`

_defined in `slappyengine.diagnostics`_

Return the process-wide collector (lazy init). The first call
constructs the collector with default parameters (`max_events=500`,
`min_level="WARNING"`) but does *not* call :meth:`install` — the caller
(HUD widget, app bootstrap, test harness) decides when to attach the
handler.

## App integration (QQ4)

The following :class:`slappyengine.App` methods are thin façades over
this module and defined in `python/slappyengine/app.py`:

### `App.enable_diagnostics(min_level="WARNING", max_events=500) -> DiagnosticsCollector`

Instantiate a fresh :class:`DiagnosticsCollector`, call
:meth:`~DiagnosticsCollector.install`, and stash it on
`self._diagnostics`. Idempotent — a second call returns the same
collector. When a HUD is already mounted (`self._hud_overlay` is not
`None`), also attaches a diagnostics readout widget via
:func:`slappyengine.hud_bridge.add_diagnostics_widget` so warnings +
errors surface in-viewport without further wiring.

### `App.disable_diagnostics() -> dict[str, Any]`

Uninstall the bound collector. Returns `{"status": "disabled"}` when a
collector was detached, `{"status": "not_enabled"}` when nothing was
bound. Never raises — an `uninstall()` failure is logged as a warning.

### `App.get_diagnostics() -> DiagnosticsCollector | None`

Convenience accessor — equivalent to
`getattr(app, "_diagnostics", None)` but explicit.

### `App.diagnostics_events() -> list[DiagnosticEvent]`

Convenience shim over :meth:`DiagnosticsCollector.events`. Returns
`[]` when diagnostics are not enabled.

### `App.diagnostics_stats() -> dict[str, int]`

Convenience shim over :meth:`DiagnosticsCollector.stats`. Returns `{}`
when diagnostics are not enabled.

## Usage

Standalone (no `App`):

```python
import logging
from slappyengine.diagnostics import get_global_collector

collector = get_global_collector()
collector.install()
try:
    # Any subsystem emitting via `logging.getLogger("slappyengine.*")`
    # is now captured.
    logging.getLogger("slappyengine.render.ssao").warning(
        "ssao pass fallback: %s", "no depth texture"
    )
    stats = collector.stats()
    assert stats["total"] >= 1
    assert stats["level:WARNING"] >= 1
    for evt in collector.events()[-3:]:
        print(evt.level, evt.subsystem, evt.message)
finally:
    collector.uninstall()
```

`App` façade:

```python
from slappyengine.app import App

app = App()
collector = app.enable_diagnostics(min_level="WARNING", max_events=200)
# ... game runs; subsystems log warnings ...
events = app.diagnostics_events()
stats = app.diagnostics_stats()
app.disable_diagnostics()
```

## Skip the wrapper

`slappyengine.diagnostics` is Python-only. Grep of
`slappyengine._core_facade.RUST_MODULE_MAP` shows **no**
`diagnostics` entry — the per-record work is a `_subsystem_from_logger_name`
string split plus a `deque.append` under an `RLock`, dwarfed by the
formatting cost of the log record itself.

Callers who want to bypass the :class:`App` façade (custom
`min_level` per subsystem, collector attached to a non-`slappyengine`
logger, multi-app sharing) should reach for :class:`DiagnosticsCollector`
/ :func:`get_global_collector` directly. Games with their own log
sink can install a :class:`logging.Handler` on the `slappyengine`
logger themselves and never touch this module.

## See also

- [`hud_overlay.md`](hud_overlay.md) — the compact diagnostics
  readout widget wired through
  :func:`slappyengine.hud_bridge.add_diagnostics_widget`.
- [`telemetry.md`](telemetry.md) — structured event bus for
  first-party engine telemetry (diagnostics is the passive listener
  for stdlib `logging`; telemetry is the active emitter).
- `python/slappyengine/app.py` — QQ4 façade methods
  :meth:`~slappyengine.App.enable_diagnostics` and friends.
