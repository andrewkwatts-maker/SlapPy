"""
Tests for post-process chain, RenderTarget.post_process, and SceneUIEntity.
No GPU required.
"""
import pytest

try:
    from playslap.post_process.chain import PostProcessChain, PostProcessPass
except ImportError as _pp_err:
    pytest.skip(
        f"playslap.post_process.chain not importable: {_pp_err}",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# PostProcessChain — add helpers
# ---------------------------------------------------------------------------

def test_postprocesschain_add_blur():
    chain = PostProcessChain()
    p = chain.add_blur(radius=3)
    assert p.shader_path == "blur.wgsl"
    assert p.params["radius"] == 3
    assert len(chain.passes) == 1


def test_postprocesschain_add_pixelate():
    chain = PostProcessChain()
    p = chain.add_pixelate(block_size=8)
    assert p.params["block_size"] == 8


def test_postprocesschain_add_outline():
    chain = PostProcessChain()
    p = chain.add_outline(color=(0.0, 1.0, 0.0, 1.0), threshold=0.2)
    assert p.shader_path == "outline.wgsl"
    assert p.params["outline_g"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# PostProcessChain — remove by label
# ---------------------------------------------------------------------------

def test_postprocesschain_remove():
    chain = PostProcessChain()
    chain.add_blur(radius=2)
    chain.add_pixelate(block_size=4)
    chain.remove("blur")
    assert len(chain.passes) == 1
    assert chain.passes[0].label == "pixelate"


# ---------------------------------------------------------------------------
# PostProcessPass — disabled passes are excluded from chain.passes
# ---------------------------------------------------------------------------

def test_postprocesspass_disabled():
    chain = PostProcessChain()
    p = chain.add_blur(radius=2)
    p.enabled = False
    assert len(chain.passes) == 0  # disabled passes excluded


# ---------------------------------------------------------------------------
# PostProcessChain — insertion order is preserved
# ---------------------------------------------------------------------------

def test_postprocesschain_ordering():
    chain = PostProcessChain()
    chain.add_blur(radius=1)
    chain.add_pixelate(block_size=4)
    chain.add_outline()
    labels = [p.label for p in chain.passes]
    assert labels == ["blur", "pixelate", "outline"]


# ---------------------------------------------------------------------------
# RenderTarget — has post_process attribute defaulting to None
# ---------------------------------------------------------------------------

def test_rendertarget_has_post_process():
    try:
        from playslap.render_target import RenderTarget
    except ImportError as exc:
        pytest.skip(f"RenderTarget not importable: {exc}")
    rt = RenderTarget(name="test")
    assert hasattr(rt, "post_process")
    assert rt.post_process is None


# ---------------------------------------------------------------------------
# SceneUIEntity — text lines
# ---------------------------------------------------------------------------

def test_scene_ui_entity_text():
    try:
        from playslap.ui.scene_ui import SceneUIEntity
    except ImportError as exc:
        pytest.skip(f"SceneUIEntity not importable: {exc}")
    ui = SceneUIEntity(name="hud", size=(100, 50))
    ui.set_text("Score: 100", "Lives: 3")
    assert "Score: 100" in ui._text_lines
    assert len(ui.layers) == 1


def test_scene_ui_entity_html():
    try:
        from playslap.ui.scene_ui import SceneUIEntity
    except ImportError as exc:
        pytest.skip(f"SceneUIEntity not importable: {exc}")
    ui = SceneUIEntity(name="menu", size=(200, 100))
    ui.set_html("<p>Hello</p><p>World</p>")
    assert len(ui._text_lines) >= 1


# ---------------------------------------------------------------------------
# SceneUIEntity — input_rect geometry
# ---------------------------------------------------------------------------

def test_scene_ui_entity_input_rect():
    try:
        from playslap.ui.scene_ui import SceneUIEntity
    except ImportError as exc:
        pytest.skip(f"SceneUIEntity not importable: {exc}")
    ui = SceneUIEntity(name="btn", position=(10.0, 20.0), size=(100, 50))
    l, t, r, b = ui.input_rect
    assert l == 10.0
    assert t == 20.0
    assert r == 110.0
    assert b == 70.0


# ---------------------------------------------------------------------------
# SceneUIEntity — handle_mouse hit-testing
# ---------------------------------------------------------------------------

def test_scene_ui_entity_handle_mouse():
    try:
        from playslap.ui.scene_ui import SceneUIEntity
    except ImportError as exc:
        pytest.skip(f"SceneUIEntity not importable: {exc}")
    ui = SceneUIEntity(name="btn", position=(0.0, 0.0), size=(100, 100))
    assert ui.handle_mouse(50.0, 50.0)
    assert not ui.handle_mouse(150.0, 50.0)
