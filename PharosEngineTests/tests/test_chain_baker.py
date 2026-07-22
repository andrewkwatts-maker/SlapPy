"""Sprint Z3 — baked post-process chain preset regression suite.

Covers the :class:`pharos_engine.post_process.ChainBaker` end-to-end:

* ``bake_defaults`` copies every baked file into the user dir
  idempotently and preserves user edits.
* Each shipping preset round-trips through
  :meth:`ChainManifest.from_yaml`.
* The user overlay wins over the baked file when both exist.
* :meth:`is_edited` correctly reports byte-level divergence.
* :meth:`revert` restores the baked bytes over the user file.
* Missing baked files raise :class:`ChainBakerError`.
* The custom pass stubs register + dispatch pass-through.

Pure-Python / numpy / PyYAML — no GPU required.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from pharos_engine.post_process.chain_baker import (
    BakerResult,
    ChainBaker,
    ChainBakerError,
    _chromatic_aberration_stub,
    _grain_stub,
)
from pharos_engine.post_process.chain_manifest import (
    ChainManifest,
    PassSpec,
    _clear_custom_handlers,
    apply_manifest,
)


SHIPPING_PRESETS: tuple[str, ...] = (
    "crisp",
    "debug",
    "default",
    "dreamy",
    "neon",
    "retro_film",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_custom_handlers():
    """Wipe the custom handler table between tests so ordering is stable."""
    _clear_custom_handlers()
    yield
    _clear_custom_handlers()


@pytest.fixture
def baker(tmp_path: Path) -> ChainBaker:
    """Return a :class:`ChainBaker` pointed at a per-test user directory.

    Uses the *real* shipping baked directory so the round-trip tests
    exercise the actual on-disk YAML this sprint ships.
    """
    return ChainBaker(user_dir=tmp_path / "postprocess_chains")


@pytest.fixture
def isolated_baker(tmp_path: Path) -> ChainBaker:
    """A :class:`ChainBaker` with both user + baked dirs in a temp tree.

    Used by revert / missing-file tests that need to mutate the baked
    directory without touching the shipping YAML.
    """
    baked_dir = tmp_path / "baked_chains"
    user_dir = tmp_path / "postprocess_chains"
    baked_dir.mkdir(parents=True, exist_ok=True)
    return ChainBaker(user_dir=user_dir, baked_dir=baked_dir)


def _sample_image(h: int = 8, w: int = 8) -> np.ndarray:
    """Deterministic HDR gradient — well within numpy's float precision."""
    rng = np.random.default_rng(42)
    return rng.uniform(0.0, 1.5, size=(h, w, 3)).astype(np.float32)


# ---------------------------------------------------------------------------
# 1. Shipping YAML sanity
# ---------------------------------------------------------------------------


def test_baked_dir_exists_on_disk():
    """The shipping baked directory is present in the wheel source tree."""
    assert ChainBaker.BAKED_DIR.is_dir(), (
        f"expected baked directory at {ChainBaker.BAKED_DIR}"
    )


def test_baked_dir_ships_six_presets(baker):
    names = baker.list_baked()
    assert names == list(SHIPPING_PRESETS)


def test_every_shipping_preset_round_trips(baker):
    """Each *.chain.yaml parses cleanly through ChainManifest.from_yaml."""
    for name in SHIPPING_PRESETS:
        manifest = baker.load(name)
        assert isinstance(manifest, ChainManifest)
        # to_yaml -> from_yaml must be lossless.
        rehydrated = ChainManifest.from_yaml(manifest.to_yaml())
        assert [p.to_dict() for p in rehydrated.passes] == (
            [p.to_dict() for p in manifest.passes]
        )


def test_default_preset_matches_default_chain_shape(baker):
    manifest = baker.load("default")
    kinds = [p.kind for p in manifest.passes]
    assert kinds == ["bloom", "taa", "tonemap", "dither"]


def test_crisp_preset_has_no_bloom_or_taa(baker):
    manifest = baker.load("crisp")
    kinds = [p.kind for p in manifest.passes]
    assert kinds == ["tonemap", "dither"]


def test_dreamy_preset_heavy_bloom_and_loose_taa(baker):
    manifest = baker.load("dreamy")
    by_name = {p.name: p for p in manifest.passes}
    assert by_name["bloom"].params["mip_count"] == 8
    assert by_name["bloom"].params["strength"] == pytest.approx(0.6)
    assert by_name["taa"].params["variance_clip_gamma"] == pytest.approx(1.4)


def test_neon_preset_uses_custom_chromatic_aberration(baker):
    manifest = baker.load("neon")
    ca = next(p for p in manifest.passes if p.name == "chromatic_aberration")
    assert ca.kind == "custom"
    assert ca.params["amount"] == pytest.approx(0.005)
    assert "bloom" in ca.depends_on


def test_retro_film_preset_uses_custom_grain(baker):
    manifest = baker.load("retro_film")
    grain = next(p for p in manifest.passes if p.name == "grain")
    assert grain.kind == "custom"
    assert grain.params["intensity"] == pytest.approx(0.05)


def test_debug_preset_is_tonemap_only(baker):
    manifest = baker.load("debug")
    kinds = [p.kind for p in manifest.passes]
    assert kinds == ["tonemap"]


# ---------------------------------------------------------------------------
# 2. bake_defaults — bootstrap
# ---------------------------------------------------------------------------


def test_bake_defaults_creates_user_dir(baker):
    assert not baker.user_dir.exists()
    result = baker.bake_defaults()
    assert baker.user_dir.is_dir()
    assert isinstance(result, BakerResult)
    assert result.user_dir == baker.user_dir


def test_bake_defaults_copies_all_presets(baker):
    result = baker.bake_defaults()
    written_names = sorted(
        p.name.replace(ChainBaker.SUFFIX, "") for p in result.written
    )
    assert written_names == list(SHIPPING_PRESETS)
    assert result.skipped == []
    assert result.baked_names == list(SHIPPING_PRESETS)


def test_bake_defaults_is_idempotent(baker):
    first = baker.bake_defaults()
    second = baker.bake_defaults()
    assert len(first.written) == len(SHIPPING_PRESETS)
    assert second.written == []
    assert sorted(second.skipped) == list(SHIPPING_PRESETS)


def test_bake_defaults_preserves_user_edits(baker):
    baker.bake_defaults()
    user_path = baker.user_dir / f"default{ChainBaker.SUFFIX}"
    user_path.write_text("passes: []\n", encoding="utf-8")
    # Second bake must NOT overwrite the hand-edited file.
    baker.bake_defaults()
    assert user_path.read_text(encoding="utf-8") == "passes: []\n"


def test_bake_defaults_repairs_missing_files(baker):
    baker.bake_defaults()
    # Simulate a user deleting one preset — the next bake should re-copy it.
    (baker.user_dir / f"crisp{ChainBaker.SUFFIX}").unlink()
    result = baker.bake_defaults()
    written_names = [p.name.replace(ChainBaker.SUFFIX, "") for p in result.written]
    assert written_names == ["crisp"]


def test_bake_defaults_accepts_override_user_dir(tmp_path, baker):
    override = tmp_path / "somewhere_else"
    result = baker.bake_defaults(user_dir=override)
    assert result.user_dir == override
    assert override.is_dir()
    # Instance user_dir must not have been mutated.
    assert baker.user_dir != override


# ---------------------------------------------------------------------------
# 3. Listing
# ---------------------------------------------------------------------------


def test_list_user_empty_before_bake(baker):
    assert baker.list_user() == []


def test_list_user_after_bake(baker):
    baker.bake_defaults()
    assert baker.list_user() == list(SHIPPING_PRESETS)


def test_list_user_and_list_baked_are_sorted(baker):
    baker.bake_defaults()
    assert baker.list_baked() == sorted(baker.list_baked())
    assert baker.list_user() == sorted(baker.list_user())


# ---------------------------------------------------------------------------
# 4. Overlay + edit detection
# ---------------------------------------------------------------------------


def test_user_overlay_wins_over_baked(baker):
    baker.bake_defaults()
    user_path = baker.user_dir / f"debug{ChainBaker.SUFFIX}"
    # Replace user file with a hand-edited manifest that's obviously different.
    hand_edit = ChainManifest(
        passes=[PassSpec(name="tonemap", kind="tonemap", params={"exposure_ev": 2.0})]
    )
    user_path.write_text(hand_edit.to_yaml(), encoding="utf-8")
    manifest = baker.load("debug")
    assert manifest.passes[0].params["exposure_ev"] == pytest.approx(2.0)


def test_is_edited_false_before_any_edit(baker):
    baker.bake_defaults()
    for name in SHIPPING_PRESETS:
        assert baker.is_edited(name) is False


def test_is_edited_true_after_hand_edit(baker):
    baker.bake_defaults()
    (baker.user_dir / f"neon{ChainBaker.SUFFIX}").write_text(
        "passes: []\n", encoding="utf-8",
    )
    assert baker.is_edited("neon") is True


def test_is_edited_false_when_user_missing(baker):
    # No bake yet — user file absent, treat as "matches baked".
    assert baker.is_edited("default") is False


def test_is_edited_false_when_baked_missing(isolated_baker):
    # No baked file at all — user-authored preset has no baseline.
    isolated_baker.user_dir.mkdir(parents=True, exist_ok=True)
    (isolated_baker.user_dir / f"custom{ChainBaker.SUFFIX}").write_text(
        "passes: []\n", encoding="utf-8",
    )
    assert isolated_baker.is_edited("custom") is False


# ---------------------------------------------------------------------------
# 5. Revert
# ---------------------------------------------------------------------------


def test_revert_restores_baked_bytes(baker):
    baker.bake_defaults()
    user_path = baker.user_dir / f"dreamy{ChainBaker.SUFFIX}"
    baked_path = baker.baked_dir / f"dreamy{ChainBaker.SUFFIX}"
    user_path.write_text("passes: []\n", encoding="utf-8")
    assert baker.is_edited("dreamy") is True
    baker.revert("dreamy")
    assert baker.is_edited("dreamy") is False
    assert user_path.read_bytes() == baked_path.read_bytes()


def test_revert_creates_user_dir_if_missing(baker):
    assert not baker.user_dir.exists()
    baker.revert("default")
    assert baker.user_dir.is_dir()
    assert (baker.user_dir / f"default{ChainBaker.SUFFIX}").exists()


def test_revert_missing_baked_raises(isolated_baker):
    with pytest.raises(ChainBakerError):
        isolated_baker.revert("not_a_real_preset")


# ---------------------------------------------------------------------------
# 6. Load errors
# ---------------------------------------------------------------------------


def test_load_missing_preset_raises(baker):
    with pytest.raises(ChainBakerError):
        baker.load("does_not_exist")


def test_load_corrupt_user_yaml_raises(baker):
    baker.bake_defaults()
    user_path = baker.user_dir / f"default{ChainBaker.SUFFIX}"
    # Not YAML at all — this makes ChainManifest.from_yaml raise.
    user_path.write_text("passes: [ {name: 'x'", encoding="utf-8")
    with pytest.raises(ChainBakerError):
        baker.load("default")


def test_load_rejects_empty_name(baker):
    with pytest.raises(Exception):
        baker.load("")


# ---------------------------------------------------------------------------
# 7. Custom pass stub handlers
# ---------------------------------------------------------------------------


def test_register_stub_handlers_returns_expected_names():
    names = ChainBaker.register_stub_handlers()
    assert set(names) == {"chromatic_aberration", "grain"}


def test_stub_chromatic_aberration_is_pass_through():
    img = _sample_image()
    spec = PassSpec(
        name="chromatic_aberration",
        kind="custom",
        params={"handler": "chromatic_aberration", "amount": 0.01},
    )
    result = _chromatic_aberration_stub(img, spec, {})
    assert result.shape == img.shape
    assert result.dtype == np.float32
    np.testing.assert_array_equal(result, img)
    # It's a copy — mutating result must not touch input.
    result[0, 0, 0] = 999.0
    assert img[0, 0, 0] != 999.0


def test_stub_grain_is_pass_through():
    img = _sample_image()
    spec = PassSpec(
        name="grain",
        kind="custom",
        params={"handler": "grain", "intensity": 0.05},
    )
    result = _grain_stub(img, spec, {})
    assert result.shape == img.shape
    np.testing.assert_array_equal(result, img)


def test_neon_manifest_dispatches_after_stub_registration(baker):
    """apply_manifest raises on neon until the CA stub is registered."""
    manifest = baker.load("neon")
    img = _sample_image()
    # Without stubs the custom pass has no handler and raises.
    with pytest.raises(Exception):
        apply_manifest(img, manifest)
    ChainBaker.register_stub_handlers()
    out = apply_manifest(img, manifest)
    assert out.shape == img.shape
    assert out.dtype == np.float32


def test_retro_film_manifest_dispatches_after_stub_registration(baker):
    manifest = baker.load("retro_film")
    ChainBaker.register_stub_handlers()
    img = _sample_image()
    out = apply_manifest(img, manifest)
    assert out.shape == img.shape


# ---------------------------------------------------------------------------
# 8. Lazy exports on the subpackage
# ---------------------------------------------------------------------------


def test_lazy_exports_expose_chain_baker():
    import pharos_engine.post_process as pp

    assert pp.ChainBaker is ChainBaker
    assert pp.ChainBakerError is ChainBakerError
    assert pp.BakerResult is BakerResult


# ---------------------------------------------------------------------------
# 9. Directory + suffix constants
# ---------------------------------------------------------------------------


def test_suffix_constant():
    assert ChainBaker.SUFFIX == ".chain.yaml"


def test_default_user_dir_is_home_pharos_engine_postprocess_chains():
    from pathlib import Path

    expected = Path.home() / ".pharos_engine" / "postprocess_chains"
    assert ChainBaker.USER_DIR == expected


def test_baker_result_defaults():
    r = BakerResult(user_dir=Path("."))
    assert r.written == []
    assert r.skipped == []
    assert r.baked_names == []
