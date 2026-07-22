"""Pharos Engine project scaffolder.

Usage::

    from pharos_engine.build.scaffolder import scaffold_project

    project_path = scaffold_project("MyGame", "C:/Projects", template="2d")
"""
from __future__ import annotations

import shutil
from pathlib import Path

# ---------------------------------------------------------------------------
# Engine-config source (resolved relative to this file at import time)
# ---------------------------------------------------------------------------
_ENGINE_CONFIG_SRC = Path(__file__).parent.parent.parent.parent / "config" / "engine.yml"

# ---------------------------------------------------------------------------
# Template: main.py content
# ---------------------------------------------------------------------------

_MAIN_BLANK = """\
import pharos_engine as se

engine = se.Engine()
engine.run()
"""

_MAIN_2D = """\
import pharos_engine as se

scene = se.Scene(name="Main")

# Placeholder entity
player = se.Entity(name="Player")
player.position = (0.0, 0.0)
scene.add(player)

# Basic lighting
lighting = se.LightingSystem()
lighting.ambient_color = (0.2, 0.2, 0.25)
scene.set_lighting(lighting)

engine = se.Engine()
engine.load_scene(scene)
engine.run()
"""

_MAIN_3D = """\
import pharos_engine as se

scene = se.Scene(name="Main")

# Placeholder entity
prop = se.Entity(name="Prop")
prop.position = (0.0, 0.0, 0.0)
scene.add(prop)

engine = se.Engine()
engine.enable_ibl()
engine.load_scene(scene)
engine.run()
"""

_TEMPLATE_MAINS: dict[str, str] = {
    "blank": _MAIN_BLANK,
    "2d": _MAIN_2D,
    "3d": _MAIN_3D,
}

# ---------------------------------------------------------------------------
# Static file contents
# ---------------------------------------------------------------------------

_GITIGNORE = """\
Builds/
.slap_cache/
__pycache__/
*.pyc
*.pyd
.venv/
"""

_EDITOR_YML = """\
# Editor shortcut overrides (leave empty to use engine defaults)
shortcuts: {}
"""

_HUD_YML = """\
# HUD layout stub (define panels and widget positions here)
layout: {}
"""

_BUILD_SETTINGS_YML = """\
# Build settings — override per-platform values in Config/platform/
output_dir: Builds
compression: lz4
strip_debug: true
"""

_LOCALIZATION_EN = """\
# English localisation strings
hello_world: "Hello, World!"
"""

_DESKTOP_YML = """\
rendering:
  backend: auto
"""

_MOBILE_YML = """\
rendering:
  backend: vulkan
  max_texture_size: 2048
"""

_WEB_YML = """\
rendering:
  backend: webgpu
  max_texture_size: 1024
"""

_TESTS_INIT = """\
"""

# ---------------------------------------------------------------------------
# Batch scripts
# ---------------------------------------------------------------------------

_BAT_EXE = """\
@echo off
slap build --target exe --release
pause
"""

_BAT_APK = """\
@echo off
slap build --target apk --release
pause
"""

_BAT_WEB = """\
@echo off
slap build --target web --release
pause
"""

_BAT_TESTS = """\
@echo off
slap test
pause
"""

_BAT_DEV = """\
@echo off
slap run --dev
pause
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mkdir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    # Print relative to the project root (parent of path's root component)
    print(f"  + {path.name}/")


def _write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def _slap_proj_manifest(name: str, template: str) -> str:
    return (
        f"name: {name}\n"
        f"version: 1\n"
        f'engine_version: "0.1.0"\n'
        f"template: {template}\n"
        f"entry: Source/main.py\n"
        f"scenes: []\n"
        f"assets_dir: Content/Assets\n"
    )


def _readme(name: str) -> str:
    return (
        f"# {name}\n\n"
        f"A Pharos Engine project.\n\n"
        f"Run with: `python Source/main.py`\n"
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def scaffold_project(name: str, parent_dir: str, template: str = "blank") -> Path:
    """Create a new Pharos Engine project scaffold.

    Parameters
    ----------
    name:
        Project name (used as the root directory name).
    parent_dir:
        Parent directory under which the project folder will be created.
    template:
        One of ``"blank"``, ``"2d"``, or ``"3d"``.

    Returns
    -------
    Path
        Absolute path to the newly created project root.
    """
    if template not in _TEMPLATE_MAINS:
        raise ValueError(
            f"Unknown template {template!r}. Choose from: {sorted(_TEMPLATE_MAINS)}"
        )

    root = Path(parent_dir).resolve() / name
    print(f"Scaffolding project '{name}' at {root}")

    # ------------------------------------------------------------------
    # Content/
    # ------------------------------------------------------------------
    content_dir = root / "Content"
    _mkdir(content_dir)

    scenes_dir = content_dir / "Scenes"
    _mkdir(scenes_dir)

    assets_dir = content_dir / "Assets"
    _mkdir(assets_dir)

    for sub in ("sprites", "audio", "meshes", "maps", "fonts"):
        _mkdir(assets_dir / sub)

    loc_dir = content_dir / "Localization"
    _mkdir(loc_dir)
    _write(loc_dir / "en.yml", _LOCALIZATION_EN)

    # ------------------------------------------------------------------
    # Source/
    # ------------------------------------------------------------------
    source_dir = root / "Source"
    _mkdir(source_dir)
    _write(source_dir / "main.py", _TEMPLATE_MAINS[template])

    tests_dir = source_dir / "tests"
    _mkdir(tests_dir)
    _write(tests_dir / "__init__.py", _TESTS_INIT)

    # ------------------------------------------------------------------
    # Config/
    # ------------------------------------------------------------------
    config_dir = root / "Config"
    _mkdir(config_dir)

    # Copy engine.yml from the engine distribution
    engine_yml_dst = config_dir / "engine.yml"
    if _ENGINE_CONFIG_SRC.exists():
        shutil.copy2(_ENGINE_CONFIG_SRC, engine_yml_dst)
    else:
        # Fallback: write an empty stub so the project is still usable
        _write(engine_yml_dst, "# engine configuration — fill in from engine defaults\n")

    _write(config_dir / "editor.yml", _EDITOR_YML)
    _write(config_dir / "hud.yml", _HUD_YML)
    _write(config_dir / "build_settings.yml", _BUILD_SETTINGS_YML)

    platform_dir = config_dir / "platform"
    _mkdir(platform_dir)
    _write(platform_dir / "desktop.yml", _DESKTOP_YML)
    _write(platform_dir / "mobile.yml", _MOBILE_YML)
    _write(platform_dir / "web.yml", _WEB_YML)

    # ------------------------------------------------------------------
    # Builds/
    # ------------------------------------------------------------------
    builds_dir = root / "Builds"
    _mkdir(builds_dir)
    for sub in ("EXE", "APK", "Web"):
        _mkdir(builds_dir / sub)

    # ------------------------------------------------------------------
    # Root files
    # ------------------------------------------------------------------
    _write(root / ".gitignore", _GITIGNORE)
    _write(root / "README.md", _readme(name))
    _write(root / "project.slap_proj", _slap_proj_manifest(name, template))
    _write(root / "Build_EXE.bat", _BAT_EXE)
    _write(root / "Build_APK.bat", _BAT_APK)
    _write(root / "Build_Web.bat", _BAT_WEB)
    _write(root / "Run_Tests.bat", _BAT_TESTS)
    _write(root / "Run_Dev.bat", _BAT_DEV)

    print(f"Done. Project created at {root}")
    return root
