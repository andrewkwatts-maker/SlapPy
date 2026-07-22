"""Sprint X5 — declarative post-process chain manifest regression suite.

Covers the ``chain_manifest`` module end-to-end: YAML round-trip,
topological ordering, cycle / duplicate / unknown-dependency detection,
the disabled-pass skip semantics, custom handler dispatch, and the
``DEFAULT_CHAIN`` equivalence against direct ``apply_bloom`` /
``TAAPass.resolve_numpy`` calls.

The suite is pure-Python / numpy / PyYAML — no GPU required.
"""
from __future__ import annotations

import copy

import numpy as np
import pytest

from pharos_engine.post_process.bloom import apply_bloom
from pharos_engine.post_process.chain_manifest import (
    DEFAULT_CHAIN,
    KNOWN_KINDS,
    ChainManifest,
    ChainManifestError,
    PassSpec,
    _BUILTIN_HANDLERS,
    _clear_custom_handlers,
    _handle_dither,
    _handle_tonemap,
    apply_manifest,
    register_pass_handler,
)
from pharos_engine.post_process.executor import PostProcessExecutor
from pharos_engine.post_process.taa import TAAPass


# ---------------------------------------------------------------------------
# Fixtures + helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_custom_handlers():
    """Wipe the custom handler table between tests so ordering is stable."""
    _clear_custom_handlers()
    yield
    _clear_custom_handlers()


def _sample_image(h: int = 8, w: int = 8) -> np.ndarray:
    """Deterministic HDR gradient — well within numpy's float precision."""
    rng = np.random.default_rng(42)
    return rng.uniform(0.0, 1.5, size=(h, w, 3)).astype(np.float32)


def _fresh_default() -> ChainManifest:
    return copy.deepcopy(DEFAULT_CHAIN)


# ---------------------------------------------------------------------------
# 1. Structural basics
# ---------------------------------------------------------------------------


def test_passspec_defaults():
    p = PassSpec(name="a", kind="bloom")
    assert p.enabled is True
    assert p.params == {}
    assert p.depends_on == []


def test_chainmanifest_default_ctor_is_empty():
    m = ChainManifest()
    assert m.passes == []
    # Empty manifests are trivially valid.
    m.validate()
    assert m.topological_order() == []


def test_default_chain_shape():
    m = _fresh_default()
    kinds = [p.kind for p in m.passes]
    assert kinds == ["bloom", "taa", "tonemap", "dither"]
    names = [p.name for p in m.passes]
    assert names == ["bloom", "taa", "tonemap", "dither"]


def test_default_chain_deps_form_a_line():
    m = _fresh_default()
    deps = {p.name: p.depends_on for p in m.passes}
    assert deps["bloom"] == []
    assert deps["taa"] == ["bloom"]
    assert deps["tonemap"] == ["taa"]
    assert deps["dither"] == ["tonemap"]


def test_known_kinds_matches_advertised_pipeline():
    assert set(KNOWN_KINDS) >= {"bloom", "taa", "tonemap", "dither", "custom"}


# ---------------------------------------------------------------------------
# 2. YAML round-trip
# ---------------------------------------------------------------------------


def test_default_chain_yaml_roundtrip():
    m = _fresh_default()
    text = m.to_yaml()
    back = ChainManifest.from_yaml(text)
    assert [p.to_dict() for p in back.passes] == [p.to_dict() for p in m.passes]


def test_yaml_roundtrip_preserves_disabled_flag():
    m = _fresh_default()
    m.passes[1].enabled = False  # disable TAA
    round_tripped = ChainManifest.from_yaml(m.to_yaml())
    assert round_tripped.passes[1].enabled is False
    assert round_tripped.passes[0].enabled is True


def test_yaml_roundtrip_preserves_params_deeply():
    m = ChainManifest(
        passes=[
            PassSpec(
                name="bloom",
                kind="bloom",
                params={"strength": 0.42, "nested": {"a": 1, "b": [1, 2, 3]}},
            )
        ]
    )
    back = ChainManifest.from_yaml(m.to_yaml())
    assert back.passes[0].params["nested"]["b"] == [1, 2, 3]
    assert back.passes[0].params["strength"] == pytest.approx(0.42)


def test_from_yaml_accepts_bare_list():
    text = (
        "- {name: bloom, kind: bloom}\n"
        "- {name: taa, kind: taa, depends_on: [bloom]}\n"
    )
    m = ChainManifest.from_yaml(text)
    assert [p.name for p in m.passes] == ["bloom", "taa"]


def test_from_yaml_empty_string_returns_empty_manifest():
    m = ChainManifest.from_yaml("")
    assert m.passes == []


def test_from_yaml_rejects_scalar_top_level():
    with pytest.raises(ChainManifestError):
        ChainManifest.from_yaml("42")


# ---------------------------------------------------------------------------
# 3. Topological ordering
# ---------------------------------------------------------------------------


def test_topological_order_preserves_insertion_when_no_deps():
    m = ChainManifest(
        passes=[
            PassSpec(name="a", kind="bloom"),
            PassSpec(name="b", kind="tonemap"),
            PassSpec(name="c", kind="dither"),
        ]
    )
    order = [p.name for p in m.topological_order()]
    assert order == ["a", "b", "c"]


def test_topological_order_respects_declared_deps():
    m = ChainManifest(
        passes=[
            PassSpec(name="c", kind="dither", depends_on=["b"]),
            PassSpec(name="b", kind="tonemap", depends_on=["a"]),
            PassSpec(name="a", kind="bloom"),
        ]
    )
    order = [p.name for p in m.topological_order()]
    assert order == ["a", "b", "c"]


def test_topological_order_stable_when_multiple_roots():
    m = ChainManifest(
        passes=[
            PassSpec(name="first", kind="bloom"),
            PassSpec(name="second", kind="tonemap"),
            PassSpec(name="third", kind="dither", depends_on=["first", "second"]),
        ]
    )
    order = [p.name for p in m.topological_order()]
    assert order.index("first") < order.index("third")
    assert order.index("second") < order.index("third")
    # Insertion order breaks the tie between the two roots.
    assert order.index("first") < order.index("second")


def test_topological_order_returns_all_passes():
    m = _fresh_default()
    assert len(m.topological_order()) == len(m.passes)


# ---------------------------------------------------------------------------
# 4. Validation errors
# ---------------------------------------------------------------------------


def test_cycle_detection_raises():
    m = ChainManifest(
        passes=[
            PassSpec(name="a", kind="bloom", depends_on=["b"]),
            PassSpec(name="b", kind="tonemap", depends_on=["a"]),
        ]
    )
    with pytest.raises(ChainManifestError, match="cycle"):
        m.validate()


def test_cycle_detection_via_topological_order():
    m = ChainManifest(
        passes=[
            PassSpec(name="a", kind="bloom", depends_on=["c"]),
            PassSpec(name="b", kind="tonemap", depends_on=["a"]),
            PassSpec(name="c", kind="dither", depends_on=["b"]),
        ]
    )
    with pytest.raises(ChainManifestError, match="cycle"):
        m.topological_order()


def test_self_loop_detected():
    m = ChainManifest(
        passes=[PassSpec(name="a", kind="bloom", depends_on=["a"])]
    )
    with pytest.raises(ChainManifestError, match="itself"):
        m.validate()


def test_unknown_dep_raises():
    m = ChainManifest(
        passes=[PassSpec(name="a", kind="bloom", depends_on=["ghost"])]
    )
    with pytest.raises(ChainManifestError, match="unknown pass"):
        m.validate()


def test_duplicate_name_raises():
    m = ChainManifest(
        passes=[
            PassSpec(name="clash", kind="bloom"),
            PassSpec(name="clash", kind="tonemap"),
        ]
    )
    with pytest.raises(ChainManifestError, match="duplicate"):
        m.validate()


def test_unknown_kind_raises():
    m = ChainManifest(passes=[PassSpec(name="mystery", kind="not_a_pass")])
    with pytest.raises(ChainManifestError, match="unknown pass kind"):
        m.validate()


def test_passspec_from_dict_requires_name_and_kind():
    with pytest.raises(ChainManifestError):
        PassSpec.from_dict({"kind": "bloom"})
    with pytest.raises(ChainManifestError):
        PassSpec.from_dict({"name": "bloom"})


def test_passspec_from_dict_rejects_non_mapping():
    with pytest.raises(ChainManifestError):
        PassSpec.from_dict(["not", "a", "dict"])


# ---------------------------------------------------------------------------
# 5. apply_manifest — dispatching
# ---------------------------------------------------------------------------


def test_apply_manifest_empty_returns_copy():
    img = _sample_image()
    out = apply_manifest(img, ChainManifest())
    assert out is not img
    np.testing.assert_array_equal(out, img)


def test_apply_manifest_skips_disabled_passes():
    img = _sample_image()
    m = ChainManifest(
        passes=[
            PassSpec(name="d", kind="dither", enabled=False,
                     params={"strength": 1.0}),
        ]
    )
    out = apply_manifest(img, m)
    # Dither disabled -> identity.
    np.testing.assert_allclose(out, img, atol=0.0)


def test_apply_manifest_runs_dither_when_enabled():
    img = _sample_image()
    m = ChainManifest(
        passes=[PassSpec(name="d", kind="dither", params={"strength": 0.1})]
    )
    out = apply_manifest(img, m)
    # Something should have changed.
    assert not np.allclose(out, img)


def test_apply_manifest_missing_handler_raises_for_custom():
    img = _sample_image()
    m = ChainManifest(
        passes=[PassSpec(name="mystery", kind="custom")]
    )
    with pytest.raises(ChainManifestError, match="no handler"):
        apply_manifest(img, m)


def test_custom_handler_dispatch_by_name():
    img = _sample_image()
    called = {"n": 0}

    def double_it(image, spec, ctx):
        called["n"] += 1
        return image * 2.0

    register_pass_handler("doubler", double_it)
    m = ChainManifest(
        passes=[PassSpec(name="doubler", kind="custom")]
    )
    out = apply_manifest(img, m)
    assert called["n"] == 1
    np.testing.assert_allclose(out, img * 2.0)


def test_custom_handler_dispatch_by_params_handler_key():
    img = _sample_image()

    def brighten(image, spec, ctx):
        return image + float(spec.params.get("boost", 0.0))

    register_pass_handler("brighten", brighten)
    m = ChainManifest(
        passes=[PassSpec(
            name="anything",
            kind="custom",
            params={"handler": "brighten", "boost": 0.25},
        )]
    )
    out = apply_manifest(img, m)
    np.testing.assert_allclose(out, img + 0.25, atol=1e-6)


def test_register_pass_handler_overrides_builtin():
    """A custom registration for a built-in kind wins over the default."""
    img = _sample_image()

    def stub(image, spec, ctx):
        return np.zeros_like(image)

    register_pass_handler("tonemap", stub)
    m = ChainManifest(
        passes=[PassSpec(name="t", kind="tonemap")]
    )
    out = apply_manifest(img, m)
    np.testing.assert_array_equal(out, np.zeros_like(img))


def test_register_pass_handler_rejects_bad_inputs():
    with pytest.raises(ChainManifestError):
        register_pass_handler("", lambda a, b, c: a)
    with pytest.raises(ChainManifestError):
        register_pass_handler("bad", "not callable")


# ---------------------------------------------------------------------------
# 6. Default chain equivalence
# ---------------------------------------------------------------------------


def test_default_chain_matches_direct_bloom_then_taa():
    """The manifest's bloom -> TAA prefix reproduces manual chaining."""
    img = _sample_image()

    m = ChainManifest(
        passes=[
            PassSpec(
                name="bloom",
                kind="bloom",
                params={
                    "strength": 1.0,
                    "threshold": 1.0,
                    "knee": 0.2,
                    "mip_count": 6,
                },
            ),
            PassSpec(
                name="taa",
                kind="taa",
                params={"alpha": 0.1},
                depends_on=["bloom"],
            ),
        ]
    )
    manifest_out = apply_manifest(img, m)

    # Reference: manual call chain.
    ref = apply_bloom(img, strength=1.0, threshold=1.0, knee=0.2, mip_count=6)
    taa = TAAPass(
        alpha=0.1,
        reject_on_depth_disocclusion=False,
        reject_on_normal_disocclusion=False,
    )
    ref = taa.resolve_numpy(ref, ref, motion_uv=None)

    l2 = float(np.sqrt(np.mean((manifest_out - ref) ** 2)))
    assert l2 <= 1e-4, f"L2 divergence {l2} exceeds 1e-4"


def test_apply_manifest_runs_bloom_when_default_chain_used():
    """Sanity check: DEFAULT_CHAIN's bloom stage is actually additive."""
    img = np.zeros((8, 8, 3), dtype=np.float32)
    img[4, 4, :] = 5.0  # single HDR firefly
    m = ChainManifest(
        passes=[c for c in _fresh_default().passes if c.name == "bloom"]
    )
    out = apply_manifest(img, m)
    # Bloom should smear brightness beyond the single input pixel.
    assert (out > 0).sum() > 3


def test_default_chain_yaml_roundtrip_apply_matches():
    """YAML round-tripping the default chain does not perturb outputs."""
    img = _sample_image()
    round_tripped = ChainManifest.from_yaml(_fresh_default().to_yaml())
    a = apply_manifest(img, _fresh_default())
    b = apply_manifest(img, round_tripped)
    np.testing.assert_allclose(a, b, atol=1e-6)


# ---------------------------------------------------------------------------
# 7. Executor integration
# ---------------------------------------------------------------------------


def test_executor_from_manifest_stores_reference():
    m = _fresh_default()
    exe = PostProcessExecutor.from_manifest(m)
    assert exe.manifest is m


def test_executor_from_manifest_validates():
    bad = ChainManifest(
        passes=[
            PassSpec(name="a", kind="bloom", depends_on=["ghost"]),
        ]
    )
    with pytest.raises(ChainManifestError):
        PostProcessExecutor.from_manifest(bad)


def test_executor_from_manifest_rejects_non_manifest():
    with pytest.raises(ChainManifestError):
        PostProcessExecutor.from_manifest({"passes": []})  # type: ignore[arg-type]


def test_legacy_executor_manifest_is_none():
    """Executor built the legacy way exposes ``manifest is None``.

    The legacy constructor still requires a GPU context; we skip
    gracefully when wgpu can't spin one up.
    """
    try:
        from pharos_engine.gpu.context import GPUContext
    except Exception:
        pytest.skip("GPUContext unavailable in this environment")
    try:
        ctx = GPUContext()  # type: ignore[call-arg]
    except Exception:
        pytest.skip("GPU context could not be created")
    exe = PostProcessExecutor(ctx)
    assert exe.manifest is None


def test_executor_manifest_survives_yaml_roundtrip():
    m = _fresh_default()
    round_tripped = ChainManifest.from_yaml(m.to_yaml())
    exe = PostProcessExecutor.from_manifest(round_tripped)
    assert exe.manifest is round_tripped
    assert [p.name for p in exe.manifest.passes] == [
        "bloom",
        "taa",
        "tonemap",
        "dither",
    ]


# ---------------------------------------------------------------------------
# 8. Built-in handler smoke tests
# ---------------------------------------------------------------------------


def test_builtin_handlers_registered_for_all_advertised_kinds():
    for kind in ("bloom", "taa", "tonemap", "dither"):
        assert kind in _BUILTIN_HANDLERS


def test_tonemap_handler_reinhard_mode_clamps_below_one():
    img = np.full((4, 4, 3), 5.0, dtype=np.float32)
    spec = PassSpec(
        name="t", kind="tonemap", params={"exposure_ev": 0.0, "mode": 1}
    )
    out = _handle_tonemap(img, spec, {})
    # Reinhard L' = L / (1 + L) => 5 / 6 ~= 0.833.
    np.testing.assert_allclose(out, np.full_like(img, 5.0 / 6.0), atol=1e-5)


def test_dither_handler_strength_zero_is_identity():
    img = _sample_image()
    spec = PassSpec(name="d", kind="dither", params={"strength": 0.0})
    out = _handle_dither(img, spec, {})
    np.testing.assert_array_equal(out, img)


def test_dither_handler_perturbs_within_strength():
    img = np.full((16, 16, 3), 0.5, dtype=np.float32)
    spec = PassSpec(name="d", kind="dither", params={"strength": 0.1})
    out = _handle_dither(img, spec, {})
    assert np.abs(out - img).max() <= 0.05 + 1e-6
    # But it should have actually moved something.
    assert np.any(out != img)


# ---------------------------------------------------------------------------
# 9. Miscellaneous edge cases
# ---------------------------------------------------------------------------


def test_passspec_to_dict_returns_deep_copy_of_params():
    spec = PassSpec(name="a", kind="bloom", params={"nested": {"x": 1}})
    d = spec.to_dict()
    d["params"]["nested"]["x"] = 999
    assert spec.params["nested"]["x"] == 1


def test_manifest_topological_order_does_not_mutate_input():
    m = _fresh_default()
    before = [p.name for p in m.passes]
    _ = m.topological_order()
    after = [p.name for p in m.passes]
    assert before == after


def test_apply_manifest_returns_float32():
    img = _sample_image().astype(np.float64)
    out = apply_manifest(img, _fresh_default())
    assert out.dtype == np.float32


def test_apply_manifest_never_returns_input_alias():
    img = _sample_image()
    out = apply_manifest(img, ChainManifest())
    assert out is not img


def test_ctx_dict_is_shared_between_handlers():
    img = _sample_image()

    def writer(image, spec, ctx):
        ctx["marker"] = spec.name
        return image

    def reader(image, spec, ctx):
        assert ctx.get("marker") == "one"
        return image

    register_pass_handler("writer", writer)
    register_pass_handler("reader", reader)
    m = ChainManifest(
        passes=[
            PassSpec(name="one", kind="custom",
                     params={"handler": "writer"}),
            PassSpec(name="two", kind="custom",
                     params={"handler": "reader"},
                     depends_on=["one"]),
        ]
    )
    apply_manifest(img, m, ctx={})


def test_default_chain_is_module_level_singleton_not_shared_state():
    """Callers mutating DEFAULT_CHAIN.passes should not affect fresh copies."""
    fresh = _fresh_default()
    fresh.passes.pop()
    # The module-level DEFAULT_CHAIN is untouched — we deep-copied it.
    assert len(DEFAULT_CHAIN.passes) == 4
