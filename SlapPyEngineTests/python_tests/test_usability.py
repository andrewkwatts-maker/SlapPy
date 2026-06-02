"""Tests for engine usability features (no DearPyGui required for most):
- Engine lifecycle hooks (on_launch, on_tick, on_end)
- First-run scaffold
- project.yml config merge
- AssetManifest / SceneManifest / LevelManifest round-trip
- ScriptBinding (on_launch/on_tick/on_end per-entity hooks)
- ManifestRegistry.scan
- content_encrypt round-trip
- docs_gen.generate_docs
- build_gen.generate_build_scripts
"""
from __future__ import annotations

import sys
import os
import importlib
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── Engine lifecycle hooks ────────────────────────────────────────────────────

class TestEngineHooks:
    def _engine(self):
        from slappyengine.engine import Engine
        e = Engine.__new__(Engine)
        e._launch_hooks = []
        e._tick_hooks = []
        e._end_hooks = []
        return e

    def test_on_launch_decorator(self):
        e = self._engine()
        calls = []

        @e.on_launch
        def setup():
            calls.append("launch")

        assert len(e._launch_hooks) == 1

    def test_on_tick_decorator(self):
        e = self._engine()
        dts = []

        @e.on_tick
        def update(dt):
            dts.append(dt)

        assert len(e._tick_hooks) == 1

    def test_on_end_decorator(self):
        e = self._engine()
        called = []

        @e.on_end
        def cleanup():
            called.append(True)

        assert len(e._end_hooks) == 1

    def test_on_launch_plain_call(self):
        e = self._engine()
        fn = lambda: None
        e.on_launch(fn)
        assert fn in e._launch_hooks

    def test_on_tick_plain_call(self):
        e = self._engine()
        fn = lambda dt: None
        e.on_tick(fn)
        assert fn in e._tick_hooks

    def test_on_end_plain_call(self):
        e = self._engine()
        fn = lambda: None
        e.on_end(fn)
        assert fn in e._end_hooks

    def test_multiple_hooks_registered(self):
        e = self._engine()
        e.on_launch(lambda: None)
        e.on_launch(lambda: None)
        assert len(e._launch_hooks) == 2

    def test_on_launch_decorator_returns_function(self):
        e = self._engine()

        @e.on_launch
        def setup():
            pass

        assert callable(setup)


# ── First-run scaffold ────────────────────────────────────────────────────────

class TestFirstRunScaffold:
    def test_scaffold_creates_engine_yml(self, tmp_path):
        from slappyengine.config import _scaffold_first_run
        cfg_dir = _scaffold_first_run(tmp_path)
        assert (cfg_dir / "engine.yml").exists()

    def test_scaffold_creates_project_yml(self, tmp_path):
        from slappyengine.config import _scaffold_first_run
        _scaffold_first_run(tmp_path)
        assert (tmp_path / "project.yml").exists()

    def test_scaffold_creates_asset_dirs(self, tmp_path):
        from slappyengine.config import _scaffold_first_run
        _scaffold_first_run(tmp_path)
        assert (tmp_path / "assets").is_dir()
        assert (tmp_path / "scenes").is_dir()
        assert (tmp_path / "scripts").is_dir()

    def test_scaffold_engine_yml_parseable(self, tmp_path):
        import yaml
        from slappyengine.config import _scaffold_first_run
        cfg_dir = _scaffold_first_run(tmp_path)
        raw = yaml.safe_load((cfg_dir / "engine.yml").read_text())
        assert "window" in raw
        assert "physics" in raw

    def test_scaffold_project_yml_parseable(self, tmp_path):
        import yaml
        from slappyengine.config import _scaffold_first_run
        _scaffold_first_run(tmp_path)
        raw = yaml.safe_load((tmp_path / "project.yml").read_text())
        assert "name" in raw
        assert "platforms" in raw

    def test_scaffold_idempotent(self, tmp_path):
        from slappyengine.config import _scaffold_first_run
        _scaffold_first_run(tmp_path)
        _scaffold_first_run(tmp_path)  # second call must not crash
        assert (tmp_path / "project.yml").exists()


# ── project.yml config merge ──────────────────────────────────────────────────

class TestProjectYmlMerge:
    def test_deep_merge_flat(self):
        from slappyengine.config import _deep_merge
        base = {"a": 1, "b": 2}
        override = {"b": 99, "c": 3}
        result = _deep_merge(base, override)
        assert result == {"a": 1, "b": 99, "c": 3}

    def test_deep_merge_nested(self):
        from slappyengine.config import _deep_merge
        base = {"window": {"title": "Engine", "width": 800}}
        override = {"window": {"title": "My Game"}}
        result = _deep_merge(base, override)
        assert result["window"]["title"] == "My Game"
        assert result["window"]["width"] == 800

    def test_deep_merge_does_not_mutate_base(self):
        from slappyengine.config import _deep_merge
        base = {"x": {"y": 1}}
        _deep_merge(base, {"x": {"y": 2}})
        assert base["x"]["y"] == 1


# ── AssetManifest round-trip ──────────────────────────────────────────────────

class TestAssetManifest:
    def test_from_dict_minimal(self):
        from slappyengine.asset_manifest import AssetManifest
        m = AssetManifest.from_dict({"name": "Player"})
        assert m.name == "Player"
        assert m.type == "asset"
        assert m.layers == []

    def test_to_dict_round_trips(self):
        from slappyengine.asset_manifest import AssetManifest, LayerManifest
        m = AssetManifest(
            name="Car",
            layers=[LayerManifest(name="body", texture="car.png")],
            scripts=["scripts/car.py"],
        )
        d = m.to_dict()
        m2 = AssetManifest.from_dict(d)
        assert m2.name == "Car"
        assert m2.layers[0].texture == "car.png"
        assert m2.scripts == ["scripts/car.py"]

    def test_save_load_round_trip(self, tmp_path):
        from slappyengine.asset_manifest import AssetManifest, LayerManifest
        m = AssetManifest(name="Enemy", layers=[LayerManifest(name="body")])
        p = tmp_path / "enemy.yml"
        m.save(p)
        m2 = AssetManifest.load(p)
        assert m2.name == "Enemy"

    def test_checksum_stable(self):
        from slappyengine.asset_manifest import AssetManifest
        m = AssetManifest(name="X")
        assert m.checksum() == m.checksum()

    def test_checksum_changes_with_content(self):
        from slappyengine.asset_manifest import AssetManifest
        m1 = AssetManifest(name="A")
        m2 = AssetManifest(name="B")
        assert m1.checksum() != m2.checksum()

    def test_collision_round_trips(self):
        from slappyengine.asset_manifest import AssetManifest, CollisionManifest
        m = AssetManifest(name="Wall", collision=CollisionManifest(width=64, height=16))
        m2 = AssetManifest.from_dict(m.to_dict())
        assert m2.collision is not None
        assert m2.collision.width == 64


# ── SceneManifest / LevelManifest ─────────────────────────────────────────────

class TestSceneManifest:
    def test_round_trip(self, tmp_path):
        from slappyengine.asset_manifest import SceneManifest
        m = SceneManifest(
            name="Main",
            entities=[{"manifest": "assets/player.yml", "position": [0, 0]}],
            lighting={"ambient_intensity": 0.3},
        )
        p = tmp_path / "main.yml"
        m.save(p)
        m2 = SceneManifest.load(p)
        assert m2.name == "Main"
        assert m2.lighting["ambient_intensity"] == pytest.approx(0.3)

    def test_load_manifest_routes_scene(self, tmp_path):
        import yaml
        from slappyengine.asset_manifest import load_manifest, SceneManifest
        p = tmp_path / "scene.yml"
        p.write_text(yaml.dump({"name": "Test", "type": "scene", "entities": []}))
        result = load_manifest(p)
        assert isinstance(result, SceneManifest)


# ── ScriptBinding ─────────────────────────────────────────────────────────────

class TestScriptBinding:
    def _write_script(self, tmp_path, content: str) -> Path:
        p = tmp_path / "test_script.py"
        p.write_text(content)
        return p

    def test_launch_called(self, tmp_path):
        from slappyengine.asset_manifest import AssetManifest, ScriptBinding
        script = self._write_script(tmp_path, "called = []\ndef on_launch(e): called.append(e)\n")
        m = AssetManifest(name="E", scripts=[str(script)])
        # Clear module cache so the freshly-written file is loaded
        ScriptBinding._module_cache.clear()
        binding = ScriptBinding(m, search_paths=[tmp_path])

        class _FakeEntity:
            pass

        entity = _FakeEntity()
        binding.launch(entity)
        # Verify the module was actually loaded and the hook ran
        assert len(binding._modules) == 1
        assert entity in binding._modules[0].called

    def test_tick_called_with_dt(self, tmp_path):
        from slappyengine.asset_manifest import AssetManifest, ScriptBinding
        script = self._write_script(tmp_path, "ticks=[]\ndef on_tick(e,dt): ticks.append(dt)\n")
        m = AssetManifest(name="E2", scripts=[str(script)])
        ScriptBinding._module_cache.clear()
        binding = ScriptBinding(m, search_paths=[tmp_path])
        binding.tick(object(), 0.016)
        assert binding._modules[0].ticks == [pytest.approx(0.016)]

    def test_end_called(self, tmp_path):
        from slappyengine.asset_manifest import AssetManifest, ScriptBinding
        script = self._write_script(tmp_path, "ended=[]\ndef on_end(e): ended.append(True)\n")
        m = AssetManifest(name="E3", scripts=[str(script)])
        ScriptBinding._module_cache.clear()
        binding = ScriptBinding(m, search_paths=[tmp_path])
        binding.end(object())
        assert binding._modules[0].ended == [True]

    def test_missing_script_warns(self, tmp_path):
        from slappyengine.asset_manifest import AssetManifest, ScriptBinding
        m = AssetManifest(name="E4", scripts=["nonexistent.py"])
        ScriptBinding._module_cache.clear()
        with pytest.warns(UserWarning, match="not found"):
            binding = ScriptBinding(m, search_paths=[tmp_path])
        assert len(binding._modules) == 0

    def test_partial_hooks_ok(self, tmp_path):
        """Script with only on_tick (no on_launch/on_end) should not crash."""
        from slappyengine.asset_manifest import AssetManifest, ScriptBinding
        script = self._write_script(tmp_path, "def on_tick(e,dt): pass\n")
        m = AssetManifest(name="E5", scripts=[str(script)])
        ScriptBinding._module_cache.clear()
        binding = ScriptBinding(m, search_paths=[tmp_path])
        binding.launch(object())  # no on_launch defined — must not raise
        binding.end(object())

    def test_module_cache_shared(self, tmp_path):
        """Two bindings on the same script share the module object."""
        from slappyengine.asset_manifest import AssetManifest, ScriptBinding
        script = self._write_script(tmp_path, "counter = 0\ndef on_launch(e): pass\n")
        m1 = AssetManifest(name="EA", scripts=[str(script)])
        m2 = AssetManifest(name="EB", scripts=[str(script)])
        ScriptBinding._module_cache.clear()
        b1 = ScriptBinding(m1, search_paths=[tmp_path])
        b2 = ScriptBinding(m2, search_paths=[tmp_path])
        assert b1._modules[0] is b2._modules[0]


# ── ManifestRegistry ──────────────────────────────────────────────────────────

class TestManifestRegistry:
    def test_scan_finds_assets(self, tmp_path):
        import yaml
        from slappyengine.asset_manifest import ManifestRegistry
        (tmp_path / "player.yml").write_text(
            yaml.dump({"name": "Player", "type": "asset"})
        )
        reg = ManifestRegistry()
        reg.scan(tmp_path)
        assert reg.get_asset("Player") is not None

    def test_scan_finds_scenes(self, tmp_path):
        import yaml
        from slappyengine.asset_manifest import ManifestRegistry
        (tmp_path / "main.yml").write_text(
            yaml.dump({"name": "Main", "type": "scene", "entities": []})
        )
        reg = ManifestRegistry()
        reg.scan(tmp_path)
        assert reg.get_scene("Main") is not None


# ── content_encrypt ───────────────────────────────────────────────────────────

class TestContentEncrypt:
    def test_encrypt_decrypt_round_trip(self):
        from slappyengine.content_encrypt import derive_key, encrypt_bytes, decrypt_bytes
        key, _ = derive_key("test-pass")
        data = b"hello world"
        ct = encrypt_bytes(data, key)
        assert decrypt_bytes(ct, key) == data

    def test_ciphertext_differs_from_plaintext(self):
        from slappyengine.content_encrypt import derive_key, encrypt_bytes
        key, _ = derive_key("pass")
        ct = encrypt_bytes(b"plain", key)
        assert ct != b"plain"

    def test_derive_key_produces_32_bytes(self):
        from slappyengine.content_encrypt import derive_key
        key, salt = derive_key("abc")
        assert len(key) == 32
        assert len(salt) == 16

    def test_encrypt_file_decrypt_file(self, tmp_path):
        from slappyengine.content_encrypt import derive_key, encrypt_file, decrypt_file
        key, _ = derive_key("filekey")
        src = tmp_path / "asset.png"
        src.write_bytes(b"\x89PNG fake")
        enc = tmp_path / "asset.png.enc"
        encrypt_file(src, enc, key)
        assert enc.exists()
        recovered = decrypt_file(enc, key)
        assert recovered == b"\x89PNG fake"

    def test_encrypt_dir_mirrors_structure(self, tmp_path):
        from slappyengine.content_encrypt import derive_key, encrypt_dir
        key, _ = derive_key("dirkey")
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.png").write_bytes(b"AAA")
        (src / "sub").mkdir()
        (src / "sub" / "b.yml").write_text("key: val")
        dst = tmp_path / "dst"
        paths = encrypt_dir(src, dst, key, extensions=[".png", ".yml"])
        assert len(paths) == 2


# ── docs_gen ─────────────────────────────────────────────────────────────────

class TestDocsGen:
    def test_generate_docs_creates_html(self, tmp_path):
        from slappyengine.docs_gen import generate_docs
        out = generate_docs(output_dir=tmp_path)
        assert out.exists()
        content = out.read_text(encoding="utf-8")
        assert "SlapPyEngine" in content
        assert "<html" in content

    def test_generate_docs_contains_lifecycle_section(self, tmp_path):
        from slappyengine.docs_gen import generate_docs
        out = generate_docs(output_dir=tmp_path)
        content = out.read_text()
        assert "on_launch" in content
        assert "on_tick" in content

    def test_generate_docs_contains_manifest_section(self, tmp_path):
        from slappyengine.docs_gen import generate_docs
        out = generate_docs(output_dir=tmp_path)
        content = out.read_text()
        assert "asset_manifest" in content.lower() or "Asset Manifest" in content


# ── build_gen ─────────────────────────────────────────────────────────────────

class TestBuildGen:
    def _write_project_yml(self, tmp_path, platforms, encrypt=False):
        import yaml
        p = tmp_path / "project.yml"
        p.write_text(yaml.dump({
            "name": "TestGame",
            "entry": "main.py",
            "platforms": platforms,
            "encryption": {"enabled": encrypt, "key": ""},
        }))
        return p

    def test_generates_windows_bat(self, tmp_path):
        from slappyengine.build_gen import generate_build_scripts
        yml = self._write_project_yml(tmp_path, ["windows"])
        paths = generate_build_scripts(yml, tmp_path)
        bat = tmp_path / "build_windows.bat"
        assert bat.exists()
        assert "maturin" in bat.read_text()

    def test_generates_linux_sh(self, tmp_path):
        from slappyengine.build_gen import generate_build_scripts
        yml = self._write_project_yml(tmp_path, ["linux"])
        generate_build_scripts(yml, tmp_path)
        sh = tmp_path / "build_linux.sh"
        assert sh.exists()
        assert "#!/usr/bin/env bash" in sh.read_text()

    def test_generates_macos_sh(self, tmp_path):
        from slappyengine.build_gen import generate_build_scripts
        yml = self._write_project_yml(tmp_path, ["macos"])
        generate_build_scripts(yml, tmp_path)
        assert (tmp_path / "build_macos.sh").exists()

    def test_multiple_platforms(self, tmp_path):
        from slappyengine.build_gen import generate_build_scripts
        yml = self._write_project_yml(tmp_path, ["windows", "linux"])
        paths = generate_build_scripts(yml, tmp_path)
        assert len(paths) == 2

    def test_encryption_wired_in_bat(self, tmp_path):
        from slappyengine.build_gen import generate_build_scripts
        yml = self._write_project_yml(tmp_path, ["windows"], encrypt=True)
        generate_build_scripts(yml, tmp_path)
        content = (tmp_path / "build_windows.bat").read_text()
        assert "encrypt" in content.lower() or "SLAP_CONTENT_KEY" in content

    def test_unknown_platform_warns(self, tmp_path):
        from slappyengine.build_gen import generate_build_scripts
        yml = self._write_project_yml(tmp_path, ["amiga"])
        with pytest.warns(UserWarning, match="Unknown platform"):
            paths = generate_build_scripts(yml, tmp_path)
        assert paths == []

    def test_missing_project_yml_raises(self, tmp_path):
        from slappyengine.build_gen import generate_build_scripts
        with pytest.raises(FileNotFoundError):
            generate_build_scripts(tmp_path / "nonexistent.yml", tmp_path)


# ── ScriptBindingPanel (headless, no DPG) ────────────────────────────────────

class TestScriptBindingPanel:
    def test_inspect_script_detects_hooks(self, tmp_path):
        from slappyengine.ui.editor.script_binding_panel import _inspect_script
        p = tmp_path / "ctrl.py"
        p.write_text("def on_launch(e): pass\ndef on_tick(e,dt): pass\n")
        info = _inspect_script(p)
        assert "on_launch" in info["hooks"]
        assert "on_tick" in info["hooks"]
        assert "on_end" not in info["hooks"]

    def test_inspect_script_detects_subscribe(self, tmp_path):
        from slappyengine.ui.editor.script_binding_panel import _inspect_script
        p = tmp_path / "sub.py"
        p.write_text('from slappyengine.event_bus import global_bus\nglobal_bus.subscribe("vehicle:hit", lambda p: None)\n')
        info = _inspect_script(p)
        assert "vehicle:hit" in info["subscribes"]

    def test_inspect_missing_script_returns_empty(self, tmp_path):
        from slappyengine.ui.editor.script_binding_panel import _inspect_script
        info = _inspect_script(tmp_path / "nonexistent.py")
        assert info["hooks"] == set()
        assert info["subscribes"] == []

    def test_scan_scripts_finds_py_files(self, tmp_path):
        from slappyengine.ui.editor.script_binding_panel import _scan_scripts
        (tmp_path / "a.py").write_text("pass")
        (tmp_path / "b.py").write_text("pass")
        (tmp_path / "data.yml").write_text("x: 1")
        found = _scan_scripts([tmp_path])
        names = {p.name for p in found}
        assert "a.py" in names
        assert "b.py" in names
        assert "data.yml" not in names

    def test_panel_set_entity_with_manifest(self, tmp_path):
        import yaml
        from slappyengine.ui.editor.script_binding_panel import ScriptBindingPanel
        # Write a minimal manifest
        m_path = tmp_path / "assets" / "player.yml"
        m_path.parent.mkdir()
        m_path.write_text(yaml.dump({
            "name": "Player", "type": "asset",
            "scripts": ["scripts/ctrl.py"],
            "layers": [],
        }))

        class _Entity:
            name = "Player"

        panel = ScriptBindingPanel(search_dirs=[tmp_path / "scripts"])
        panel.set_entity(_Entity(), manifest_path=m_path)
        assert panel._manifest is not None
        assert panel._manifest.scripts == ["scripts/ctrl.py"]

    def test_auto_create_script(self, tmp_path):
        import os
        from slappyengine.ui.editor.script_binding_panel import ScriptBindingPanel

        class _Entity:
            name = "Hero"

        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        panel = ScriptBindingPanel(search_dirs=[scripts_dir])
        panel._entity = _Entity()
        # Manually set cwd-relative lookup base
        original_cwd = Path.cwd()
        os.chdir(tmp_path)
        try:
            panel._on_create()
        finally:
            os.chdir(original_cwd)
        assert (scripts_dir / "hero.py").exists()
        content = (scripts_dir / "hero.py").read_text()
        assert "on_launch" in content
        assert "on_tick" in content
        assert "on_end" in content
