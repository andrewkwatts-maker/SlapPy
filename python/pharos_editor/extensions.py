"""Sprint 7: extension architecture — one registry for every plugin type.

Extensions can register:

* **panels** — DearPyGui panels the notebook shell mounts alongside its
  built-in tabs.
* **themes** — additional YAML theme files (dropped into
  ``~/.pharos/themes/`` or contributed directly by the plugin).
* **importers** — asset importers keyed by file extension.
* **http routes** — plugin endpoints attached to
  :class:`pharos_engine.net.http_bridge.HttpBridge` under any path.
* **commands** — named commands invocable via the HTTP bridge
  ``POST /api/command`` (Sprint 6) or directly through
  :meth:`ExtensionRegistry.dispatch_command`.

Discovery uses ``importlib.metadata.entry_points`` with the group name
``pharos_editor.plugins``. A plugin declares in its ``pyproject.toml``::

    [project.entry-points."pharos_editor.plugins"]
    my_mod = "my_mod:register"

The referenced callable receives one argument — the shared
:class:`ExtensionRegistry` — and calls the relevant register_* method
for each contribution.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Iterable

logger = logging.getLogger(__name__)


PanelFactory = Callable[..., Any]
ImporterFn = Callable[[str], Any]
HttpHandler = Callable[[Any], Awaitable[Any]]
CommandFn = Callable[..., Any]


@dataclass
class ExtensionRegistry:
    """Central registry of every plugin contribution."""

    panels: dict[str, PanelFactory] = field(default_factory=dict)
    themes: list[str] = field(default_factory=list)
    importers: dict[str, ImporterFn] = field(default_factory=dict)
    http_routes: dict[str, HttpHandler] = field(default_factory=dict)
    commands: dict[str, CommandFn] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Contribution API called from plugin register() hooks
    # ------------------------------------------------------------------
    def register_panel(self, panel_id: str, factory: PanelFactory) -> None:
        if panel_id in self.panels:
            logger.warning("extension: replacing existing panel %r", panel_id)
        self.panels[panel_id] = factory

    def register_theme(self, path_or_id: str) -> None:
        """Register a theme by absolute YAML path or logical id.

        Path-form entries are copied into ``~/.pharos/themes/`` on the
        next ``sync_user_themes`` call so :class:`ThemeCatalog` picks
        them up automatically.
        """
        if path_or_id not in self.themes:
            self.themes.append(path_or_id)

    def register_importer(self, ext: str, importer: ImporterFn) -> None:
        self.importers[ext.lower()] = importer

    def register_http_route(self, path: str, handler: HttpHandler) -> None:
        if not path.startswith("/"):
            raise ValueError(f"http route must start with '/'; got {path!r}")
        self.http_routes[path] = handler

    def register_command(self, name: str, cmd: CommandFn) -> None:
        self.commands[name] = cmd

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------
    def discover(self, group: str = "pharos_editor.plugins") -> list[str]:
        """Load every plugin registered under the entry-point group.

        Returns the list of successfully loaded plugin names for
        logging + test assertions.
        """
        from importlib.metadata import entry_points

        try:
            eps: Iterable[Any] = entry_points(group=group)
        except TypeError:  # pragma: no cover - Python 3.9 fallback shape
            eps = entry_points().get(group, [])  # type: ignore[attr-defined]

        loaded: list[str] = []
        for ep in eps:
            try:
                register = ep.load()
                register(self)
                loaded.append(ep.name)
            except Exception as exc:
                logger.warning("extension %s failed to load: %s", ep.name, exc)
        return loaded

    # ------------------------------------------------------------------
    # Integration surfaces
    # ------------------------------------------------------------------
    def sync_user_themes(self, target_dir: Any = None) -> int:
        """Copy path-form registered themes into ``target_dir``.

        Returns the number of files copied. When ``target_dir`` is
        ``None`` the default ``~/.pharos/themes/`` is used.
        """
        import shutil
        from pathlib import Path

        target = Path(target_dir) if target_dir is not None else (
            Path.home() / ".pharos" / "themes"
        )
        target.mkdir(parents=True, exist_ok=True)
        copied = 0
        for entry in self.themes:
            src = Path(entry)
            if not src.is_file():
                continue
            dst = target / src.name
            if dst.exists() and dst.read_bytes() == src.read_bytes():
                continue
            try:
                shutil.copy2(src, dst)
                copied += 1
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("sync_user_themes: %s -> %s failed: %s", src, dst, exc)
        return copied

    def attach_to_bridge(self, bridge: Any) -> None:
        """Wire every registered HTTP route into a live
        :class:`pharos_engine.net.http_bridge.HttpBridge`."""
        for path, handler in self.http_routes.items():
            bridge.register_route(path, handler)

    def install_commands_on(self, app: Any) -> None:
        """Publish every registered command onto ``app._http_commands``
        so the Sprint 6 bridge's ``POST /api/command`` can dispatch."""
        registry = getattr(app, "_http_commands", None)
        if registry is None:
            registry = {}
            setattr(app, "_http_commands", registry)
        for name, cmd in self.commands.items():
            registry[name] = cmd

    def dispatch_command(self, cmd_name: str, /, **kwargs: Any) -> Any:
        cmd = self.commands.get(cmd_name)
        if cmd is None:
            raise KeyError(f"unknown command {cmd_name!r}")
        return cmd(**kwargs)


__all__ = ["ExtensionRegistry"]
