"""Sprint CC4 — baked editor-layout preset regression suite.

Covers :class:`pharos_engine.ui.editor.layout_baker.LayoutBaker`
end-to-end:

* ``bake_defaults`` copies every baked file into the user dir
  idempotently and preserves user edits.
* Each shipping preset round-trips through YAML -> ``EditorLayout``.
* The user overlay wins over the baked file when both exist.
* :meth:`is_edited` correctly reports byte-level divergence.
* :meth:`revert` restores the baked bytes over the user file.
* Missing baked files raise :class:`LayoutBakerError`.
* :meth:`LayoutPersistence.load_baked_preset` delegates through the
  baker and returns a valid :class:`EditorLayout`.

Pure-Python / PyYAML — no GPU required.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from pharos_engine.ui.editor.layout_baker import (
    BakerResult,
    LayoutBaker,
    LayoutBakerError,
)
from pharos_engine.ui.editor.layout_persistence import (
    EditorLayout,
    LayoutPersistence,
    PanelLayoutState,
    SCHEMA_VERSION,
)


SHIPPING_PRESETS: tuple[str, ...] = (
    "debugging",
    "default",
    "focus_mode",
    "presentation",
    "triple_pane",
    "wide_code",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def baker(tmp_path: Path) -> LayoutBaker:
    """Return a :class:`LayoutBaker` pointed at a per-test user dir.

    Uses the *real* shipping baked directory so the round-trip tests
    exercise the actual on-disk YAML this sprint ships.
    """
    return LayoutBaker(user_dir=tmp_path / "layouts")


@pytest.fixture
def isolated_baker(tmp_path: Path) -> LayoutBaker:
    """A :class:`LayoutBaker` with both user + baked dirs in a temp tree.

    Used by revert / missing-file tests that need to mutate the baked
    directory without touching the shipping YAML.
    """
    baked_dir = tmp_path / "baked_layouts"
    user_dir = tmp_path / "layouts"
    baked_dir.mkdir(parents=True)
    # Seed one hand-authored preset in the baked dir.
    (baked_dir / "custom.layout.yaml").write_text(
        _minimal_layout_yaml(), encoding="utf-8",
    )
    return LayoutBaker(user_dir=user_dir, baked_dir=baked_dir)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _minimal_layout_yaml() -> str:
    return (
        "schema_version: 1\n"
        "theme: teengirl_notebook\n"
        "viewport_size: [1280, 800]\n"
        "panels:\n"
        "  notebook_toolbar:\n"
        "    position: [0, 24]\n"
        "    size: [1280, 56]\n"
        "    visible: true\n"
        "    z_order: 0\n"
        "    docked_to: top\n"
    )


# ---------------------------------------------------------------------------
# bake_defaults
# ---------------------------------------------------------------------------


def test_bake_defaults_copies_all_shipping_presets(baker: LayoutBaker) -> None:
    result = baker.bake_defaults()
    assert isinstance(result, BakerResult)
    assert result.user_dir == baker.user_dir
    assert set(result.baked_names) == set(SHIPPING_PRESETS)
    assert set(baker.list_user()) == set(SHIPPING_PRESETS)
    # Every path in `written` really exists on disk.
    for path in result.written:
        assert path.is_file()


def test_bake_defaults_idempotent(baker: LayoutBaker) -> None:
    first = baker.bake_defaults()
    second = baker.bake_defaults()
    # Second call must be a pure skip: every preset already present.
    assert second.written == []
    assert set(second.skipped) == set(SHIPPING_PRESETS)
    # The user dir is unchanged between runs.
    assert set(baker.list_user()) == set(first.baked_names)


def test_bake_defaults_preserves_user_edits(baker: LayoutBaker) -> None:
    baker.bake_defaults()
    target = baker.user_dir / "default.layout.yaml"
    hand_edit = "# user hand-edit\n" + target.read_text(encoding="utf-8")
    target.write_text(hand_edit, encoding="utf-8")
    baker.bake_defaults()
    assert target.read_text(encoding="utf-8") == hand_edit


def test_bake_defaults_one_off_target_override(
    baker: LayoutBaker, tmp_path: Path,
) -> None:
    override = tmp_path / "somewhere_else"
    result = baker.bake_defaults(user_dir=override)
    assert result.user_dir == override
    # Instance dir was NOT mutated.
    assert baker.user_dir != override
    assert set(p.name for p in override.iterdir()) == {
        f"{n}.layout.yaml" for n in SHIPPING_PRESETS
    }


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------


def test_list_baked_matches_shipping(baker: LayoutBaker) -> None:
    assert baker.list_baked() == list(SHIPPING_PRESETS)


def test_list_user_empty_before_bake(baker: LayoutBaker) -> None:
    assert baker.list_user() == []


def test_list_user_after_bake(baker: LayoutBaker) -> None:
    baker.bake_defaults()
    assert baker.list_user() == list(SHIPPING_PRESETS)


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", SHIPPING_PRESETS)
def test_load_returns_editor_layout(baker: LayoutBaker, name: str) -> None:
    layout = baker.load(name)
    assert isinstance(layout, EditorLayout)
    assert layout.schema_version == SCHEMA_VERSION
    assert isinstance(layout.panels, dict)
    assert len(layout.panels) >= 1
    # Every persisted panel is a validated dataclass instance.
    for state in layout.panels.values():
        assert isinstance(state, PanelLayoutState)


@pytest.mark.parametrize("name", SHIPPING_PRESETS)
def test_shipping_preset_round_trips(baker: LayoutBaker, name: str) -> None:
    """Each ``.layout.yaml`` must survive a YAML -> dict -> EditorLayout ->
    dict round-trip without dropping any panel keys.
    """
    baked_path = baker.baked_dir / f"{name}.layout.yaml"
    text = baked_path.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    assert isinstance(data, dict)
    # Strip optional meta before feeding EditorLayout.from_dict.
    data.pop("meta", None)
    layout = EditorLayout.from_dict(data)
    out = layout.to_dict()
    assert set(out["panels"].keys()) == set(data["panels"].keys())
    assert out["theme"] == data["theme"]
    assert out["viewport_size"] == list(data["viewport_size"])


def test_load_missing_preset_raises(baker: LayoutBaker) -> None:
    with pytest.raises(LayoutBakerError):
        baker.load("does_not_exist")


def test_load_user_wins_over_baked(baker: LayoutBaker) -> None:
    baker.bake_defaults()
    user_path = baker.user_dir / "default.layout.yaml"
    # Rewrite the user file with a distinct theme so we can tell them apart.
    edited = _minimal_layout_yaml().replace(
        "teengirl_notebook", "user_override_theme",
    )
    user_path.write_text(edited, encoding="utf-8")
    layout = baker.load("default")
    assert layout.theme == "user_override_theme"


def test_load_falls_back_to_baked_when_user_absent(baker: LayoutBaker) -> None:
    # Do NOT run bake_defaults — user dir stays empty.
    layout = baker.load("default")
    assert layout.theme == "teengirl_notebook"


def test_load_corrupt_yaml_raises(
    isolated_baker: LayoutBaker,
) -> None:
    (isolated_baker.baked_dir / "broken.layout.yaml").write_text(
        "schema_version: 1\npanels: [not a mapping\n", encoding="utf-8",
    )
    with pytest.raises(LayoutBakerError):
        isolated_baker.load("broken")


def test_load_wrong_schema_raises(
    isolated_baker: LayoutBaker,
) -> None:
    (isolated_baker.baked_dir / "future.layout.yaml").write_text(
        "schema_version: 99\ntheme: t\nviewport_size: [800, 600]\npanels: {}\n",
        encoding="utf-8",
    )
    with pytest.raises(LayoutBakerError):
        isolated_baker.load("future")


# ---------------------------------------------------------------------------
# is_edited / revert
# ---------------------------------------------------------------------------


def test_is_edited_false_when_user_missing(baker: LayoutBaker) -> None:
    # Bake NOT called; user file does not exist.
    assert baker.is_edited("default") is False


def test_is_edited_false_after_bake(baker: LayoutBaker) -> None:
    baker.bake_defaults()
    for name in SHIPPING_PRESETS:
        assert baker.is_edited(name) is False, name


def test_is_edited_true_after_user_change(baker: LayoutBaker) -> None:
    baker.bake_defaults()
    target = baker.user_dir / "default.layout.yaml"
    target.write_text(
        target.read_text(encoding="utf-8") + "# tweak\n", encoding="utf-8",
    )
    assert baker.is_edited("default") is True
    # Other presets remain untouched.
    assert baker.is_edited("triple_pane") is False


def test_revert_restores_baked_bytes(baker: LayoutBaker) -> None:
    baker.bake_defaults()
    target = baker.user_dir / "default.layout.yaml"
    baked = baker.baked_dir / "default.layout.yaml"
    target.write_text("# clobbered\n", encoding="utf-8")
    assert baker.is_edited("default") is True
    baker.revert("default")
    assert baker.is_edited("default") is False
    assert target.read_bytes() == baked.read_bytes()


def test_revert_missing_baked_raises(baker: LayoutBaker) -> None:
    with pytest.raises(LayoutBakerError):
        baker.revert("no_such_preset")


# ---------------------------------------------------------------------------
# Meta hints (focus_mode / presentation)
# ---------------------------------------------------------------------------


def test_focus_mode_carries_font_bump_meta(baker: LayoutBaker) -> None:
    layout = baker.load("focus_mode")
    meta = getattr(layout, "meta", {})
    assert isinstance(meta, dict)
    assert meta.get("font_size_bump") == pytest.approx(1.2)


def test_presentation_carries_status_bar_meta(baker: LayoutBaker) -> None:
    layout = baker.load("presentation")
    meta = getattr(layout, "meta", {})
    assert isinstance(meta, dict)
    assert meta.get("status_bar_size") == "large"


# ---------------------------------------------------------------------------
# Preset-specific structural expectations
# ---------------------------------------------------------------------------


def test_focus_mode_hides_content_browser(baker: LayoutBaker) -> None:
    layout = baker.load("focus_mode")
    cb = layout.panels.get("notebook_content_browser")
    assert cb is not None
    assert cb.visible is False


def test_debugging_layout_shows_message_log(baker: LayoutBaker) -> None:
    layout = baker.load("debugging")
    log = layout.panels.get("notebook_message_log")
    assert log is not None
    assert log.visible is True


def test_presentation_hides_toolbar(baker: LayoutBaker) -> None:
    layout = baker.load("presentation")
    tb = layout.panels.get("notebook_toolbar")
    assert tb is not None
    assert tb.visible is False


def test_default_matches_default_layout_constant(baker: LayoutBaker) -> None:
    from pharos_engine.ui.editor.default_layouts import DEFAULT_LAYOUT
    layout = baker.load("default")
    assert layout.theme == DEFAULT_LAYOUT.theme
    assert layout.viewport_size == DEFAULT_LAYOUT.viewport_size
    assert set(layout.panels.keys()) == set(DEFAULT_LAYOUT.panels.keys())
    for pid, state in DEFAULT_LAYOUT.panels.items():
        loaded = layout.panels[pid]
        assert loaded.position == state.position
        assert loaded.size == state.size
        assert loaded.visible == state.visible


# ---------------------------------------------------------------------------
# LayoutPersistence.load_baked_preset delegation
# ---------------------------------------------------------------------------


def test_load_baked_preset_returns_layout() -> None:
    layout = LayoutPersistence.load_baked_preset("default")
    assert isinstance(layout, EditorLayout)
    assert "notebook_toolbar" in layout.panels


def test_load_baked_preset_missing_raises() -> None:
    with pytest.raises(LayoutBakerError):
        LayoutPersistence.load_baked_preset("obviously_not_a_preset")


@pytest.mark.parametrize("name", SHIPPING_PRESETS)
def test_load_baked_preset_covers_every_shipping_preset(name: str) -> None:
    layout = LayoutPersistence.load_baked_preset(name)
    assert isinstance(layout, EditorLayout)
    assert layout.schema_version == SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Validation guards
# ---------------------------------------------------------------------------


def test_baker_rejects_empty_name(baker: LayoutBaker) -> None:
    with pytest.raises((TypeError, ValueError)):
        baker.load("")


def test_baker_paths_are_public(baker: LayoutBaker) -> None:
    # ``user_dir`` and ``baked_dir`` are public accessors — the shell
    # uses them to surface a "Reveal in Finder" action.
    assert isinstance(baker.user_dir, Path)
    assert isinstance(baker.baked_dir, Path)


def test_suffix_constant_matches_baked_files(baker: LayoutBaker) -> None:
    # If somebody renames SUFFIX the baked YAMLs stop being discovered;
    # lock the invariant so the regression triggers here first.
    assert LayoutBaker.SUFFIX == ".layout.yaml"
    for path in baker.baked_dir.iterdir():
        if path.is_file():
            assert path.name.endswith(LayoutBaker.SUFFIX)
