"""``EditorAutosaveIntegration`` — wires Y6 autosave into the editor lifecycle.

This helper sits *next to* :class:`EditorShell` rather than inside it —
the shell is a large, historically-fragile module we deliberately leave
untouched. The integration lives here as a sibling so a boot-time hook
in the shell (a single call) can defer the entire autosave surface to
this module.

Responsibilities
----------------
* Own the :class:`AutosaveManager` instance for the current editor
  session (start on ``wire``, stop on ``unwire``).
* Bridge the shell's dirty-state snapshot (whatever
  ``shell.get_dirty_state()`` returns) to the autosave callback.
* Offer a boot-time :class:`RecoveryPrompt` check so the shell can raise
  a modal iff a fresher snapshot exists.
* Apply the user's recovery choice (RESTORE / DISCARD / KEEP_BOTH) via
  a small, well-defined restore handler.
* Track the last-save timestamp so the status bar can render an
  "Autosaved 12 s ago" hint.
* Push a transient "Autosaved" toast to a status bar (if provided) on
  every tick.

Design provenance: sprint Z6 (editor autosave integration).
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from pharos_engine.autosave import (
    AutosaveManager,
    AutosaveState,
    RecoveryChoice,
    RecoveryOffer,
    RecoveryPrompt,
    default_snapshot_dir,
)


__all__ = [
    "EditorAutosaveIntegration",
    "default_dirty_state_provider",
    "default_restore_handler",
]


# Attributes the shell is expected to expose that get captured in the
# dirty-state dict. Missing attributes are silently skipped so a
# partially-constructed shell still autosaves cleanly.
_DEFAULT_SHELL_ATTRS: tuple[str, ...] = (
    "_selected_entity",
    "_project",
    "_active_layer",
    "_last_active_theme_id",
)


# ---------------------------------------------------------------------------
# Helper serialisation — walks the shell attributes → dict
# ---------------------------------------------------------------------------


def _serialise_value(value: Any) -> Any:
    """Coerce *value* into a YAML-safe representation.

    * ``None`` / ``bool`` / ``int`` / ``float`` / ``str`` pass through.
    * ``Path`` → ``str``.
    * ``dict`` / ``list`` / ``tuple`` → recursively serialised
      (tuples become lists).
    * objects with a ``.name`` attribute (e.g. RegisteredProject,
      Layer) → ``{"__name__": name}`` marker dict.
    * anything else → ``repr(value)`` as fallback.
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _serialise_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialise_value(v) for v in value]
    # Common shell attribute pattern: objects that expose a .name field.
    name = getattr(value, "name", None)
    if isinstance(name, str) and name:
        return {"__name__": name}
    return repr(value)


def default_dirty_state_provider(shell: Any) -> dict:
    """Walk *shell*'s common attributes and package a dirty-state dict.

    Reads the four attributes listed in :data:`_DEFAULT_SHELL_ATTRS`
    (``_selected_entity``, ``_project``, ``_active_layer``,
    ``_last_active_theme_id``) and serialises each via
    :func:`_serialise_value`. Missing attributes are silently omitted so
    a shell mid-construction still yields a valid (possibly empty) dict.

    Parameters
    ----------
    shell:
        The editor shell (or a stand-in for tests).

    Returns
    -------
    dict
        YAML-safe dict keyed by attribute name (without the leading
        underscore) so the snapshot payload stays legible.
    """
    if shell is None:
        return {}
    payload: dict = {}
    sentinel = object()
    for attr in _DEFAULT_SHELL_ATTRS:
        # Guard both the getattr() call *and* the presence check: a
        # descriptor property whose __get__ raises will explode a plain
        # hasattr() on modern Pythons, so we probe via getattr() with a
        # sentinel default and swallow every exception.
        try:
            value = getattr(shell, attr, sentinel)
        except Exception:
            continue
        if value is sentinel:
            continue
        # Strip leading underscore for readability in the YAML snapshot.
        key = attr.lstrip("_") or attr
        payload[key] = _serialise_value(value)
    return payload


def default_restore_handler(shell: Any, state: dict) -> None:
    """Set every ``<key>``/``_<key>`` on *shell* from a restored *state* dict.

    Uses :func:`object.__setattr__` so the setter works even on frozen
    dataclass holders (which the shell often keeps for small immutable
    state slots). Missing shell attributes are set best-effort; failures
    are swallowed so a partial restore still populates what it can.

    Parameters
    ----------
    shell:
        The editor shell to receive the restored attributes.
    state:
        The decoded snapshot payload (typically the dict produced by
        :func:`default_dirty_state_provider`).
    """
    if shell is None or not isinstance(state, dict):
        return
    for key, value in state.items():
        # Prefer the underscore-prefixed private form (matches the
        # provider's key stripping) but fall back to the raw key.
        underscored = f"_{key}"
        target_attr = underscored if hasattr(shell, underscored) else key
        try:
            object.__setattr__(shell, target_attr, value)
        except Exception:
            # Best-effort — a frozen slot without a matching field will
            # simply be skipped. The editor can prompt the user later.
            try:
                setattr(shell, target_attr, value)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# EditorAutosaveIntegration
# ---------------------------------------------------------------------------


@dataclass
class _TickRecord:
    """Bookkeeping stamp for the last successful autosave tick."""

    at: float


class EditorAutosaveIntegration:
    """Glues :class:`AutosaveManager` to the editor shell lifecycle.

    The class deliberately holds *no* reference to any UI framework: the
    only external surfaces it touches are

    * ``shell.get_dirty_state()`` (optional — a missing method makes
      :meth:`wire` a silent no-op),
    * ``status_bar.set_message(text, kind)`` (optional — attached via
      :meth:`attach_to_status_bar`),

    and the on-disk autosave ring buffer owned by
    :class:`AutosaveManager`.

    Parameters
    ----------
    shell:
        The editor shell — typically :class:`EditorShell`. Must expose a
        ``get_dirty_state()`` method for autosave to arm; otherwise
        :meth:`wire` silently no-ops.
    project:
        Optional :class:`pharos_engine.project_registry.RegisteredProject`
        (or any object exposing ``.name``). When omitted, an anonymous
        placeholder is used so the manager can still be constructed.
    state:
        Optional pre-built :class:`AutosaveState`. When omitted, a
        default state is created with the project's snapshot dir.
    dirty_state_provider:
        Zero-arg callable returning the payload dict. Defaults to a
        lambda that calls ``shell.get_dirty_state()``.
    restore_handler:
        One-arg callable that receives the decoded snapshot payload.
        Defaults to :func:`default_restore_handler` bound to *shell*.
    """

    def __init__(
        self,
        shell: Any,
        project: Any = None,
        state: Optional[AutosaveState] = None,
        dirty_state_provider: Optional[Callable[[], Any]] = None,
        restore_handler: Optional[Callable[[Any], None]] = None,
    ) -> None:
        self._shell = shell
        self._project = project if project is not None else _AnonymousProject()
        self._state = state
        self._dirty_provider = dirty_state_provider
        self._restore_handler = restore_handler
        self._manager: Optional[AutosaveManager] = None
        self._status_bar: Any = None
        self._last_tick: Optional[_TickRecord] = None
        self._wired: bool = False

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def manager(self) -> Optional[AutosaveManager]:
        """The underlying manager (``None`` until :meth:`wire` succeeds)."""
        return self._manager

    @property
    def is_wired(self) -> bool:
        """``True`` iff :meth:`wire` armed a manager successfully."""
        return self._wired and self._manager is not None

    @property
    def project(self) -> Any:
        return self._project

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def wire(self) -> bool:
        """Construct + start an :class:`AutosaveManager` bound to the shell.

        Silently returns ``False`` (no-op) when the shell doesn't expose
        a ``get_dirty_state`` method and no explicit ``dirty_state_provider``
        was passed to ``__init__`` — the editor can then run in a
        degraded no-autosave mode until the shell exposes the hook.

        Returns
        -------
        bool
            ``True`` iff the manager was armed.
        """
        provider = self._dirty_provider
        if provider is None:
            if not hasattr(self._shell, "get_dirty_state"):
                return False
            # Bind late so the shell can populate the method after
            # construction if it wants.
            def provider():  # type: ignore[misc]
                return self._shell.get_dirty_state()

        state = self._state
        if state is None:
            snapshot_dir = default_snapshot_dir(
                getattr(self._project, "name", "unnamed"),
            )
            state = AutosaveState(
                enabled=True,
                interval_seconds=60.0,
                snapshot_dir=snapshot_dir,
            )
        self._state = state

        def _save_callback() -> Any:
            payload = provider()
            self._last_tick = _TickRecord(at=time.time())
            self._notify_status_bar()
            return payload

        self._manager = AutosaveManager(state, self._project, _save_callback)
        self._manager.start()
        self._wired = True
        return True

    def unwire(self) -> None:
        """Stop the manager cleanly. Safe to call more than once."""
        manager = self._manager
        self._manager = None
        self._wired = False
        if manager is not None:
            try:
                manager.stop()
            except Exception:
                # Never let a stop-time exception bubble out of teardown
                # — the editor may be mid-quit and can't handle it.
                pass

    # ------------------------------------------------------------------
    # Recovery
    # ------------------------------------------------------------------

    def recover_on_boot(self) -> Optional[RecoveryOffer]:
        """Run a :class:`RecoveryPrompt` check for the current project.

        Returns the offer iff a snapshot fresher than the project's
        ``last_opened`` timestamp exists. The caller (the boot flow) is
        expected to display a modal and then call
        :meth:`apply_recovery`.

        Returns ``None`` when there is nothing to offer or the check
        fails for any reason.
        """
        try:
            snapshot_dir = self._resolve_snapshot_dir()
        except Exception:
            return None
        last_saved = getattr(self._project, "last_opened", None)
        try:
            prompt = RecoveryPrompt(snapshot_dir, last_saved)
        except Exception:
            return None
        try:
            return prompt.check()
        except Exception:
            return None

    def apply_recovery(
        self,
        choice: RecoveryChoice,
        offer: RecoveryOffer,
    ) -> None:
        """Act on the user's response to a boot-time recovery prompt.

        * :attr:`RecoveryChoice.RESTORE` — pipe the snapshot payload
          through :meth:`AutosaveManager.restore_snapshot` into the
          restore handler.
        * :attr:`RecoveryChoice.DISCARD` — delete the snapshot file.
        * :attr:`RecoveryChoice.KEEP_BOTH` — rename the snapshot with a
          ``.bak`` suffix so it stays on disk for later archaeology.
        """
        if not isinstance(choice, RecoveryChoice):
            raise TypeError(
                "EditorAutosaveIntegration.apply_recovery: choice must be a "
                f"RecoveryChoice; got {type(choice).__name__}"
            )
        if not isinstance(offer, RecoveryOffer):
            raise TypeError(
                "EditorAutosaveIntegration.apply_recovery: offer must be a "
                f"RecoveryOffer; got {type(offer).__name__}"
            )
        snap_path = Path(offer.snapshot_path)
        if choice is RecoveryChoice.RESTORE:
            handler = self._restore_handler
            if handler is None:
                shell = self._shell

                def handler(payload):  # type: ignore[misc]
                    default_restore_handler(shell, payload if isinstance(payload, dict) else {})

            # Ensure we have a manager for restore_snapshot; construct
            # a throwaway one if wire() hasn't run yet.
            manager = self._manager
            if manager is None:
                state = self._state or AutosaveState(
                    enabled=False,
                    interval_seconds=60.0,
                    snapshot_dir=snap_path.parent,
                )
                manager = AutosaveManager(
                    state, self._project, lambda: None,
                )
            manager.restore_snapshot(snap_path, handler)
            return
        if choice is RecoveryChoice.DISCARD:
            try:
                snap_path.unlink()
            except FileNotFoundError:
                pass
            return
        if choice is RecoveryChoice.KEEP_BOTH:
            bak_path = snap_path.with_suffix(snap_path.suffix + ".bak")
            # If the .bak already exists (repeat KEEP_BOTH), stamp a
            # counter suffix so nothing is silently overwritten.
            counter = 1
            candidate = bak_path
            while candidate.exists():
                candidate = snap_path.with_suffix(
                    f"{snap_path.suffix}.bak{counter}",
                )
                counter += 1
            snap_path.rename(candidate)
            return

    # ------------------------------------------------------------------
    # Status bar bridge
    # ------------------------------------------------------------------

    def attach_to_status_bar(self, status_bar: Any) -> None:
        """Subscribe the integration to a status bar for autosave toasts.

        Any object exposing ``set_message(text, kind)`` works — matches
        :class:`pharos_engine.ui.editor.notebook_status_bar.NotebookStatusBar`.
        On every successful autosave tick we push a 2-second
        ``"Autosaved"`` toast at ``kind="success"``.
        """
        if status_bar is None:
            self._status_bar = None
            return
        if not hasattr(status_bar, "set_message"):
            raise TypeError(
                "EditorAutosaveIntegration.attach_to_status_bar: status_bar "
                "must expose set_message(text, kind); "
                f"got {type(status_bar).__name__}"
            )
        self._status_bar = status_bar

    def _notify_status_bar(self) -> None:
        """Push an 'Autosaved' toast to the bound status bar (if any).

        Also sets ``transient_ttl_s`` to 2 s when the bar exposes that
        attribute so the toast dismisses after the target 2-second
        window. Swallows every exception — a broken status bar must
        never bring down the autosave timer.
        """
        bar = self._status_bar
        if bar is None:
            return
        # Best-effort tweak of the transient TTL to the required 2 s.
        try:
            if hasattr(bar, "_transient_ttl_s"):
                object.__setattr__(bar, "_transient_ttl_s", 2.0)
        except Exception:
            pass
        try:
            bar.set_message("Autosaved", "success")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # UI helpers
    # ------------------------------------------------------------------

    def last_saved_ago_seconds(self) -> Optional[float]:
        """Seconds since the most recent autosave tick (``None`` if none yet).

        Reads from a cached tick timestamp bumped by the save callback
        — this avoids a lock on the manager's ``AutosaveState`` for
        every UI refresh.
        """
        tick = self._last_tick
        if tick is None:
            return None
        return max(0.0, time.time() - tick.at)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _resolve_snapshot_dir(self) -> Path:
        """Return the snapshot dir for the current project.

        Prefers an explicit :attr:`_state` dir; falls back to
        :func:`default_snapshot_dir` keyed by the project's name.
        """
        if self._state is not None:
            return self._state.snapshot_dir
        name = getattr(self._project, "name", "unnamed")
        return default_snapshot_dir(name)


# ---------------------------------------------------------------------------
# Anonymous project placeholder
# ---------------------------------------------------------------------------


@dataclass
class _AnonymousProject:
    """Fallback project descriptor when the shell has none loaded yet.

    Exposes just enough surface (``.name``) to satisfy the
    :class:`AutosaveManager` constructor. The manager's snapshot files
    land under ``~/.pharos_engine/autosave/unnamed/`` in this case, which
    keeps recovery predictable even for scratch sessions.
    """

    name: str = "unnamed"
    last_opened: Optional[str] = None
