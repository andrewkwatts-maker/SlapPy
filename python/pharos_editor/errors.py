"""Centralised error router (Nova3D flaw #10 remediation).

Nova3D's editor swallowed 50+ exceptions with bare ``except: pass``
across ``shell.py``, ``layout_persistence.py``, and various panel
init paths. Users got no signal; devs had no diagnostic breadcrumb.

Pharos rule: no bare ``except: pass`` in ``pharos_editor``. When you
must catch broadly, route via :func:`route` — one call sink that:

1. Logs to ``pharos_editor.log`` (rolling, size-capped).
2. Emits a telemetry event on the ``pharos.editor.error`` topic.
3. Optionally pushes a status-bar toast (when the shell is up).

CI enforcement: :mod:`scripts.import_lint` (already landed in Sprint 2)
gains a companion :mod:`scripts.errors_lint` that greps for the ban
pattern — see ``scripts/errors_lint.py``.
"""
from __future__ import annotations

import datetime
import logging
import sys
import traceback
from typing import Callable, Optional


_logger = logging.getLogger("pharos_editor")
if not _logger.handlers:
    _logger.setLevel(logging.INFO)
    _handler = logging.StreamHandler(sys.stderr)
    _handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] pharos_editor.%(name)s: %(message)s")
    )
    _logger.addHandler(_handler)


# Optional pluggable toast sink. The editor shell registers its
# status-bar handler here during startup; standalone / CI callers get
# a no-op.
_toast_sink: Optional[Callable[[str, str], None]] = None


def register_toast_sink(sink: Callable[[str, str], None] | None) -> None:
    """Install (or clear) the status-bar toast callback.

    The callback receives ``(level, message)`` where level is one of
    ``"info" | "warn" | "error"``. Pass ``None`` to detach.
    """
    global _toast_sink
    _toast_sink = sink


def _describe(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"


def route(
    exc: BaseException,
    context: str,
    *,
    toast: bool = True,
    level: str = "error",
    logger_name: str | None = None,
) -> None:
    """Route a caught exception through the standard sink.

    Parameters
    ----------
    exc:
        The exception object caught by the caller.
    context:
        Short human-readable string describing what the caller was
        doing when it failed. Example: ``"panel.NotebookOutliner.refresh"``.
    toast:
        Whether to try to push a status-bar toast (silently no-ops if
        the shell hasn't registered a sink).
    level:
        One of ``"info" | "warn" | "error"``. Selects the log level and
        toast severity.
    logger_name:
        Optional child-logger name (appended to ``pharos_editor``).
    """
    log = _logger.getChild(logger_name) if logger_name else _logger
    msg = _describe(exc)
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    if level == "info":
        log.info("%s :: %s\n%s", context, msg, tb)
    elif level == "warn":
        log.warning("%s :: %s\n%s", context, msg, tb)
    else:
        log.error("%s :: %s\n%s", context, msg, tb)

    if toast and _toast_sink is not None:
        try:
            _toast_sink(level, f"{context}: {msg}")
        except Exception as sink_exc:
            log.error("toast sink raised: %s", sink_exc)

    # Telemetry emit is best-effort — keep the import lazy so this
    # module remains importable in the pharos-engine wheel tests that
    # don't have the telemetry runtime loaded.
    try:
        from pharos_engine.telemetry import emit as _emit
    except Exception:
        return
    try:
        # pharos_engine.telemetry.emit takes payload as **kwargs, not a
        # positional dict. Splatting here so both the current and any
        # future emit signature stays satisfied.
        _emit(
            "pharos.editor.error",
            context=context,
            exc_type=type(exc).__name__,
            message=str(exc),
            level=level,
            timestamp=datetime.datetime.utcnow().isoformat(),
        )
    except Exception as emit_exc:
        log.error("telemetry emit raised: %s", emit_exc)


__all__ = ["route", "register_toast_sink"]
