"""Tests for ``pharos_editor.ui.editor.layout_persistence``.

The persistence layer is Dear PyGui-free and operates exclusively on
plain Python objects, so every test in this module runs headlessly
without standing up a viewport. ``EditorShell`` integration is
exercised against a lightweight fake shell so we don't need the editor
extra installed for these tests to pass.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

# Hard-dependency guard — yaml is optional in some thin install matrices.
try:
    import yaml  # noqa: F401
except Exception as exc:  # pragma: no cover - exotic install matrix
    pytest.skip(f"yaml not importable: {exc}", allow_module_level=True)

from pharos_editor.ui.editor.layout_persistence import (
    EditorLayout,
    LayoutPersistence,
    PanelLayoutState,
    SCHEMA_VERSION,
    VALID_DOCK_SIDES,
)
from pharos_editor.ui.editor.default_layouts import (
    DEFAULT_LAYOUT,
    PRESET_LAYOUTS,
    TRIPLE_PANE_LAYOUT,
    WIDE_CODE_LAYOUT,
)


# ---------------------------------------------------------------------------
# Lightweight fakes — keep tests independent of the editor extra
# ---------------------------------------------------------------------------


class FakePanel:
    """Minimal stand-in for a notebook panel handle.

    Implements the four optional setter / getter pairs the persistence
    layer probes so we can capture round-tripped state without DPG.
    """

    def __init__(
        self,
        position: tuple[int, int] = (0, 0),
        size: tuple[int, int] = (200, 200),
        visible: bool = True,
        z_order: int = 0,
    ) -> None:
        self._position = position
        self._size = size
        self._visible = visible
        self._z_order = z_order

    # Getters surfaced via attribute (the persistence layer also tries
    # ``get_position`` etc., so we expose both flavours).
    @property
    def position(self) -> tuple[int, int]:
        return self._position

    @property
    def size(self) -> tuple[int, int]:
        return self._size

    @property
    def visible(self) -> bool:
        return self._visible

    @property
    def z_order(self) -> int:
        return self._z_order

    def set_position(self, position: tuple[int, int]) -> None:
        self._position = (int(position[0]), int(position[1]))

    def set_size(self, size: tuple[int, int]) -> None:
        self._size = (int(size[0]), int(size[1]))

    def set_visible(self, visible: bool) -> None:
        self._visible = bool(visible)

    def set_z_order(self, z_order: int) -> None:
        self._z_order = int(z_order)


@dataclass
class FakeUISettings:
    default_theme: str = "teengirl_notebook"


@dataclass
class FakeShell:
    """Replacement for ``EditorShell`` covering the persistence surface."""

    _width: int = 1280
    _height: int = 800
    _ui_settings: FakeUISettings = field(default_factory=FakeUISettings)
    _toolbar: FakePanel | None = None
    _scene_outliner: FakePanel | None = None
    _inspector: FakePanel | None = None
    _content_browser: FakePanel | None = None
    _code_mode_panel: FakePanel | None = None
    _theme_switcher_panel: FakePanel | None = None

    @classmethod
    def fully_populated(cls) -> "FakeShell":
        return cls(
            _toolbar=FakePanel(position=(0, 24), size=(1280, 56)),
            _scene_outliner=FakePanel(position=(0, 80), size=(260, 480)),
            _inspector=FakePanel(position=(1020, 80), size=(260, 480)),
            _content_browser=FakePanel(position=(0, 560), size=(1280, 200)),
            _code_mode_panel=FakePanel(
                position=(300, 100), size=(640, 400), visible=False,
            ),
            _theme_switcher_panel=FakePanel(
                position=(280, 200), size=(280, 360), visible=False,
            ),
        )


# ===========================================================================
# 1. PanelLayoutState dataclass — construction + validation
# ===========================================================================


class TestPanelLayoutState:

    # 1
    def test_construct_minimal(self) -> None:
        s = PanelLayoutState(
            panel_id="p", position=(10, 20), size=(100, 50),
        )
        assert s.panel_id == "p"
        assert s.position == (10, 20)
        assert s.size == (100, 50)
        assert s.visible is True
        assert s.z_order == 0
        assert s.docked_to == ""

    # 2
    def test_construct_full(self) -> None:
        s = PanelLayoutState(
            panel_id="p",
            position=(0, 0),
            size=(50, 50),
            visible=False,
            z_order=3,
            docked_to="left",
        )
        assert s.visible is False
        assert s.z_order == 3
        assert s.docked_to == "left"

    # 3
    def test_empty_panel_id_raises(self) -> None:
        with pytest.raises(ValueError):
            PanelLayoutState(panel_id="", position=(0, 0), size=(10, 10))

    # 4
    def test_invalid_dock_side_raises(self) -> None:
        with pytest.raises(ValueError):
            PanelLayoutState(
                panel_id="p", position=(0, 0), size=(10, 10),
                docked_to="diagonal",
            )

    # 5
    def test_zero_size_raises(self) -> None:
        with pytest.raises(ValueError):
            PanelLayoutState(
                panel_id="p", position=(0, 0), size=(0, 10),
            )

    # 6
    def test_round_trip_dict(self) -> None:
        s = PanelLayoutState(
            panel_id="p", position=(1, 2), size=(3, 4),
            visible=False, z_order=2, docked_to="top",
        )
        body = s.to_dict()
        restored = PanelLayoutState.from_dict("p", body)
        assert restored == s


# ===========================================================================
# 2. EditorLayout dataclass — construction + dict round-trip
# ===========================================================================


class TestEditorLayout:

    # 7
    def test_default_layout_validates(self) -> None:
        layout = EditorLayout()
        assert layout.schema_version == SCHEMA_VERSION
        assert layout.panels == {}

    # 8
    def test_panels_dict_round_trip(self) -> None:
        layout = EditorLayout(
            panels={
                "a": PanelLayoutState(
                    panel_id="a", position=(0, 0), size=(10, 10),
                ),
            },
        )
        body = layout.to_dict()
        restored = EditorLayout.from_dict(body)
        assert "a" in restored.panels
        assert restored.panels["a"].size == (10, 10)

    # 9
    def test_panels_dict_accepts_dict_member(self) -> None:
        # Allows raw dict-style construction (e.g. from YAML).
        layout = EditorLayout(
            panels={"a": {"position": [1, 2], "size": [3, 4]}},
        )
        assert isinstance(layout.panels["a"], PanelLayoutState)

    # 10
    def test_invalid_panels_type_raises(self) -> None:
        with pytest.raises(TypeError):
            EditorLayout(panels=["not a dict"])  # type: ignore[arg-type]


# ===========================================================================
# 3. LayoutPersistence — file operations
# ===========================================================================


class TestLayoutPersistenceFileOps:

    # 11
    def test_get_file_path_with_project(self, tmp_path: Path) -> None:
        lp = LayoutPersistence(tmp_path)
        assert lp.get_file_path() == tmp_path / ".slappy" / "layout.yaml"

    # 12
    def test_get_file_path_no_project_falls_back_to_home(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        lp = LayoutPersistence(None)
        assert lp.get_file_path() == (
            tmp_path / ".pharos_engine" / "default_layout.yaml"
        )

    # 13
    def test_save_and_load_round_trip(self, tmp_path: Path) -> None:
        lp = LayoutPersistence(tmp_path)
        original = EditorLayout(
            theme="moody_violet",
            viewport_size=(1024, 768),
            panels={
                "notebook_outliner": PanelLayoutState(
                    panel_id="notebook_outliner",
                    position=(5, 6), size=(200, 300),
                    visible=False, z_order=2, docked_to="left",
                ),
            },
        )
        lp.save(original)
        restored = lp.load()
        assert restored is not None
        assert restored.theme == "moody_violet"
        assert restored.viewport_size == (1024, 768)
        assert restored.panels["notebook_outliner"].position == (5, 6)
        assert restored.panels["notebook_outliner"].visible is False
        assert restored.panels["notebook_outliner"].docked_to == "left"

    # 14
    def test_load_missing_file_returns_none(self, tmp_path: Path) -> None:
        lp = LayoutPersistence(tmp_path)
        assert lp.load() is None

    # 15
    def test_schema_mismatch_returns_none(self, tmp_path: Path) -> None:
        lp = LayoutPersistence(tmp_path)
        path = lp.get_file_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "schema_version: 9999\ntheme: x\nviewport_size: [10, 10]\n"
            "panels: {}\n",
            encoding="utf-8",
        )
        assert lp.load() is None

    # 16
    def test_malformed_yaml_returns_none(self, tmp_path: Path) -> None:
        lp = LayoutPersistence(tmp_path)
        path = lp.get_file_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not: valid: yaml", encoding="utf-8")
        assert lp.load() is None

    # 17
    def test_reset_deletes_file(self, tmp_path: Path) -> None:
        lp = LayoutPersistence(tmp_path)
        lp.save(EditorLayout())
        assert lp.get_file_path().is_file()
        lp.reset()
        assert not lp.get_file_path().is_file()

    # 18
    def test_reset_when_missing_does_not_raise(self, tmp_path: Path) -> None:
        lp = LayoutPersistence(tmp_path)
        lp.reset()  # should be a no-op

    # 19
    def test_save_rejects_non_layout(self, tmp_path: Path) -> None:
        lp = LayoutPersistence(tmp_path)
        with pytest.raises(TypeError):
            lp.save({"not": "a layout"})  # type: ignore[arg-type]


# ===========================================================================
# 4. Shell integration — snapshot / apply
# ===========================================================================


class TestShellIntegration:

    # 20
    def test_snapshot_from_shell_captures_positions(self) -> None:
        shell = FakeShell.fully_populated()
        lp = LayoutPersistence(None)
        layout = lp.snapshot_from_shell(shell)
        # All six canonical panels are present.
        assert set(layout.panels) == {
            "notebook_toolbar",
            "notebook_outliner",
            "notebook_inspector",
            "notebook_content_browser",
            "notebook_code_panel",
            "theme_switcher_panel",
        }
        assert layout.panels["notebook_outliner"].position == (0, 80)
        assert layout.panels["notebook_outliner"].size == (260, 480)

    # 21
    def test_snapshot_uses_default_when_panel_missing(self) -> None:
        shell = FakeShell()  # no panels at all
        lp = LayoutPersistence(None)
        layout = lp.snapshot_from_shell(shell)
        assert layout.panels["notebook_toolbar"].size == (1280, 56)

    # 22
    def test_apply_to_shell_sets_position_size_visible(self) -> None:
        shell = FakeShell.fully_populated()
        # Build a custom layout that differs from defaults.
        layout = EditorLayout(
            panels={
                "notebook_outliner": PanelLayoutState(
                    panel_id="notebook_outliner",
                    position=(11, 22), size=(33, 44),
                    visible=False, z_order=5, docked_to="left",
                ),
            },
        )
        lp = LayoutPersistence(None)
        lp.apply_to_shell(shell, layout)
        assert shell._scene_outliner is not None
        assert shell._scene_outliner.position == (11, 22)
        assert shell._scene_outliner.size == (33, 44)
        assert shell._scene_outliner.visible is False
        assert shell._scene_outliner.z_order == 5

    # 23
    def test_apply_to_shell_records_layout_on_shell(self) -> None:
        shell = FakeShell.fully_populated()
        lp = LayoutPersistence(None)
        lp.apply_to_shell(shell, DEFAULT_LAYOUT)
        assert getattr(shell, "_layout_state", None) is DEFAULT_LAYOUT

    # 24
    def test_apply_to_shell_pushes_theme_to_settings(self) -> None:
        shell = FakeShell.fully_populated()
        layout = EditorLayout(theme="moody_violet")
        lp = LayoutPersistence(None)
        lp.apply_to_shell(shell, layout)
        assert shell._ui_settings.default_theme == "moody_violet"

    # 25
    def test_apply_to_shell_rejects_non_layout(self) -> None:
        shell = FakeShell()
        lp = LayoutPersistence(None)
        with pytest.raises(TypeError):
            lp.apply_to_shell(shell, "not a layout")  # type: ignore[arg-type]

    # 26
    def test_snapshot_then_apply_round_trip(self, tmp_path: Path) -> None:
        shell = FakeShell.fully_populated()
        # Move the outliner to a non-default position.
        shell._scene_outliner.set_position((77, 88))
        shell._scene_outliner.set_size((123, 456))
        lp = LayoutPersistence(tmp_path)
        captured = lp.snapshot_from_shell(shell)
        lp.save(captured)

        # Fresh shell, reload from disk, apply, verify.
        shell2 = FakeShell.fully_populated()
        loaded = lp.load()
        assert loaded is not None
        lp.apply_to_shell(shell2, loaded)
        assert shell2._scene_outliner.position == (77, 88)
        assert shell2._scene_outliner.size == (123, 456)


# ===========================================================================
# 5. Default layout presets
# ===========================================================================


class TestDefaultLayouts:

    # 27
    def test_default_layout_has_all_six_main_panels(self) -> None:
        expected = {
            "notebook_toolbar",
            "notebook_outliner",
            "notebook_inspector",
            "notebook_content_browser",
            "notebook_code_panel",
            "theme_switcher_panel",
        }
        assert set(DEFAULT_LAYOUT.panels) == expected

    # 28
    def test_three_preset_layouts_register(self) -> None:
        assert set(PRESET_LAYOUTS) == {"default", "wide_code", "triple_pane"}

    # 29
    def test_all_presets_validate_without_error(self) -> None:
        # The dataclass __post_init__ runs at module import; ensure
        # iterating through each preset still produces valid panels.
        for name, preset in PRESET_LAYOUTS.items():
            assert isinstance(preset, EditorLayout), name
            for pid, state in preset.panels.items():
                assert state.panel_id == pid
                assert state.docked_to in VALID_DOCK_SIDES

    # 30
    def test_wide_code_layout_shows_code_panel(self) -> None:
        assert WIDE_CODE_LAYOUT.panels["notebook_code_panel"].visible is True

    # 31
    def test_triple_pane_hides_content_browser(self) -> None:
        assert (
            TRIPLE_PANE_LAYOUT.panels["notebook_content_browser"].visible
            is False
        )

    # 32
    def test_default_layout_round_trips_through_yaml(
        self, tmp_path: Path,
    ) -> None:
        lp = LayoutPersistence(tmp_path)
        lp.save(DEFAULT_LAYOUT)
        loaded = lp.load()
        assert loaded is not None
        assert set(loaded.panels) == set(DEFAULT_LAYOUT.panels)
        for pid, state in DEFAULT_LAYOUT.panels.items():
            assert loaded.panels[pid].position == state.position
            assert loaded.panels[pid].size == state.size
            assert loaded.panels[pid].visible == state.visible
            assert loaded.panels[pid].docked_to == state.docked_to
