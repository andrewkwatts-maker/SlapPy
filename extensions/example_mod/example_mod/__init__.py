"""Sample Pharos editor plugin.

Registers a panel, a theme, an HTTP route, and a command. Wire up:

    pip install ./extensions/example_mod
    from pharos_editor.extensions import ExtensionRegistry
    r = ExtensionRegistry()
    r.discover()   # picks up this plugin

See ``docs/EXTENSIONS.md`` for the full plugin author guide.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

THEME_PATH = Path(__file__).parent / "themes" / "example_mod_theme.yaml"


def _make_panel(shell: Any = None) -> dict[str, Any]:
    """Build the plugin's panel descriptor.

    Real DearPyGui panels return a widget handle here; the sample
    returns a plain dict so downstream tests can assert on the payload
    without a live DPG context.
    """
    return {
        "id": "example_mod.panel",
        "title": "Example Mod",
        "body": "Hello from the example plugin!",
    }


async def _http_hello(_request: Any) -> Any:
    from aiohttp import web

    return web.json_response({"greeting": "hello from example_mod"})


def _cmd_greet(name: str = "world") -> dict[str, Any]:
    return {"greeting": f"hello, {name}!"}


def register(registry: Any) -> None:
    """Entry-point callback. Called by ExtensionRegistry.discover()."""
    registry.register_panel("example_mod", _make_panel)
    registry.register_theme(str(THEME_PATH))
    registry.register_http_route("/api/mods/example/hello", _http_hello)
    registry.register_command("example.greet", _cmd_greet)
