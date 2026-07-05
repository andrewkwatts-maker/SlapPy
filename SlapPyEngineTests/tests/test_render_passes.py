"""Tests for KK2 — DepthPrepass + MSAAResolvePass + PassChain.

All tests exercise the NullRenderer path so no GPU is required. The
soft-skip pattern is used where a symbol is optional in older engine
builds; nothing in KK2 requires wgpu.
"""
from __future__ import annotations

import numpy as np
import pytest

from slappyengine.render import (
    DEPTH_ONLY_WGSL,
    DepthPrepass,
    EarlyZPass,
    MSAAResolvePass,
    Material,
    NullRenderer,
    PassChain,
    RenderPass,
    Renderer,
    STOCK_SHADERS,
    cube,
    install_default_passes,
)


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def _fake_meshes(n_opaque: int = 2, n_transparent: int = 0):
    """Yield ``(mesh, model, material)`` triples for the pass to iterate."""
    for _ in range(n_opaque):
        yield cube(), np.eye(4, dtype=np.float32), Material(name="opaque_a")
    for _ in range(n_transparent):
        yield cube(), np.eye(4, dtype=np.float32), Material(name="glass", alpha_mode="blend")


# ======================================================================
# RenderPass base
# ======================================================================
def test_render_pass_base_execute_raises():
    p = RenderPass(name="abstract")
    with pytest.raises(NotImplementedError):
        p.execute(None, None, None)


def test_render_pass_setup_teardown_toggles_flag():
    p = RenderPass(name="lifecycle")
    r = NullRenderer()
    assert not p.is_setup
    p.setup(r)
    assert p.is_setup
    p.teardown()
    assert not p.is_setup


def test_render_pass_named_default():
    class Custom(RenderPass):
        name = "custom_default"

        def execute(self, e, t, c):
            pass

    p = Custom()
    assert p.name == "custom_default"


# ======================================================================
# Depth prepass
# ======================================================================
def test_depth_prepass_setup_execute_doesnt_crash():
    r = NullRenderer()
    p = DepthPrepass()
    p.setup(r)
    p.execute(None, None, None, meshes=list(_fake_meshes(2, 0)))
    p.teardown()  # must not throw


def test_depth_prepass_records_begin_call():
    r = NullRenderer()
    p = DepthPrepass()
    p.setup(r)
    p.execute(None, None, None, meshes=[])
    assert r.calls_of("depth_prepass_begin"), "prepass should log its begin marker"


def test_depth_prepass_uses_less_color_writes_than_full_pass():
    """Full pass logs one 'mesh' call per mesh; prepass logs a
    'depth_prepass_mesh' call with color_write=False and no 'mesh' calls."""
    r = NullRenderer()
    p = DepthPrepass()
    p.setup(r)
    p.execute(None, None, None, meshes=list(_fake_meshes(3, 0)))
    prepass_calls = r.calls_of("depth_prepass_mesh")
    color_writes = [c for c in prepass_calls if c.payload.get("color_write") is True]
    assert len(prepass_calls) == 3
    assert len(color_writes) == 0
    # And no full mesh submissions were emitted by the prepass:
    assert r.calls_of("mesh") == []


def test_depth_prepass_skips_transparent_meshes():
    r = NullRenderer()
    p = DepthPrepass()
    p.setup(r)
    p.execute(None, None, None, meshes=list(_fake_meshes(2, 3)))
    assert p.stats.meshes_submitted == 2
    assert p.stats.meshes_skipped_transparent == 3
    assert len(r.calls_of("depth_prepass_mesh")) == 2


def test_depth_prepass_write_depth_configurable():
    p = DepthPrepass(write_depth=False)
    assert p.write_depth is False
    r = NullRenderer()
    p.setup(r)
    p.execute(None, None, None, meshes=list(_fake_meshes(1, 0)))
    call = r.calls_of("depth_prepass_mesh")[0]
    assert call.payload["write_depth"] is False


def test_depth_prepass_depth_bias_recorded_on_begin():
    r = NullRenderer()
    p = DepthPrepass(depth_bias=0.0025)
    p.setup(r)
    p.execute(None, None, None, meshes=[])
    begin = r.calls_of("depth_prepass_begin")[0]
    assert begin.payload["depth_bias"] == pytest.approx(0.0025)


def test_depth_prepass_no_meshes_kwarg_is_safe():
    r = NullRenderer()
    p = DepthPrepass()
    p.setup(r)
    # No meshes iterable — should still log its begin marker cleanly.
    p.execute(None, None, None)
    assert r.calls_of("depth_prepass_begin")
    assert r.calls_of("depth_prepass_mesh") == []


def test_depth_prepass_wgsl_registered_in_shader_stock():
    assert "depth_only" in STOCK_SHADERS
    assert "vs_main" in DEPTH_ONLY_WGSL
    assert "fs_main" in DEPTH_ONLY_WGSL


def test_depth_prepass_records_last_execute_time():
    r = NullRenderer()
    p = DepthPrepass()
    p.setup(r)
    p.execute(None, None, None, meshes=list(_fake_meshes(1, 0)))
    assert p.last_execute_ns >= 0


# ======================================================================
# MSAA resolve
# ======================================================================
def test_msaa_resolve_pass_noop_for_msaa1():
    r = NullRenderer()
    p = MSAAResolvePass()
    p.setup(r)
    p.resolve(src_texture=None, dst_texture=None, samples=1)
    assert r.calls_of("msaa_resolve_noop")
    assert r.calls_of("msaa_resolve") == []
    assert p.last_op == "noop"
    assert p.last_samples == 1


def test_msaa_resolve_pass_resolves_for_msaa4():
    r = NullRenderer()
    p = MSAAResolvePass()
    p.setup(r)
    p.resolve(src_texture="src_msaa", dst_texture="dst_single", samples=4)
    resolves = r.calls_of("msaa_resolve")
    assert len(resolves) == 1
    assert resolves[0].payload["samples"] == 4
    assert p.last_op == "resolve"


def test_msaa_resolve_pass_valid_sample_counts():
    r = NullRenderer()
    p = MSAAResolvePass()
    p.setup(r)
    for s in (2, 4, 8, 16):
        p.resolve(None, None, s)
    assert len(r.calls_of("msaa_resolve")) == 4


def test_msaa_resolve_pass_rejects_invalid_samples():
    p = MSAAResolvePass()
    p.setup(NullRenderer())
    with pytest.raises(ValueError):
        p.resolve(None, None, 3)


def test_msaa_resolve_execute_pulls_samples_from_renderer():
    r = Renderer(force_null=True, msaa=4)
    p = MSAAResolvePass()
    p.setup(r)
    p.execute(None, None, None)
    assert p.last_samples == 4
    assert p.last_op == "resolve"


def test_msaa_resolve_execute_noop_when_msaa_is_1():
    r = Renderer(force_null=True, msaa=1)
    p = MSAAResolvePass()
    p.setup(r)
    p.execute(None, None, None)
    assert p.last_op == "noop"


# ======================================================================
# EarlyZ
# ======================================================================
def test_early_z_pass_sets_depth_compare_less_equal():
    r = Renderer(force_null=True)
    assert r.depth_compare == "less"
    p = EarlyZPass()
    p.setup(r)
    assert r.depth_compare == "less_equal"
    p.teardown()
    # Restored on teardown.
    assert r.depth_compare == "less"


def test_early_z_uses_less_equal_class_attr():
    assert EarlyZPass.DEPTH_COMPARE == "less_equal"


def test_early_z_execute_runs_depth_prepass():
    r = Renderer(force_null=True)
    p = EarlyZPass()
    p.setup(r)
    p.execute(None, None, None, meshes=list(_fake_meshes(2, 1)))
    null = r._null
    assert null.calls_of("depth_prepass_begin")
    assert len(null.calls_of("depth_prepass_mesh")) == 2
    assert null.calls_of("early_z_execute")


def test_early_z_setup_records_marker():
    r = Renderer(force_null=True)
    p = EarlyZPass()
    p.setup(r)
    setup_calls = r._null.calls_of("early_z_setup")
    assert setup_calls
    assert setup_calls[0].payload["depth_compare"] == "less_equal"


# ======================================================================
# PassChain
# ======================================================================
def test_pass_chain_add_and_names():
    r = NullRenderer()
    chain = PassChain(renderer=r)
    chain.add(DepthPrepass())
    chain.add(MSAAResolvePass())
    assert chain.names == ["depth_prepass", "msaa_resolve"]
    assert len(chain) == 2


def test_pass_chain_add_rejects_non_render_pass():
    chain = PassChain()
    with pytest.raises(TypeError):
        chain.add("not a pass")  # type: ignore[arg-type]


def test_pass_chain_add_rejects_duplicate_name():
    chain = PassChain()
    chain.add(DepthPrepass())
    with pytest.raises(ValueError):
        chain.add(DepthPrepass())


def test_pass_chain_executes_in_registered_order():
    """Executes passes in the order add() was called."""
    calls: list[str] = []

    class _Recorder(RenderPass):
        def __init__(self, name):
            super().__init__(name=name)

        def execute(self, e, t, c):
            calls.append(self.name)

    chain = PassChain()
    chain.add(_Recorder("a"))
    chain.add(_Recorder("b"))
    chain.add(_Recorder("c"))
    chain.execute_all(None, None)
    assert calls == ["a", "b", "c"]


def test_pass_chain_remove_returns_true_when_present():
    chain = PassChain()
    chain.add(DepthPrepass())
    assert chain.remove("depth_prepass") is True
    assert "depth_prepass" not in chain
    assert len(chain) == 0


def test_pass_chain_remove_returns_false_when_absent():
    chain = PassChain()
    assert chain.remove("nope") is False


def test_pass_chain_get_returns_pass_or_none():
    chain = PassChain()
    p = chain.add(DepthPrepass())
    assert chain.get("depth_prepass") is p
    assert chain.get("nope") is None


def test_pass_chain_contains_operator():
    chain = PassChain()
    chain.add(DepthPrepass())
    assert "depth_prepass" in chain
    assert "not_here" not in chain


def test_pass_chain_iter_and_len():
    chain = PassChain()
    chain.add(DepthPrepass())
    chain.add(MSAAResolvePass())
    names = [p.name for p in chain]
    assert names == ["depth_prepass", "msaa_resolve"]


def test_pass_chain_tracks_total_ns():
    chain = PassChain()
    chain.add(DepthPrepass())
    chain.execute_all(None, {"target": None, "camera": None, "meshes": None})
    assert chain.stats.total_ns >= 0
    assert "depth_prepass" in chain.stats.per_pass_ns


def test_pass_chain_execute_all_forwards_ctx_dict():
    r = NullRenderer()
    prepass = DepthPrepass()
    prepass.setup(r)
    chain = PassChain(renderer=r)
    # Add without triggering a second setup (already set up above).
    chain._passes.append(prepass)
    chain.execute_all(None, {"target": None, "camera": None,
                              "meshes": list(_fake_meshes(2, 0))})
    assert prepass.stats.meshes_submitted == 2


def test_pass_chain_teardown_all_clears():
    chain = PassChain(renderer=NullRenderer())
    chain.add(DepthPrepass())
    chain.add(MSAAResolvePass())
    chain.teardown_all()
    assert len(chain) == 0


# ======================================================================
# Renderer.pass_chain / enable_depth_prepass integration
# ======================================================================
def test_renderer_exposes_pass_chain_property():
    r = Renderer(force_null=True)
    assert isinstance(r.pass_chain, PassChain)
    # MSAAResolvePass is registered eagerly.
    assert "msaa_resolve" in r.pass_chain


def test_renderer_enable_depth_prepass_registers_it():
    r = Renderer(force_null=True)
    assert "depth_prepass" not in r.pass_chain
    r.enable_depth_prepass(True)
    assert "depth_prepass" in r.pass_chain
    # And it runs before the resolve.
    assert r.pass_chain.names[0] == "depth_prepass"


def test_renderer_enable_depth_prepass_toggle_off():
    r = Renderer(force_null=True)
    r.enable_depth_prepass(True)
    r.enable_depth_prepass(False)
    assert "depth_prepass" not in r.pass_chain


def test_renderer_enable_depth_prepass_idempotent():
    r = Renderer(force_null=True)
    r.enable_depth_prepass(True)
    r.enable_depth_prepass(True)
    # Only one instance despite two toggles.
    assert sum(1 for n in r.pass_chain.names if n == "depth_prepass") == 1


def test_renderer_lifecycle_backward_compat():
    """Existing begin/end frame flow still works — no forced pass chain calls."""
    r = Renderer(force_null=True)
    r.begin_frame()
    r.submit_mesh(cube(), np.eye(4, dtype=np.float32), Material())
    r.end_frame()
    assert r.frame_count == 1
    assert r.calls_of("mesh")


# ======================================================================
# install_default_passes helper
# ======================================================================
def test_install_default_passes_msaa_only_by_default():
    r = Renderer(force_null=True)
    chain = install_default_passes(r)
    assert chain.names == ["msaa_resolve"]


def test_install_default_passes_with_depth_prepass():
    r = Renderer(force_null=True)
    chain = install_default_passes(r, enable_depth_prepass=True)
    assert chain.names == ["depth_prepass", "msaa_resolve"]


def test_install_default_passes_nothing_when_all_disabled():
    r = Renderer(force_null=True)
    chain = install_default_passes(r, enable_depth_prepass=False, enable_msaa_resolve=False)
    assert list(chain) == []
