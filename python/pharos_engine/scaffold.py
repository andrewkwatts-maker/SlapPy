"""Project scaffolder for SlapPyEngine (HH2).

This module builds new SlapPyEngine game projects from templates.  It powers
the ``slap new`` / ``slap launch`` / ``slap dev`` / ``slap config`` CLI
subcommands defined in :mod:`pharos_engine.cli` and can also be used as a
library::

    from pharos_engine import scaffold
    project_dir = scaffold.create_project("my_game", "./games")
    scaffold.launch_project(project_dir)

Design goals
------------
* **Zero engine imports at scaffold time** — the template strings are pure
  Python source so the scaffolder can run on a fresh install without pulling
  the whole engine.
* **Cross-platform launchers** — every project ships with ``.bat``, ``.ps1``
  and ``.sh`` variants for launching and (optionally) launching the editor.
* **Editor is optional** — if the ``pharos_engine[editor]`` extra is not
  installed the ``launch_editor.*`` scripts print a helpful install message
  rather than silently failing.
* **Temp projects for lambdas** — :func:`create_temp_project` scaffolds a
  disposable project into ``~/.pharos_engine/temp_projects/`` so users can
  pass in ``on_begin`` / ``on_tick`` / ``on_end`` lambdas without committing
  to a folder layout.

The template list is exposed as :data:`PROJECT_TEMPLATE` so callers (and
tests) can enumerate the exact set of files that a fresh project contains.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from string import Template
from typing import Callable, Iterable

__all__ = [
    "TemplateFile",
    "PROJECT_TEMPLATE",
    "DEFAULT_APP_CONFIG",
    "PROJECT_MARKER",
    "create_project",
    "create_temp_project",
    "is_project_dir",
    "launch_project",
    "regenerate_config",
    "editor_installed",
    "render_template",
    "temp_projects_root",
]


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TemplateFile:
    """Single file inside :data:`PROJECT_TEMPLATE`.

    ``content_template`` uses :class:`string.Template` substitution — the
    following placeholders are supported and expanded by
    :func:`render_template`::

        ${project_name}   — sanitised project name (also directory basename)
        ${project_title}  — human-readable project title
        ${created_iso}    — ISO-8601 timestamp of scaffold creation
        ${engine_version} — best-effort engine version string

    ``executable`` is advisory: on POSIX we ``chmod +x`` matching files after
    write.  ``binary`` short-circuits template rendering — currently unused
    but reserved for future binary asset templates.
    """

    relative_path: str
    content_template: str
    executable: bool = False
    binary: bool = False


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


#: Marker file that identifies a scaffolded project directory.  Written by
#: :func:`create_project` and detected by :func:`is_project_dir`.
PROJECT_MARKER = ".slappyproject"


#: Default AppConfig YAML — every option is documented inline so users can
#: discover the full surface area by opening ``config.yaml`` in an editor.
DEFAULT_APP_CONFIG = """\
# ---------------------------------------------------------------------------
# SlapPyEngine project config for ${project_title}
# Generated ${created_iso} by pharos_engine ${engine_version}
# ---------------------------------------------------------------------------
# Every option below is documented with its default value.  Delete a key to
# fall back to the engine default, or edit the value to override it.
# ---------------------------------------------------------------------------

project:
  name: ${project_name}
  title: ${project_title}
  version: 0.1.0

window:
  title: ${project_title}
  width: 1280
  height: 720
  clear_color: [0.05, 0.06, 0.09, 1.0]
  vsync: true

rendering:
  max_layers_per_asset: 32
  max_frames_per_animation: 64
  texture_format: rgba8unorm
  backend: auto            # auto | vulkan | metal | dx12 | gl
  power_preference: high_performance

physics:
  default_dt: 0.016667
  substeps: 1

audio:
  master_volume: 1.0
  music_volume: 0.7
  sfx_volume: 1.0

input:
  default_player0: wasd
  default_player1: arrows

lighting:
  enabled: true
  ambient_intensity: 0.15
  clustered_lighting: true

fluid_sim:
  enabled: false

editor:
  autoload_scene: null
  hot_reload: true

scripts:
  begin: begin.py          # called once at startup after engine boots
  tick: tick.py            # called every frame with (app, dt)
  end: end.py              # called once at shutdown

assets:
  # Additional asset search paths relative to the project root.
  paths:
    - assets/

scenes:
  # Additional scene search paths relative to the project root.
  paths:
    - scenes/
"""


# ---------------------------------------------------------------------------
# Template file contents
# ---------------------------------------------------------------------------


_BEGIN_PY = '''\
"""begin.py — called once at project startup.

The ``begin`` function is invoked by ``main.py`` after the engine boots but
before the first tick.  Use it to load scenes, spawn initial entities, and
register event handlers.
"""
from __future__ import annotations


def begin(app) -> None:
    """Called once at startup.  ``app`` is the running Engine/App instance."""
    # TODO: load a scene, spawn entities, wire up systems
    pass
'''


_TICK_PY = '''\
"""tick.py — called every frame.

The ``tick`` function receives ``(app, dt)`` where ``dt`` is the frame time
in seconds.  Keep the work here bounded — heavy simulation should live in
engine subsystems, not the user tick.
"""
from __future__ import annotations


def tick(app, dt: float) -> None:
    """Called every frame.  ``dt`` is the frame duration in seconds."""
    # TODO: per-frame game logic
    pass
'''


_END_PY = '''\
"""end.py — called once at project shutdown.

The ``end`` function fires after the main loop exits.  Use it to persist
save data, flush logs, and release external resources.
"""
from __future__ import annotations


def end(app) -> None:
    """Called once at shutdown."""
    # TODO: save game state, close files, teardown
    pass
'''


_MAIN_PY = '''\
"""${project_title} — entry point.

Run with::

    python main.py

or via a launcher script::

    ./launch.sh          # POSIX
    launch.bat           # Windows cmd
    launch.ps1           # Windows PowerShell

This file wires the ``begin`` / ``tick`` / ``end`` hooks from
``begin.py`` / ``tick.py`` / ``end.py`` into the engine's main loop.  You
normally do not need to edit it — customise the per-hook files instead.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Make sibling modules importable when launched from any cwd
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from begin import begin  # noqa: E402
from tick import tick    # noqa: E402
from end import end      # noqa: E402


def _make_app():
    """Build the engine/App instance.

    Newer engine releases expose ``pharos_engine.App``; older releases only
    expose :class:`pharos_engine.Engine`.  We try App first and fall back to
    Engine so this scaffold works across versions.
    """
    try:
        from pharos_engine import App  # type: ignore[attr-defined]
        return App(config_path=str(_HERE / "config.yaml"))
    except (ImportError, AttributeError):
        from pharos_engine import Engine
        # Engine takes a config path directly
        cfg = _HERE / "config.yaml"
        return Engine(config_path=str(cfg) if cfg.exists() else None)


def main() -> int:
    app = _make_app()

    # Attach lifecycle hooks — every attribute is optional so we probe first.
    for name, fn in (("on_begin", begin), ("on_tick", tick), ("on_end", end)):
        if hasattr(app, name):
            setattr(app, name, fn)

    # Run the main loop.  ``run()`` is the canonical entry point for both
    # ``App`` and ``Engine``; a smoke_frames kwarg is accepted by newer
    # releases for CI runs.
    smoke = int((os.environ.get("SLAPPY_SMOKE_FRAMES") or "0"))
    try:
        if smoke > 0 and "smoke_frames" in getattr(app.run, "__code__", type("x", (), {"co_varnames": ()})).co_varnames:
            app.run(smoke_frames=smoke)
        else:
            # In headless / no-display environments, fall back to a smoke run
            if smoke > 0:
                app.run()
            else:
                app.run()
    finally:
        # Best-effort end hook — always fires even on exception
        try:
            end(app)
        except Exception as exc:  # pragma: no cover - defensive
            print(f"end() raised: {exc}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


_GITIGNORE = """\
# Python
__pycache__/
*.py[cod]
*.egg-info/
.venv/
venv/
env/

# SlapPyEngine
*.blob
assets/**/*.blob
build/
dist/
*.log

# Editor / IDE
.idea/
.vscode/
*.swp
.DS_Store
"""


_README = """\
# ${project_title}

A SlapPyEngine project scaffolded on ${created_iso}.

## Quickstart

```
python main.py            # or double-click launch.bat / launch.ps1 / ./launch.sh
```

## Layout

| Path             | Purpose                                             |
| ---------------- | --------------------------------------------------- |
| `main.py`        | Entry point — wires begin/tick/end into the engine. |
| `begin.py`       | `begin(app)` — one-shot startup hook.               |
| `tick.py`        | `tick(app, dt)` — per-frame update hook.            |
| `end.py`         | `end(app)` — shutdown hook.                         |
| `config.yaml`    | Project + engine configuration (fully commented).   |
| `assets/`        | Textures, audio, sprite atlases, prefab YAML.       |
| `scenes/`        | Scene YAML / JSON files.                            |
| `launch.*`       | Cross-platform launcher scripts.                    |
| `build.*`        | Install deps + run — useful for fresh clones.       |
| `launch_editor.*`| Launches the SlapPyEngine editor (extra required).  |

## Editing config

`config.yaml` is generated with every option documented.  Delete a key to
fall back to the engine default, or run `slap config` to reconcile your
file against the current defaults.
"""


_LAUNCH_BAT = """\
@echo off
REM ${project_title} — Windows launcher
setlocal
set "PROJECT_DIR=%~dp0"
set "PYTHONPATH=%PROJECT_DIR%;%PYTHONPATH%"

REM Activate a local venv if one exists
if exist "%PROJECT_DIR%.venv\\Scripts\\activate.bat" (
    call "%PROJECT_DIR%.venv\\Scripts\\activate.bat"
)

python "%PROJECT_DIR%main.py" %*
set EC=%ERRORLEVEL%
endlocal & exit /b %EC%
"""


_LAUNCH_PS1 = """\
# ${project_title} — PowerShell launcher
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$env:PYTHONPATH = "$ProjectDir;$env:PYTHONPATH"

# Activate a local venv if one exists
$Activate = Join-Path $ProjectDir ".venv\\Scripts\\Activate.ps1"
if (Test-Path $Activate) {
    . $Activate
}

python (Join-Path $ProjectDir "main.py") @args
exit $LASTEXITCODE
"""


_LAUNCH_SH = """\
#!/usr/bin/env bash
# ${project_title} — POSIX launcher
set -e
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="$PROJECT_DIR:$PYTHONPATH"

# Activate a local venv if one exists
if [ -f "$PROJECT_DIR/.venv/bin/activate" ]; then
    # shellcheck disable=SC1091
    . "$PROJECT_DIR/.venv/bin/activate"
fi

python "$PROJECT_DIR/main.py" "$@"
exit $?
"""


_BUILD_BAT = """\
@echo off
REM ${project_title} — install deps and run
setlocal
set "PROJECT_DIR=%~dp0"
pushd "%PROJECT_DIR%"

echo Installing / upgrading dependencies...
python -m pip install --upgrade pharos-engine pyyaml
if errorlevel 1 goto :fail

echo Launching...
python "%PROJECT_DIR%main.py" %*
set EC=%ERRORLEVEL%
popd
endlocal & exit /b %EC%

:fail
popd
endlocal & exit /b 1
"""


_BUILD_SH = """\
#!/usr/bin/env bash
# ${project_title} — install deps and run
set -e
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Installing / upgrading dependencies..."
python -m pip install --upgrade pharos-engine pyyaml

echo "Launching..."
python "$PROJECT_DIR/main.py" "$@"
exit $?
"""


_LAUNCH_EDITOR_BAT = """\
@echo off
REM ${project_title} — launch the SlapPyEngine editor
setlocal
set "PROJECT_DIR=%~dp0"
set "PYTHONPATH=%PROJECT_DIR%;%PYTHONPATH%"

python -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('pharos_editor.ui.editor') else 1)"
if errorlevel 1 (
    echo.
    echo The SlapPyEngine editor is not installed.
    echo Install it with:  pip install "pharos-engine[editor]"
    echo.
    exit /b 1
)

python -m pharos_editor.ui.editor "%PROJECT_DIR%" %*
set EC=%ERRORLEVEL%
endlocal & exit /b %EC%
"""


_LAUNCH_EDITOR_PS1 = """\
# ${project_title} — launch the SlapPyEngine editor
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$env:PYTHONPATH = "$ProjectDir;$env:PYTHONPATH"

$probe = python -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('pharos_editor.ui.editor') else 1)"
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "The SlapPyEngine editor is not installed."
    Write-Host 'Install it with:  pip install "pharos-engine[editor]"'
    Write-Host ""
    exit 1
}

python -m pharos_editor.ui.editor $ProjectDir @args
exit $LASTEXITCODE
"""


_LAUNCH_EDITOR_SH = """\
#!/usr/bin/env bash
# ${project_title} — launch the SlapPyEngine editor
set -e
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="$PROJECT_DIR:$PYTHONPATH"

if ! python -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('pharos_editor.ui.editor') else 1)"; then
    echo
    echo "The SlapPyEngine editor is not installed."
    echo 'Install it with:  pip install "pharos-engine[editor]"'
    echo
    exit 1
fi

python -m pharos_editor.ui.editor "$PROJECT_DIR" "$@"
exit $?
"""


_ASSETS_README = """\
# Assets

Drop textures, sprite atlases, audio, and prefab YAML into this folder.
`config.yaml` lists this directory under `assets.paths` so the engine will
discover files placed here automatically.
"""


_SCENES_README = """\
# Scenes

Scene YAML / JSON files live here.  Load one from `begin.py` via
`app.load_scene("scenes/main.yaml")` once the engine exposes a scene loader.
"""


# ---------------------------------------------------------------------------
# Project template
# ---------------------------------------------------------------------------


PROJECT_TEMPLATE: list[TemplateFile] = [
    TemplateFile(".slappyproject", "name: ${project_name}\ncreated: ${created_iso}\nengine: ${engine_version}\n"),
    TemplateFile("begin.py", _BEGIN_PY),
    TemplateFile("tick.py", _TICK_PY),
    TemplateFile("end.py", _END_PY),
    TemplateFile("main.py", _MAIN_PY),
    TemplateFile("config.yaml", DEFAULT_APP_CONFIG),
    TemplateFile("README.md", _README),
    TemplateFile(".gitignore", _GITIGNORE),
    TemplateFile("assets/README.md", _ASSETS_README),
    TemplateFile("scenes/README.md", _SCENES_README),
    TemplateFile("launch.bat", _LAUNCH_BAT),
    TemplateFile("launch.ps1", _LAUNCH_PS1),
    TemplateFile("launch.sh", _LAUNCH_SH, executable=True),
    TemplateFile("build.bat", _BUILD_BAT),
    TemplateFile("build.sh", _BUILD_SH, executable=True),
    TemplateFile("launch_editor.bat", _LAUNCH_EDITOR_BAT),
    TemplateFile("launch_editor.ps1", _LAUNCH_EDITOR_PS1),
    TemplateFile("launch_editor.sh", _LAUNCH_EDITOR_SH, executable=True),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _engine_version() -> str:
    try:
        from pharos_engine import __version__ as v  # type: ignore
        return str(v)
    except Exception:
        return "unknown"


def _sanitise_name(name: str) -> str:
    """Return a filesystem-safe project identifier.

    Rules mirror what ``pip`` / ``setuptools`` accept for distribution names:
    ASCII letters, digits, ``_`` and ``-``.  Whitespace is replaced with
    underscores; other characters are stripped.
    """
    if not name or not name.strip():
        raise ValueError("project name must not be empty")
    out = []
    for ch in name.strip():
        if ch.isalnum() or ch in "_-":
            out.append(ch)
        elif ch.isspace() or ch in "._":
            out.append("_")
        # else: drop
    sanitised = "".join(out)
    if not sanitised or sanitised[0] in "-_":
        sanitised = "project_" + sanitised.lstrip("-_")
    return sanitised


def _title_from_name(name: str) -> str:
    words = name.replace("_", " ").replace("-", " ").split()
    return " ".join(w.capitalize() for w in words) if words else name


def render_template(template: str, context: dict) -> str:
    """Substitute ``${...}`` placeholders using :class:`string.Template`.

    Unknown placeholders are left in place (via ``safe_substitute``) so that
    templates containing e.g. shell ``${BASH_SOURCE[0]}`` don't blow up.
    """
    return Template(template).safe_substitute(context)


def editor_installed() -> bool:
    """Return True if the ``pharos_engine[editor]`` extra can be imported."""
    import importlib.util
    return importlib.util.find_spec("pharos_editor.ui.editor") is not None


def temp_projects_root() -> Path:
    """Directory that holds temp projects created by :func:`create_temp_project`."""
    root = Path(os.environ.get("SLAPPY_TEMP_ROOT", str(Path.home() / ".pharos_engine" / "temp_projects")))
    root.mkdir(parents=True, exist_ok=True)
    return root


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def create_project(
    name: str,
    dest_dir: str | Path | None = None,
    *,
    editor: bool = True,
    overwrite: bool = False,
    extra_context: dict | None = None,
) -> Path:
    """Scaffold a new SlapPyEngine project.

    Parameters
    ----------
    name
        Project name.  Sanitised into an ASCII-safe identifier; the
        original string is also used as the human-readable title.
    dest_dir
        Parent directory.  The project is created at ``dest_dir / name``.
        Defaults to the current working directory.
    editor
        If False, the ``launch_editor.*`` scripts are omitted.
    overwrite
        If True, an existing project directory is replaced.  Without this
        flag :class:`FileExistsError` is raised when the target exists.
    extra_context
        Additional placeholders merged into the template context.

    Returns
    -------
    Path
        Absolute path to the created project directory.
    """
    safe_name = _sanitise_name(name)
    title = _title_from_name(name)
    parent = Path(dest_dir).resolve() if dest_dir is not None else Path.cwd()
    parent.mkdir(parents=True, exist_ok=True)

    project_dir = parent / safe_name
    if project_dir.exists():
        if not overwrite:
            raise FileExistsError(f"project directory already exists: {project_dir}")
        shutil.rmtree(project_dir)
    project_dir.mkdir(parents=True)

    context = {
        "project_name": safe_name,
        "project_title": title,
        "created_iso": _dt.datetime.now().isoformat(timespec="seconds"),
        "engine_version": _engine_version(),
    }
    if extra_context:
        context.update(extra_context)

    for tpl in PROJECT_TEMPLATE:
        if not editor and tpl.relative_path.startswith("launch_editor."):
            continue
        target = project_dir / tpl.relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        if tpl.binary:
            target.write_bytes(tpl.content_template.encode("utf-8"))
        else:
            target.write_text(render_template(tpl.content_template, context), encoding="utf-8")
        if tpl.executable and os.name != "nt":
            try:
                target.chmod(target.stat().st_mode | 0o111)
            except OSError:
                pass

    return project_dir


def create_temp_project(
    *,
    name: str | None = None,
    config_yaml: str | None = None,
    config_json: str | dict | None = None,
    editor: bool = False,
    on_begin: Callable | None = None,
    on_tick: Callable | None = None,
    on_end: Callable | None = None,
) -> Path:
    """Create a disposable project in ``~/.pharos_engine/temp_projects/``.

    Callers can pass raw YAML text, a JSON blob (string or dict), or nothing
    at all — the default config is written when neither is supplied.  The
    ``on_begin`` / ``on_tick`` / ``on_end`` callables, when provided, are
    stringified into ``begin.py`` / ``tick.py`` / ``end.py`` via
    :func:`inspect.getsource`; if the source is not available (e.g. a
    lambda in the REPL) a stub calling ``pickle`` is not attempted — we
    fall back to the default empty hook and log a warning to stderr.

    Returns the absolute path to the freshly created temp project.
    """
    stamp = time.strftime("%Y%m%d_%H%M%S")
    short_uuid = uuid.uuid4().hex[:8]
    base_name = name or f"temp_{stamp}_{short_uuid}"
    root = temp_projects_root()
    # Ensure uniqueness even if the caller supplied the same explicit name twice
    project_dir = root / base_name
    n = 1
    while project_dir.exists():
        project_dir = root / f"{base_name}_{n}"
        n += 1

    project_dir = create_project(project_dir.name, root, editor=editor, overwrite=False)

    # Override config with user-supplied YAML/JSON
    cfg_path = project_dir / "config.yaml"
    if config_yaml is not None:
        cfg_path.write_text(config_yaml, encoding="utf-8")
    elif config_json is not None:
        import yaml
        data = config_json if isinstance(config_json, dict) else json.loads(config_json)
        cfg_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    # Best-effort lambda -> file wiring
    for hook_name, fn, filename, sig in (
        ("begin", on_begin, "begin.py", "def begin(app) -> None:"),
        ("tick", on_tick, "tick.py", "def tick(app, dt: float) -> None:"),
        ("end", on_end, "end.py", "def end(app) -> None:"),
    ):
        if fn is None:
            continue
        source = _try_getsource(fn)
        if source is None:
            print(
                f"warning: cannot serialize on_{hook_name} callable "
                "(likely a lambda from the REPL); keeping default stub",
                file=sys.stderr,
            )
            continue
        (project_dir / filename).write_text(
            f'"""Auto-generated {hook_name} hook (temp project)."""\n'
            f"from __future__ import annotations\n\n"
            f"{source}\n\n"
            f"# Re-export under the canonical name so main.py can import it\n"
            f"if '{hook_name}' not in globals():\n"
            f"    # user function has a different name — wrap it\n"
            f"    _user = list(v for k, v in list(globals().items()) if callable(v) and not k.startswith('_'))[-1]\n"
            f"    {sig}\n"
            f"        _user(app)  # best-effort dispatch\n",
            encoding="utf-8",
        )

    return project_dir


def _try_getsource(fn: Callable) -> str | None:
    import inspect
    try:
        return inspect.getsource(fn)
    except (OSError, TypeError):
        return None


def is_project_dir(path: str | Path) -> bool:
    """Return True if *path* looks like a scaffolded SlapPyEngine project.

    We require the marker file *and* the three lifecycle hooks — a directory
    that only contains one of these is treated as ambiguous and rejected.
    """
    p = Path(path)
    if not p.is_dir():
        return False
    marker = p / PROJECT_MARKER
    if not marker.is_file():
        return False
    for required in ("begin.py", "tick.py", "end.py", "main.py"):
        if not (p / required).is_file():
            return False
    return True


def launch_project(
    path: str | Path,
    *,
    editor: bool = False,
    dry_run: bool = False,
    extra_args: Iterable[str] = (),
    env: dict | None = None,
) -> subprocess.CompletedProcess | list[str]:
    """Launch a scaffolded project by shelling out to ``python main.py``.

    Parameters
    ----------
    path
        Project directory (created by :func:`create_project`).
    editor
        When True, invoke ``python -m pharos_editor.ui.editor <path>`` instead
        of ``main.py``.  If the editor extra is not installed a
        :class:`RuntimeError` is raised.
    dry_run
        Return the command list without executing it — used by CLI tests.
    extra_args
        Extra arguments appended to the command line.
    env
        Additional environment variables (merged on top of ``os.environ``).
    """
    p = Path(path).resolve()
    if not is_project_dir(p):
        raise FileNotFoundError(f"not a SlapPyEngine project: {p}")

    if editor:
        if not editor_installed():
            raise RuntimeError(
                "editor extra not installed — pip install 'pharos-engine[editor]'"
            )
        cmd = [sys.executable, "-m", "pharos_editor.ui.editor", str(p)]
    else:
        cmd = [sys.executable, str(p / "main.py")]
    cmd.extend(list(extra_args))

    if dry_run:
        return cmd

    run_env = os.environ.copy()
    # Prepend the project dir to PYTHONPATH so main.py's siblings import cleanly
    pythonpath = os.pathsep.join(filter(None, [str(p), run_env.get("PYTHONPATH", "")]))
    run_env["PYTHONPATH"] = pythonpath
    if env:
        run_env.update({str(k): str(v) for k, v in env.items()})

    return subprocess.run(cmd, cwd=str(p), env=run_env)


# ---------------------------------------------------------------------------
# Config regeneration
# ---------------------------------------------------------------------------


def regenerate_config(path: str | Path, *, preserve: bool = True) -> Path:
    """Regenerate ``config.yaml`` at *path*, filling in missing keys.

    Existing top-level keys are preserved when ``preserve=True`` (the
    default).  Missing keys are populated from :data:`DEFAULT_APP_CONFIG`.
    The rewritten file keeps the original inline comments from the default
    template — user comments in the existing file are NOT preserved (YAML
    round-tripping without a lossy library is out of scope for this
    scaffolder).
    """
    import yaml

    project_dir = Path(path)
    cfg_path = project_dir / "config.yaml"
    if not cfg_path.is_file():
        # No existing file — just write defaults
        rendered = render_template(
            DEFAULT_APP_CONFIG,
            {
                "project_name": project_dir.name,
                "project_title": _title_from_name(project_dir.name),
                "created_iso": _dt.datetime.now().isoformat(timespec="seconds"),
                "engine_version": _engine_version(),
            },
        )
        cfg_path.write_text(rendered, encoding="utf-8")
        return cfg_path

    existing = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    default_rendered = render_template(
        DEFAULT_APP_CONFIG,
        {
            "project_name": project_dir.name,
            "project_title": _title_from_name(project_dir.name),
            "created_iso": _dt.datetime.now().isoformat(timespec="seconds"),
            "engine_version": _engine_version(),
        },
    )
    defaults = yaml.safe_load(default_rendered) or {}

    if preserve:
        merged = _deep_merge(defaults, existing)
    else:
        merged = defaults

    # Preserve the commented header block from the rendered defaults
    header_lines = []
    for line in default_rendered.splitlines():
        if line.startswith("#") or not line.strip():
            header_lines.append(line)
        else:
            break
    body = yaml.safe_dump(merged, sort_keys=False, default_flow_style=False)
    cfg_path.write_text("\n".join(header_lines) + "\n" + body, encoding="utf-8")
    return cfg_path


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge ``override`` onto ``base``.  ``override`` wins."""
    out = dict(base)
    for k, v in override.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out
