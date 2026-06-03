"""Default-project scaffolding.

When a new :class:`~slappyengine.projects.project.Project` is created
the engine writes a small starter directory tree so the first-launch
experience is *something* opens-and-runs rather than an empty folder.
The layout is intentionally minimal so it does not race with
opinionated game templates the editor may add later:

.. code-block:: text

    <root>/
      project.slap_proj      # YAML metadata (written by Project.new)
      scenes/
        main.scene.yaml      # welcome scene stub
      assets/
        README.md            # "drop your assets here" placeholder
      scripts/
        main.py              # entry-point stub
      icon.png               # 64x64 placeholder icon

The icon is rendered with PIL when available so an unconfigured editor
shows *something* rather than a missing-image glyph; if PIL is not
present the icon step is skipped silently (the welcome screen will
fall back to the engine default icon).
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from .project import Project


__all__ = ["scaffold_project"]


# ---------------------------------------------------------------------------
# Seed file bodies — kept module-level so they can be inspected from tests
# (e.g. "the scene stub mentions the project name") without re-parsing.
# ---------------------------------------------------------------------------


_MAIN_SCENE_TEMPLATE = """\
# Welcome scene — edit me!
#
# Open the editor with ``slappy editor`` (or your IDE's launch button)
# to load this scene visually. Every YAML key under ``entities`` becomes
# an :class:`slappyengine.Entity`.
name: "{name}"
camera:
  position: [0.0, 0.0]
  zoom: 1.0
entities: []
"""


_ASSETS_README = """\
# {name} — assets

Drop sprite sheets, audio files, fonts, and any other game assets here.

The engine's :class:`slappyengine.assets.AssetDatabase` scans this
directory recursively at startup; sub-folders are fine (use them to
group by domain — ``ui/``, ``sfx/``, ``levels/`` …).
"""


_MAIN_PY_TEMPLATE = '''\
"""{name} — entry point.

Run this file with ``python scripts/main.py`` or via the editor's
"Play" button.
"""
from __future__ import annotations

from slappyengine import Engine, Scene


def main() -> None:
    """Boot the engine on the welcome scene."""
    engine = Engine()
    scene = Scene.from_yaml("scenes/main.scene.yaml")
    engine.run(scene)


if __name__ == "__main__":
    main()
'''


_PLACEHOLDER_ICON_NOTE = (
    "# Placeholder icon — drop a custom ``icon.png`` here to replace it.\n"
)


# ---------------------------------------------------------------------------
# scaffold_project
# ---------------------------------------------------------------------------


def scaffold_project(project: "Project") -> dict[str, Path]:
    """Create the default directory tree for *project*.

    Idempotent: existing files are *not* overwritten so re-scaffolding
    a partially populated project preserves user content.

    Parameters
    ----------
    project:
        Project to scaffold. ``project.path`` is created if missing.

    Returns
    -------
    dict[str, Path]
        Mapping ``{"scenes_dir", "assets_dir", "scripts_dir",
        "main_scene", "assets_readme", "main_py", "icon"}`` →
        absolute paths to the seeded files / dirs.
    """
    # Local import to avoid the project → scaffolding circular at module
    # load (scaffold_project is called from Project.new).
    from .project import Project

    if not isinstance(project, Project):
        raise TypeError(
            f"scaffold_project: expected Project; got {type(project).__name__}"
        )

    root = project.path
    root.mkdir(parents=True, exist_ok=True)

    scenes = root / "scenes"
    assets = root / "assets"
    scripts = root / "scripts"
    for d in (scenes, assets, scripts):
        d.mkdir(parents=True, exist_ok=True)

    name = project.metadata.name

    main_scene = scenes / "main.scene.yaml"
    if not main_scene.exists():
        main_scene.write_text(
            _MAIN_SCENE_TEMPLATE.format(name=name), encoding="utf-8",
        )

    assets_readme = assets / "README.md"
    if not assets_readme.exists():
        assets_readme.write_text(
            _ASSETS_README.format(name=name), encoding="utf-8",
        )

    main_py = scripts / "main.py"
    if not main_py.exists():
        main_py.write_text(
            _MAIN_PY_TEMPLATE.format(name=name), encoding="utf-8",
        )

    icon = root / "icon.png"
    if not icon.exists():
        _write_placeholder_icon(icon)

    return {
        "scenes_dir": scenes,
        "assets_dir": assets,
        "scripts_dir": scripts,
        "main_scene": main_scene,
        "assets_readme": assets_readme,
        "main_py": main_py,
        "icon": icon,
    }


# ---------------------------------------------------------------------------
# Placeholder icon
# ---------------------------------------------------------------------------


def _write_placeholder_icon(path: Path) -> None:
    """Render a tiny 64x64 PNG with the engine's mark, or fall back.

    If Pillow is available we paint a teen-girl-notebook-themed pink
    square with a centred capital "S". If PIL is not installed (CI on
    a slim image) we drop a one-line text file at the same path so
    callers checking ``icon.exists()`` still see *something* — the
    engine's image loader recognises the ``# Placeholder icon`` first
    line and falls back to the default icon at runtime.
    """
    try:
        from PIL import Image, ImageDraw  # noqa: WPS433 — soft dep
    except ImportError:
        # Soft fallback so a Pillow-less environment still has a file
        # at the expected location. The leading ``#`` is so any code
        # that later tries to read it as PNG bytes can detect the stub.
        path.write_text(_PLACEHOLDER_ICON_NOTE, encoding="utf-8")
        return

    size = 64
    bg = (255, 192, 215, 255)  # notebook pink
    fg = (98, 32, 64, 255)     # plum ink
    img = Image.new("RGBA", (size, size), bg)
    draw = ImageDraw.Draw(img)
    # Draw a centred capital "S" using the default bitmap font (small
    # but always available — every Pillow ships at least the default
    # bitmap fontset).
    text = "S"
    try:
        bbox = draw.textbbox((0, 0), text)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
    except AttributeError:
        # Pillow < 9.2: textsize is the older API.
        tw, th = draw.textsize(text)
    draw.text(((size - tw) / 2, (size - th) / 2 - 4), text, fill=fg)
    img.save(path, format="PNG")
