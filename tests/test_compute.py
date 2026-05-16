"""Tests for M4 compute API (stats, bounds, pixel mutation).

GPU tests skip if no adapter available.
"""
import pytest
import numpy as np

wgpu = pytest.importorskip("wgpu")


def _get_device():
    try:
        adapter = wgpu.gpu.request_adapter_sync(power_preference="high-performance")
        return adapter.request_device_sync() if adapter else None
    except Exception:
        return None


@pytest.fixture(scope="module")
def gpu():
    dev = _get_device()
    if dev is None:
        pytest.skip("No GPU adapter available")
    return dev


# --- AST compiler tests (no GPU needed) ---

def test_ast_compiler_simple_expr():
    from playslap.struct_registry import StructRegistry
    from playslap.modules.health import HealthModule
    from playslap.compute.ast_compiler import LambdaToWGSL

    reg = StructRegistry()
    reg.register(HealthModule)

    compiler = LambdaToWGSL(reg)
    # Simple attribute access
    result = compiler.compile_lambda(lambda px: px.health)
    assert "health" in result


def test_ast_compiler_arithmetic():
    from playslap.struct_registry import StructRegistry
    from playslap.modules.health import HealthModule
    from playslap.compute.ast_compiler import LambdaToWGSL

    reg = StructRegistry()
    reg.register(HealthModule)
    compiler = LambdaToWGSL(reg)

    result = compiler.compile_lambda(lambda px: px.health * 0.9 - 0.01)
    assert "*" in result
    assert "-" in result


def test_ast_compiler_comparison():
    from playslap.struct_registry import StructRegistry
    from playslap.modules.health import HealthModule
    from playslap.compute.ast_compiler import LambdaToWGSL

    reg = StructRegistry()
    reg.register(HealthModule)
    compiler = LambdaToWGSL(reg)

    result = compiler.compile_lambda(lambda px: px.health > 0.5)
    assert ">" in result


def test_ast_compiler_unknown_channel_raises():
    from playslap.struct_registry import StructRegistry
    from playslap.modules.health import HealthModule
    from playslap.compute.ast_compiler import LambdaToWGSL, ASTCompilerError

    reg = StructRegistry()
    reg.register(HealthModule)
    compiler = LambdaToWGSL(reg)

    with pytest.raises(ASTCompilerError):
        compiler.compile_lambda(lambda px: px.nonexistent_channel)


def test_ast_compiler_used_channels():
    from playslap.struct_registry import StructRegistry
    from playslap.modules.health import HealthModule
    from playslap.modules.physics import PhysicsModule
    from playslap.compute.ast_compiler import LambdaToWGSL

    reg = StructRegistry()
    reg.register(HealthModule)
    reg.register(PhysicsModule)
    compiler = LambdaToWGSL(reg)

    compiler.compile_lambda(lambda px: px.health * px.strength)
    assert "health" in compiler.used_channels
    assert "strength" in compiler.used_channels


# --- Struct layout tests ---

def test_pixel_mutator_channel_resolution():
    from playslap.struct_registry import StructRegistry
    from playslap.modules.health import HealthModule
    from playslap.modules.physics import PhysicsModule

    reg = StructRegistry()
    reg.register(HealthModule)
    reg.register(PhysicsModule)

    layout = reg._compute_layout()
    # color at offset 0 (vec4f = 16 bytes), health follows
    assert layout["color"] == 0
    assert layout["health"] == 16
    assert layout["strength"] > layout["health"]


def test_stats_result_dataclass():
    from playslap.compute.stats import StatsResult
    r = StatsResult(mean=0.5, sum=50.0, min=0.0, max=1.0, count=100)
    assert r.mean == 0.5
    assert r.count == 100


def test_aabb_methods():
    from playslap.compute.spatial import AABB
    aabb = AABB(10.0, 20.0, 50.0, 80.0)
    assert aabb.width() == 40.0
    assert aabb.height() == 60.0
    cx, cy = aabb.center()
    assert cx == 30.0
    assert cy == 50.0
    assert aabb.contains(30.0, 50.0)
    assert not aabb.contains(0.0, 0.0)
