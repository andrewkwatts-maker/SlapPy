"""Declarative event -> creature animation bindings.

The table in this module is the **only** place that knows the engine's
event-name vocabulary. The adapter (:mod:`bus_adapter`) reads from it;
the scheduler (sibling U3 module) never touches it directly. This keeps
:class:`~pharos_editor.ui.theme.creatures.bus_adapter.CreatureBusAdapter`
the single integration seam.

Each entry maps one engine-published event type to a list of
``(creature_id, anim_name)`` pairs to trigger. Multiple pairs let a
single event light up several creatures (e.g. a successful build wakes
both the bee and the acorn confetti shower).

The keys are sourced verbatim from
``docs/idle_animation_system_2026_06_03.md`` §2 "Event bindings".
Adding or removing an entry here is the supported way to extend the
roster — no code in :mod:`bus_adapter` needs to change.
"""
from __future__ import annotations

# Mapping: engine event type -> list of (creature_id, anim_name) pairs.
# Keys correspond 1:1 to the table in
# ``docs/idle_animation_system_2026_06_03.md`` §2.
EVENT_TO_CREATURE_ANIMS: dict[str, list[tuple[str, str]]] = {
    "engine.save": [("butterfly_01", "flutter")],
    "engine.build_success": [
        ("bee_01", "dive"),
        ("acorn_01", "confetti"),
    ],
    "engine.build_failure": [("owl_01", "hoot")],
    "engine.error": [
        ("owl_01", "hoot"),
        ("porcupine_01", "ball_up"),
    ],
    "engine.scene_loaded": [("deer_01", "peek_in")],
    "engine.scene_closed": [("deer_01", "peek_out")],
    "engine.test_pass": [("acorn_01", "drop")],
    "engine.idle_60s": [("fox_01", "stretch")],
    "engine.idle_120s": [("frog_01", "hop")],
    "engine.first_run": [
        ("rabbit_01", "spawn"),
        ("butterfly_01", "flutter"),
    ],
    "engine.progress_start": [("rabbit_01", "run")],
    "engine.progress_end": [("rabbit_01", "sit")],
    "engine.loading_start": [("snail_01", "crawl")],
    "engine.loading_cancel": [("snail_01", "hide")],
    "ui.scene_outliner.select_root": [("flower_01", "bloom")],
    "ui.code_mode.bookmark_add": [("pinecone_01", "drop")],
    "ui.click_on_mushroom_decoration": [("mushroom_01", "spore_puff")],
}


__all__ = ["EVENT_TO_CREATURE_ANIMS"]
