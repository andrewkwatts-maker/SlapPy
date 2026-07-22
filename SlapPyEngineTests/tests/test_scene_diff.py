"""Tests for ``pharos_engine.scenes.scene_diff`` (sprint GG6).

Covers:

* Empty A + entities in B → all added.
* Entities in A + empty B → all removed.
* Same id, changed position → modified with field_deltas.
* Layer + metadata diffs.
* pretty_print_diff contains + / - prefixes.
* apply_diff replays a → b.
* filter_by_kind subset.
* merge_diffs preserves ordering (later wins).
* Corner cases: duplicate ids, missing id, invalid types.
"""
from __future__ import annotations

import re

import pytest

from pharos_engine.scenes import Scene
from pharos_engine.scenes.scene_diff import (
    EntityDiff,
    SceneDiff,
    apply_diff,
    diff_scenes,
    filter_by_kind,
    merge_diffs,
    pretty_print_diff,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_scene(name: str, entities=None, layers=None, metadata=None) -> Scene:
    return Scene(
        name=name,
        entities=list(entities or []),
        layers=list(layers or ["default"]),
        metadata=dict(metadata or {}),
    )


def _box(eid: str, pos=(0.0, 0.0), width=1.0, height=1.0, mass=1.0) -> dict:
    return {
        "id": eid,
        "kind": "box",
        "position": list(pos),
        "params": {"width": width, "height": height, "mass": mass},
    }


def _point(eid: str, pos=(0.0, 0.0), mass=1.0) -> dict:
    return {
        "id": eid,
        "kind": "point",
        "position": list(pos),
        "params": {"mass": mass},
    }


# ---------------------------------------------------------------------------
# 1. Added / removed / modified basics
# ---------------------------------------------------------------------------


def test_empty_a_all_added() -> None:
    a = _make_scene("A")
    b = _make_scene("B", entities=[_box("b1"), _point("b2")])
    diff = diff_scenes(a, b)
    kinds = [ed.kind for ed in diff.entity_diffs]
    assert kinds == ["added", "added"]
    assert {ed.entity_id for ed in diff.entity_diffs} == {"b1", "b2"}
    assert diff.total_changes == 2


def test_empty_b_all_removed() -> None:
    a = _make_scene("A", entities=[_box("a1"), _point("a2")])
    b = _make_scene("B")
    diff = diff_scenes(a, b)
    kinds = [ed.kind for ed in diff.entity_diffs]
    assert kinds == ["removed", "removed"]
    assert {ed.entity_id for ed in diff.entity_diffs} == {"a1", "a2"}
    assert all(ed.after is None for ed in diff.entity_diffs)


def test_modified_position_records_field_delta() -> None:
    a = _make_scene("A", entities=[_box("e1", pos=(1.0, 1.0))])
    b = _make_scene("B", entities=[_box("e1", pos=(2.0, 5.0))])
    diff = diff_scenes(a, b)
    assert len(diff.entity_diffs) == 1
    ed = diff.entity_diffs[0]
    assert ed.kind == "modified"
    assert ed.entity_id == "e1"
    assert "position" in ed.field_deltas
    before, after = ed.field_deltas["position"]
    assert before == [1.0, 1.0]
    assert after == [2.0, 5.0]


def test_modified_params_flattened() -> None:
    a = _make_scene("A", entities=[_box("e1", mass=1.0)])
    b = _make_scene("B", entities=[_box("e1", mass=9.0)])
    diff = diff_scenes(a, b)
    ed = diff.entity_diffs[0]
    assert ed.kind == "modified"
    assert "params.mass" in ed.field_deltas
    assert ed.field_deltas["params.mass"] == (1.0, 9.0)


def test_no_changes_gives_empty_diff() -> None:
    a = _make_scene("A", entities=[_box("e1")])
    b = _make_scene("B", entities=[_box("e1")])
    diff = diff_scenes(a, b)
    assert diff.entity_diffs == []
    assert diff.total_changes == 0
    assert diff.is_empty()


def test_scene_names_recorded() -> None:
    a = _make_scene("intro_pit")
    b = _make_scene("intro_pit_v2")
    diff = diff_scenes(a, b)
    assert diff.scene_a_name == "intro_pit"
    assert diff.scene_b_name == "intro_pit_v2"


# ---------------------------------------------------------------------------
# 2. Layers and metadata
# ---------------------------------------------------------------------------


def test_layer_diff_added_and_removed() -> None:
    a = _make_scene("A", layers=["default", "fx"])
    b = _make_scene("B", layers=["default", "hud"])
    diff = diff_scenes(a, b)
    assert ("removed", "fx") in diff.layer_diffs
    assert ("added", "hud") in diff.layer_diffs


def test_layer_diff_empty_when_same() -> None:
    a = _make_scene("A", layers=["default", "fx"])
    b = _make_scene("B", layers=["default", "fx"])
    diff = diff_scenes(a, b)
    assert diff.layer_diffs == []


def test_metadata_added_and_removed() -> None:
    a = _make_scene("A", metadata={"author": "alice"})
    b = _make_scene("B", metadata={"desc": "boss room"})
    diff = diff_scenes(a, b)
    assert diff.metadata_diffs["author"] == ("alice", None)
    assert diff.metadata_diffs["desc"] == (None, "boss room")


def test_metadata_value_changed() -> None:
    a = _make_scene("A", metadata={"author": "alice"})
    b = _make_scene("B", metadata={"author": "bob"})
    diff = diff_scenes(a, b)
    assert diff.metadata_diffs["author"] == ("alice", "bob")


# ---------------------------------------------------------------------------
# 3. pretty_print_diff
# ---------------------------------------------------------------------------


def test_pretty_print_contains_plus_and_minus() -> None:
    a = _make_scene("A", entities=[_box("a1")])
    b = _make_scene("B", entities=[_box("a1", pos=(2.0, 2.0)), _point("b1")])
    diff = diff_scenes(a, b)
    text = pretty_print_diff(diff, colour=False)
    assert "+ entity b1" in text
    assert "-   position" in text
    assert "+   position" in text


def test_pretty_print_no_ansi_when_colour_false() -> None:
    a = _make_scene("A", entities=[_box("a1")])
    b = _make_scene("B")
    text = pretty_print_diff(diff_scenes(a, b), colour=False)
    assert "\x1b[" not in text


def test_pretty_print_uses_ansi_when_colour_true() -> None:
    a = _make_scene("A", entities=[_box("a1")])
    b = _make_scene("B", entities=[_box("a1"), _point("b1")])
    text = pretty_print_diff(diff_scenes(a, b), colour=True)
    assert "\x1b[" in text


def test_pretty_print_no_changes_reads_cleanly() -> None:
    a = _make_scene("A")
    b = _make_scene("B")
    text = pretty_print_diff(diff_scenes(a, b), colour=False)
    assert "no changes" in text


def test_pretty_print_lists_metadata_changes() -> None:
    a = _make_scene("A", metadata={"author": "alice"})
    b = _make_scene("B", metadata={"author": "bob"})
    text = pretty_print_diff(diff_scenes(a, b), colour=False)
    assert "metadata.author" in text


# ---------------------------------------------------------------------------
# 4. apply_diff replays
# ---------------------------------------------------------------------------


def test_apply_diff_reconstructs_b_entities() -> None:
    a = _make_scene("A", entities=[_box("a1"), _point("a2")])
    b = _make_scene(
        "B", entities=[_box("a1", pos=(3.0, 4.0)), _point("b_new")],
    )
    diff = diff_scenes(a, b)
    replayed = apply_diff(a, diff)
    ids = {e["id"] for e in replayed.entities}
    assert ids == {"a1", "b_new"}
    a1 = replayed.get("a1")
    assert a1 is not None and a1["position"] == [3.0, 4.0]


def test_apply_diff_does_not_mutate_input() -> None:
    a = _make_scene("A", entities=[_box("a1")])
    b = _make_scene("B", entities=[_box("a1", pos=(9.0, 9.0))])
    diff = diff_scenes(a, b)
    _ = apply_diff(a, diff)
    # a is unchanged.
    assert a.get("a1")["position"] == [0.0, 0.0]


def test_apply_diff_layers_and_metadata() -> None:
    a = _make_scene("A", layers=["default"], metadata={"k": "v0"})
    b = _make_scene("B", layers=["default", "hud"], metadata={"k": "v1"})
    diff = diff_scenes(a, b)
    replayed = apply_diff(a, diff)
    assert "hud" in replayed.layers
    assert replayed.metadata["k"] == "v1"


def test_apply_diff_removes_layer() -> None:
    a = _make_scene("A", layers=["default", "fx"])
    b = _make_scene("B", layers=["default"])
    replayed = apply_diff(a, diff_scenes(a, b))
    assert "fx" not in replayed.layers


def test_apply_diff_removes_metadata_key() -> None:
    a = _make_scene("A", metadata={"k": "v"})
    b = _make_scene("B", metadata={})
    replayed = apply_diff(a, diff_scenes(a, b))
    assert "k" not in replayed.metadata


def test_apply_diff_full_roundtrip_matches_b() -> None:
    a = _make_scene(
        "A",
        entities=[_box("keep"), _box("drop", mass=3.0)],
        layers=["default", "fx"],
        metadata={"author": "alice"},
    )
    b = _make_scene(
        "B",
        entities=[
            _box("keep", pos=(5.0, 5.0)),
            _point("brand_new"),
        ],
        layers=["default", "hud"],
        metadata={"author": "bob", "desc": "combat"},
    )
    diff = diff_scenes(a, b)
    replayed = apply_diff(a, diff)
    # Sort by id for stable comparison.
    replayed_ids = sorted(e["id"] for e in replayed.entities)
    b_ids = sorted(e["id"] for e in b.entities)
    assert replayed_ids == b_ids
    for eid in b_ids:
        assert replayed.get(eid)["position"] == b.get(eid)["position"]
        assert replayed.get(eid)["kind"] == b.get(eid)["kind"]
    assert set(replayed.layers) == set(b.layers)
    assert replayed.metadata == b.metadata


# ---------------------------------------------------------------------------
# 5. filter_by_kind
# ---------------------------------------------------------------------------


def test_filter_by_kind_added_only() -> None:
    a = _make_scene("A", entities=[_box("a1")])
    b = _make_scene(
        "B", entities=[_box("a1", pos=(1.0, 1.0)), _point("b_new")],
    )
    diff = diff_scenes(a, b)
    only_added = filter_by_kind(diff, {"added"})
    assert len(only_added.entity_diffs) == 1
    assert only_added.entity_diffs[0].kind == "added"
    assert only_added.entity_diffs[0].entity_id == "b_new"


def test_filter_by_kind_removed_only() -> None:
    a = _make_scene("A", entities=[_box("a1"), _point("a2")])
    b = _make_scene("B")
    filtered = filter_by_kind(diff_scenes(a, b), {"removed"})
    assert all(ed.kind == "removed" for ed in filtered.entity_diffs)
    assert len(filtered.entity_diffs) == 2


def test_filter_by_kind_preserves_layers_and_metadata() -> None:
    a = _make_scene("A", layers=["default"], metadata={"k": "v"})
    b = _make_scene("B", layers=["default", "fx"], metadata={"k": "v2"})
    diff = diff_scenes(a, b)
    filtered = filter_by_kind(diff, {"added"})
    assert filtered.layer_diffs == diff.layer_diffs
    assert filtered.metadata_diffs == diff.metadata_diffs


def test_filter_by_kind_unknown_kind_gives_empty() -> None:
    a = _make_scene("A", entities=[_box("a1")])
    b = _make_scene("B", entities=[_box("a1", pos=(2.0, 2.0))])
    diff = diff_scenes(a, b)
    filtered = filter_by_kind(diff, {"never"})
    assert filtered.entity_diffs == []


# ---------------------------------------------------------------------------
# 6. merge_diffs
# ---------------------------------------------------------------------------


def test_merge_diffs_single_diff_is_identity() -> None:
    a = _make_scene("A")
    b = _make_scene("B", entities=[_box("e1")])
    d1 = diff_scenes(a, b)
    merged = merge_diffs(d1)
    assert len(merged.entity_diffs) == 1
    assert merged.entity_diffs[0].entity_id == "e1"


def test_merge_diffs_later_wins_on_same_entity() -> None:
    a = _make_scene("A", entities=[_box("e1", mass=1.0)])
    b = _make_scene("B", entities=[_box("e1", mass=5.0)])
    c = _make_scene("C", entities=[_box("e1", mass=99.0)])
    d1 = diff_scenes(a, b)
    d2 = diff_scenes(b, c)
    merged = merge_diffs(d1, d2)
    ed = merged.entity_diffs[0]
    assert ed.field_deltas["params.mass"][1] == 99.0


def test_merge_diffs_preserves_span_of_names() -> None:
    a = _make_scene("A")
    b = _make_scene("B")
    c = _make_scene("C")
    merged = merge_diffs(diff_scenes(a, b), diff_scenes(b, c))
    assert merged.scene_a_name == "A"
    assert merged.scene_b_name == "C"


def test_merge_diffs_add_then_remove_lands_on_remove() -> None:
    a = _make_scene("A")
    b = _make_scene("B", entities=[_box("e1")])
    c = _make_scene("C")
    merged = merge_diffs(diff_scenes(a, b), diff_scenes(b, c))
    assert len(merged.entity_diffs) == 1
    assert merged.entity_diffs[0].kind == "removed"


def test_merge_diffs_layer_later_wins() -> None:
    a = _make_scene("A", layers=["default"])
    b = _make_scene("B", layers=["default", "fx"])
    c = _make_scene("C", layers=["default"])
    merged = merge_diffs(diff_scenes(a, b), diff_scenes(b, c))
    # b added fx; c removed it. Later wins → removed.
    ops = {name: op for op, name in merged.layer_diffs}
    assert ops.get("fx") == "removed"


def test_merge_diffs_metadata_later_wins() -> None:
    a = _make_scene("A", metadata={"k": "v0"})
    b = _make_scene("B", metadata={"k": "v1"})
    c = _make_scene("C", metadata={"k": "v2"})
    merged = merge_diffs(diff_scenes(a, b), diff_scenes(b, c))
    # earliest 'before' preserved, latest 'after' taken.
    assert merged.metadata_diffs["k"][0] == "v0"
    assert merged.metadata_diffs["k"][1] == "v2"


def test_merge_diffs_empty_raises() -> None:
    with pytest.raises(ValueError):
        merge_diffs()


# ---------------------------------------------------------------------------
# 7. Corner cases and type safety
# ---------------------------------------------------------------------------


def test_diff_scenes_wrong_type_raises() -> None:
    a = _make_scene("A")
    with pytest.raises(TypeError):
        diff_scenes(a, {"not": "a scene"})  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        diff_scenes("nope", a)  # type: ignore[arg-type]


def test_apply_diff_wrong_type_raises() -> None:
    a = _make_scene("A")
    with pytest.raises(TypeError):
        apply_diff(a, "not-a-diff")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        apply_diff("not-a-scene", SceneDiff("a", "b"))  # type: ignore[arg-type]


def test_filter_by_kind_wrong_type_raises() -> None:
    a = _make_scene("A")
    b = _make_scene("B")
    diff = diff_scenes(a, b)
    with pytest.raises(TypeError):
        filter_by_kind("nope", {"added"})  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        filter_by_kind(diff, 42)  # type: ignore[arg-type]


def test_merge_diffs_wrong_type_raises() -> None:
    with pytest.raises(TypeError):
        merge_diffs("not a diff")  # type: ignore[arg-type]


def test_pretty_print_wrong_type_raises() -> None:
    with pytest.raises(TypeError):
        pretty_print_diff({"not": "a diff"})  # type: ignore[arg-type]


def test_duplicate_ids_first_wins_when_matching() -> None:
    # Bypass validation by constructing the entity list post-hoc.
    scene_a = Scene(name="A", entities=[_box("dup", pos=(1.0, 1.0))])
    scene_a.entities.append(_box("dup", pos=(9.0, 9.0)))
    scene_b = _make_scene("B", entities=[_box("dup", pos=(2.0, 2.0))])
    diff = diff_scenes(scene_a, scene_b)
    # One entry per unique id.
    ids = [ed.entity_id for ed in diff.entity_diffs]
    assert ids.count("dup") == 1
    ed = diff.entity_diffs[0]
    # First occurrence in A was (1,1); B is (2,2). Should show that delta.
    assert ed.field_deltas["position"] == ([1.0, 1.0], [2.0, 2.0])


def test_missing_id_entities_ignored() -> None:
    # Bypass validation to inject an entity dict without an 'id'.
    scene_a = _make_scene("A", entities=[_box("valid")])
    scene_a.entities.append({"kind": "point", "position": [0.0, 0.0], "params": {}})
    scene_b = _make_scene("B", entities=[_box("valid", pos=(3.0, 3.0))])
    # Should not crash; the id-less entity is skipped.
    diff = diff_scenes(scene_a, scene_b)
    assert len(diff.entity_diffs) == 1
    assert diff.entity_diffs[0].entity_id == "valid"


def test_entity_diff_to_dict_json_safe() -> None:
    ed = EntityDiff(
        entity_id="e1",
        kind="modified",
        before={"id": "e1"},
        after={"id": "e1"},
        field_deltas={"params.mass": (1.0, 2.0)},
    )
    d = ed.to_dict()
    assert d["entity_id"] == "e1"
    assert d["field_deltas"]["params.mass"] == [1.0, 2.0]


def test_scene_diff_to_dict_json_safe() -> None:
    a = _make_scene("A", entities=[_box("e1")], layers=["default"])
    b = _make_scene(
        "B",
        entities=[_box("e1", pos=(5.0, 5.0))],
        layers=["default", "hud"],
        metadata={"k": "v"},
    )
    diff = diff_scenes(a, b)
    d = diff.to_dict()
    assert d["scene_a_name"] == "A"
    assert d["scene_b_name"] == "B"
    assert isinstance(d["entity_diffs"], list)
    assert isinstance(d["layer_diffs"], list)
    assert isinstance(d["metadata_diffs"], dict)
    assert d["total_changes"] == diff.total_changes


def test_entity_order_removed_before_added() -> None:
    a = _make_scene("A", entities=[_box("removed_one")])
    b = _make_scene("B", entities=[_point("added_one")])
    diff = diff_scenes(a, b)
    kinds = [ed.kind for ed in diff.entity_diffs]
    assert kinds == ["removed", "added"]


def test_modified_entity_preserves_before_and_after_snapshots() -> None:
    a = _make_scene("A", entities=[_box("e1", pos=(1.0, 1.0), mass=1.0)])
    b = _make_scene("B", entities=[_box("e1", pos=(2.0, 2.0), mass=2.0)])
    diff = diff_scenes(a, b)
    ed = diff.entity_diffs[0]
    assert ed.before is not None
    assert ed.after is not None
    assert ed.before["position"] == [1.0, 1.0]
    assert ed.after["position"] == [2.0, 2.0]


def test_prefab_ref_change_captured() -> None:
    a = _make_scene(
        "A",
        entities=[
            {
                "id": "e1",
                "kind": "box",
                "position": [0.0, 0.0],
                "params": {},
                "prefab_ref": "ball_a",
            }
        ],
    )
    b = _make_scene(
        "B",
        entities=[
            {
                "id": "e1",
                "kind": "box",
                "position": [0.0, 0.0],
                "params": {},
                "prefab_ref": "ball_b",
            }
        ],
    )
    diff = diff_scenes(a, b)
    ed = diff.entity_diffs[0]
    assert ed.field_deltas["prefab_ref"] == ("ball_a", "ball_b")


def test_pretty_print_shows_metadata_and_layer_sections() -> None:
    a = _make_scene("A", layers=["default"], metadata={"k": "v"})
    b = _make_scene("B", layers=["default", "fx"], metadata={"k": "v2"})
    text = pretty_print_diff(diff_scenes(a, b), colour=False)
    assert "## metadata" in text
    assert "## layers" in text
    assert "+ layer: fx" in text
