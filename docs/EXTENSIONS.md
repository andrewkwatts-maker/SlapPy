# Writing a Pharos editor extension

Pharos editor plugins register themselves through a single
`ExtensionRegistry`. One plugin can contribute panels, themes,
importers, HTTP routes, and commands. Discovery happens via
`importlib.metadata.entry_points`; you declare the group in your
plugin's `pyproject.toml` and Pharos calls your `register(registry)`
function at boot.

## Minimal plugin

`extensions/example_mod/` in the Pharos repo is a working reference
plugin. It contributes one of every kind:

```
extensions/example_mod/
├── pyproject.toml
└── example_mod/
    ├── __init__.py            # register(registry) entry point
    └── themes/
        └── example_mod_theme.yaml
```

### 1. `pyproject.toml`

```toml
[project]
name = "example-mod"
version = "0.1.0"
requires-python = ">=3.11"

[project.entry-points."pharos_editor.plugins"]
example = "example_mod:register"
```

### 2. `example_mod/__init__.py`

```python
from pathlib import Path

THEME_PATH = Path(__file__).parent / "themes" / "example_mod_theme.yaml"

def _make_panel(shell=None):
    return {"id": "example_mod.panel", "title": "Example Mod"}

async def _http_hello(_request):
    from aiohttp import web
    return web.json_response({"greeting": "hello from example_mod"})

def _cmd_greet(name="world"):
    return {"greeting": f"hello, {name}!"}

def register(registry):
    registry.register_panel("example_mod", _make_panel)
    registry.register_theme(str(THEME_PATH))
    registry.register_http_route("/api/mods/example/hello", _http_hello)
    registry.register_command("example.greet", _cmd_greet)
```

### 3. Install + verify

```bash
pip install extensions/example_mod/
python - <<'EOF'
from pharos_editor.extensions import ExtensionRegistry
r = ExtensionRegistry()
loaded = r.discover()
print("loaded:", loaded)
print("panels:", list(r.panels))
print("themes:", r.themes)
print("routes:", list(r.http_routes))
print("commands:", list(r.commands))
EOF
```

Then boot the editor:

```bash
pharos-edit
```

Your panel appears in the notebook shell; your theme shows up in the
theme picker; your HTTP route is live at `POST /api/mods/example/hello`
(when `App(enable_http=True)`); your command is dispatchable via
`POST /api/command` with `{"name":"example.greet","args":{"name":"you"}}`.

## Registry surface

| Method                                         | Contract                                                     |
|------------------------------------------------|--------------------------------------------------------------|
| `register_panel(panel_id, factory)`            | `factory(shell) -> Any` returning a widget or dict.          |
| `register_theme(path_or_id)`                   | Absolute YAML path. Copied to `~/.pharos/themes/` on sync.   |
| `register_importer(ext, importer)`             | `importer(path: str) -> Any` for file extension `ext`.       |
| `register_http_route(path, async handler)`     | Attached to `HttpBridge` when the editor mounts one.         |
| `register_command(name, callable)`             | Dispatched from `POST /api/command` or `dispatch_command`.   |

## User theme overlay

Themes registered as paths get copied into `~/.pharos/themes/` on
`registry.sync_user_themes()`. The `ThemeCatalog` scans that directory
in addition to the shipped themes, so a user theme with the same
`name:` as a shipped theme wins.

## Discovery gotchas

* Entry-point group is exactly `pharos_editor.plugins`. Typos silently
  fail — plugins never load.
* `discover()` swallows plugin errors and logs a warning. Test locally
  by importing the plugin directly before shipping.
* `sync_user_themes()` skips YAMLs that already match byte-for-byte,
  so repeated calls are cheap.
