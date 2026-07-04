"""AA1 STUB-triage tests — fourth round of feature-map wiring.

Covers the five new action ids added by the 2026-07-05 AA1 sprint tick
(``docs/engine_feature_map_2026_07_04.md`` §"AA1 STUB-triage patch"):

* ``edit.cut_selection`` — snapshot into the clipboard + delete
  originals from the scene.
* ``edit.delete_selection`` — remove selected entities from the scene
  without touching the clipboard.
* ``view.center_on_selection`` — pan the viewport camera to the centroid
  of the selected entities' positions.
* ``view.frame_all`` — pan + zoom to encompass every entity in the
  active scene.
* ``tool.pan`` — activate the pan navigation tool by writing
  ``shell._active_tool = "pan"``.

Every test dispatches through :class:`~slappyengine.tool_router.ToolRouter`
so the wire-up (``action_id`` → Python fallback) is exercised end-to-end.
No DPG context is required — everything routes through ``SimpleNamespace``
mocks so the suite is headless.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from slappyengine.tool_router import (
    REGISTRY,
    ToolRouter,
    register_default_actions,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def router() -> ToolRouter:
    """A router seeded with the canonical action registry."""
    r = ToolRouter()
    register_default_actions(r)
    return r


@pytest.fixture(autouse=True)
def _reset_clipboard() -> None:
    """Drop the process-wide EntityClipboard between tests."""
    from slappyengine.ui.editor.entity_clipboard import (
        reset_active_clipboard,
    )
    reset_active_clipboard()


class _FakeEntity:
    """Minimal entity stand-in with ``position`` + ``z_height``."""

    def __init__(
        self,
        name: str = "e",
        position: tuple[float, float] = (0.0, 0.0),
        z_height: float = 0.0,
    ) -> None:
        self.name = name
        self.position = position
        self.z_height = z_height


class _FakeScene:
    """Minimal scene stand-in matching :class:`slappyengine.scene.Scene`.

    Only implements the surfaces the AA1 actions poke: ``entities()``
    (as either a list attr or a method), ``remove_entity``, and the
    ``_entities`` dict fallback.
    """

    def __init__(self, entities: list[Any] | None = None) -> None:
        # Store as a dict so ``_list_scene_entities`` walks the same
        # code path as :class:`Scene`.
        self._entities: dict[str, Any] = {}
        for i, ent in enumerate(entities or []):
            self._entities[f"eid_{i}"] = ent

    def entities(self) -> list[Any]:
        return list(self._entities.values())

    def remove_entity(self, entity: Any) -> None:
        for eid, ent in list(self._entities.items()):
            if ent is entity:
                del self._entities[eid]
                return
        raise KeyError(entity)


def _make_camera(
    distance: float = 5.0,
    target: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> Any:
    """Return a bare 3D camera object with ``_cam_target`` + ``_cam_distance``."""
    return SimpleNamespace(
        _cam_distance=distance,
        _cam_target=list(target),
    )


# ---------------------------------------------------------------------------
# 1. Every AA1 action is registered on the router + module REGISTRY
# ---------------------------------------------------------------------------


def test_cut_selection_registered(router: ToolRouter) -> None:
    assert router.has_action("edit.cut_selection")


def test_delete_selection_registered(router: ToolRouter) -> None:
    assert router.has_action("edit.delete_selection")


def test_center_on_selection_registered(router: ToolRouter) -> None:
    assert router.has_action("view.center_on_selection")


def test_frame_all_registered(router: ToolRouter) -> None:
    assert router.has_action("view.frame_all")


def test_pan_tool_registered(router: ToolRouter) -> None:
    assert router.has_action("tool.pan")


def test_module_registry_has_aa1_actions() -> None:
    """The default REGISTRY must expose the new AA1 action ids."""
    ids = {a.action_id for a in REGISTRY.list_actions()}
    for aid in (
        "edit.cut_selection",
        "edit.delete_selection",
        "view.center_on_selection",
        "view.frame_all",
        "tool.pan",
    ):
        assert aid in ids, f"{aid} missing from module-level REGISTRY"


def test_aa1_actions_have_expected_categories() -> None:
    """Ensure the new ids landed in the right category buckets."""
    lookup = {a.action_id: a for a in REGISTRY.list_actions()}
    assert lookup["edit.cut_selection"].category == "edit"
    assert lookup["edit.delete_selection"].category == "edit"
    assert lookup["view.center_on_selection"].category == "view"
    assert lookup["view.frame_all"].category == "view"
    assert lookup["tool.pan"].category == "tool"


def test_aa1_actions_have_python_fallbacks() -> None:
    """None of the AA1 actions should be declared-but-not-implemented."""
    lookup = {a.action_id: a for a in REGISTRY.list_actions()}
    for aid in (
        "edit.cut_selection",
        "edit.delete_selection",
        "view.center_on_selection",
        "view.frame_all",
        "tool.pan",
    ):
        assert lookup[aid].python_fallback is not None, (
            f"{aid} has no python_fallback"
        )


# ---------------------------------------------------------------------------
# 2. edit.cut_selection — clipboard + scene removal
# ---------------------------------------------------------------------------


def test_cut_selection_empty_returns_status(router: ToolRouter) -> None:
    """No selection => ``{"status": "no_selection"}``."""
    result = router.dispatch("edit.cut_selection", {})
    assert result == {"status": "no_selection"}


def test_cut_selection_stashes_and_removes(router: ToolRouter) -> None:
    """Cut copies to the clipboard + removes the originals from the scene."""
    e1 = _FakeEntity(name="a")
    e2 = _FakeEntity(name="b")
    scene = _FakeScene([e1, e2])
    shell = SimpleNamespace(
        _engine=SimpleNamespace(scene=scene),
        _selected_entities=[e1, e2],
        _selected_entity=e1,
    )
    result = router.dispatch("edit.cut_selection", {"shell": shell})
    assert result["status"] == "cut"
    assert result["count"] == 2
    assert result["removed"] == 2
    # Originals gone from scene.
    assert e1 not in scene.entities()
    assert e2 not in scene.entities()
    # Selection cleared.
    assert shell._selected_entity is None
    assert shell._selected_entities == []


def test_cut_selection_marks_clipboard_action_cut(router: ToolRouter) -> None:
    """The clipboard's ``last_action`` reads ``"cut"`` after the router call."""
    from slappyengine.ui.editor.entity_clipboard import get_active_clipboard
    e = _FakeEntity(name="cut_me")
    router.dispatch(
        "edit.cut_selection", {"selection": [e]},
    )
    clipboard = get_active_clipboard()
    assert clipboard.last_action == "cut"
    assert len(clipboard) == 1


def test_cut_selection_headless_no_scene(router: ToolRouter) -> None:
    """Without a scene the cut still snapshots + returns removed=0."""
    e = _FakeEntity(name="lonely")
    result = router.dispatch(
        "edit.cut_selection", {"selection": [e]},
    )
    assert result["status"] == "cut"
    assert result["count"] == 1
    assert result["removed"] == 0


# ---------------------------------------------------------------------------
# 3. edit.delete_selection — remove without clipboard
# ---------------------------------------------------------------------------


def test_delete_selection_empty_returns_status(router: ToolRouter) -> None:
    result = router.dispatch("edit.delete_selection", {})
    assert result == {"status": "no_selection"}


def test_delete_selection_removes_from_scene(router: ToolRouter) -> None:
    e1 = _FakeEntity(name="a")
    e2 = _FakeEntity(name="b")
    scene = _FakeScene([e1, e2])
    result = router.dispatch(
        "edit.delete_selection", {"scene": scene, "selection": [e1, e2]},
    )
    assert result["status"] == "deleted"
    assert result["count"] == 2
    assert result["requested"] == 2
    assert scene.entities() == []


def test_delete_selection_no_scene_returns_status(router: ToolRouter) -> None:
    """A selection but no scene => ``{"status": "no_scene"}``."""
    e = _FakeEntity()
    result = router.dispatch(
        "edit.delete_selection", {"selection": [e]},
    )
    assert result["status"] == "no_scene"
    assert result["requested"] == 1


def test_delete_selection_does_not_touch_clipboard(router: ToolRouter) -> None:
    """Delete must not stash anything on the clipboard."""
    from slappyengine.ui.editor.entity_clipboard import get_active_clipboard
    e = _FakeEntity(name="gone")
    scene = _FakeScene([e])
    router.dispatch(
        "edit.delete_selection", {"scene": scene, "selection": [e]},
    )
    clipboard = get_active_clipboard()
    assert clipboard.is_empty()


def test_delete_selection_clears_shell_slots(router: ToolRouter) -> None:
    e = _FakeEntity(name="a")
    scene = _FakeScene([e])
    shell = SimpleNamespace(
        _engine=SimpleNamespace(scene=scene),
        _selected_entity=e,
        _selected_entities=[e],
    )
    router.dispatch("edit.delete_selection", {"shell": shell})
    assert shell._selected_entity is None
    assert shell._selected_entities == []


# ---------------------------------------------------------------------------
# 4. view.center_on_selection — pan camera to centroid
# ---------------------------------------------------------------------------


def test_center_on_selection_no_camera_returns_status(
    router: ToolRouter,
) -> None:
    result = router.dispatch("view.center_on_selection", {})
    assert result == {"status": "no_camera"}


def test_center_on_selection_no_selection_returns_status(
    router: ToolRouter,
) -> None:
    camera = _make_camera()
    result = router.dispatch(
        "view.center_on_selection", {"camera": camera},
    )
    assert result == {"status": "no_selection"}


def test_center_on_selection_pans_to_centroid(router: ToolRouter) -> None:
    """Camera target ends up at the mean of the selection positions."""
    camera = _make_camera(target=(0.0, 0.0, 0.0))
    e1 = _FakeEntity(position=(2.0, 4.0), z_height=1.0)
    e2 = _FakeEntity(position=(4.0, 8.0), z_height=3.0)
    result = router.dispatch(
        "view.center_on_selection",
        {"camera": camera, "selection": [e1, e2]},
    )
    assert result["status"] == "centered"
    assert result["target"] == [3.0, 6.0, 2.0]
    assert result["count"] == 2
    assert camera._cam_target == [3.0, 6.0, 2.0]


def test_center_on_selection_distance_untouched(router: ToolRouter) -> None:
    """Center-on-selection only pans — ``_cam_distance`` is left alone."""
    camera = _make_camera(distance=17.3)
    e = _FakeEntity(position=(1.0, 1.0))
    router.dispatch(
        "view.center_on_selection",
        {"camera": camera, "selection": [e]},
    )
    assert camera._cam_distance == 17.3


# ---------------------------------------------------------------------------
# 5. view.frame_all — pan + zoom to fit every entity
# ---------------------------------------------------------------------------


def test_frame_all_no_camera_returns_status(router: ToolRouter) -> None:
    result = router.dispatch("view.frame_all", {})
    assert result == {"status": "no_camera"}


def test_frame_all_empty_scene_returns_status(router: ToolRouter) -> None:
    camera = _make_camera()
    scene = _FakeScene([])
    result = router.dispatch(
        "view.frame_all", {"camera": camera, "scene": scene},
    )
    assert result == {"status": "empty_scene"}


def test_frame_all_positions_target_at_aabb_centre(
    router: ToolRouter,
) -> None:
    """Centroid = midpoint of AABB spans."""
    camera = _make_camera()
    entities = [
        _FakeEntity(position=(-4.0, -2.0), z_height=-1.0),
        _FakeEntity(position=(4.0, 2.0), z_height=1.0),
    ]
    result = router.dispatch(
        "view.frame_all", {"camera": camera, "entities": entities},
    )
    assert result["status"] == "framed"
    assert result["target"] == [0.0, 0.0, 0.0]
    assert result["count"] == 2
    assert camera._cam_target == [0.0, 0.0, 0.0]


def test_frame_all_writes_distance_from_radius(router: ToolRouter) -> None:
    """Distance grows with the AABB diagonal."""
    camera = _make_camera(distance=1.0)
    entities = [
        _FakeEntity(position=(-6.0, -8.0), z_height=0.0),
        _FakeEntity(position=(6.0, 8.0), z_height=0.0),
    ]
    result = router.dispatch(
        "view.frame_all", {"camera": camera, "entities": entities},
    )
    # Radius = 0.5 * sqrt(12^2 + 16^2 + 0) = 0.5 * 20 = 10.
    # Distance = 10 * 2 * 1.15 = 23.
    assert result["radius"] == pytest.approx(10.0, rel=1e-6)
    assert result["distance"] == pytest.approx(23.0, rel=1e-6)
    assert camera._cam_distance == pytest.approx(23.0, rel=1e-6)


def test_frame_all_single_entity_uses_min_distance(
    router: ToolRouter,
) -> None:
    """A single-point scene keeps a sane minimum distance."""
    camera = _make_camera(distance=100.0)
    entities = [_FakeEntity(position=(0.0, 0.0))]
    result = router.dispatch(
        "view.frame_all", {"camera": camera, "entities": entities},
    )
    assert result["distance"] == pytest.approx(5.0, rel=1e-6)
    assert camera._cam_distance == pytest.approx(5.0, rel=1e-6)


def test_frame_all_reads_from_scene(router: ToolRouter) -> None:
    """When no ``entities`` override is passed, the scene is enumerated."""
    camera = _make_camera()
    e1 = _FakeEntity(position=(2.0, 2.0))
    e2 = _FakeEntity(position=(-2.0, -2.0))
    scene = _FakeScene([e1, e2])
    result = router.dispatch(
        "view.frame_all", {"camera": camera, "scene": scene},
    )
    assert result["status"] == "framed"
    assert result["target"] == [0.0, 0.0, 0.0]


# ---------------------------------------------------------------------------
# 6. tool.pan — activate pan navigation tool
# ---------------------------------------------------------------------------


def test_pan_tool_headless(router: ToolRouter) -> None:
    """No shell => fallback path but still status=activated."""
    result = router.dispatch("tool.pan", {})
    assert result == {
        "status": "activated",
        "tool": "pan",
        "path": "fallback",
    }


def test_pan_tool_sets_shell_active_tool(router: ToolRouter) -> None:
    """When a shell is present ``_active_tool`` becomes ``"pan"``."""
    shell = SimpleNamespace(_active_tool="select")
    result = router.dispatch("tool.pan", {"shell": shell})
    assert result["status"] == "activated"
    assert result["tool"] == "pan"
    assert result["path"] == "shell"
    assert shell._active_tool == "pan"


def test_pan_tool_notifies_status_bar(router: ToolRouter) -> None:
    """The notebook status bar's ``set_active_tool`` is invoked."""
    calls: list[str] = []

    class _StatusBar:
        def set_active_tool(self, tool_id: str) -> None:
            calls.append(tool_id)

    shell = SimpleNamespace(
        _active_tool="select",
        _notebook_status_bar=_StatusBar(),
    )
    router.dispatch("tool.pan", {"shell": shell})
    assert calls == ["pan"]


def test_pan_tool_notifies_engine(router: ToolRouter) -> None:
    """When engine exposes ``set_active_tool`` it also gets called."""
    engine_calls: list[str] = []

    class _Engine:
        def set_active_tool(self, tool_id: str) -> None:
            engine_calls.append(tool_id)

    shell = SimpleNamespace(_active_tool="", _engine=_Engine())
    router.dispatch("tool.pan", {"shell": shell})
    assert engine_calls == ["pan"]


# ---------------------------------------------------------------------------
# 7. Direct-import smoke tests — bypass ToolRouter
# ---------------------------------------------------------------------------


def test_direct_import_cut_and_delete() -> None:
    """Every new helper is importable from ``slappyengine.actions``."""
    from slappyengine.actions import cut_selection, delete_selection
    assert callable(cut_selection)
    assert callable(delete_selection)
    # No-op smoke — empty ctx returns the expected status dict.
    assert cut_selection({}) == {"status": "no_selection"}
    assert delete_selection({}) == {"status": "no_selection"}


def test_direct_import_framing_actions() -> None:
    from slappyengine.actions import center_on_selection, frame_all
    assert center_on_selection({}) == {"status": "no_camera"}
    assert frame_all({}) == {"status": "no_camera"}


def test_direct_import_pan_tool() -> None:
    from slappyengine.actions import PAN_TOOL_ID, activate_pan_tool
    assert PAN_TOOL_ID == "pan"
    result = activate_pan_tool({})
    assert result["tool"] == "pan"
