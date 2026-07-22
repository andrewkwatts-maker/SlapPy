"""Tests for :mod:`pharos_editor.ui.user_overrides`.

Verifies the brief's contract:

* Scaffolding creates the expected directory tree + README files.
* Missing directories silently no-op.
* A single broken panel file is logged but does not prevent other
  panels from loading.
* Hotkey YAMLs are parsed + user entries win on collision.
* Shader files are discovered with the correct ``kind`` (parent
  directory).
* Config toggles disable each category individually.
* The returned :class:`UserOverrideBundle` carries every discovered
  item.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from pharos_editor.ui.user_overrides import (
    UserOverrideBundle,
    UserOverrideLoader,
    _CONFIG_DEFAULTS,
    _SHADER_KINDS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def loader(tmp_path: Path) -> UserOverrideLoader:
    """A loader rooted at a tmp path (never touches ``~/.pharos_engine``)."""
    return UserOverrideLoader(root=tmp_path / "ui")


# ---------------------------------------------------------------------------
# Basic wiring
# ---------------------------------------------------------------------------


def test_bundle_defaults_empty() -> None:
    """A default bundle has zero items and no errors."""
    b = UserOverrideBundle()
    assert b.panels == []
    assert b.hotkey_bindings == {}
    assert b.spawn_actions == []
    assert b.shaders == {}
    assert not b.has_errors()
    assert b.summary() == {
        "panels": 0, "hotkeys": 0, "spawn_actions": 0,
        "shaders": 0, "errors": 0,
    }


def test_default_root_is_home_dot_pharos_engine_ui() -> None:
    """Loader without explicit root points at ``~/.pharos_engine/ui``."""
    loader = UserOverrideLoader()
    assert loader.root == Path.home() / ".pharos_engine" / "ui"


def test_root_override_respected(tmp_path: Path) -> None:
    """Explicit root overrides the class default."""
    root = tmp_path / "custom_ui_root"
    loader = UserOverrideLoader(root=root)
    assert loader.root == root


# ---------------------------------------------------------------------------
# Missing directory -> silent no-op
# ---------------------------------------------------------------------------


def test_load_all_missing_root_returns_empty_bundle(tmp_path: Path) -> None:
    """A non-existent root does not raise + returns an empty bundle."""
    loader = UserOverrideLoader(root=tmp_path / "does" / "not" / "exist")
    bundle = loader.load_all()
    assert isinstance(bundle, UserOverrideBundle)
    assert bundle.panels == []
    assert bundle.hotkey_bindings == {}
    assert bundle.spawn_actions == []
    assert bundle.shaders == {}


def test_list_methods_missing_dirs_return_empty(tmp_path: Path) -> None:
    """All ``list_*`` methods no-op when their subdirs are missing."""
    loader = UserOverrideLoader(root=tmp_path / "ui")
    assert loader.list_user_panels() == []
    assert loader.list_user_hotkeys() == []
    assert loader.list_user_spawn_actions() == []
    assert loader.list_user_shaders() == []


# ---------------------------------------------------------------------------
# Scaffolding
# ---------------------------------------------------------------------------


def test_scaffolding_creates_expected_tree(loader: UserOverrideLoader) -> None:
    """``ensure_scaffolded`` creates every documented subdirectory."""
    loader.ensure_scaffolded()
    root = loader.root
    assert root.is_dir()
    for sub in (
        "panels",
        "hotkeys",
        "spawn_actions",
        "shaders",
        "shaders/page_linings",
        "shaders/washi_tape",
        "shaders/edge_strokes",
        "examples",
    ):
        assert (root / sub).is_dir(), f"{sub} missing after scaffolding"


def test_scaffolding_creates_readmes(loader: UserOverrideLoader) -> None:
    """Every top-level folder gets a README.md."""
    loader.ensure_scaffolded()
    for name in (
        "README.md",
        "panels/README.md",
        "hotkeys/README.md",
        "spawn_actions/README.md",
        "shaders/README.md",
        "examples/README.md",
    ):
        path = loader.root / name
        assert path.is_file(), f"{name} not created"
        assert path.read_text(encoding="utf-8").strip(), f"{name} is empty"


def test_scaffolding_creates_config_and_examples(
    loader: UserOverrideLoader,
) -> None:
    """A default ``config.yaml`` plus disabled example files are dropped."""
    loader.ensure_scaffolded()
    assert (loader.root / "config.yaml").is_file()
    assert (loader.root / "examples" / "_example_panel.py").is_file()
    assert (loader.root / "examples" / "_example_hotkeys.yaml").is_file()
    assert (loader.root / "examples" / "_example_shader.wgsl").is_file()


def test_scaffolding_idempotent_leaves_user_edits_alone(
    loader: UserOverrideLoader,
) -> None:
    """Re-running scaffolding does not overwrite existing files."""
    loader.ensure_scaffolded()
    cfg = loader.root / "config.yaml"
    cfg.write_text("enable_user_panels: false\n", encoding="utf-8")
    loader.ensure_scaffolded()
    assert cfg.read_text(encoding="utf-8") == "enable_user_panels: false\n"


# ---------------------------------------------------------------------------
# Panel loading
# ---------------------------------------------------------------------------


_GOOD_PANEL_A = (
    "class Panel:\n"
    "    label = 'A'\n"
    "def get_panel():\n"
    "    return Panel()\n"
)

_GOOD_PANEL_B = (
    "class Panel:\n"
    "    label = 'B'\n"
    "def get_panel():\n"
    "    return Panel()\n"
)

_BROKEN_PANEL_SYNTAX = "def get_panel(: broken\n"

_BROKEN_PANEL_RAISES = (
    "def get_panel():\n"
    "    raise RuntimeError('boom')\n"
)

_MISSING_FACTORY_PANEL = "class Panel: pass\n"


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def test_valid_panels_loaded(loader: UserOverrideLoader) -> None:
    """Two well-formed panel files both produce panel instances."""
    _write(loader.root / "panels" / "a_panel.py", _GOOD_PANEL_A)
    _write(loader.root / "panels" / "b_panel.py", _GOOD_PANEL_B)
    bundle = loader.load_all()
    assert len(bundle.panels) == 2
    labels = sorted(p.label for p in bundle.panels)
    assert labels == ["A", "B"]
    assert not bundle.has_errors()


def test_broken_panel_logged_others_still_load(
    loader: UserOverrideLoader,
) -> None:
    """A syntax-broken panel does not stop the good ones from loading."""
    _write(loader.root / "panels" / "good.py", _GOOD_PANEL_A)
    _write(loader.root / "panels" / "syntax_bad.py", _BROKEN_PANEL_SYNTAX)
    _write(loader.root / "panels" / "raises_bad.py", _BROKEN_PANEL_RAISES)
    _write(loader.root / "panels" / "missing_factory.py", _MISSING_FACTORY_PANEL)
    bundle = loader.load_all()
    assert len(bundle.panels) == 1
    assert bundle.panels[0].label == "A"
    assert len(bundle.errors) == 3
    # Every recorded error has (path, message)
    for path, msg in bundle.errors:
        assert Path(path).exists()
        assert isinstance(msg, str) and msg


def test_underscore_panel_files_skipped(loader: UserOverrideLoader) -> None:
    """Files prefixed with `_` are disabled by convention."""
    _write(loader.root / "panels" / "_disabled.py", _GOOD_PANEL_A)
    _write(loader.root / "panels" / "enabled.py", _GOOD_PANEL_B)
    bundle = loader.load_all()
    assert len(bundle.panels) == 1
    assert bundle.panels[0].label == "B"


# ---------------------------------------------------------------------------
# Hotkey loading
# ---------------------------------------------------------------------------


def test_hotkey_yaml_parsed(loader: UserOverrideLoader) -> None:
    """A hotkey YAML populates ``bundle.hotkey_bindings``."""
    _write(
        loader.root / "hotkeys" / "my_keys.yaml",
        "ctrl+shift+m: user.my_command\nctrl+alt+p: editor.profiler_toggle\n",
    )
    bundle = loader.load_all()
    assert bundle.hotkey_bindings["ctrl+shift+m"] == "user.my_command"
    assert bundle.hotkey_bindings["ctrl+alt+p"] == "editor.profiler_toggle"


def test_hotkey_user_wins_on_collision(loader: UserOverrideLoader) -> None:
    """When two YAMLs bind the same key, the later file wins (a-z order)."""
    _write(
        loader.root / "hotkeys" / "a_first.yaml",
        "ctrl+shift+m: user.first\n",
    )
    _write(
        loader.root / "hotkeys" / "z_last.yaml",
        "ctrl+shift+m: user.last\n",
    )
    bundle = loader.load_all()
    assert bundle.hotkey_bindings["ctrl+shift+m"] == "user.last"


def test_hotkey_commands_wired_from_commands_py(
    loader: UserOverrideLoader,
) -> None:
    """A ``commands.py`` next to the YAML supplies ``user.*`` callables."""
    _write(
        loader.root / "hotkeys" / "keys.yaml",
        "ctrl+shift+m: user.my_command\n",
    )
    _write(
        loader.root / "hotkeys" / "commands.py",
        "calls = []\n"
        "def my_command():\n"
        "    calls.append(1)\n",
    )
    bundle = loader.load_all()
    assert "user.my_command" in bundle.hotkey_commands
    fn = bundle.hotkey_commands["user.my_command"]
    assert callable(fn)
    fn()  # should not raise


def test_hotkey_broken_yaml_logged(loader: UserOverrideLoader) -> None:
    """A malformed YAML file records an error but keeps other files."""
    _write(loader.root / "hotkeys" / "good.yaml", "ctrl+s: editor.save\n")
    _write(loader.root / "hotkeys" / "bad.yaml", "not: a: valid: yaml: [\n")
    bundle = loader.load_all()
    assert bundle.hotkey_bindings.get("ctrl+s") == "editor.save"
    assert any("bad.yaml" in p for p, _ in bundle.errors)


# ---------------------------------------------------------------------------
# Spawn actions
# ---------------------------------------------------------------------------


_GOOD_SPAWN = (
    "def get_spawn_card():\n"
    "    return {\n"
    "        'card_id': 'user.my_card',\n"
    "        'label': 'My Card',\n"
    "        'portrait_svg': '<svg/>',\n"
    "        'on_summon': lambda world: None,\n"
    "    }\n"
)

_BAD_SPAWN_RETURN = "def get_spawn_card():\n    return 42\n"

_BAD_SPAWN_MISSING_ID = "def get_spawn_card():\n    return {'label': 'x'}\n"


def test_spawn_actions_loaded(loader: UserOverrideLoader) -> None:
    """A well-formed spawn action lands in ``bundle.spawn_actions``."""
    _write(loader.root / "spawn_actions" / "my_spawn.py", _GOOD_SPAWN)
    bundle = loader.load_all()
    assert len(bundle.spawn_actions) == 1
    card = bundle.spawn_actions[0]
    assert card["card_id"] == "user.my_card"
    assert card["label"] == "My Card"
    assert callable(card["on_summon"])


def test_spawn_action_wrong_return_logged(loader: UserOverrideLoader) -> None:
    """Non-dict return values are recorded as errors."""
    _write(loader.root / "spawn_actions" / "bad.py", _BAD_SPAWN_RETURN)
    bundle = loader.load_all()
    assert bundle.spawn_actions == []
    assert bundle.errors and "bad.py" in bundle.errors[0][0]


def test_spawn_action_missing_card_id_logged(
    loader: UserOverrideLoader,
) -> None:
    """A dict missing ``card_id`` is rejected."""
    _write(loader.root / "spawn_actions" / "bad.py", _BAD_SPAWN_MISSING_ID)
    bundle = loader.load_all()
    assert bundle.spawn_actions == []
    assert bundle.errors


# ---------------------------------------------------------------------------
# Shaders
# ---------------------------------------------------------------------------


def test_shaders_discovered_by_parent_dir(loader: UserOverrideLoader) -> None:
    """Each shader's kind is derived from the parent directory name."""
    _write(
        loader.root / "shaders" / "page_linings" / "my_lining.wgsl",
        "// lining shader\n",
    )
    _write(
        loader.root / "shaders" / "washi_tape" / "my_tape.wgsl",
        "// tape shader\n",
    )
    _write(
        loader.root / "shaders" / "edge_strokes" / "my_stroke.wgsl",
        "// stroke shader\n",
    )
    listed = loader.list_user_shaders()
    kinds = {kind for kind, _ in listed}
    assert kinds == set(_SHADER_KINDS.values())

    bundle = loader.load_all()
    assert bundle.shaders["my_lining"].startswith("// lining")
    assert bundle.shader_kinds["my_lining"] == "page_linings"
    assert bundle.shader_kinds["my_tape"] == "washi_tape"
    assert bundle.shader_kinds["my_stroke"] == "edge_strokes"


def test_shaders_outside_kind_dirs_ignored(loader: UserOverrideLoader) -> None:
    """A shader directly under ``shaders/`` (no kind subdir) is skipped."""
    _write(
        loader.root / "shaders" / "orphan.wgsl",
        "// orphan\n",
    )
    bundle = loader.load_all()
    assert bundle.shaders == {}


# ---------------------------------------------------------------------------
# Config toggles
# ---------------------------------------------------------------------------


def test_config_defaults_when_missing(loader: UserOverrideLoader) -> None:
    """Absent ``config.yaml`` -> every category enabled."""
    loader.root.mkdir(parents=True)
    bundle = loader.load_all()
    for key, default in _CONFIG_DEFAULTS.items():
        assert bundle.config[key] == default


def test_config_disable_panels(loader: UserOverrideLoader) -> None:
    """``enable_user_panels: false`` prevents panel loading."""
    _write(loader.root / "panels" / "a.py", _GOOD_PANEL_A)
    _write(loader.root / "config.yaml", "enable_user_panels: false\n")
    bundle = loader.load_all()
    assert bundle.panels == []
    assert bundle.config["enable_user_panels"] is False


def test_config_disable_hotkeys(loader: UserOverrideLoader) -> None:
    """``enable_user_hotkeys: false`` prevents hotkey loading."""
    _write(loader.root / "hotkeys" / "k.yaml", "ctrl+s: editor.save\n")
    _write(loader.root / "config.yaml", "enable_user_hotkeys: false\n")
    bundle = loader.load_all()
    assert bundle.hotkey_bindings == {}


def test_config_disable_spawn_actions(loader: UserOverrideLoader) -> None:
    """``enable_user_spawn_actions: false`` prevents spawn card loading."""
    _write(loader.root / "spawn_actions" / "s.py", _GOOD_SPAWN)
    _write(loader.root / "config.yaml", "enable_user_spawn_actions: false\n")
    bundle = loader.load_all()
    assert bundle.spawn_actions == []


def test_config_disable_shaders(loader: UserOverrideLoader) -> None:
    """``enable_user_shaders: false`` prevents shader loading."""
    _write(
        loader.root / "shaders" / "page_linings" / "x.wgsl",
        "// x\n",
    )
    _write(loader.root / "config.yaml", "enable_user_shaders: false\n")
    bundle = loader.load_all()
    assert bundle.shaders == {}


def test_partial_config_merges_with_defaults(
    loader: UserOverrideLoader,
) -> None:
    """A partial ``config.yaml`` inherits defaults for missing keys."""
    _write(loader.root / "config.yaml", "enable_user_panels: false\n")
    bundle = loader.load_all()
    assert bundle.config["enable_user_panels"] is False
    assert bundle.config["enable_user_hotkeys"] is True  # default


# ---------------------------------------------------------------------------
# Full bundle round-trip
# ---------------------------------------------------------------------------


def test_full_bundle_carries_everything(loader: UserOverrideLoader) -> None:
    """A populated tree returns a bundle with every category filled."""
    _write(loader.root / "panels" / "p.py", _GOOD_PANEL_A)
    _write(loader.root / "hotkeys" / "k.yaml", "ctrl+shift+m: user.foo\n")
    _write(loader.root / "spawn_actions" / "s.py", _GOOD_SPAWN)
    _write(
        loader.root / "shaders" / "page_linings" / "l.wgsl",
        "// lining\n",
    )
    bundle = loader.load_all()
    summary = bundle.summary()
    assert summary["panels"] == 1
    assert summary["hotkeys"] == 1
    assert summary["spawn_actions"] == 1
    assert summary["shaders"] == 1
    assert summary["errors"] == 0
