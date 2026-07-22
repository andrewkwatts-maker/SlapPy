"""Tests for :mod:`pharos_editor.ui.hotkey_remap` (AA7).

Covers:

* :class:`HotkeyBinding` validation + canonicalisation,
* :class:`HotkeyMap` add / remove / resolve / list / len / contains,
* YAML round-trip (flat + explicit shapes),
* :meth:`HotkeyMap.merge` — user wins per combo,
* :meth:`HotkeyMap.validate` against a fake registry,
* :func:`load_user_hotkeys` with ``tmp_path`` fixtures,
* Corrupt YAML skipped without raising,
* :func:`bake_defaults` idempotency,
* All three shipped baked YAMLs parse cleanly.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from pharos_editor.ui.hotkey_remap import (
    BAKED_HOTKEY_DIR,
    HotkeyBinding,
    HotkeyMap,
    HotkeyRemapWatcher,
    apply_remap,
    bake_defaults,
    default_hotkey_map,
    load_user_hotkeys,
)
from pharos_editor.ui.hotkey_remap import _canon_combo


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeRegistry:
    """Minimal ToolRouter stand-in with a ``has_action`` method."""

    def __init__(self, known: set[str] | None = None) -> None:
        self._known = set(known or ())

    def has_action(self, action_id: str) -> bool:
        return action_id in self._known


# ---------------------------------------------------------------------------
# HotkeyBinding
# ---------------------------------------------------------------------------


def test_binding_basic() -> None:
    b = HotkeyBinding(combo="ctrl+s", action_id="editor.save")
    assert b.combo == "ctrl+s"
    assert b.action_id == "editor.save"
    assert b.enabled is True
    assert b.source == "user"


def test_binding_canonicalises_modifier_order() -> None:
    b = HotkeyBinding(combo="Shift+Ctrl+M", action_id="editor.foo")
    # ctrl before shift before alt
    assert b.combo == "ctrl+shift+m"


def test_binding_canonicalises_multichord() -> None:
    b = HotkeyBinding(combo="Ctrl+X Ctrl+S", action_id="editor.save")
    assert b.combo == "ctrl+x ctrl+s"


def test_binding_alias_expansion() -> None:
    b = HotkeyBinding(combo="Cmd+S", action_id="editor.save")
    # "cmd" aliases to "meta"
    assert b.combo == "meta+s"


def test_binding_empty_combo_raises() -> None:
    with pytest.raises((ValueError, TypeError)):
        HotkeyBinding(combo="", action_id="editor.save")


def test_binding_empty_action_id_raises() -> None:
    with pytest.raises((ValueError, TypeError)):
        HotkeyBinding(combo="ctrl+s", action_id="")


def test_binding_non_string_combo_raises() -> None:
    with pytest.raises(TypeError):
        HotkeyBinding(combo=123, action_id="editor.save")  # type: ignore[arg-type]


def test_binding_source_preserved() -> None:
    b = HotkeyBinding(
        combo="ctrl+p", action_id="editor.help", source="vim_style",
    )
    assert b.source == "vim_style"


# ---------------------------------------------------------------------------
# _canon_combo edge cases
# ---------------------------------------------------------------------------


def test_canon_combo_dedupes_mods() -> None:
    assert _canon_combo("Ctrl+ctrl+S") == "ctrl+s"


def test_canon_combo_whitespace_only_chord_rejects() -> None:
    with pytest.raises(ValueError):
        _canon_combo("   ")


def test_canon_combo_multiple_leaves_last_wins() -> None:
    # "ctrl+s+shift" → ctrl+shift are mods; s is leaf → ctrl+shift+s.
    assert _canon_combo("ctrl+s+shift") == "ctrl+shift+s"


# ---------------------------------------------------------------------------
# HotkeyMap basics
# ---------------------------------------------------------------------------


def test_map_add_and_resolve() -> None:
    m = HotkeyMap()
    m.add(HotkeyBinding(combo="ctrl+s", action_id="editor.save"))
    assert m.resolve("ctrl+s") == "editor.save"
    assert len(m) == 1


def test_map_resolve_case_insensitive() -> None:
    m = HotkeyMap([HotkeyBinding(combo="ctrl+s", action_id="editor.save")])
    assert m.resolve("CTRL+S") == "editor.save"


def test_map_remove() -> None:
    m = HotkeyMap([HotkeyBinding(combo="ctrl+s", action_id="editor.save")])
    assert m.remove("ctrl+s") is True
    assert m.resolve("ctrl+s") is None
    # second remove returns False
    assert m.remove("ctrl+s") is False


def test_map_add_overwrites() -> None:
    m = HotkeyMap()
    m.add(HotkeyBinding(combo="ctrl+s", action_id="editor.save"))
    m.add(HotkeyBinding(combo="ctrl+s", action_id="editor.help"))
    assert m.resolve("ctrl+s") == "editor.help"
    assert len(m) == 1


def test_map_list_all_ordered() -> None:
    m = HotkeyMap([
        HotkeyBinding(combo="a", action_id="x.a"),
        HotkeyBinding(combo="b", action_id="x.b"),
        HotkeyBinding(combo="c", action_id="x.c"),
    ])
    assert [b.combo for b in m.list_all()] == ["a", "b", "c"]


def test_map_disabled_binding_hidden_from_resolve() -> None:
    m = HotkeyMap([
        HotkeyBinding(combo="ctrl+s", action_id="editor.save", enabled=False),
    ])
    assert m.resolve("ctrl+s") is None
    # get() still returns the row so the UI can show the disabled state
    row = m.get("ctrl+s")
    assert row is not None
    assert row.enabled is False


def test_map_contains_and_iter() -> None:
    m = HotkeyMap([HotkeyBinding(combo="ctrl+s", action_id="editor.save")])
    assert "ctrl+s" in m
    assert "CTRL+S" in m
    assert "ctrl+q" not in m
    assert [b.action_id for b in m] == ["editor.save"]


# ---------------------------------------------------------------------------
# YAML round-trip
# ---------------------------------------------------------------------------


def test_map_yaml_roundtrip_flat() -> None:
    m = HotkeyMap([
        HotkeyBinding(combo="ctrl+s", action_id="editor.save"),
        HotkeyBinding(combo="ctrl+z", action_id="editor.undo"),
    ])
    text = m.to_yaml()
    m2 = HotkeyMap.from_yaml(text)
    assert m2.resolve("ctrl+s") == "editor.save"
    assert m2.resolve("ctrl+z") == "editor.undo"
    assert len(m2) == 2


def test_map_yaml_roundtrip_explicit_when_disabled() -> None:
    m = HotkeyMap([
        HotkeyBinding(combo="ctrl+s", action_id="editor.save", enabled=False),
    ])
    text = m.to_yaml()
    # Explicit shape includes bindings: key
    assert "bindings:" in text
    m2 = HotkeyMap.from_yaml(text)
    row = m2.get("ctrl+s")
    assert row is not None
    assert row.enabled is False


def test_map_yaml_roundtrip_preserves_source() -> None:
    m = HotkeyMap([
        HotkeyBinding(
            combo="ctrl+s", action_id="editor.save", source="vim_style",
        ),
    ])
    text = m.to_yaml()
    m2 = HotkeyMap.from_yaml(text)
    row = m2.get("ctrl+s")
    assert row is not None
    assert row.source == "vim_style"


def test_map_yaml_parses_flat_mapping() -> None:
    text = "ctrl+s: editor.save\nctrl+z: editor.undo\n"
    m = HotkeyMap.from_yaml(text)
    assert m.resolve("ctrl+s") == "editor.save"
    assert m.resolve("ctrl+z") == "editor.undo"


def test_map_yaml_default_source_applied() -> None:
    text = "ctrl+s: editor.save\n"
    m = HotkeyMap.from_yaml(text, default_source="vim_style")
    row = m.get("ctrl+s")
    assert row is not None
    assert row.source == "vim_style"


def test_map_yaml_skips_malformed_rows() -> None:
    text = (
        "ctrl+s: editor.save\n"
        "42: not-a-string-key\n"        # int key → skipped
        "ctrl+z: 3.14\n"                # non-string value → skipped
    )
    m = HotkeyMap.from_yaml(text)
    assert m.resolve("ctrl+s") == "editor.save"
    assert len(m) == 1


def test_map_yaml_non_mapping_root_returns_empty() -> None:
    m = HotkeyMap.from_yaml("- just\n- a list\n")
    assert len(m) == 0


# ---------------------------------------------------------------------------
# Merge / apply_remap
# ---------------------------------------------------------------------------


def test_merge_user_wins() -> None:
    d = HotkeyMap([HotkeyBinding(combo="ctrl+s", action_id="editor.save")])
    u = HotkeyMap([HotkeyBinding(combo="ctrl+s", action_id="editor.help")])
    merged = d.merge(u)
    assert merged.resolve("ctrl+s") == "editor.help"


def test_merge_preserves_non_conflicting() -> None:
    d = HotkeyMap([
        HotkeyBinding(combo="ctrl+s", action_id="editor.save"),
        HotkeyBinding(combo="ctrl+z", action_id="editor.undo"),
    ])
    u = HotkeyMap([HotkeyBinding(combo="ctrl+p", action_id="editor.help")])
    merged = d.merge(u)
    assert merged.resolve("ctrl+s") == "editor.save"
    assert merged.resolve("ctrl+z") == "editor.undo"
    assert merged.resolve("ctrl+p") == "editor.help"


def test_merge_disabled_user_removes_default() -> None:
    d = HotkeyMap([HotkeyBinding(combo="ctrl+s", action_id="editor.save")])
    u = HotkeyMap([
        HotkeyBinding(
            combo="ctrl+s", action_id="editor.save", enabled=False,
        ),
    ])
    merged = d.merge(u)
    assert merged.resolve("ctrl+s") is None
    assert "ctrl+s" not in merged


def test_apply_remap_wrapper() -> None:
    d = HotkeyMap([HotkeyBinding(combo="ctrl+s", action_id="editor.save")])
    u = HotkeyMap([HotkeyBinding(combo="ctrl+s", action_id="editor.help")])
    merged = apply_remap(d, u)
    assert merged.resolve("ctrl+s") == "editor.help"


def test_merge_type_error() -> None:
    d = HotkeyMap()
    with pytest.raises(TypeError):
        d.merge("not-a-map")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# validate()
# ---------------------------------------------------------------------------


def test_validate_all_known() -> None:
    m = HotkeyMap([
        HotkeyBinding(combo="ctrl+s", action_id="editor.save"),
        HotkeyBinding(combo="ctrl+z", action_id="editor.undo"),
    ])
    registry = _FakeRegistry({"editor.save", "editor.undo"})
    assert m.validate(registry) == []


def test_validate_reports_unknown() -> None:
    m = HotkeyMap([
        HotkeyBinding(combo="ctrl+s", action_id="editor.save"),
        HotkeyBinding(combo="ctrl+q", action_id="editor.bogus"),
    ])
    registry = _FakeRegistry({"editor.save"})
    unknown = m.validate(registry)
    assert unknown == ["editor.bogus"]


def test_validate_dedupes_repeated_action_ids() -> None:
    m = HotkeyMap([
        HotkeyBinding(combo="a", action_id="editor.bogus"),
        HotkeyBinding(combo="b", action_id="editor.bogus"),
    ])
    registry = _FakeRegistry(set())
    assert m.validate(registry) == ["editor.bogus"]


def test_validate_type_error_when_registry_has_no_has_action() -> None:
    m = HotkeyMap()
    with pytest.raises(TypeError):
        m.validate(object())


def test_validate_against_real_registry() -> None:
    from pharos_editor.tool_router import REGISTRY
    m = HotkeyMap([
        HotkeyBinding(combo="ctrl+s", action_id="editor.save"),
    ])
    assert m.validate(REGISTRY) == []


# ---------------------------------------------------------------------------
# load_user_hotkeys
# ---------------------------------------------------------------------------


def test_load_user_hotkeys_missing_dir_returns_empty(tmp_path: Path) -> None:
    m = load_user_hotkeys(tmp_path / "does-not-exist")
    assert len(m) == 0


def test_load_user_hotkeys_reads_yaml(tmp_path: Path) -> None:
    (tmp_path / "custom.yaml").write_text(
        "ctrl+s: editor.save\n", encoding="utf-8",
    )
    m = load_user_hotkeys(tmp_path)
    assert m.resolve("ctrl+s") == "editor.save"


def test_load_user_hotkeys_later_files_win(tmp_path: Path) -> None:
    (tmp_path / "a_first.yaml").write_text(
        "ctrl+s: editor.save\n", encoding="utf-8",
    )
    (tmp_path / "z_last.yaml").write_text(
        "ctrl+s: editor.help\n", encoding="utf-8",
    )
    m = load_user_hotkeys(tmp_path)
    assert m.resolve("ctrl+s") == "editor.help"


def test_load_user_hotkeys_default_source_from_filename(
    tmp_path: Path,
) -> None:
    (tmp_path / "vim_style.yaml").write_text(
        "ctrl+s: editor.save\n", encoding="utf-8",
    )
    m = load_user_hotkeys(tmp_path)
    row = m.get("ctrl+s")
    assert row is not None
    assert row.source == "vim_style"


def test_load_user_hotkeys_skips_corrupt_file(tmp_path: Path) -> None:
    # One good file + one broken file — good survives.
    (tmp_path / "good.yaml").write_text(
        "ctrl+s: editor.save\n", encoding="utf-8",
    )
    (tmp_path / "broken.yaml").write_text(
        "::: this is not: valid: yaml:::\n  - [unclosed\n",
        encoding="utf-8",
    )
    m = load_user_hotkeys(tmp_path)
    assert m.resolve("ctrl+s") == "editor.save"


def test_load_user_hotkeys_ignores_non_yaml(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("ctrl+s: editor.save\n", encoding="utf-8")
    (tmp_path / "hotkeys.yaml").write_text(
        "ctrl+z: editor.undo\n", encoding="utf-8",
    )
    m = load_user_hotkeys(tmp_path)
    assert m.resolve("ctrl+z") == "editor.undo"
    assert m.resolve("ctrl+s") is None


# ---------------------------------------------------------------------------
# bake_defaults
# ---------------------------------------------------------------------------


def test_bake_defaults_copies_all(tmp_path: Path) -> None:
    copied = bake_defaults(tmp_path)
    # 3 baked presets shipped
    names = sorted(p.name for p in copied)
    assert names == ["default.yaml", "emacs_style.yaml", "vim_style.yaml"]


def test_bake_defaults_idempotent(tmp_path: Path) -> None:
    first = bake_defaults(tmp_path)
    assert len(first) == 3
    second = bake_defaults(tmp_path)
    assert second == []  # nothing new to copy


def test_bake_defaults_does_not_overwrite(tmp_path: Path) -> None:
    bake_defaults(tmp_path)
    target = tmp_path / "default.yaml"
    target.write_text("custom: user.edit\n", encoding="utf-8")
    bake_defaults(tmp_path)
    # User content preserved on second bake
    assert "custom: user.edit" in target.read_text(encoding="utf-8")


def test_bake_defaults_creates_missing_dir(tmp_path: Path) -> None:
    nested = tmp_path / "nested" / "hotkeys"
    copied = bake_defaults(nested)
    assert nested.is_dir()
    assert len(copied) == 3


# ---------------------------------------------------------------------------
# Baked YAMLs parse cleanly
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "filename", ["default.yaml", "vim_style.yaml", "emacs_style.yaml"],
)
def test_baked_yaml_parses(filename: str) -> None:
    path = BAKED_HOTKEY_DIR / filename
    assert path.is_file(), f"missing baked preset: {path}"
    m = HotkeyMap.from_yaml(path.read_text(encoding="utf-8"))
    assert len(m) > 0


def test_baked_default_matches_notebook_bindings() -> None:
    # Baked default should include every action id from the notebook table
    # (the combos themselves may differ if we later remap defaults, but
    # the action ids stay in lockstep).
    from pharos_editor.ui.editor.notebook_hotkeys import NotebookHotkeys

    m = HotkeyMap.from_yaml(
        (BAKED_HOTKEY_DIR / "default.yaml").read_text(encoding="utf-8"),
    )
    baked_actions = {b.action_id for b in m.list_all()}
    notebook_actions = set(NotebookHotkeys.BINDINGS.values())
    missing = notebook_actions - baked_actions
    assert not missing, f"baked default missing action ids: {missing}"


def test_baked_vim_style_uses_multichord() -> None:
    m = HotkeyMap.from_yaml(
        (BAKED_HOTKEY_DIR / "vim_style.yaml").read_text(encoding="utf-8"),
    )
    # "g g" and "d d" should canonicalise with a space between chords
    assert any(" " in b.combo for b in m.list_all()), (
        "vim_style preset should include at least one multi-chord binding"
    )


def test_baked_emacs_style_has_ctrl_x_prefix_chords() -> None:
    m = HotkeyMap.from_yaml(
        (BAKED_HOTKEY_DIR / "emacs_style.yaml").read_text(encoding="utf-8"),
    )
    # C-x C-s save
    assert m.resolve("ctrl+x ctrl+s") == "editor.save"
    assert m.resolve("ctrl+x ctrl+f") == "editor.open"


# ---------------------------------------------------------------------------
# default_hotkey_map + apply_remap end-to-end
# ---------------------------------------------------------------------------


def test_default_hotkey_map_populated() -> None:
    m = default_hotkey_map()
    assert m.resolve("ctrl+s") == "editor.save"
    assert m.resolve("ctrl+z") == "editor.undo"
    # Every default binding carries source="default"
    for b in m.list_all():
        assert b.source == "default"


def test_apply_remap_end_to_end(tmp_path: Path) -> None:
    (tmp_path / "user.yaml").write_text(
        "ctrl+s: editor.help\n", encoding="utf-8",
    )
    defaults = default_hotkey_map()
    user = load_user_hotkeys(tmp_path)
    merged = apply_remap(defaults, user)
    # user override wins
    assert merged.resolve("ctrl+s") == "editor.help"
    # non-overridden default preserved
    assert merged.resolve("ctrl+z") == "editor.undo"


def test_full_bake_load_merge_validate_flow(tmp_path: Path) -> None:
    from pharos_editor.tool_router import REGISTRY

    # 1. Bake defaults into a fresh user dir.
    bake_defaults(tmp_path)
    # 2. Load the baked default preset only (drop the style presets so
    #    we don't validate style action_ids we don't own here).
    (tmp_path / "vim_style.yaml").unlink()
    (tmp_path / "emacs_style.yaml").unlink()
    loaded = load_user_hotkeys(tmp_path)
    # 3. Merge over the code-side default map.
    defaults = default_hotkey_map()
    merged = apply_remap(defaults, loaded)
    # 4. Every merged action_id resolves against the real registry.
    unknown = merged.validate(REGISTRY)
    assert unknown == [], f"unknown action ids after merge: {unknown}"


# ---------------------------------------------------------------------------
# HotkeyRemapWatcher — construction only (no watchdog dependency)
# ---------------------------------------------------------------------------


def test_watcher_construction(tmp_path: Path) -> None:
    calls: list[HotkeyMap] = []

    def _cb(m: HotkeyMap) -> None:
        calls.append(m)

    w = HotkeyRemapWatcher(_cb, user_dir=tmp_path)
    assert w.is_running() is False
    w.stop()  # no-op before start


def test_watcher_bad_callback_raises(tmp_path: Path) -> None:
    with pytest.raises(TypeError):
        HotkeyRemapWatcher("not-callable", user_dir=tmp_path)  # type: ignore[arg-type]
