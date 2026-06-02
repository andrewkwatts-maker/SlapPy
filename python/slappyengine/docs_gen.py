"""HTML reference documentation generator for SlapPyEngine.

Generates a single-page ``docs/reference.html`` from:
- Engine public API (docstrings via ``inspect``)
- ``config/engine.yml`` schema (every key, type, and default)
- ``project.yml`` schema
- Asset/Layer/Scene manifest YAML format

Called automatically when the editor is launched (if ``editor.generate_docs: true``
in project.yml) and available as ``slap docs`` CLI command.

Usage::

    from slappyengine.docs_gen import generate_docs
    generate_docs(output_dir="docs/")          # writes docs/reference.html
    generate_docs(output_dir="docs/", open=True)  # also opens in browser
"""
from __future__ import annotations

import inspect
import textwrap
import html
from dataclasses import fields, is_dataclass
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------

_HTML_HEAD = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SlapPyEngine — Reference</title>
<style>
  :root {{ --bg: #0d0d14; --fg: #d0d0e0; --accent: #4e9af1; --dim: #888;
          --code-bg: #161622; --border: #2a2a3e; }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: var(--bg); color: var(--fg); font: 14px/1.6 "Segoe UI", system-ui, sans-serif;
         display: flex; min-height: 100vh; }}
  nav {{ width: 220px; min-height: 100vh; background: #0a0a10; border-right: 1px solid var(--border);
        padding: 16px; position: sticky; top: 0; overflow-y: auto; }}
  nav h2 {{ font-size: 11px; text-transform: uppercase; letter-spacing: .08em; color: var(--dim);
            margin-bottom: 8px; margin-top: 16px; }}
  nav h2:first-child {{ margin-top: 0; }}
  nav a {{ display: block; color: var(--fg); text-decoration: none; padding: 3px 6px;
           border-radius: 4px; font-size: 13px; }}
  nav a:hover {{ background: var(--border); color: var(--accent); }}
  main {{ flex: 1; padding: 32px 48px; max-width: 860px; }}
  h1 {{ font-size: 24px; color: var(--accent); border-bottom: 1px solid var(--border);
       padding-bottom: 12px; margin-bottom: 24px; }}
  h2 {{ font-size: 18px; color: var(--accent); margin: 32px 0 12px; border-bottom: 1px solid var(--border);
       padding-bottom: 6px; }}
  h3 {{ font-size: 14px; color: #9ab; margin: 20px 0 6px; }}
  p {{ margin-bottom: 10px; }}
  pre {{ background: var(--code-bg); border: 1px solid var(--border); border-radius: 6px;
        padding: 12px 16px; overflow-x: auto; font-family: "Cascadia Code", "Fira Code", monospace;
        font-size: 13px; margin: 10px 0; }}
  code {{ background: var(--code-bg); padding: 1px 5px; border-radius: 3px;
         font-family: "Cascadia Code", "Fira Code", monospace; font-size: 13px; }}
  table {{ border-collapse: collapse; width: 100%; margin: 10px 0; font-size: 13px; }}
  th {{ background: #16162a; text-align: left; padding: 6px 10px; color: var(--dim);
       border-bottom: 1px solid var(--border); font-weight: 600; }}
  td {{ padding: 5px 10px; border-bottom: 1px solid var(--border); vertical-align: top; }}
  td code {{ font-size: 12px; }}
  .tag {{ display: inline-block; padding: 1px 7px; border-radius: 10px; font-size: 11px;
          background: #1e2a3a; color: var(--accent); margin-right: 4px; }}
  .section-anchor {{ scroll-margin-top: 20px; }}
  .dim {{ color: var(--dim); font-size: 12px; }}
</style>
</head>
<body>
<nav>
  <h2>Getting Started</h2>
  <a href="#lifecycle">Lifecycle Hooks</a>
  <a href="#config-hierarchy">Config Hierarchy</a>
  <h2>Configuration</h2>
  <a href="#engine-yml">engine.yml</a>
  <a href="#project-yml">project.yml</a>
  <h2>Manifests</h2>
  <a href="#asset-manifest">Asset Manifest</a>
  <a href="#scene-manifest">Scene Manifest</a>
  <a href="#layer-manifest">Layer Manifest</a>
  <a href="#level-manifest">Level Manifest</a>
  <h2>API Reference</h2>
  {nav_api_links}
</nav>
<main>
<h1>SlapPyEngine — Reference</h1>
"""

_HTML_FOOT = """\
</main>
</body>
</html>
"""

# ---------------------------------------------------------------------------
# Section writers
# ---------------------------------------------------------------------------

def _escape(s: str) -> str:
    return html.escape(str(s or ""))


def _section(anchor: str, title: str, body: str) -> str:
    return f'<h2 id="{anchor}" class="section-anchor">{_escape(title)}</h2>\n{body}\n'


def _cfg_table(rows: list[tuple[str, str, str, str]]) -> str:
    """Render a table of (key, type, default, description) rows."""
    out = ['<table>', '<tr><th>Key</th><th>Type</th><th>Default</th><th>Description</th></tr>']
    for key, typ, default, desc in rows:
        out.append(
            f'<tr><td><code>{_escape(key)}</code></td>'
            f'<td><code>{_escape(typ)}</code></td>'
            f'<td><code>{_escape(default)}</code></td>'
            f'<td>{_escape(desc)}</td></tr>'
        )
    out.append('</table>')
    return '\n'.join(out)


def _dataclass_rows(dc) -> list[tuple[str, str, str, str]]:
    rows = []
    for f in fields(dc):
        typ = str(f.type) if isinstance(f.type, str) else f.type.__name__ if hasattr(f.type, '__name__') else str(f.type)
        default = repr(f.default) if f.default is not f.default_factory else "…"  # type: ignore[misc]
        rows.append((f.name, typ, default, ""))
    return rows


def _api_class(cls) -> str:
    doc = inspect.getdoc(cls) or ""
    out = [f'<h3>{_escape(cls.__name__)}</h3>']
    if doc:
        paragraphs = doc.split('\n\n')
        out.append(f'<p>{_escape(paragraphs[0])}</p>')
    methods = [
        (name, obj) for name, obj in inspect.getmembers(cls, predicate=inspect.isfunction)
        if not name.startswith('_') and inspect.getdoc(obj)
    ]
    if methods:
        out.append('<table><tr><th>Method</th><th>Description</th></tr>')
        for name, fn in methods:
            fn_doc = (inspect.getdoc(fn) or "").split('\n')[0]
            sig = ""
            try:
                sig = str(inspect.signature(fn))
            except (ValueError, TypeError):
                pass
            out.append(
                f'<tr><td><code>{_escape(name)}{_escape(sig)}</code></td>'
                f'<td>{_escape(fn_doc)}</td></tr>'
            )
        out.append('</table>')
    return '\n'.join(out)


# ---------------------------------------------------------------------------
# Static section bodies
# ---------------------------------------------------------------------------

_LIFECYCLE_BODY = """\
<p>Register callbacks for the three engine lifecycle events.
All three work as decorators or plain function calls.</p>
<pre>
import slappyengine as se

engine = se.Engine()

@engine.on_launch
def setup():
    print("GPU ready — load resources here")

@engine.on_tick
def update(dt):
    player.position = (player.position[0] + speed * dt, player.position[1])

@engine.on_end
def cleanup():
    save_progress()

engine.run()
</pre>
<p>Hooks on assets are registered via the asset's YAML manifest
<code>scripts:</code> list.  Each referenced Python file may define
<code>on_launch(entity)</code>, <code>on_tick(entity, dt)</code>, and
<code>on_end(entity)</code> at module level.  Multiple assets can reference
the same script file.</p>
<pre>
# assets/player.yml
name: Player
type: asset
scripts:
  - scripts/player_controller.py   # defines on_launch, on_tick, on_end
  - scripts/combat.py              # defines on_tick only — that's fine
</pre>
"""

_CONFIG_HIERARCHY_BODY = """\
<p>Settings are resolved in three layers, each overriding the previous:</p>
<ol style="margin: 10px 0 10px 24px">
  <li><code>config/engine.yml</code> — engine-wide defaults (shipped with the engine)</li>
  <li><code>project.yml</code> — per-project overrides; only specify keys you want to change</li>
  <li><code>Engine(title="…", width=1920)</code> — runtime keyword overrides in code</li>
</ol>
<p>Both YAML files support partial sections: you don't need to repeat every key, just the ones you override.</p>
<pre>
# project.yml — only override what differs from engine defaults
window:
  title: "My Awesome Game"
  width: 1920
  height: 1080
lighting:
  ambient_intensity: 0.3
</pre>
"""

_ASSET_MANIFEST_BODY = """\
<p>Every asset, layer, scene, and level can be defined as a YAML file.
The visual editor reads and writes the same files — they round-trip perfectly.
AI tools can edit YAML directly or call the Python API.</p>
<pre>
# assets/player.yml
name: Player
type: asset

layers:
  - name: body
    texture: sprites/player.png
    opacity: 1.0
    deformable: false
    lighting_mode: "2d"   # "unlit" | "2d" | "3d"
  - name: shadow
    texture: sprites/player_shadow.png
    opacity: 0.5

scripts:
  - scripts/player_controller.py   # on_launch(entity), on_tick(entity, dt), on_end(entity)
  - scripts/combat.py

collision:
  type: aabb
  width: 32
  height: 32

properties:
  position: [0.0, 0.0]
  rotation: 0.0
  tags: ["player"]
</pre>
<p>Load from Python:</p>
<pre>
from slappyengine.asset_manifest import AssetManifest
player = AssetManifest.load("assets/player.yml")
</pre>
"""

_SCENE_MANIFEST_BODY = """\
<pre>
# scenes/main.yml
name: Main
type: scene

entities:
  - manifest: assets/player.yml
    position: [100, 200]
  - manifest: assets/enemy.yml
    position: [400, 300]
    rotation: 180.0

lighting:
  ambient_color: [0.2, 0.2, 0.3]
  ambient_intensity: 0.2

post_process:
  - type: vignette
    strength: 0.4
  - type: chromatic_aberration
    strength: 0.003
</pre>
"""

_LAYER_MANIFEST_BODY = """\
<p>Individual layers can be defined as standalone YAML files and referenced
by asset manifests or composed in the editor.</p>
<pre>
# assets/layers/car_body.yml
name: car_body
type: layer

texture: sprites/car.png
width: 128
height: 64
opacity: 1.0
deformable: true         # enables DeformableLayerComponent
lighting_mode: "2d"      # "unlit" | "2d" | "3d"
tint: [1.0, 1.0, 1.0, 1.0]
</pre>
"""

_LEVEL_MANIFEST_BODY = """\
<pre>
# levels/campaign.yml
name: Campaign
type: level
description: "Single-player campaign — three acts"

scenes:
  - scenes/act1_intro.yml
  - scenes/act1_city.yml
  - scenes/act2_mountains.yml
</pre>
"""

_PROJECT_YML_ROWS = [
    ("name", "str", '"My Game"', "Display name of your project"),
    ("version", "str", '"0.1.0"', "Semantic version string"),
    ("author", "str", '""', "Author / studio name"),
    ("entry", "str", '"main.py"', "Entry-point script relative to project root"),
    ("platforms", "list[str]", "[windows]", "Build targets: windows, linux, macos, web"),
    ("asset_dirs", "list[str]", "[assets, scenes]", "Directories scanned for *.yml manifests"),
    ("encryption.enabled", "bool", "false", "Encrypt packaged assets"),
    ("encryption.key", "str", '""', "Passphrase for AES-256-GCM encryption — never commit to VCS"),
    ("editor.theme", "str", '"dark"', '"dark" | "light"'),
    ("editor.generate_docs", "bool", "true", "Regenerate docs/reference.html when editor opens"),
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_docs(
    output_dir: str | Path = "docs",
    open_browser: bool = False,
) -> Path:
    """Generate ``reference.html`` in *output_dir*.

    Parameters
    ----------
    output_dir:
        Directory to write the HTML file into (created if absent).
    open_browser:
        If ``True``, open the generated file in the default browser.

    Returns
    -------
    Path
        Absolute path to the generated HTML file.
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "reference.html"

    # Gather public API classes to document
    api_classes: list[type] = []
    try:
        import slappyengine as _se
        for name in getattr(_se, '__all__', []):
            obj = getattr(_se, name, None)
            if inspect.isclass(obj) and inspect.getdoc(obj):
                api_classes.append(obj)
    except Exception:
        pass

    nav_api_links = "\n  ".join(
        f'<a href="#{cls.__name__.lower()}">{_escape(cls.__name__)}</a>'
        for cls in api_classes
    )

    body_parts = [_HTML_HEAD.format(nav_api_links=nav_api_links)]

    body_parts.append(_section("lifecycle", "Lifecycle Hooks", _LIFECYCLE_BODY))
    body_parts.append(_section("config-hierarchy", "Config Hierarchy", _CONFIG_HIERARCHY_BODY))

    # engine.yml table — parse the real file if available
    engine_yml_rows = _gather_engine_yml_rows()
    body_parts.append(_section(
        "engine-yml", "engine.yml",
        "<p>Engine-wide defaults. Copy to your project's <code>config/</code> directory "
        "and edit freely — missing keys fall back to these defaults.</p>\n" +
        _cfg_table(engine_yml_rows)
    ))

    body_parts.append(_section(
        "project-yml", "project.yml",
        "<p>Per-project overrides layered on top of <code>engine.yml</code>. "
        "Created automatically on first run.</p>\n" +
        _cfg_table(_PROJECT_YML_ROWS)
    ))

    body_parts.append(_section("asset-manifest", "Asset Manifest (YAML)", _ASSET_MANIFEST_BODY))
    body_parts.append(_section("scene-manifest", "Scene Manifest (YAML)", _SCENE_MANIFEST_BODY))
    body_parts.append(_section("layer-manifest", "Layer Manifest (YAML)", _LAYER_MANIFEST_BODY))
    body_parts.append(_section("level-manifest", "Level Manifest (YAML)", _LEVEL_MANIFEST_BODY))

    if api_classes:
        api_html = "\n".join(_api_class(cls) for cls in api_classes)
        body_parts.append(_section("api", "Python API", api_html))

    body_parts.append(_HTML_FOOT)
    out_path.write_text("\n".join(body_parts), encoding="utf-8")

    if open_browser:
        import webbrowser
        webbrowser.open(out_path.as_uri())

    return out_path


def _gather_engine_yml_rows() -> list[tuple[str, str, str, str]]:
    """Read the canonical engine.yml and produce table rows from it."""
    candidates = [
        Path(__file__).resolve().parent.parent.parent / "config" / "engine.yml",
        Path.cwd() / "config" / "engine.yml",
    ]
    for p in candidates:
        if p.exists():
            try:
                import yaml
                with p.open("r", encoding="utf-8") as fh:
                    raw = yaml.safe_load(fh)
                return _flatten_dict(raw)
            except Exception:
                pass
    return []


def _flatten_dict(
    d: dict, prefix: str = "", rows: list | None = None
) -> list[tuple[str, str, str, str]]:
    if rows is None:
        rows = []
    for k, v in d.items():
        full_key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            _flatten_dict(v, full_key, rows)
        else:
            typ = type(v).__name__
            rows.append((full_key, typ, repr(v), ""))
    return rows
