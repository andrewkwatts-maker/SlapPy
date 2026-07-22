"""Tripwire suite for :mod:`pharos_engine.ui.plugin_registry` — sprint GG3.

Covers:

* :class:`PluginManifest.from_dict` / :meth:`from_yaml` parsing +
  validation (missing fields, unknown fields, list-type coercion).
* :meth:`PluginRegistry.discover` walks nested plugin trees under
  ``tmp_path`` and finds every ``plugin.yaml``.
* :meth:`PluginRegistry.load` imports a file-path entry, invokes
  ``on_load``, and populates :class:`LoadedPlugin`.
* :meth:`PluginRegistry.load_all` respects dependency order — a
  plugin that requires another is imported *after* its dep.
* Circular dependencies raise :class:`PluginDependencyError` with the
  cycle path attached.
* Missing dependencies raise :class:`PluginError`.
* Disabled plugins land in the registry but never import their entry.
* A plugin whose ``on_load`` hook raises does **not** kill the
  registry; ``load_error`` is populated.
* :meth:`PluginRegistry.unload` invokes ``on_unload`` and evicts the
  plugin; :meth:`unload` on an unknown name raises
  :class:`PluginNotFoundError`.
* :meth:`PluginRegistry.reload` round-trips a plugin.
* :meth:`PluginRegistry.find_by_capability` filters by ``provides``.
* :meth:`PluginRegistry.fire_shell_ready` fires deferred hooks exactly
  once and skips errored / disabled plugins.
* Bundled ``hello_plugin`` sample loads through the real code path.
* ``default_plugin_dir`` respects ``$HOME`` at call time.

Every test uses ``tmp_path`` so the suite never touches the real
``~/.pharos_engine/`` directory.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from pharos_engine.ui.plugin_registry import (
    LoadedPlugin,
    PluginDependencyError,
    PluginError,
    PluginManifest,
    PluginNotFoundError,
    PluginRegistry,
    default_plugin_dir,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _write_plugin(
    root: Path,
    name: str,
    *,
    entry_body: str = "def on_load():\n    pass\n",
    on_load: str | None = "on_load",
    on_shell_ready: str | None = None,
    on_unload: str | None = None,
    provides: list[str] | None = None,
    requires: list[str] | None = None,
    enabled: bool = True,
    version: str = "0.1.0",
    author: str | None = "tester",
) -> Path:
    """Write a plugin manifest + entry file under ``root/name`` and return the manifest path."""
    plugin_dir = root / name
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / f"{name}.py").write_text(entry_body, encoding="utf-8")
    lines = [
        f'name: "{name}"',
        f'version: "{version}"',
    ]
    if author is not None:
        lines.append(f"author: {author}")
    lines.append(f"entry: {name}.py")
    if on_load is not None:
        lines.append(f"on_load: {on_load}")
    if on_shell_ready is not None:
        lines.append(f"on_shell_ready: {on_shell_ready}")
    if on_unload is not None:
        lines.append(f"on_unload: {on_unload}")
    if provides:
        lines.append("provides:")
        for p in provides:
            lines.append(f"  - {p}")
    if requires:
        lines.append("requires:")
        for r in requires:
            lines.append(f"  - {r}")
    lines.append(f"enabled: {'true' if enabled else 'false'}")
    (plugin_dir / "plugin.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return plugin_dir / "plugin.yaml"


@pytest.fixture
def plugin_dir(tmp_path: Path) -> Path:
    """A fresh empty extensions directory rooted in ``tmp_path``."""
    root = tmp_path / "extensions"
    root.mkdir()
    return root


# ---------------------------------------------------------------------------
# Manifest tests
# ---------------------------------------------------------------------------


class TestManifest:
    def test_from_dict_minimum(self) -> None:
        m = PluginManifest.from_dict(
            {"name": "foo", "version": "1.0", "entry": "foo.py"}
        )
        assert m.name == "foo"
        assert m.version == "1.0"
        assert m.entry == "foo.py"
        assert m.enabled is True
        assert m.provides == []
        assert m.requires == []
        assert m.author is None

    def test_from_dict_missing_name(self) -> None:
        with pytest.raises(PluginError, match="name"):
            PluginManifest.from_dict({"version": "1.0", "entry": "foo.py"})

    def test_from_dict_missing_version(self) -> None:
        with pytest.raises(PluginError, match="version"):
            PluginManifest.from_dict({"name": "foo", "entry": "foo.py"})

    def test_from_dict_missing_entry(self) -> None:
        with pytest.raises(PluginError, match="entry"):
            PluginManifest.from_dict({"name": "foo", "version": "1.0"})

    def test_from_dict_rejects_non_list_provides(self) -> None:
        with pytest.raises(PluginError, match="provides"):
            PluginManifest.from_dict(
                {"name": "foo", "version": "1.0", "entry": "foo.py", "provides": "cap"}
            )

    def test_from_dict_rejects_non_list_requires(self) -> None:
        with pytest.raises(PluginError, match="requires"):
            PluginManifest.from_dict(
                {"name": "foo", "version": "1.0", "entry": "foo.py", "requires": "bar"}
            )

    def test_from_dict_ignores_unknown_keys(self) -> None:
        m = PluginManifest.from_dict(
            {
                "name": "foo",
                "version": "1.0",
                "entry": "foo.py",
                "some_future_field": 123,
            }
        )
        assert m.name == "foo"

    def test_from_yaml_populates_manifest_path(
        self, plugin_dir: Path
    ) -> None:
        path = _write_plugin(plugin_dir, "alpha")
        m = PluginManifest.from_yaml(path)
        assert m.manifest_path == path


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


class TestDiscover:
    def test_discover_empty_dir(self, plugin_dir: Path) -> None:
        reg = PluginRegistry()
        assert reg.discover(plugin_dir) == []

    def test_discover_missing_dir(self, tmp_path: Path) -> None:
        reg = PluginRegistry()
        assert reg.discover(tmp_path / "does_not_exist") == []

    def test_discover_finds_multiple(self, plugin_dir: Path) -> None:
        p1 = _write_plugin(plugin_dir, "alpha")
        p2 = _write_plugin(plugin_dir, "bravo")
        reg = PluginRegistry()
        found = reg.discover(plugin_dir)
        assert set(found) == {p1, p2}

    def test_discover_uses_default_when_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = tmp_path / "home"
        (home / ".pharos_engine" / "extensions").mkdir(parents=True)
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setenv("USERPROFILE", str(home))  # windows
        reg = PluginRegistry()
        # We don't put any manifests there — result should be empty
        # and no exception raised for using the default dir.
        assert reg.discover() == []

    def test_default_plugin_dir_uses_home(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        assert default_plugin_dir() == tmp_path / ".pharos_engine" / "extensions"


# ---------------------------------------------------------------------------
# Single-plugin load
# ---------------------------------------------------------------------------


class TestLoad:
    def test_load_invokes_on_load(self, plugin_dir: Path) -> None:
        body = textwrap.dedent(
            """
            CALLED = []
            def on_load():
                CALLED.append('load')
            """
        )
        p = _write_plugin(plugin_dir, "alpha", entry_body=body)
        reg = PluginRegistry()
        rec = reg.load(p)
        assert rec.module is not None
        assert rec.load_error is None
        assert rec.module.CALLED == ["load"]

    def test_load_missing_hook_records_error(self, plugin_dir: Path) -> None:
        body = "# no on_load defined\n"
        p = _write_plugin(plugin_dir, "alpha", entry_body=body)
        reg = PluginRegistry()
        rec = reg.load(p)
        assert rec.module is not None
        assert rec.load_error is not None
        assert "on_load" in rec.load_error

    def test_load_captures_hook_exception(self, plugin_dir: Path) -> None:
        body = textwrap.dedent(
            """
            def on_load():
                raise RuntimeError('boom')
            """
        )
        p = _write_plugin(plugin_dir, "buggy", entry_body=body)
        reg = PluginRegistry()
        rec = reg.load(p)
        assert rec.module is not None
        assert rec.load_error is not None
        assert "boom" in rec.load_error
        assert "RuntimeError" in rec.load_error

    def test_load_disabled_skips_import(self, plugin_dir: Path) -> None:
        body = textwrap.dedent(
            """
            def on_load():
                raise RuntimeError('should not run')
            """
        )
        p = _write_plugin(plugin_dir, "sleeper", entry_body=body, enabled=False)
        reg = PluginRegistry()
        rec = reg.load(p)
        assert rec.module is None
        assert rec.load_error == "disabled"

    def test_load_missing_entry_file(self, plugin_dir: Path) -> None:
        _write_plugin(plugin_dir, "ghost")
        (plugin_dir / "ghost" / "ghost.py").unlink()
        reg = PluginRegistry()
        with pytest.raises(PluginError, match="not found"):
            reg.load(plugin_dir / "ghost" / "plugin.yaml")

    def test_load_syntax_error_raises(self, plugin_dir: Path) -> None:
        body = "def broken(:\n"
        p = _write_plugin(plugin_dir, "broken", entry_body=body)
        reg = PluginRegistry()
        with pytest.raises(PluginError, match="import"):
            reg.load(p)


# ---------------------------------------------------------------------------
# load_all + dependency ordering
# ---------------------------------------------------------------------------


class TestLoadAll:
    def test_dependency_order(self, plugin_dir: Path) -> None:
        # 'b' depends on 'a'; ensure 'a' loads first.
        _write_plugin(
            plugin_dir,
            "a",
            entry_body="ORDER=['a']\ndef on_load():\n    pass\n",
        )
        _write_plugin(
            plugin_dir,
            "b",
            entry_body="ORDER=['b']\ndef on_load():\n    pass\n",
            requires=["a"],
        )
        reg = PluginRegistry()
        records = reg.load_all(plugin_dir)
        names = [r.name for r in records]
        assert names.index("a") < names.index("b")

    def test_multi_level_chain(self, plugin_dir: Path) -> None:
        _write_plugin(plugin_dir, "a")
        _write_plugin(plugin_dir, "b", requires=["a"])
        _write_plugin(plugin_dir, "c", requires=["b"])
        _write_plugin(plugin_dir, "d", requires=["a", "c"])
        reg = PluginRegistry()
        records = reg.load_all(plugin_dir)
        names = [r.name for r in records]
        for parent, child in [("a", "b"), ("b", "c"), ("a", "d"), ("c", "d")]:
            assert names.index(parent) < names.index(child), (parent, child, names)

    def test_circular_dependency_raises(self, plugin_dir: Path) -> None:
        _write_plugin(plugin_dir, "a", requires=["b"])
        _write_plugin(plugin_dir, "b", requires=["a"])
        reg = PluginRegistry()
        with pytest.raises(PluginDependencyError) as exc_info:
            reg.load_all(plugin_dir)
        assert exc_info.value.cycle  # populated
        # cycle path starts + ends with same name
        assert exc_info.value.cycle[0] == exc_info.value.cycle[-1]

    def test_missing_dependency_raises(self, plugin_dir: Path) -> None:
        _write_plugin(plugin_dir, "solo", requires=["ghost"])
        reg = PluginRegistry()
        with pytest.raises(PluginError, match="ghost"):
            reg.load_all(plugin_dir)

    def test_disabled_dep_skips_dependent(self, plugin_dir: Path) -> None:
        _write_plugin(plugin_dir, "core", enabled=False)
        _write_plugin(plugin_dir, "user", requires=["core"])
        reg = PluginRegistry()
        records = reg.load_all(plugin_dir)
        by_name = {r.name: r for r in records}
        assert by_name["core"].load_error == "disabled"
        assert by_name["user"].load_error is not None
        assert "core" in by_name["user"].load_error

    def test_duplicate_name_raises(self, plugin_dir: Path) -> None:
        _write_plugin(plugin_dir / "sub_a", "same")
        _write_plugin(plugin_dir / "sub_b", "same")
        reg = PluginRegistry()
        with pytest.raises(PluginError, match="duplicate"):
            reg.load_all(plugin_dir)

    def test_load_all_survives_hook_error(self, plugin_dir: Path) -> None:
        _write_plugin(
            plugin_dir,
            "good",
            entry_body="def on_load():\n    pass\n",
        )
        _write_plugin(
            plugin_dir,
            "bad",
            entry_body="def on_load():\n    raise RuntimeError('nope')\n",
        )
        reg = PluginRegistry()
        records = reg.load_all(plugin_dir)
        by_name = {r.name: r for r in records}
        assert by_name["good"].load_error is None
        assert by_name["bad"].load_error is not None
        # registry still has both
        assert set(reg.list_loaded()) == {"good", "bad"}


# ---------------------------------------------------------------------------
# Unload / reload
# ---------------------------------------------------------------------------


class TestUnload:
    def test_unload_calls_on_unload(self, plugin_dir: Path) -> None:
        body = textwrap.dedent(
            """
            CALLED = []
            def on_load(): CALLED.append('load')
            def on_unload(): CALLED.append('unload')
            """
        )
        p = _write_plugin(
            plugin_dir,
            "with_unload",
            entry_body=body,
            on_unload="on_unload",
        )
        reg = PluginRegistry()
        rec = reg.load(p)
        mod = rec.module
        reg.unload("with_unload")
        assert "unload" in mod.CALLED
        assert "with_unload" not in reg.list_loaded()

    def test_unload_unknown_raises(self) -> None:
        reg = PluginRegistry()
        with pytest.raises(PluginNotFoundError):
            reg.unload("nope")

    def test_reload_reruns_on_load(self, plugin_dir: Path) -> None:
        body = textwrap.dedent(
            """
            COUNT = [0]
            def on_load():
                COUNT[0] += 1
            """
        )
        p = _write_plugin(plugin_dir, "loop", entry_body=body)
        reg = PluginRegistry()
        rec1 = reg.load(p)
        assert rec1.module.COUNT == [1]
        rec2 = reg.reload("loop")
        # module was re-imported so COUNT reset to [0] then +1
        assert rec2.module is not rec1.module
        assert rec2.module.COUNT == [1]

    def test_reload_unknown_raises(self) -> None:
        reg = PluginRegistry()
        with pytest.raises(PluginNotFoundError):
            reg.reload("nope")

    def test_unload_all_clears_registry(self, plugin_dir: Path) -> None:
        _write_plugin(plugin_dir, "a")
        _write_plugin(plugin_dir, "b")
        reg = PluginRegistry()
        reg.load_all(plugin_dir)
        assert reg.list_loaded()
        reg.unload_all()
        assert reg.list_loaded() == []


# ---------------------------------------------------------------------------
# Capability + shell-ready
# ---------------------------------------------------------------------------


class TestQueries:
    def test_find_by_capability(self, plugin_dir: Path) -> None:
        _write_plugin(plugin_dir, "cap_a", provides=["ui", "audio"])
        _write_plugin(plugin_dir, "cap_b", provides=["ui"])
        _write_plugin(plugin_dir, "cap_c", provides=["physics"])
        reg = PluginRegistry()
        reg.load_all(plugin_dir)
        ui_plugins = {p.name for p in reg.find_by_capability("ui")}
        assert ui_plugins == {"cap_a", "cap_b"}
        assert {p.name for p in reg.find_by_capability("physics")} == {"cap_c"}
        assert reg.find_by_capability("nothing") == []

    def test_find_by_capability_excludes_errored(
        self, plugin_dir: Path
    ) -> None:
        _write_plugin(
            plugin_dir,
            "cap_bad",
            provides=["ui"],
            entry_body="def on_load():\n    raise RuntimeError('x')\n",
        )
        reg = PluginRegistry()
        reg.load_all(plugin_dir)
        assert reg.find_by_capability("ui") == []

    def test_get_unknown_raises(self) -> None:
        reg = PluginRegistry()
        with pytest.raises(PluginNotFoundError):
            reg.get("nope")

    def test_fire_shell_ready_invokes_hook_once(
        self, plugin_dir: Path
    ) -> None:
        body = textwrap.dedent(
            """
            COUNT = [0]
            def on_load():
                pass
            def on_shell_ready():
                COUNT[0] += 1
            """
        )
        p = _write_plugin(
            plugin_dir,
            "shell",
            entry_body=body,
            on_shell_ready="on_shell_ready",
        )
        reg = PluginRegistry()
        rec = reg.load(p)
        reg.fire_shell_ready()
        reg.fire_shell_ready()  # second call must not re-fire
        assert rec.module.COUNT == [1]
        assert rec.shell_ready_fired

    def test_fire_shell_ready_skips_disabled(self, plugin_dir: Path) -> None:
        _write_plugin(
            plugin_dir,
            "off",
            enabled=False,
            on_shell_ready="on_shell_ready",
        )
        reg = PluginRegistry()
        reg.load_all(plugin_dir)
        # No exception even though the disabled plugin has no module.
        reg.fire_shell_ready()
        assert reg.get("off").shell_ready_fired is False

    def test_list_loaded_returns_all_states(self, plugin_dir: Path) -> None:
        _write_plugin(plugin_dir, "a")
        _write_plugin(plugin_dir, "b", enabled=False)
        _write_plugin(
            plugin_dir,
            "c",
            entry_body="def on_load():\n    raise RuntimeError('x')\n",
        )
        reg = PluginRegistry()
        reg.load_all(plugin_dir)
        assert set(reg.list_loaded()) == {"a", "b", "c"}


# ---------------------------------------------------------------------------
# Sample plugin round-trip
# ---------------------------------------------------------------------------


class TestSamplePlugin:
    def test_sample_plugin_loads(self) -> None:
        """The bundled hello_plugin sample must round-trip through the registry."""
        sample = (
            Path(__file__).resolve().parents[2]
            / "python"
            / "pharos_engine"
            / "ui"
            / "plugin_samples"
            / "hello_plugin"
            / "plugin.yaml"
        )
        assert sample.exists(), f"missing sample manifest at {sample}"
        reg = PluginRegistry()
        rec = reg.load(sample)
        assert rec.load_error is None
        assert rec.module is not None
        assert "Loaded from GG3 sample" in rec.module.MESSAGES
        assert rec.module.greet("gg3") == "hello, gg3"
        # Fire shell-ready + unload to exercise the full lifecycle.
        reg.fire_shell_ready()
        assert "GG3 sample: shell ready" in rec.module.MESSAGES
        reg.unload("hello_plugin")
        assert "GG3 sample: unloading" in rec.module.MESSAGES
        assert "hello_plugin" not in reg.list_loaded()

    def test_sample_plugin_capability(self) -> None:
        sample = (
            Path(__file__).resolve().parents[2]
            / "python"
            / "pharos_engine"
            / "ui"
            / "plugin_samples"
            / "hello_plugin"
            / "plugin.yaml"
        )
        reg = PluginRegistry()
        reg.load(sample)
        assert [p.name for p in reg.find_by_capability("greeting")] == ["hello_plugin"]
        assert [p.name for p in reg.find_by_capability("sample")] == ["hello_plugin"]


# ---------------------------------------------------------------------------
# LoadedPlugin sanity
# ---------------------------------------------------------------------------


class TestLoadedPlugin:
    def test_name_property(self) -> None:
        manifest = PluginManifest(
            name="ping", version="1", entry="ping.py"
        )
        rec = LoadedPlugin(manifest=manifest)
        assert rec.name == "ping"
        assert rec.load_error is None
        assert rec.shell_ready_fired is False
