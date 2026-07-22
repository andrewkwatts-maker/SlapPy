"""Sprint 9 theme expansion + picker panel tests."""
from __future__ import annotations


def test_ships_three_new_themes():
    from pharos_editor.themes import ThemeCatalog

    catalog = ThemeCatalog()
    names = catalog.names()
    for expected in ("dark_studio", "high_contrast", "pastel_soft"):
        assert expected in names, f"missing shipped theme {expected!r}"


def test_notebook_knobs_parse_when_absent():
    """Older themes without washi/lining/edge_stroke still load."""
    from pharos_editor.themes import ThemeCatalog

    catalog = ThemeCatalog()
    theme = catalog.get("teengirl_notebook")
    # Not required to have data; presence + type is enough.
    assert isinstance(theme.washi_tape, dict)
    assert isinstance(theme.page_lining, dict)
    assert isinstance(theme.edge_stroke, dict)


def test_notebook_knobs_parse_when_present():
    """New themes populate the notebook decor knobs."""
    from pharos_editor.themes import ThemeCatalog

    catalog = ThemeCatalog()
    theme = catalog.get("pastel_soft")
    assert theme.washi_tape.get("variant") == "floral"
    assert theme.washi_tape.get("density") == "high"
    assert theme.page_lining.get("style") == "dot_grid"
    assert theme.edge_stroke.get("style") == "pencil"


def test_picker_swatch_shape():
    from pharos_editor.ui.editor.notebook_theme_picker import NotebookThemePicker

    picker = NotebookThemePicker()
    swatch = picker.swatch_for("dark_studio")
    assert swatch.name == "dark_studio"
    assert swatch.display_name == "Dark Studio"
    keys = [k for k, _ in swatch.palette_swatches]
    assert "bg" in keys
    assert "accent_pink" in keys


def test_picker_apply_calls_hook():
    from pharos_editor.ui.editor.notebook_theme_picker import NotebookThemePicker

    seen: list[str] = []
    picker = NotebookThemePicker(on_apply=lambda name: seen.append(name))
    applied = picker.apply("high_contrast")
    assert applied == "high_contrast"
    assert seen == ["high_contrast"]
    assert picker.current() == "high_contrast"


def test_picker_apply_rejects_unknown():
    import pytest

    from pharos_editor.ui.editor.notebook_theme_picker import NotebookThemePicker

    picker = NotebookThemePicker()
    with pytest.raises(KeyError):
        picker.apply("no_such_theme")


def test_panel_style_hints_expose_token_map():
    from pharos_editor.ui.editor.notebook_theme_picker import PANEL_STYLE_HINTS

    assert "background" in PANEL_STYLE_HINTS
    assert "apply_button_accent" in PANEL_STYLE_HINTS
