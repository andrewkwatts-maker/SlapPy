"""BBB2 — ruled-paper background must reach the notebook panels.

The notebook theme ships a ``background_shader=ShaderEffect("ruled_paper")``
whose baked RGBA ndarray is expected to appear as each panel's
backdrop. Until BBB2 landed the ndarray was baked but never handed to
Dear PyGui, so panels rendered a flat surface colour and the ruled
lines / ink margin never appeared on screen.

These tests exercise the two halves of the wiring:

* :func:`slappyengine.ui.theme.resolve_background` returns a real
  ``(H, W, 4)`` uint8 ndarray for the ``ruled_paper`` numpy-side
  effect (BBB1 fixed the sig-injection crash — this is a smoke test
  that it stays fixed and produces a non-empty texture).
* :meth:`EditorShell.setup_theme_subsystem` calls
  :func:`slappyengine.ui.editor.theme._bind_paper_texture` for each
  of the four notebook surface panels (outliner, viewport, inspector,
  content browser). The helper records the intent on a module-level
  tracker so the test can prove the wiring ran without a live DPG
  context.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _reset_theme_state():
    """Drop theme registry + paper-texture bookkeeping between cases."""
    from slappyengine.ui.theme import _reset_registry_for_tests
    from slappyengine.ui.editor.theme import (
        _reset_paper_texture_bindings_for_tests,
    )

    _reset_registry_for_tests()
    _reset_paper_texture_bindings_for_tests()
    yield
    _reset_registry_for_tests()
    _reset_paper_texture_bindings_for_tests()


# ---------------------------------------------------------------------------
# resolve_background — must produce a non-empty RGBA ndarray for
# the ``ruled_paper`` numpy-side ShaderEffect. BBB1 fixed this; this
# guard prevents a future refactor from regressing the wiring.
# ---------------------------------------------------------------------------


class TestResolveRuledPaperBackground:
    def test_returns_rgba_ndarray_from_shader_effect(self):
        import numpy as np

        from slappyengine.ui.theme import ShaderEffect, resolve_background

        effect = ShaderEffect(
            name="ruled_paper",
            params={
                "paper_color": (251, 247, 236, 255),
                "line_color": (231, 221, 241, 255),
                "margin_color": (255, 111, 181, 255),
            },
        )

        arr = resolve_background(effect)

        assert arr is not None, "ruled_paper effect must resolve to a texture"
        assert isinstance(arr, np.ndarray)
        assert arr.ndim == 3, f"expected 3-D RGBA, got {arr.ndim}-D"
        assert arr.shape[-1] == 4, f"expected 4 channels, got {arr.shape[-1]}"
        assert arr.shape[0] > 0 and arr.shape[1] > 0, (
            f"expected non-empty texture, got shape {arr.shape}"
        )
        # The default width/height injection lands at 512x512.
        assert arr.shape[0] == 512
        assert arr.shape[1] == 512

    def test_ruled_paper_texture_contains_line_pixels(self):
        """The output must actually differ from the paper base — otherwise
        we'd be back to the flat off-white bug the user reported."""
        import numpy as np

        from slappyengine.ui.theme import ShaderEffect, resolve_background

        effect = ShaderEffect(
            name="ruled_paper",
            params={
                "paper_color": (251, 247, 236, 255),
                "line_color": (231, 221, 241, 255),
                "margin_color": (255, 111, 181, 255),
            },
        )
        arr = resolve_background(effect)
        assert arr is not None

        # The texture must contain at least a few pixels that differ
        # from the paper base colour. A uniform texture would mean the
        # rules never rendered.
        pixels = arr.reshape(-1, 4)
        unique_rows = np.unique(pixels, axis=0)
        assert len(unique_rows) >= 2, (
            f"ruled_paper produced a flat texture: only {len(unique_rows)} "
            f"unique colour(s). The rules / margin never rendered."
        )


# ---------------------------------------------------------------------------
# EditorShell.setup_theme_subsystem — must record a texture-registry
# entry for every notebook surface panel.
# ---------------------------------------------------------------------------


class _StubEngine:
    """Minimal engine stand-in — the shell only stores the reference."""

    def __init__(self) -> None:
        self.scene = None


class TestPanelTextureWiring:
    def test_setup_theme_subsystem_binds_paper_for_four_panels(self):
        from slappyengine.ui.editor.shell import EditorShell
        from slappyengine.ui.editor.theme import get_bound_paper_textures

        shell = EditorShell(_StubEngine())
        shell.setup_theme_subsystem()

        bound = get_bound_paper_textures()
        expected = {
            "notebook_paper_outliner",
            "notebook_paper_viewport",
            "notebook_paper_inspector",
            "notebook_paper_content_browser",
        }
        missing = expected - set(bound)
        assert not missing, (
            f"setup_theme_subsystem failed to bind paper texture for "
            f"panels: {sorted(missing)}"
        )

    def test_bound_textures_have_unique_registry_tags(self):
        """Each panel gets its own texture-registry tag so DPG doesn't
        collide when the theme is re-applied on a live editor."""
        from slappyengine.ui.editor.shell import EditorShell
        from slappyengine.ui.editor.theme import get_bound_paper_textures

        shell = EditorShell(_StubEngine())
        shell.setup_theme_subsystem()

        bound = get_bound_paper_textures()
        tags = list(bound.values())
        assert len(tags) == len(set(tags)), (
            f"paper-texture tags must be unique per panel; got {tags}"
        )

    def test_bind_helper_tolerates_missing_baked_background(self):
        """When ``get_baked_background`` returns ``None`` (no theme or
        no shader) the helper must still record the intent so panels
        wire up their solid fallback colour instead of crashing."""
        from slappyengine.ui.editor.theme import (
            _bind_paper_texture,
            get_bound_paper_textures,
        )

        result = _bind_paper_texture(None, "notebook_paper_test_panel")
        assert result is not None
        bound = get_bound_paper_textures()
        assert "notebook_paper_test_panel" in bound

    def test_bind_helper_rejects_empty_panel_tag(self):
        """A blank panel tag is a caller bug — we return ``None`` so the
        caller can log + skip rather than register a nameless texture."""
        from slappyengine.ui.editor.theme import _bind_paper_texture

        assert _bind_paper_texture(None, "") is None
