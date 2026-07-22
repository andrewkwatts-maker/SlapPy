"""pharos_editor.ui.editor.deform_panel — REMOVED.

This editor panel was decommissioned in Phase D step 6 (2026-06-01).

The panel inspected ``DeformableLayerComponent`` settings exposed by the
legacy ``deform_modes`` / ``deform_controller`` / ``deform_crack`` /
``deform_repair`` modules. All four are retired surface — the per-pixel
deformation state machine they represented is gone in the rebuild solver,
replaced by ``softbody.solver`` beam-break events and the unified
``dynamics.World`` step cadence.

The per-import migration audit at
``docs/phase_d_strip_plan_2026_05_31.md`` §"Step 5 prerequisite audit"
found that 14 of 16 ``deform_modes`` imports in this panel mapped to
retired features whose UI dies with the panel; only ``list_materials``
(softbody.material.MATERIALS / fluid.material.MATERIALS keys) and
``MaterialPreset`` / ``get_material`` had real replacement paths, and
those are already shimmed via ``pharos_engine._compat``.

The replacement for both ``DeformPanel`` and ``ZoneEditorPanel`` is the
property inspector wired against ``softbody.Body`` and
``pharos_engine.zones``, tracked under the editor sprint
(``project_editor_sprint.md``).

Importing this module now raises ``ImportError`` to signal the removal
to any surviving caller.
"""
raise ImportError(
    "pharos_editor.ui.editor.deform_panel was decommissioned in Phase D "
    "step 6 (2026-06-01). Both DeformPanel and ZoneEditorPanel are retired "
    "surface — their replacement is the property inspector at "
    "pharos_editor.ui.editor.property_inspector wired against softbody.Body "
    "and pharos_engine.zones. See docs/phase_d_strip_plan_2026_05_31.md "
    "§'Step 5 prerequisite audit' for the migration table."
)
