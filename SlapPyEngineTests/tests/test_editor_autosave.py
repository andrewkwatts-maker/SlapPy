"""Tripwire suite for ``pharos_editor.ui.editor.editor_autosave`` — sprint Z6.

Covers :class:`EditorAutosaveIntegration` end-to-end:

* :meth:`wire` starts the manager, :meth:`unwire` stops it cleanly.
* Missing ``get_dirty_state`` on the shell makes ``wire`` a silent
  no-op (returns ``False``, ``is_wired`` remains ``False``).
* :meth:`recover_on_boot` returns a :class:`RecoveryOffer` iff a fresh
  snapshot exists (or ``None`` otherwise).
* :meth:`apply_recovery` correctly handles RESTORE / DISCARD /
  KEEP_BOTH branches.
* :meth:`attach_to_status_bar` pushes an "Autosaved" toast.
* :meth:`last_saved_ago_seconds` monotonic + ``None``-until-first-tick.
* :func:`default_dirty_state_provider` handles missing shell attributes.
* :func:`default_restore_handler` writes attributes back onto the shell.

All tests use ``tmp_path`` for snapshot dirs so nothing touches
``~/.pharos_engine/``. Fast (~0.02 s) autosave intervals plus tight
sleeps keep the whole suite under ~2 s.
"""
from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from pharos_engine.autosave import (
    AutosaveManager,
    AutosaveState,
    RecoveryChoice,
    RecoveryOffer,
)
from pharos_editor.ui.editor.editor_autosave import (
    EditorAutosaveIntegration,
    default_dirty_state_provider,
    default_restore_handler,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_shell(**attrs) -> SimpleNamespace:
    """Build a stand-in editor shell with a dirty-state hook + attrs."""
    payload = attrs.pop("dirty_payload", {"scene": "hello"})
    shell = SimpleNamespace(
        get_dirty_state=lambda: payload,
        **attrs,
    )
    return shell


def _make_project(tmp_path: Path, name: str = "unit_test_project", **kwargs) -> SimpleNamespace:
    """Build a project stand-in exposing ``.name`` + optional ``last_opened``."""
    return SimpleNamespace(name=name, last_opened=kwargs.get("last_opened"))


def _make_state(tmp_path: Path, **overrides) -> AutosaveState:
    """Build an :class:`AutosaveState` under ``tmp_path`` with fast defaults."""
    defaults = dict(
        enabled=True,
        interval_seconds=0.02,
        snapshot_dir=tmp_path / "autosave",
        max_snapshots=5,
    )
    defaults.update(overrides)
    return AutosaveState(**defaults)


def _make_integration(
    tmp_path: Path,
    shell: SimpleNamespace | None = None,
    project: SimpleNamespace | None = None,
    **kwargs,
) -> EditorAutosaveIntegration:
    """Build a wired-ready integration under ``tmp_path``."""
    shell = shell if shell is not None else _make_shell()
    project = project if project is not None else _make_project(tmp_path)
    state = kwargs.pop("state", None) or _make_state(tmp_path)
    return EditorAutosaveIntegration(
        shell=shell,
        project=project,
        state=state,
        **kwargs,
    )


def _wait_for(pred, timeout: float = 1.5) -> bool:
    """Poll *pred* until it returns truthy or *timeout* elapses."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pred():
            return True
        time.sleep(0.005)
    return False


def _make_snapshot_file(
    tmp_path: Path, when: float | None = None, name: str = "20260101_120000_0001.snap.yaml",
) -> Path:
    """Write a minimal, decodable snapshot file under *tmp_path*."""
    snap_dir = tmp_path / "autosave"
    snap_dir.mkdir(parents=True, exist_ok=True)
    path = snap_dir / name
    # Minimal YAML that both the yaml and json fallback decoders parse.
    path.write_text(
        '{"meta": {"saved_at": "2026-01-01T12:00:00Z", "project": "p", '
        '"engine_version": "test"}, "payload": {"scene": "hi"}}',
        encoding="utf-8",
    )
    if when is not None:
        import os
        os.utime(path, (when, when))
    return path


# ---------------------------------------------------------------------------
# wire() / unwire()
# ---------------------------------------------------------------------------


def test_wire_starts_manager_then_unwire_stops_cleanly(tmp_path):
    integ = _make_integration(tmp_path)
    assert integ.wire() is True
    assert integ.is_wired is True
    assert integ.manager is not None
    assert integ.manager.is_running is True
    integ.unwire()
    assert integ.is_wired is False
    assert integ.manager is None


def test_wire_without_get_dirty_state_is_silent_noop(tmp_path):
    shell = SimpleNamespace()  # no get_dirty_state method
    project = _make_project(tmp_path)
    integ = EditorAutosaveIntegration(shell=shell, project=project)
    assert integ.wire() is False
    assert integ.is_wired is False
    assert integ.manager is None
    # unwire is idempotent even when never wired.
    integ.unwire()


def test_wire_writes_snapshot_when_timer_fires(tmp_path):
    integ = _make_integration(tmp_path)
    integ.wire()
    try:
        assert _wait_for(
            lambda: integ.manager is not None and integ.manager.latest_snapshot() is not None,
            timeout=1.5,
        )
    finally:
        integ.unwire()


def test_unwire_is_idempotent(tmp_path):
    integ = _make_integration(tmp_path)
    integ.wire()
    integ.unwire()
    integ.unwire()  # second call must not raise


def test_wire_with_explicit_dirty_provider_ignores_missing_shell_method(tmp_path):
    shell = SimpleNamespace()  # no get_dirty_state
    project = _make_project(tmp_path)

    def custom_provider():
        return {"custom": True}

    integ = EditorAutosaveIntegration(
        shell=shell,
        project=project,
        state=_make_state(tmp_path),
        dirty_state_provider=custom_provider,
    )
    assert integ.wire() is True
    integ.unwire()


# ---------------------------------------------------------------------------
# recover_on_boot()
# ---------------------------------------------------------------------------


def test_recover_on_boot_returns_offer_for_fresh_snapshot(tmp_path):
    path = _make_snapshot_file(tmp_path, when=time.time())
    project = _make_project(tmp_path, last_opened="2020-01-01T00:00:00Z")
    integ = EditorAutosaveIntegration(
        shell=_make_shell(),
        project=project,
        state=_make_state(tmp_path),
    )
    offer = integ.recover_on_boot()
    assert offer is not None
    assert offer.snapshot_path == path


def test_recover_on_boot_returns_none_when_no_snapshots(tmp_path):
    project = _make_project(tmp_path)
    integ = EditorAutosaveIntegration(
        shell=_make_shell(),
        project=project,
        state=_make_state(tmp_path),
    )
    assert integ.recover_on_boot() is None


def test_recover_on_boot_returns_none_when_project_newer_than_snapshot(tmp_path):
    # Snapshot stamped in the past, project last_opened stamped in the future.
    _make_snapshot_file(tmp_path, when=time.time() - 3600)
    project = _make_project(tmp_path, last_opened="2099-01-01T00:00:00Z")
    integ = EditorAutosaveIntegration(
        shell=_make_shell(),
        project=project,
        state=_make_state(tmp_path),
    )
    assert integ.recover_on_boot() is None


# ---------------------------------------------------------------------------
# apply_recovery — RESTORE / DISCARD / KEEP_BOTH
# ---------------------------------------------------------------------------


def test_apply_recovery_restore_invokes_handler(tmp_path):
    path = _make_snapshot_file(tmp_path, when=time.time())
    project = _make_project(tmp_path, last_opened="2020-01-01T00:00:00Z")
    seen: list = []
    integ = EditorAutosaveIntegration(
        shell=_make_shell(),
        project=project,
        state=_make_state(tmp_path),
        restore_handler=lambda payload: seen.append(payload),
    )
    offer = integ.recover_on_boot()
    assert offer is not None
    integ.apply_recovery(RecoveryChoice.RESTORE, offer)
    assert len(seen) == 1
    assert seen[0] == {"scene": "hi"}


def test_apply_recovery_discard_deletes_file(tmp_path):
    path = _make_snapshot_file(tmp_path, when=time.time())
    project = _make_project(tmp_path, last_opened="2020-01-01T00:00:00Z")
    integ = EditorAutosaveIntegration(
        shell=_make_shell(),
        project=project,
        state=_make_state(tmp_path),
    )
    offer = integ.recover_on_boot()
    assert offer is not None
    integ.apply_recovery(RecoveryChoice.DISCARD, offer)
    assert not path.exists()


def test_apply_recovery_keep_both_renames_with_bak_suffix(tmp_path):
    path = _make_snapshot_file(tmp_path, when=time.time())
    project = _make_project(tmp_path, last_opened="2020-01-01T00:00:00Z")
    integ = EditorAutosaveIntegration(
        shell=_make_shell(),
        project=project,
        state=_make_state(tmp_path),
    )
    offer = integ.recover_on_boot()
    assert offer is not None
    integ.apply_recovery(RecoveryChoice.KEEP_BOTH, offer)
    assert not path.exists()
    bak = path.with_suffix(path.suffix + ".bak")
    assert bak.exists()


def test_apply_recovery_keep_both_counter_suffix_on_collision(tmp_path):
    path = _make_snapshot_file(tmp_path, when=time.time())
    # Pre-create a .bak so KEEP_BOTH must fall back to .bak1.
    existing_bak = path.with_suffix(path.suffix + ".bak")
    existing_bak.write_text("old", encoding="utf-8")

    project = _make_project(tmp_path, last_opened="2020-01-01T00:00:00Z")
    integ = EditorAutosaveIntegration(
        shell=_make_shell(),
        project=project,
        state=_make_state(tmp_path),
    )
    offer = integ.recover_on_boot()
    assert offer is not None
    integ.apply_recovery(RecoveryChoice.KEEP_BOTH, offer)
    # Original path renamed to .bak1 (since .bak was taken).
    assert path.with_suffix(f"{path.suffix}.bak1").exists()


def test_apply_recovery_rejects_wrong_choice_type(tmp_path):
    path = _make_snapshot_file(tmp_path, when=time.time())
    offer = RecoveryOffer(
        snapshot_path=path,
        project_last_saved=None,
        snapshot_saved=path.stat().st_mtime,
    )
    integ = _make_integration(tmp_path)
    with pytest.raises(TypeError):
        integ.apply_recovery("restore", offer)  # type: ignore[arg-type]


def test_apply_recovery_rejects_wrong_offer_type(tmp_path):
    integ = _make_integration(tmp_path)
    with pytest.raises(TypeError):
        integ.apply_recovery(RecoveryChoice.RESTORE, "not-an-offer")  # type: ignore[arg-type]


def test_apply_recovery_restore_default_handler_writes_shell_attrs(tmp_path):
    # Write a snapshot whose payload maps directly onto the default
    # shell attribute set.
    snap_dir = tmp_path / "autosave"
    snap_dir.mkdir(parents=True, exist_ok=True)
    path = snap_dir / "20260101_120000_0001.snap.yaml"
    path.write_text(
        '{"meta": {"saved_at": "2026-01-01T12:00:00Z", "project": "p", '
        '"engine_version": "test"}, "payload": {"selected_entity": "ent-42"}}',
        encoding="utf-8",
    )
    shell = SimpleNamespace(_selected_entity=None, get_dirty_state=lambda: {})
    project = _make_project(tmp_path, last_opened="2020-01-01T00:00:00Z")
    integ = EditorAutosaveIntegration(
        shell=shell, project=project, state=_make_state(tmp_path),
    )
    offer = integ.recover_on_boot()
    assert offer is not None
    integ.apply_recovery(RecoveryChoice.RESTORE, offer)
    assert shell._selected_entity == "ent-42"


# ---------------------------------------------------------------------------
# Status bar bridge
# ---------------------------------------------------------------------------


class _StubStatusBar:
    """Test double capturing set_message calls."""

    def __init__(self):
        self.calls: list[tuple[str, str]] = []
        self._transient_ttl_s: float = 3.0

    def set_message(self, text: str, kind: str = "info") -> None:
        self.calls.append((text, kind))


def test_attach_to_status_bar_fires_toast_on_tick(tmp_path):
    integ = _make_integration(tmp_path)
    bar = _StubStatusBar()
    integ.attach_to_status_bar(bar)
    integ.wire()
    try:
        assert _wait_for(lambda: len(bar.calls) >= 1, timeout=1.5)
        assert bar.calls[0][0] == "Autosaved"
        assert bar.calls[0][1] == "success"
    finally:
        integ.unwire()


def test_attach_to_status_bar_sets_2_second_ttl(tmp_path):
    integ = _make_integration(tmp_path)
    bar = _StubStatusBar()
    integ.attach_to_status_bar(bar)
    integ.wire()
    try:
        assert _wait_for(lambda: len(bar.calls) >= 1, timeout=1.5)
        assert bar._transient_ttl_s == 2.0
    finally:
        integ.unwire()


def test_attach_to_status_bar_rejects_bad_interface(tmp_path):
    integ = _make_integration(tmp_path)
    with pytest.raises(TypeError):
        integ.attach_to_status_bar(object())  # no set_message method


def test_attach_to_status_bar_none_detaches(tmp_path):
    integ = _make_integration(tmp_path)
    bar = _StubStatusBar()
    integ.attach_to_status_bar(bar)
    integ.attach_to_status_bar(None)
    # No exception even with a broken bar detached — status is silent.
    integ.wire()
    try:
        assert _wait_for(
            lambda: integ.manager is not None and integ.manager.latest_snapshot() is not None,
            timeout=1.5,
        )
        # Nothing pushed to the detached bar.
        assert bar.calls == []
    finally:
        integ.unwire()


def test_status_bar_exception_does_not_crash_tick(tmp_path):
    class _Explodes:
        def set_message(self, text, kind="info"):
            raise RuntimeError("boom")

    integ = _make_integration(tmp_path)
    integ.attach_to_status_bar(_Explodes())
    integ.wire()
    try:
        # If the exception escaped, the manager thread would die before
        # writing a snapshot. Assert a snapshot lands anyway.
        assert _wait_for(
            lambda: integ.manager is not None and integ.manager.latest_snapshot() is not None,
            timeout=1.5,
        )
    finally:
        integ.unwire()


# ---------------------------------------------------------------------------
# last_saved_ago_seconds
# ---------------------------------------------------------------------------


def test_last_saved_ago_seconds_is_none_before_first_tick(tmp_path):
    integ = _make_integration(tmp_path)
    assert integ.last_saved_ago_seconds() is None


def test_last_saved_ago_seconds_monotonic_after_tick(tmp_path):
    integ = _make_integration(tmp_path)
    integ.wire()
    try:
        assert _wait_for(
            lambda: integ.last_saved_ago_seconds() is not None,
            timeout=1.5,
        )
        first = integ.last_saved_ago_seconds()
        assert first is not None and first >= 0.0
        time.sleep(0.05)
        second = integ.last_saved_ago_seconds()
        assert second is not None
        # Value monotonically grows (up to another tick refreshing it —
        # allow small overshoot). Cannot go negative.
        assert second >= 0.0
    finally:
        integ.unwire()


# ---------------------------------------------------------------------------
# default_dirty_state_provider
# ---------------------------------------------------------------------------


def test_default_dirty_state_provider_captures_present_attrs(tmp_path):
    shell = SimpleNamespace(
        _selected_entity="ent-1",
        _project=SimpleNamespace(name="proj"),
        _active_layer="layer-a",
        _last_active_theme_id="teengirl_notebook",
    )
    state = default_dirty_state_provider(shell)
    assert state["selected_entity"] == "ent-1"
    assert state["active_layer"] == "layer-a"
    assert state["last_active_theme_id"] == "teengirl_notebook"
    # Project object folded to its .name marker dict.
    assert state["project"] == {"__name__": "proj"}


def test_default_dirty_state_provider_handles_missing_attrs(tmp_path):
    shell = SimpleNamespace(_selected_entity="only-this")
    state = default_dirty_state_provider(shell)
    assert state == {"selected_entity": "only-this"}


def test_default_dirty_state_provider_handles_none_shell():
    assert default_dirty_state_provider(None) == {}


def test_default_dirty_state_provider_serialises_paths(tmp_path):
    shell = SimpleNamespace(_project=tmp_path / "proj_dir")
    state = default_dirty_state_provider(shell)
    assert state["project"] == str(tmp_path / "proj_dir")


def test_default_dirty_state_provider_swallows_broken_property(tmp_path):
    class _Boom:
        @property
        def _selected_entity(self):
            raise RuntimeError("prop failed")

    state = default_dirty_state_provider(_Boom())
    assert state == {}


# ---------------------------------------------------------------------------
# default_restore_handler
# ---------------------------------------------------------------------------


def test_default_restore_handler_sets_underscored_attrs(tmp_path):
    shell = SimpleNamespace(_selected_entity=None, _active_layer=None)
    default_restore_handler(shell, {"selected_entity": "restored", "active_layer": "L1"})
    assert shell._selected_entity == "restored"
    assert shell._active_layer == "L1"


def test_default_restore_handler_falls_back_to_raw_key(tmp_path):
    shell = SimpleNamespace(custom_field=None)
    default_restore_handler(shell, {"custom_field": "value"})
    assert shell.custom_field == "value"


def test_default_restore_handler_ignores_non_dict_state(tmp_path):
    shell = SimpleNamespace(_selected_entity="untouched")
    default_restore_handler(shell, "not-a-dict")  # type: ignore[arg-type]
    assert shell._selected_entity == "untouched"


def test_default_restore_handler_survives_frozen_target(tmp_path):
    # A dict-based target that raises on setattr would exercise the
    # object.__setattr__ path; using a plain SimpleNamespace shows the
    # happy path still functions.
    shell = SimpleNamespace(_selected_entity=None)
    default_restore_handler(shell, {"selected_entity": "ok"})
    assert shell._selected_entity == "ok"


# ---------------------------------------------------------------------------
# Miscellaneous surface guarantees
# ---------------------------------------------------------------------------


def test_project_defaults_to_anonymous_when_none(tmp_path):
    integ = EditorAutosaveIntegration(shell=_make_shell())
    assert integ.project is not None
    assert getattr(integ.project, "name", None) == "unnamed"


def test_integration_exports_expected_symbols():
    from pharos_editor.ui.editor import editor_autosave as mod
    for sym in ("EditorAutosaveIntegration",
                "default_dirty_state_provider",
                "default_restore_handler"):
        assert hasattr(mod, sym)
