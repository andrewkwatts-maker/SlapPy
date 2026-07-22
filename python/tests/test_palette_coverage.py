"""Palette-coverage guard for :data:`PhysicsRenderer.DEFAULT_PALETTE`.

The renderer falls back to medium-grey ``(128, 128, 128)`` for any material
name it can't find in the palette, which used to mean materials like
``snow``, ``concrete``, ``magma`` etc. rendered as featureless grey blobs
in the visual-drop tests.  These tests ensure that every variant of
:class:`pharos_engine.deform_modes.MaterialPreset` has an explicit palette
entry, that the entries are well-formed RGB tuples, and that no two
materials look indistinguishable on screen.
"""
from __future__ import annotations

from itertools import combinations

import pytest

from pharos_engine.deform_modes import MaterialPreset
from pharos_engine.physics.render import DEFAULT_PALETTE


# ``CUSTOM`` is the user-overrides preset and intentionally has no fixed
# look — palette entries for it would be misleading.  Everything else
# must be covered.
_SKIP_PRESETS = {MaterialPreset.CUSTOM}

_COVERED_PRESETS = [p for p in MaterialPreset if p not in _SKIP_PRESETS]


@pytest.mark.parametrize("preset", _COVERED_PRESETS, ids=lambda p: p.value)
def test_every_material_preset_has_palette_entry(preset: MaterialPreset) -> None:
    """Every non-``CUSTOM`` MaterialPreset must have a DEFAULT_PALETTE entry."""
    assert preset.value in DEFAULT_PALETTE, (
        f"MaterialPreset.{preset.name} (value={preset.value!r}) has no "
        f"DEFAULT_PALETTE entry — it will render as the grey fallback."
    )


def test_palette_values_are_valid_rgb_tuples() -> None:
    """Each palette value must be a 3-tuple of ints in [0, 255]."""
    for name, value in DEFAULT_PALETTE.items():
        assert isinstance(value, tuple), f"{name!r} palette value is not a tuple: {value!r}"
        assert len(value) == 3, f"{name!r} palette value is not length-3: {value!r}"
        for i, ch in enumerate(value):
            assert isinstance(ch, int), (
                f"{name!r} channel {i} is not an int: {ch!r} ({type(ch).__name__})"
            )
            assert 0 <= ch <= 255, f"{name!r} channel {i} out of range: {ch}"


def test_distinct_palette_colours() -> None:
    """Any two material colours must differ by at least 10 channels total.

    Prevents accidentally giving two materials nearly-identical palette
    entries (which would make them indistinguishable in the renderer).
    """
    too_close: list[tuple[str, str, int]] = []
    for (name_a, rgb_a), (name_b, rgb_b) in combinations(DEFAULT_PALETTE.items(), 2):
        diff = sum(abs(int(a) - int(b)) for a, b in zip(rgb_a, rgb_b))
        if diff < 10:
            too_close.append((name_a, name_b, diff))
    assert not too_close, (
        "Palette entries too visually similar (channel-sum diff < 10): "
        + ", ".join(f"{a}~{b} (diff={d})" for a, b, d in too_close)
    )
