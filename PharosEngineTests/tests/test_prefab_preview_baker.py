"""Sprint BB6 — regression suite for :mod:`pharos_engine.prefabs.preview_baker`.

Covers the :class:`PreviewBaker` end-to-end:

* Every body kind produces a 64x64 RGBA PNG.
* Bakes are deterministic (byte-identical on repeat).
* :meth:`bake_all_previews` writes one PNG per registered prefab.
* :meth:`load_preview` returns ``None`` for unknown names + falls back
  to on-demand bake when a *library* is passed.
* The colour palette is applied deterministically from the prefab name.
* Composite prefabs render without crashing even when they reference
  unknown children.

Pure Python + Pillow only — no GPU / world-boot required.
"""
from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image

from pharos_engine.prefabs import Prefab, PrefabLibrary
from pharos_engine.prefabs.preview_baker import (
    DIARY_PALETTE,
    PreviewBaker,
    iter_baked_previews,
    png_bytes,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


ALL_KINDS: tuple[str, ...] = (
    "point",
    "circle",
    "box",
    "rope",
    "ragdoll",
    "chain",
    "composite",
)


@pytest.fixture
def library() -> PrefabLibrary:
    lib = PrefabLibrary()
    lib.load_baked()
    return lib


@pytest.fixture
def baker() -> PreviewBaker:
    return PreviewBaker()


def _prefab_for_kind(kind: str) -> Prefab:
    """Return a minimal Prefab for each supported body kind."""
    if kind == "ragdoll":
        return Prefab(
            name=f"tp_{kind}",
            category="characters",
            body_spec={
                "kind": "ragdoll",
                "bones": [
                    {"parent_idx": -1, "length": 0.6, "mass": 1.0},
                    {"parent_idx": 0, "length": 0.5, "mass": 1.0},
                ],
            },
        )
    return Prefab(
        name=f"tp_{kind}",
        category="props",
        body_spec={"kind": kind},
    )


# ---------------------------------------------------------------------------
# 1. Every kind produces a 64x64 PNG
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ALL_KINDS)
def test_bake_every_kind_is_64x64(baker: PreviewBaker, kind: str) -> None:
    img = baker.bake_preview(_prefab_for_kind(kind))
    assert img.size == (64, 64)


@pytest.mark.parametrize("kind", ALL_KINDS)
def test_bake_every_kind_is_rgba_png(baker: PreviewBaker, kind: str) -> None:
    img = baker.bake_preview(_prefab_for_kind(kind))
    assert img.mode == "RGBA"
    raw = png_bytes(img)
    # PNG magic byte header — proves the payload actually encodes.
    assert raw.startswith(b"\x89PNG\r\n\x1a\n")


def test_bake_custom_size(baker: PreviewBaker) -> None:
    img = baker.bake_preview(_prefab_for_kind("box"), size=32)
    assert img.size == (32, 32)


def test_bake_reject_too_small(baker: PreviewBaker) -> None:
    with pytest.raises(ValueError):
        baker.bake_preview(_prefab_for_kind("box"), size=4)


def test_bake_reject_non_prefab(baker: PreviewBaker) -> None:
    with pytest.raises(TypeError):
        baker.bake_preview("crate", size=64)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 2. Deterministic
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ALL_KINDS)
def test_bake_is_deterministic(baker: PreviewBaker, kind: str) -> None:
    prefab = _prefab_for_kind(kind)
    a = png_bytes(baker.bake_preview(prefab))
    b = png_bytes(baker.bake_preview(prefab))
    assert a == b


def test_bake_is_deterministic_across_instances() -> None:
    prefab = _prefab_for_kind("rope")
    a = png_bytes(PreviewBaker().bake_preview(prefab))
    b = png_bytes(PreviewBaker().bake_preview(prefab))
    assert a == b


# ---------------------------------------------------------------------------
# 3. bake_all_previews writes one file per registered prefab
# ---------------------------------------------------------------------------


def test_bake_all_previews_writes_6_files(
    baker: PreviewBaker,
    library: PrefabLibrary,
    tmp_path: Path,
) -> None:
    written = baker.bake_all_previews(library, tmp_path)
    assert len(written) == 6
    # Names match the shipping palette.
    assert {p.stem for p in written} == {
        "ball", "bridge", "chain", "crate", "ragdoll", "windmill",
    }
    for path in written:
        assert path.exists()
        assert path.stat().st_size > 0


def test_bake_all_creates_missing_dir(
    baker: PreviewBaker,
    library: PrefabLibrary,
    tmp_path: Path,
) -> None:
    target = tmp_path / "nested" / "does" / "not" / "exist"
    written = baker.bake_all_previews(library, target)
    assert target.is_dir()
    assert len(written) == 6


def test_bake_all_rejects_non_library(
    baker: PreviewBaker,
    tmp_path: Path,
) -> None:
    with pytest.raises(TypeError):
        baker.bake_all_previews({}, tmp_path)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 4. load_preview behaviour
# ---------------------------------------------------------------------------


def test_load_preview_unknown_returns_none(baker: PreviewBaker, tmp_path: Path) -> None:
    assert baker.load_preview("no_such_prefab", tmp_path) is None


def test_load_preview_reads_baked_file(
    baker: PreviewBaker,
    library: PrefabLibrary,
    tmp_path: Path,
) -> None:
    baker.bake_all_previews(library, tmp_path)
    img = baker.load_preview("crate", tmp_path)
    assert img is not None
    assert img.size == (64, 64)


def test_load_preview_falls_back_to_ondemand(
    baker: PreviewBaker,
    library: PrefabLibrary,
    tmp_path: Path,
) -> None:
    # Empty baked_dir + library fallback should succeed.
    img = baker.load_preview("crate", tmp_path, library=library)
    assert img is not None
    assert img.size == (64, 64)


def test_load_preview_empty_name_returns_none(baker: PreviewBaker) -> None:
    assert baker.load_preview("") is None


# ---------------------------------------------------------------------------
# 5. Colour palette applied
# ---------------------------------------------------------------------------


def test_palette_has_8_entries() -> None:
    assert len(DIARY_PALETTE) == 8
    for rgb in DIARY_PALETTE:
        assert len(rgb) == 3
        for c in rgb:
            assert 0 <= c <= 255


def test_palette_colour_shows_up_in_render(baker: PreviewBaker) -> None:
    """The prefab's palette-slot colour must appear in the rendered image."""
    # Every prefab produces a deterministic slot, so we just render a
    # circle prefab (large fill area) and confirm the mapped colour is a
    # pixel in the output.
    from pharos_engine.prefabs.preview_baker import _hash_slot

    prefab = _prefab_for_kind("circle")
    slot = _hash_slot(prefab.name)
    expected = DIARY_PALETTE[slot]

    img = baker.bake_preview(prefab).convert("RGB")
    pixels = {img.getpixel((x, y)) for x in range(img.width) for y in range(img.height)}
    assert expected in pixels


def test_hash_slot_is_stable() -> None:
    from pharos_engine.prefabs.preview_baker import _hash_slot

    assert _hash_slot("crate") == _hash_slot("crate")
    assert 0 <= _hash_slot("crate") < 8


# ---------------------------------------------------------------------------
# 6. Composite prefab safety
# ---------------------------------------------------------------------------


def test_composite_bakes_without_library(baker: PreviewBaker) -> None:
    """Composite fallback (no library) still renders a 64x64 icon."""
    prefab = Prefab(
        name="lone_composite",
        category="structural",
        body_spec={"kind": "composite"},
    )
    img = baker.bake_preview(prefab)
    assert img.size == (64, 64)


def test_composite_bakes_with_children(
    baker: PreviewBaker, library: PrefabLibrary,
) -> None:
    """Windmill composite (has children spec but resolves via nodes) still bakes."""
    prefab = library.get("windmill")
    assert prefab is not None
    img = baker.bake_preview(prefab, library=library)
    assert img.size == (64, 64)


def test_composite_unknown_child_does_not_crash(baker: PreviewBaker) -> None:
    """A composite with dangling child_prefabs must not raise."""
    lib = PrefabLibrary()
    lib.register(
        Prefab(
            name="parent",
            category="structural",
            body_spec={"kind": "composite"},
            child_prefabs=["never_registered"],
        )
    )
    prefab = lib.get("parent")
    assert prefab is not None
    img = baker.bake_preview(prefab, library=lib)
    assert img.size == (64, 64)


def test_composite_recursion_bounded(baker: PreviewBaker) -> None:
    """Cyclic composite must not blow the stack — depth is capped internally."""
    lib = PrefabLibrary()
    lib.register(
        Prefab(
            name="cyclic_a",
            category="structural",
            body_spec={"kind": "composite"},
            child_prefabs=["cyclic_b"],
        )
    )
    lib.register(
        Prefab(
            name="cyclic_b",
            category="structural",
            body_spec={"kind": "composite"},
            child_prefabs=["cyclic_a"],
        )
    )
    img = baker.bake_preview(lib.get("cyclic_a"), library=lib)
    assert img.size == (64, 64)


# ---------------------------------------------------------------------------
# 7. Baked previews shipped inside the wheel
# ---------------------------------------------------------------------------


def test_baked_previews_dir_ships_6_pngs() -> None:
    paths = list(iter_baked_previews())
    assert len(paths) == 6
    names = {p.stem for p in paths}
    assert names == {
        "ball", "bridge", "chain", "crate", "ragdoll", "windmill",
    }


def test_baked_preview_files_are_valid_pngs() -> None:
    for path in iter_baked_previews():
        with Image.open(path) as img:
            assert img.size == (64, 64)
            assert img.mode in ("RGBA", "RGB", "P")


def test_baked_matches_fresh_bake(
    baker: PreviewBaker, library: PrefabLibrary, tmp_path: Path,
) -> None:
    """The shipped PNGs must match a fresh bake (deterministic guarantee)."""
    fresh = baker.bake_all_previews(library, tmp_path)
    for path in fresh:
        shipped = PreviewBaker.BAKED_DIR / path.name
        if not shipped.exists():
            continue
        # Compare PNG payload bytes.
        assert path.read_bytes() == shipped.read_bytes(), (
            f"Fresh bake of {path.name} differs from shipped PNG"
        )


# ---------------------------------------------------------------------------
# 8. png_bytes helper
# ---------------------------------------------------------------------------


def test_png_bytes_returns_png(baker: PreviewBaker) -> None:
    img = baker.bake_preview(_prefab_for_kind("box"))
    raw = png_bytes(img)
    assert raw.startswith(b"\x89PNG\r\n\x1a\n")
    # Round-trip.
    reopened = Image.open(io.BytesIO(raw))
    assert reopened.size == (64, 64)


def test_png_bytes_is_deterministic(baker: PreviewBaker) -> None:
    img = baker.bake_preview(_prefab_for_kind("chain"))
    assert png_bytes(img) == png_bytes(img)
