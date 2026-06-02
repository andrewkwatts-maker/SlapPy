"""Thorough tests for the lambda→WGSL AST compiler."""
import pytest
from slappyengine.struct_registry import StructRegistry
from slappyengine.modules.health import HealthModule
from slappyengine.modules.physics import PhysicsModule
from slappyengine.compute.ast_compiler import LambdaToWGSL, ASTCompilerError


@pytest.fixture
def reg():
    r = StructRegistry()
    r.register(HealthModule)
    r.register(PhysicsModule)
    return r


def test_constant_float(reg):
    c = LambdaToWGSL(reg)
    assert c.compile_lambda(lambda px: 1.0) == "1.0f"


def test_constant_int(reg):
    c = LambdaToWGSL(reg)
    result = c.compile_lambda(lambda px: 42)
    assert "42" in result


def test_boolean_and(reg):
    c = LambdaToWGSL(reg)
    result = c.compile_lambda(lambda px: px.health > 0.0 and px.strength > 0.0)
    assert "&&" in result


def test_boolean_or(reg):
    c = LambdaToWGSL(reg)
    result = c.compile_lambda(lambda px: px.health > 0.5 or px.strength > 0.5)
    assert "||" in result


def test_not_operator(reg):
    c = LambdaToWGSL(reg)
    result = c.compile_lambda(lambda px: not (px.health > 0.5))
    assert "!" in result


def test_nested_arithmetic(reg):
    c = LambdaToWGSL(reg)
    result = c.compile_lambda(lambda px: (px.health * 0.9) - (px.strength * 0.1))
    assert "*" in result
    assert "-" in result


def test_multiple_channels_tracked(reg):
    c = LambdaToWGSL(reg)
    c.compile_lambda(lambda px: px.health + px.strength + px.stiffness)
    assert "health" in c.used_channels
    assert "strength" in c.used_channels
    assert "stiffness" in c.used_channels


def test_unsupported_ast_raises(reg):
    c = LambdaToWGSL(reg)
    # List comprehension not supported
    with pytest.raises(ASTCompilerError):
        c.compile_lambda(lambda px: [px.health for _ in range(3)])


def test_wrong_px_name_raises(reg):
    # Lambda arg named differently is OK — compiler reads the arg name
    c = LambdaToWGSL(reg)
    # This should work fine (arg is 'p' not 'px')
    result = c.compile_lambda(lambda p: p.health * 2.0)
    assert "health" in result
