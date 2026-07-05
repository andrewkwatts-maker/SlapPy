"""User extension plugin registry — sprint GG3.

Users drop a ``.py`` extension script plus a ``plugin.yaml`` manifest
into ``~/.slappyengine/extensions/<plugin_name>/`` and the engine will
auto-load it with lifecycle hooks:

    * ``on_load``          — invoked immediately after import.
    * ``on_shell_ready``   — deferred until the editor shell signals
      readiness (called manually via :meth:`PluginRegistry.fire_shell_ready`).
    * ``on_unload``        — invoked when :meth:`PluginRegistry.unload`
      is called or the registry is torn down.

Design goals
------------

* **Sandboxed** — any exception raised by a plugin's lifecycle hook is
  captured on the :class:`LoadedPlugin` record's ``load_error`` field
  and logged; it never kills the registry or other plugins.
* **Dependency-ordered** — :meth:`PluginRegistry.load_all` performs a
  topological sort based on the manifests' ``requires`` field so a
  plugin's dependencies always finish loading first.
* **Capability queries** — plugins declare tags in ``provides`` and
  other code can look them up via
  :meth:`PluginRegistry.find_by_capability`.
* **Manifest-first** — every plugin ships a ``plugin.yaml`` next to
  its entry module; the registry never imports uninitialised source.

The public surface is intentionally small: one dataclass for the
manifest, one for the loaded record, three exception classes, and the
:class:`PluginRegistry` façade.
"""
from __future__ import annotations

import importlib
import importlib.util
import logging
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import yaml

__all__ = [
    "PluginError",
    "PluginDependencyError",
    "PluginNotFoundError",
    "PluginManifest",
    "LoadedPlugin",
    "PluginRegistry",
    "default_plugin_dir",
]

_LOG = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class PluginError(Exception):
    """Base error for all plugin-registry failures."""


class PluginDependencyError(PluginError):
    """Raised when a plugin's requires list can't be satisfied.

    The :attr:`cycle` attribute is populated when the failure is a
    circular dependency; it lists the plugin names in traversal order,
    with the first name repeated at the end for clarity, e.g.
    ``["a", "b", "c", "a"]``.
    """

    def __init__(self, message: str, cycle: list[str] | None = None) -> None:
        super().__init__(message)
        self.cycle: list[str] = list(cycle or [])


class PluginNotFoundError(PluginError):
    """Raised when an operation targets a name the registry doesn't know."""


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class PluginManifest:
    """Metadata block loaded from a ``plugin.yaml`` file.

    Attributes mirror the YAML schema 1:1 — ``entry`` is the dotted
    module path (or a bare ``foo.py`` filename relative to the manifest
    directory) that hosts the plugin. Hook names, when set, are the
    attribute names of zero-arg callables inside the entry module.
    """

    name: str
    version: str
    author: str | None = None
    entry: str = ""
    on_load: str | None = None
    on_shell_ready: str | None = None
    on_unload: str | None = None
    provides: list[str] = field(default_factory=list)
    requires: list[str] = field(default_factory=list)
    enabled: bool = True
    # Path to the manifest file itself — populated by
    # ``PluginRegistry.load`` so downstream code can resolve sibling
    # resources. Not part of the YAML schema.
    manifest_path: Path | None = None

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PluginManifest":
        """Build a manifest from a parsed YAML mapping.

        Unknown keys are ignored so future versions of the schema can
        add optional fields without breaking older engines.
        """
        if not isinstance(data, dict):
            raise PluginError(f"plugin manifest must be a mapping, got {type(data).__name__}")
        name = data.get("name")
        version = data.get("version")
        entry = data.get("entry")
        if not name or not isinstance(name, str):
            raise PluginError("plugin manifest missing required 'name' string")
        if not version or not isinstance(version, str):
            raise PluginError(f"plugin '{name}' manifest missing required 'version' string")
        if not entry or not isinstance(entry, str):
            raise PluginError(f"plugin '{name}' manifest missing required 'entry' string")
        provides = data.get("provides") or []
        requires = data.get("requires") or []
        if not isinstance(provides, list):
            raise PluginError(f"plugin '{name}' 'provides' must be a list")
        if not isinstance(requires, list):
            raise PluginError(f"plugin '{name}' 'requires' must be a list")
        return cls(
            name=name,
            version=version,
            author=data.get("author"),
            entry=entry,
            on_load=data.get("on_load"),
            on_shell_ready=data.get("on_shell_ready"),
            on_unload=data.get("on_unload"),
            provides=[str(p) for p in provides],
            requires=[str(r) for r in requires],
            enabled=bool(data.get("enabled", True)),
        )

    @classmethod
    def from_yaml(cls, path: Path) -> "PluginManifest":
        """Read + parse a manifest YAML file from disk."""
        text = Path(path).read_text(encoding="utf-8")
        data = yaml.safe_load(text) or {}
        manifest = cls.from_dict(data)
        manifest.manifest_path = Path(path)
        return manifest


@dataclass
class LoadedPlugin:
    """Runtime record for a plugin that the registry has imported."""

    manifest: PluginManifest
    module: Any = None
    load_error: str | None = None
    shell_ready_fired: bool = False

    @property
    def name(self) -> str:
        return self.manifest.name


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def default_plugin_dir() -> Path:
    """Return ``~/.slappyengine/extensions`` (does not create it)."""
    return Path.home() / ".slappyengine" / "extensions"


def _iter_manifest_paths(root: Path) -> Iterable[Path]:
    """Yield every ``plugin.yaml`` under *root* (non-recursive glob first, then deeper)."""
    if not root.exists():
        return []
    # Sorted for determinism across filesystems.
    return sorted(root.rglob("plugin.yaml"))


def _import_entry(manifest: PluginManifest) -> Any:
    """Import the plugin's entry module.

    Two forms are accepted:

    * A dotted path (``mypkg.myplugin``) — imported via ``importlib``
      just like a normal Python module.
    * A relative filename (``hello_plugin.py`` or
      ``sub/entry.py``) — resolved against the manifest directory and
      loaded with ``importlib.util.spec_from_file_location``.
    """
    entry = manifest.entry
    if not entry:
        raise PluginError(f"plugin '{manifest.name}' has no entry")

    # File-path form.
    if entry.endswith(".py") or "/" in entry or "\\" in entry:
        if manifest.manifest_path is None:
            raise PluginError(
                f"plugin '{manifest.name}' uses relative entry '{entry}' but manifest_path is unset"
            )
        base = manifest.manifest_path.parent
        candidate = (base / entry).resolve()
        if not candidate.exists():
            raise PluginError(
                f"plugin '{manifest.name}' entry file not found: {candidate}"
            )
        module_name = f"_slappyengine_plugin_{manifest.name}"
        spec = importlib.util.spec_from_file_location(module_name, candidate)
        if spec is None or spec.loader is None:
            raise PluginError(f"plugin '{manifest.name}' spec_from_file_location returned None")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except Exception:
            # Roll back the sys.modules pollution so a retry via
            # reload() starts from a clean slate.
            sys.modules.pop(module_name, None)
            raise
        return module

    # Dotted-path form.
    return importlib.import_module(entry)


def _topological_order(manifests: dict[str, PluginManifest]) -> list[str]:
    """Return manifest names in dependency-safe order.

    Raises :class:`PluginDependencyError` if a cycle is detected or if
    a required dependency is missing. The algorithm is depth-first with
    a permanent / temporary mark set — classic Cormen — and reports the
    cycle path when it revisits a temporarily-marked node.
    """
    order: list[str] = []
    permanent: set[str] = set()
    temporary: dict[str, int] = {}  # name -> position in current DFS stack
    stack: list[str] = []

    def visit(name: str) -> None:
        if name in permanent:
            return
        if name in temporary:
            # Extract the cycle from the current stack.
            start = temporary[name]
            cycle = stack[start:] + [name]
            raise PluginDependencyError(
                f"circular plugin dependency: {' -> '.join(cycle)}",
                cycle=cycle,
            )
        temporary[name] = len(stack)
        stack.append(name)
        manifest = manifests[name]
        for dep in manifest.requires:
            if dep not in manifests:
                raise PluginError(
                    f"plugin '{name}' requires '{dep}' which is not present"
                )
            visit(dep)
        stack.pop()
        del temporary[name]
        permanent.add(name)
        order.append(name)

    for plugin_name in sorted(manifests.keys()):
        visit(plugin_name)
    return order


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class PluginRegistry:
    """Central façade for user-extension plugins.

    Typical use::

        registry = PluginRegistry()
        registry.load_all()             # picks up ~/.slappyengine/extensions
        ...
        registry.fire_shell_ready()     # when the editor shell is up
        ...
        registry.unload_all()           # on shutdown

    The registry does not schedule the shell-ready hook itself — the
    editor shell is expected to invoke :meth:`fire_shell_ready` once
    it's ready to accept plugin UI contributions.
    """

    def __init__(self) -> None:
        self._loaded: dict[str, LoadedPlugin] = {}

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------
    def discover(self, plugin_dir: Path | None = None) -> list[Path]:
        """Return the sorted list of ``plugin.yaml`` files under *plugin_dir*."""
        root = Path(plugin_dir) if plugin_dir is not None else default_plugin_dir()
        return list(_iter_manifest_paths(root))

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------
    def load(self, manifest_path: Path) -> LoadedPlugin:
        """Load a single plugin from its manifest path.

        Imports the entry module and invokes ``on_load`` if declared.
        Import failures raise :class:`PluginError`; hook failures are
        captured on :attr:`LoadedPlugin.load_error` and logged but do
        not raise.
        """
        manifest = PluginManifest.from_yaml(Path(manifest_path))
        if not manifest.enabled:
            record = LoadedPlugin(manifest=manifest, module=None, load_error="disabled")
            self._loaded[manifest.name] = record
            return record

        try:
            module = _import_entry(manifest)
        except PluginError:
            raise
        except Exception as exc:
            raise PluginError(
                f"failed to import plugin '{manifest.name}': {exc}"
            ) from exc

        record = LoadedPlugin(manifest=manifest, module=module)
        # Invoke on_load in a sandbox.
        self._invoke_hook(record, manifest.on_load, "on_load")
        self._loaded[manifest.name] = record
        return record

    def load_all(self, plugin_dir: Path | None = None) -> list[LoadedPlugin]:
        """Discover and load every plugin under *plugin_dir* in dep order.

        Disabled plugins are recorded but their entry module is not
        imported. Plugins that fail to import raise
        :class:`PluginError` synchronously; plugins that survive import
        but crash in ``on_load`` land with their error captured in
        :attr:`LoadedPlugin.load_error`.
        """
        manifest_paths = self.discover(plugin_dir)
        manifests: dict[str, PluginManifest] = {}
        for path in manifest_paths:
            manifest = PluginManifest.from_yaml(path)
            if manifest.name in manifests:
                raise PluginError(
                    f"duplicate plugin name '{manifest.name}' at {path}"
                )
            manifests[manifest.name] = manifest

        # Topological sort considers ALL manifests (even disabled) so
        # that a disabled dep isn't silently skipped and the dependent
        # plugin doesn't later crash on a missing symbol.
        order = _topological_order(manifests)

        loaded_records: list[LoadedPlugin] = []
        for name in order:
            manifest = manifests[name]
            if not manifest.enabled:
                record = LoadedPlugin(manifest=manifest, module=None, load_error="disabled")
                self._loaded[name] = record
                loaded_records.append(record)
                continue
            # Ensure all *enabled* deps loaded cleanly; if a dep is
            # disabled or errored, mark this one as skipped rather
            # than crashing the whole load_all.
            skip_reason: str | None = None
            for dep in manifest.requires:
                dep_rec = self._loaded.get(dep)
                if dep_rec is None:
                    skip_reason = f"dependency '{dep}' not loaded"
                    break
                if dep_rec.load_error is not None or dep_rec.module is None:
                    skip_reason = f"dependency '{dep}' failed to load"
                    break
            if skip_reason is not None:
                record = LoadedPlugin(manifest=manifest, module=None, load_error=skip_reason)
                self._loaded[name] = record
                loaded_records.append(record)
                continue

            try:
                assert manifest.manifest_path is not None  # from_yaml sets it
                record = self.load(manifest.manifest_path)
            except PluginError as exc:
                _LOG.warning("plugin %s failed to load: %s", name, exc)
                record = LoadedPlugin(manifest=manifest, module=None, load_error=str(exc))
                self._loaded[name] = record
            loaded_records.append(record)
        return loaded_records

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def fire_shell_ready(self) -> None:
        """Invoke ``on_shell_ready`` on every loaded plugin exactly once."""
        for record in self._loaded.values():
            if record.shell_ready_fired or record.module is None:
                continue
            self._invoke_hook(record, record.manifest.on_shell_ready, "on_shell_ready")
            record.shell_ready_fired = True

    def unload(self, name: str) -> None:
        """Fire ``on_unload`` for *name* and evict it from the registry."""
        record = self._loaded.get(name)
        if record is None:
            raise PluginNotFoundError(f"no plugin named '{name}' is loaded")
        if record.module is not None:
            self._invoke_hook(record, record.manifest.on_unload, "on_unload")
        del self._loaded[name]

    def unload_all(self) -> None:
        """Unload every plugin in reverse-registration order."""
        for name in list(reversed(list(self._loaded.keys()))):
            try:
                self.unload(name)
            except PluginNotFoundError:
                pass

    def reload(self, name: str) -> LoadedPlugin:
        """Unload + re-load *name* from its original manifest path."""
        record = self._loaded.get(name)
        if record is None:
            raise PluginNotFoundError(f"no plugin named '{name}' is loaded")
        manifest_path = record.manifest.manifest_path
        if manifest_path is None:
            raise PluginError(f"plugin '{name}' has no manifest_path to reload from")
        self.unload(name)
        return self.load(manifest_path)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------
    def list_loaded(self) -> list[str]:
        """Names of all plugins the registry knows about (including errored / disabled)."""
        return list(self._loaded.keys())

    def get(self, name: str) -> LoadedPlugin:
        record = self._loaded.get(name)
        if record is None:
            raise PluginNotFoundError(f"no plugin named '{name}' is loaded")
        return record

    def find_by_capability(self, cap: str) -> list[LoadedPlugin]:
        """Return every successfully-loaded plugin that advertises *cap*."""
        return [
            rec
            for rec in self._loaded.values()
            if rec.module is not None
            and rec.load_error is None
            and cap in rec.manifest.provides
        ]

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _invoke_hook(
        self,
        record: LoadedPlugin,
        hook_name: str | None,
        label: str,
    ) -> None:
        """Call the named hook on the plugin's module inside a sandbox."""
        if hook_name is None or record.module is None:
            return
        fn = getattr(record.module, hook_name, None)
        if fn is None:
            record.load_error = f"{label} hook '{hook_name}' not found on module"
            _LOG.warning(
                "plugin %s: %s hook %r missing", record.name, label, hook_name
            )
            return
        try:
            fn()
        except Exception as exc:
            tb = traceback.format_exc()
            record.load_error = f"{label} raised {type(exc).__name__}: {exc}"
            _LOG.warning(
                "plugin %s: %s hook raised — %s\n%s", record.name, label, exc, tb
            )
