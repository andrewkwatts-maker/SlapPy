"""Phase D step 4 regression — top-level lazy-map must not pull in doomed modules.

The six Phase-D-doomed symbols (``MaterialPreset``, ``CrackMode``,
``SimFrequencyBudget``, ``SimState``, ``DeformController``, ``ZoneMap``)
used to route through ``slappyengine.deform_modes`` /
``slappyengine.deform_controller`` / ``slappyengine.deform_zones`` via
the top-level ``_LAZY_MAP`` in ``python/slappyengine/__init__.py``.

Phase D step 5+ deletes ``deform_modes.py`` and ``deform_controller.py``
entirely; step 6 deletes ``deform_zones.py``. The lazy-map MUST stop
importing them before those deletions can land.

This file pins the decoupling so it cannot regress:

* :func:`test_import_slappyengine_does_not_load_deform_modules` —
  ``import slappyengine`` followed by ``dir(slappyengine)`` must not
  put any of the three doomed modules into ``sys.modules``.
* :func:`test_doomed_symbols_still_resolve` — each of the six symbols
  must still be resolvable off the public surface (per the
  multi-game compat tripwire in
  ``tests/test_game_compat_tripwire.py``).
* :func:`test_resolved_symbols_route_through_compat_not_legacy` — after
  the six symbols have been accessed, the legacy module names must
  STILL be absent from ``sys.modules`` (proving the lazy-map routes
  through ``slappyengine._compat`` and not through the doomed
  modules).
* :func:`test_zone_map_aliases_zone_manager` — the ``ZoneMap`` alias
  must resolve to ``slappyengine.zones.ZoneManager`` so legacy
  Bullet Strata code (per ``project_bullet_strata.md``) keeps working.
"""
from __future__ import annotations

import sys

import pytest


@pytest.fixture(autouse=True)
def _restore_slappyengine_modules():
    """Snapshot ``sys.modules`` for ``slappyengine.*`` and restore on teardown.

    Every test in this file calls :func:`_purge_modules` to force a clean
    re-import of ``slappyengine``. Without restoring the originals,
    downstream tests that captured class identities at module-import time
    (e.g. ``from slappyengine.dynamics import JointSpec``) end up holding
    pre-purge classes while the engine's internal validators look up the
    *new* post-purge classes via lazy import — producing confusing
    ``isinstance`` failures like ``"must be a JointSpec; got JointSpec"``.

    The known victims that captured this regression were
    ``tests/test_studio_dynamics_stage.py`` (4 tests) and
    ``tests/visual/test_vis_ragdoll.py`` (1 test).
    """
    saved = {
        name: mod
        for name, mod in sys.modules.items()
        if name == "slappyengine" or name.startswith("slappyengine.")
    }
    try:
        yield
    finally:
        # Drop anything we created during the test, then restore the
        # originals so class identities survive across the test boundary.
        current = [
            name for name in sys.modules
            if name == "slappyengine" or name.startswith("slappyengine.")
        ]
        for name in current:
            del sys.modules[name]
        sys.modules.update(saved)


# Names of the legacy modules that MUST NOT be auto-imported by
# ``import slappyengine`` or by ``dir(slappyengine)``. Phase D step 5+
# deletes these modules outright; once that lands, leaving them in
# the lazy-map would hard-break ``import slappyengine``.
_DOOMED_MODULES: tuple[str, ...] = (
    "slappyengine.deform_modes",
    "slappyengine.deform_controller",
    "slappyengine.deform_zones",
)


# The six public symbols that previously routed through one of the
# doomed modules. Listed here as a single source of truth so a future
# editor of ``__init__._LAZY_MAP`` can quickly verify which names must
# survive the lazy-map decoupling.
_DOOMED_SYMBOLS: tuple[str, ...] = (
    "MaterialPreset",
    "CrackMode",
    "SimFrequencyBudget",
    "SimState",
    "DeformController",
    "ZoneMap",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _purge_modules(prefix: str) -> None:
    """Drop every cached submodule under *prefix* from ``sys.modules``.

    Each test below needs a clean import to assert the on-import
    behaviour; without this purge a sibling test that already
    triggered ``slappyengine.deform_modes`` would falsely indicate a
    leak here.
    """
    doomed = [m for m in sys.modules if m == prefix or m.startswith(prefix + ".")]
    for m in doomed:
        del sys.modules[m]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_import_slappyengine_does_not_load_deform_modules() -> None:
    """``import slappyengine`` + ``dir()`` must not import the doomed modules.

    PEP 562 lazy resolution is only invoked on attribute access, so
    ``import slappyengine; dir(slappyengine)`` should leave
    ``sys.modules`` clean of every name in :data:`_DOOMED_MODULES`.
    """
    _purge_modules("slappyengine")
    import slappyengine  # noqa: F401  (import-only side-effect test)

    # ``dir()`` must not trigger lazy resolution either.
    _ = dir(slappyengine)

    for mod in _DOOMED_MODULES:
        assert mod not in sys.modules, (
            f"import slappyengine pulled {mod} into sys.modules — the "
            f"Phase D step 4 lazy-map decoupling has regressed. The "
            f"_LAZY_MAP in slappyengine/__init__.py must route the six "
            f"Phase-D-doomed symbols through slappyengine._compat (or "
            f"slappyengine.zones for ZoneMap) — never through "
            f"deform_modes / deform_controller / deform_zones."
        )


@pytest.mark.parametrize("name", _DOOMED_SYMBOLS)
def test_doomed_symbols_still_resolve(name: str) -> None:
    """Each of the six symbols must still resolve off ``slappyengine``.

    The multi-game compat tripwire
    (``tests/test_game_compat_tripwire.py``) treats these as required
    surface for Bullet Strata + Ochema Circuit. Phase D step 4 only
    decouples the *route* — the symbols themselves stay public.
    """
    _purge_modules("slappyengine")
    import slappyengine

    assert hasattr(slappyengine, name), (
        f"slappyengine.{name} no longer resolves — Phase D step 4 must "
        f"PRESERVE the public surface, only re-home the route. The "
        f"symbol should live in slappyengine._compat (or "
        f"slappyengine.zones.ZoneManager for ZoneMap)."
    )

    # Attribute access must not raise (verifies the lazy module loads
    # cleanly and the symbol is bound on it).
    resolved = getattr(slappyengine, name)
    assert resolved is not None


def test_resolved_symbols_route_through_compat_not_legacy() -> None:
    """After resolving every symbol, the doomed modules must still be absent.

    This is the strongest form of the decoupling assertion: even when
    a consumer touches all six names, the lazy-map must route through
    ``slappyengine._compat`` (or ``slappyengine.zones``), never through
    ``deform_modes`` / ``deform_controller`` / ``deform_zones``.
    """
    _purge_modules("slappyengine")
    import slappyengine

    for name in _DOOMED_SYMBOLS:
        getattr(slappyengine, name)

    for mod in _DOOMED_MODULES:
        assert mod not in sys.modules, (
            f"Resolving the Phase-D-doomed symbols pulled {mod} into "
            f"sys.modules. The lazy-map is still routing through the "
            f"legacy module; repoint to slappyengine._compat (or "
            f"slappyengine.zones for ZoneMap)."
        )


def test_zone_map_aliases_zone_manager() -> None:
    """``slappyengine.ZoneMap is slappyengine.zones.ZoneManager``.

    The migration matrix in
    ``docs/phase_d_strip_plan_2026_05_31.md`` §(b) repoints ZoneMap
    onto the canonical ZoneManager so Bullet Strata's per-sprite
    damage zones (head/torso/legs on DroneEnemy) keep working without
    code changes. Pin the alias so a future repoint that breaks the
    identity will fail this test.
    """
    _purge_modules("slappyengine")
    import slappyengine
    from slappyengine.zones import ZoneManager

    assert slappyengine.ZoneMap is ZoneManager, (
        "slappyengine.ZoneMap must be an alias for "
        "slappyengine.zones.ZoneManager — the migration matrix in "
        "the Phase D plan documents this as the *one* doomed symbol "
        "with a real replacement (vs the five retired-feature stubs)."
    )
