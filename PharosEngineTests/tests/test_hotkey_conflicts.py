"""Tests for :mod:`pharos_editor.ui.hotkey_conflicts` (FF5).

Covers:

* :class:`ConflictReport` construction + validation,
* Every :class:`ConflictKind` firing on a synthetic map,
* Platform-shortcut table shape + per-OS variance,
* Text-edit shadow on bare single letters,
* Modifier-missing on the danger-zone keys,
* Orphan-chord detection when the leading chord is standalone,
* Empty map / disabled bindings are silent,
* Default + user merge with a duplicate combo → user wins → no dup flag,
* :func:`format_report` output is stable + covers every report,
* :func:`has_severity` + :func:`filter_by_kind` behaviour.
"""
from __future__ import annotations

import pytest

from pharos_editor.ui.hotkey_conflicts import (
    PLATFORM_SHORTCUTS,
    ConflictKind,
    ConflictReport,
    detect_conflicts,
    filter_by_kind,
    format_report,
    has_severity,
)
from pharos_editor.ui.hotkey_remap import HotkeyBinding, HotkeyMap, apply_remap


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _map_from(*pairs: tuple[str, str]) -> HotkeyMap:
    """Return a HotkeyMap built from a list of ``(combo, action_id)`` pairs."""
    m = HotkeyMap()
    for combo, action_id in pairs:
        m.add(HotkeyBinding(combo=combo, action_id=action_id))
    return m


# ---------------------------------------------------------------------------
# ConflictReport dataclass
# ---------------------------------------------------------------------------


def test_conflict_report_frozen() -> None:
    b = HotkeyBinding(combo="ctrl+s", action_id="save")
    r = ConflictReport(
        combo="ctrl+s",
        kind=ConflictKind.DUPLICATE_COMBO,
        severity="error",
        message="dup",
        bindings=[b],
    )
    with pytest.raises(Exception):
        r.combo = "other"  # type: ignore[misc]


def test_conflict_report_rejects_bad_severity() -> None:
    b = HotkeyBinding(combo="ctrl+s", action_id="save")
    with pytest.raises(ValueError):
        ConflictReport(
            combo="ctrl+s",
            kind=ConflictKind.DUPLICATE_COMBO,
            severity="critical",
            message="dup",
            bindings=[b],
        )


def test_conflict_report_rejects_empty_message() -> None:
    b = HotkeyBinding(combo="ctrl+s", action_id="save")
    with pytest.raises(ValueError):
        ConflictReport(
            combo="ctrl+s",
            kind=ConflictKind.DUPLICATE_COMBO,
            severity="error",
            message="",
            bindings=[b],
        )


def test_conflict_report_rejects_non_binding_entry() -> None:
    with pytest.raises(TypeError):
        ConflictReport(
            combo="ctrl+s",
            kind=ConflictKind.DUPLICATE_COMBO,
            severity="error",
            message="dup",
            bindings=["not a binding"],  # type: ignore[list-item]
        )


def test_conflict_report_rejects_non_kind() -> None:
    b = HotkeyBinding(combo="ctrl+s", action_id="save")
    with pytest.raises(TypeError):
        ConflictReport(
            combo="ctrl+s",
            kind="DUPLICATE_COMBO",  # type: ignore[arg-type]
            severity="error",
            message="dup",
            bindings=[b],
        )


# ---------------------------------------------------------------------------
# Enum + platform table
# ---------------------------------------------------------------------------


def test_conflict_kind_enum_membership() -> None:
    assert {k.name for k in ConflictKind} == {
        "DUPLICATE_COMBO",
        "SHADOWS_PLATFORM",
        "SHADOWS_TEXT_EDIT",
        "MODIFIER_MISSING",
        "ORPHAN_CHORD",
    }


def test_platform_shortcuts_has_three_os() -> None:
    assert set(PLATFORM_SHORTCUTS) == {"win", "mac", "linux"}
    for combos in PLATFORM_SHORTCUTS.values():
        assert isinstance(combos, set)
        assert combos, "each OS should reserve at least one combo"


def test_platform_shortcuts_are_canonical() -> None:
    # Every listed combo should already be lowercase + use "meta" not "cmd".
    for combos in PLATFORM_SHORTCUTS.values():
        for c in combos:
            assert c == c.lower(), f"{c!r} not lowercase"
            assert "cmd" not in c.split("+"), f"{c!r} contains raw 'cmd'"


# ---------------------------------------------------------------------------
# DUPLICATE_COMBO
# ---------------------------------------------------------------------------


def test_duplicate_combo_across_two_maps() -> None:
    a = _map_from(("ctrl+s", "editor.save"))
    b = _map_from(("ctrl+s", "editor.snap"))
    reports = detect_conflicts([a, b])
    dups = filter_by_kind(reports, ConflictKind.DUPLICATE_COMBO)
    assert len(dups) == 1
    r = dups[0]
    assert r.combo == "ctrl+s"
    assert r.severity == "error"
    assert {b.action_id for b in r.bindings} == {"editor.save", "editor.snap"}


def test_no_duplicate_when_single_map() -> None:
    # HotkeyMap collapses on combo insertion, so a single-map view
    # can never show a duplicate.
    m = HotkeyMap()
    m.add(HotkeyBinding(combo="ctrl+s", action_id="a"))
    m.add(HotkeyBinding(combo="ctrl+s", action_id="b"))
    reports = detect_conflicts(m)
    assert filter_by_kind(reports, ConflictKind.DUPLICATE_COMBO) == []


def test_duplicate_ignores_disabled_bindings() -> None:
    a = _map_from(("ctrl+s", "editor.save"))
    b = HotkeyMap()
    b.add(HotkeyBinding(combo="ctrl+s", action_id="editor.snap", enabled=False))
    reports = detect_conflicts([a, b])
    assert filter_by_kind(reports, ConflictKind.DUPLICATE_COMBO) == []


# ---------------------------------------------------------------------------
# SHADOWS_PLATFORM
# ---------------------------------------------------------------------------


def test_shadows_platform_windows_alt_f4() -> None:
    m = _map_from(("alt+f4", "editor.quit"))
    reports = detect_conflicts(m, platform="win")
    hits = filter_by_kind(reports, ConflictKind.SHADOWS_PLATFORM)
    assert len(hits) == 1
    assert hits[0].combo == "alt+f4"
    assert hits[0].severity == "error"


def test_shadows_platform_mac_cmd_q() -> None:
    m = _map_from(("cmd+q", "editor.quit"))
    reports = detect_conflicts(m, platform="mac")
    hits = filter_by_kind(reports, ConflictKind.SHADOWS_PLATFORM)
    assert len(hits) == 1
    # Canonicalisation folds cmd → meta.
    assert hits[0].combo == "meta+q"


def test_shadows_platform_mac_only_on_mac() -> None:
    # cmd+q → meta+q — reserved on mac but not on win.
    m = _map_from(("cmd+q", "editor.quit"))
    win_reports = detect_conflicts(m, platform="win")
    mac_reports = detect_conflicts(m, platform="mac")
    assert filter_by_kind(win_reports, ConflictKind.SHADOWS_PLATFORM) == []
    assert filter_by_kind(mac_reports, ConflictKind.SHADOWS_PLATFORM) != []


def test_shadows_platform_windows_only_on_win() -> None:
    # alt+f4 → reserved on win but not on mac.
    m = _map_from(("alt+f4", "editor.quit"))
    win_reports = detect_conflicts(m, platform="win")
    mac_reports = detect_conflicts(m, platform="mac")
    assert filter_by_kind(win_reports, ConflictKind.SHADOWS_PLATFORM) != []
    assert filter_by_kind(mac_reports, ConflictKind.SHADOWS_PLATFORM) == []


def test_shadows_platform_alias_windows_string() -> None:
    m = _map_from(("alt+f4", "editor.quit"))
    reports = detect_conflicts(m, platform="windows")
    assert filter_by_kind(reports, ConflictKind.SHADOWS_PLATFORM) != []


def test_shadows_platform_unknown_falls_back_to_linux() -> None:
    m = _map_from(("ctrl+alt+t", "editor.terminal"))
    reports = detect_conflicts(m, platform="haiku-os")
    # Linux table reserves ctrl+alt+t.
    assert filter_by_kind(reports, ConflictKind.SHADOWS_PLATFORM) != []


# ---------------------------------------------------------------------------
# SHADOWS_TEXT_EDIT
# ---------------------------------------------------------------------------


def test_shadows_text_edit_single_letter() -> None:
    m = _map_from(("a", "editor.select_all"))
    reports = detect_conflicts(m, platform="linux")
    hits = filter_by_kind(reports, ConflictKind.SHADOWS_TEXT_EDIT)
    assert len(hits) == 1
    assert hits[0].combo == "a"
    assert hits[0].severity == "warn"


def test_shadows_text_edit_digit_flagged() -> None:
    m = _map_from(("5", "editor.jump_5"))
    reports = detect_conflicts(m, platform="linux")
    hits = filter_by_kind(reports, ConflictKind.SHADOWS_TEXT_EDIT)
    assert len(hits) == 1
    assert hits[0].combo == "5"


def test_shadows_text_edit_ignored_with_modifier() -> None:
    m = _map_from(("ctrl+a", "editor.select_all"))
    reports = detect_conflicts(m, platform="linux")
    assert filter_by_kind(reports, ConflictKind.SHADOWS_TEXT_EDIT) == []


def test_shadows_text_edit_ignored_on_multi_chord() -> None:
    m = _map_from(("ctrl+x a", "editor.chord"))
    reports = detect_conflicts(m, platform="linux")
    assert filter_by_kind(reports, ConflictKind.SHADOWS_TEXT_EDIT) == []


# ---------------------------------------------------------------------------
# MODIFIER_MISSING
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("key", ["space", "enter", "escape", "tab"])
def test_modifier_missing_on_danger_zone(key: str) -> None:
    m = _map_from((key, f"editor.{key}"))
    reports = detect_conflicts(m, platform="linux")
    hits = filter_by_kind(reports, ConflictKind.MODIFIER_MISSING)
    assert len(hits) == 1
    assert hits[0].combo == key
    assert hits[0].severity == "error"


def test_modifier_missing_alias_esc_returns_escape() -> None:
    # "esc" → alias "escape" — still flagged.
    m = _map_from(("esc", "editor.cancel"))
    reports = detect_conflicts(m, platform="linux")
    hits = filter_by_kind(reports, ConflictKind.MODIFIER_MISSING)
    assert len(hits) == 1
    assert hits[0].combo == "escape"


def test_modifier_missing_ignored_when_modifier_present() -> None:
    m = _map_from(("ctrl+space", "editor.autocomplete"))
    reports = detect_conflicts(m, platform="linux")
    assert filter_by_kind(reports, ConflictKind.MODIFIER_MISSING) == []


# ---------------------------------------------------------------------------
# ORPHAN_CHORD
# ---------------------------------------------------------------------------


def test_orphan_chord_when_leader_is_standalone() -> None:
    m = _map_from(
        ("ctrl+x", "editor.cut"),
        ("ctrl+x ctrl+s", "editor.save_all"),
    )
    reports = detect_conflicts(m, platform="linux")
    hits = filter_by_kind(reports, ConflictKind.ORPHAN_CHORD)
    assert len(hits) == 1
    assert hits[0].combo == "ctrl+x ctrl+s"
    # Both the multi-chord + the leader binding are surfaced.
    action_ids = {b.action_id for b in hits[0].bindings}
    assert action_ids == {"editor.cut", "editor.save_all"}


def test_orphan_chord_not_flagged_when_leader_absent() -> None:
    m = _map_from(("ctrl+x ctrl+s", "editor.save_all"))
    reports = detect_conflicts(m, platform="linux")
    assert filter_by_kind(reports, ConflictKind.ORPHAN_CHORD) == []


def test_orphan_chord_multiple_multi_chords_share_leader() -> None:
    m = _map_from(
        ("ctrl+x", "editor.cut"),
        ("ctrl+x ctrl+s", "editor.save_all"),
        ("ctrl+x ctrl+c", "editor.close_all"),
    )
    reports = detect_conflicts(m, platform="linux")
    hits = filter_by_kind(reports, ConflictKind.ORPHAN_CHORD)
    assert {h.combo for h in hits} == {"ctrl+x ctrl+s", "ctrl+x ctrl+c"}


# ---------------------------------------------------------------------------
# Empty + happy paths
# ---------------------------------------------------------------------------


def test_empty_map_returns_empty_report() -> None:
    assert detect_conflicts(HotkeyMap(), platform="linux") == []


def test_iterable_of_empty_maps_returns_empty_report() -> None:
    assert detect_conflicts([HotkeyMap(), HotkeyMap()], platform="linux") == []


def test_healthy_map_has_no_conflicts() -> None:
    m = _map_from(
        ("ctrl+s", "editor.save"),
        ("ctrl+z", "editor.undo"),
        ("ctrl+shift+z", "editor.redo"),
    )
    reports = detect_conflicts(m, platform="linux")
    assert reports == []


def test_non_hotkey_map_in_iterable_raises() -> None:
    with pytest.raises(TypeError):
        detect_conflicts([HotkeyMap(), "not-a-map"])  # type: ignore[list-item]


# ---------------------------------------------------------------------------
# Merge semantics: default + user with duplicate combo → user wins, no dup
# ---------------------------------------------------------------------------


def test_merged_map_user_wins_no_duplicate() -> None:
    defaults = _map_from(("ctrl+s", "editor.save"))
    user = _map_from(("ctrl+s", "editor.snap"))
    merged = apply_remap(defaults, user)
    # After merge only one binding remains on the combo.
    assert merged.resolve("ctrl+s") == "editor.snap"
    reports = detect_conflicts(merged, platform="linux")
    assert filter_by_kind(reports, ConflictKind.DUPLICATE_COMBO) == []


def test_pre_merge_view_flags_the_duplicate() -> None:
    defaults = _map_from(("ctrl+s", "editor.save"))
    user = _map_from(("ctrl+s", "editor.snap"))
    reports = detect_conflicts([defaults, user], platform="linux")
    dups = filter_by_kind(reports, ConflictKind.DUPLICATE_COMBO)
    assert len(dups) == 1


# ---------------------------------------------------------------------------
# format_report
# ---------------------------------------------------------------------------


def test_format_report_empty_sentinel() -> None:
    assert format_report([]) == "No conflicts."


def test_format_report_contains_all_conflicts() -> None:
    m = _map_from(
        ("alt+f4", "editor.quit"),          # SHADOWS_PLATFORM (win)
        ("space", "editor.play"),            # MODIFIER_MISSING
        ("a", "editor.select_all"),          # SHADOWS_TEXT_EDIT
        ("ctrl+x", "editor.cut"),            # (leader for orphan)
        ("ctrl+x ctrl+s", "editor.save_all"),  # ORPHAN_CHORD
    )
    reports = detect_conflicts(m, platform="win")
    text = format_report(reports)
    assert "alt+f4" in text
    assert "space" in text
    assert "'a'" in text or "\"a\"" in text
    assert "ctrl+x ctrl+s" in text
    # Every report kind headers a section.
    for kind in {r.kind for r in reports}:
        assert kind.name in text


def test_format_report_rejects_non_report() -> None:
    with pytest.raises(TypeError):
        format_report(["not-a-report"])  # type: ignore[list-item]


def test_format_report_ascii_safe() -> None:
    # Windows cp1252 encode must not raise.
    m = _map_from(("alt+f4", "editor.quit"))
    reports = detect_conflicts(m, platform="win")
    text = format_report(reports)
    text.encode("cp1252")


# ---------------------------------------------------------------------------
# has_severity / filter_by_kind
# ---------------------------------------------------------------------------


def test_has_severity_error_present() -> None:
    m = _map_from(("alt+f4", "editor.quit"))
    reports = detect_conflicts(m, platform="win")
    assert has_severity(reports, "error") is True
    assert has_severity(reports, "warn") is True
    assert has_severity(reports, "info") is True


def test_has_severity_only_warn() -> None:
    m = _map_from(("a", "editor.select_all"))
    reports = detect_conflicts(m, platform="linux")
    assert has_severity(reports, "warn") is True
    assert has_severity(reports, "error") is False


def test_has_severity_empty_is_false() -> None:
    assert has_severity([], "info") is False


def test_has_severity_bad_token_raises() -> None:
    with pytest.raises(ValueError):
        has_severity([], "critical")


def test_filter_by_kind_returns_matches() -> None:
    m = _map_from(
        ("alt+f4", "editor.quit"),
        ("space", "editor.play"),
    )
    reports = detect_conflicts(m, platform="win")
    plat = filter_by_kind(reports, ConflictKind.SHADOWS_PLATFORM)
    modmiss = filter_by_kind(reports, ConflictKind.MODIFIER_MISSING)
    assert len(plat) == 1
    assert plat[0].combo == "alt+f4"
    assert len(modmiss) == 1
    assert modmiss[0].combo == "space"


def test_filter_by_kind_bad_kind_raises() -> None:
    with pytest.raises(TypeError):
        filter_by_kind([], "DUPLICATE_COMBO")  # type: ignore[arg-type]


def test_detect_conflicts_default_platform_runs() -> None:
    # No explicit platform kwarg → must still return a list.
    reports = detect_conflicts(HotkeyMap())
    assert reports == []


def test_reports_sorted_deterministically() -> None:
    m = _map_from(
        ("a", "editor.a"),
        ("b", "editor.b"),
        ("space", "editor.space"),
    )
    reports = detect_conflicts(m, platform="linux")
    # Sorted by (kind.value, combo). MODIFIER_MISSING < SHADOWS_TEXT_EDIT
    # alphabetically on the enum value string.
    kinds_in_order = [r.kind for r in reports]
    # The sort key is deterministic, so a repeat run should match.
    again = detect_conflicts(m, platform="linux")
    assert [r.kind for r in again] == kinds_in_order
    assert [r.combo for r in again] == [r.combo for r in reports]
