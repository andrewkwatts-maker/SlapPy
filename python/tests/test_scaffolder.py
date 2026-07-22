"""Engine tests for build/scaffolder.py — headless."""
from __future__ import annotations
import pytest
from pathlib import Path


class TestScaffoldProject:
    def test_creates_project_dir(self, tmp_path):
        from slappyengine.build.scaffolder import scaffold_project
        result = scaffold_project("MyGame", str(tmp_path), template="blank")
        assert result.is_dir()
        assert result.name == "MyGame"

    def test_returns_absolute_path(self, tmp_path):
        from slappyengine.build.scaffolder import scaffold_project
        result = scaffold_project("TestProject", str(tmp_path))
        assert result.is_absolute()

    def test_creates_source_dir(self, tmp_path):
        from slappyengine.build.scaffolder import scaffold_project
        root = scaffold_project("G", str(tmp_path))
        assert (root / "Source").is_dir()

    def test_creates_main_py(self, tmp_path):
        from slappyengine.build.scaffolder import scaffold_project
        root = scaffold_project("G", str(tmp_path))
        assert (root / "Source" / "main.py").exists()

    def test_creates_content_dir(self, tmp_path):
        from slappyengine.build.scaffolder import scaffold_project
        root = scaffold_project("G", str(tmp_path))
        assert (root / "Content").is_dir()

    def test_creates_config_dir(self, tmp_path):
        from slappyengine.build.scaffolder import scaffold_project
        root = scaffold_project("G", str(tmp_path))
        assert (root / "Config").is_dir()

    def test_creates_asset_subdirs(self, tmp_path):
        from slappyengine.build.scaffolder import scaffold_project
        root = scaffold_project("G", str(tmp_path))
        assets = root / "Content" / "Assets"
        for sub in ("sprites", "audio", "meshes"):
            assert (assets / sub).is_dir(), f"Missing: {sub}"

    def test_creates_tests_dir(self, tmp_path):
        from slappyengine.build.scaffolder import scaffold_project
        root = scaffold_project("G", str(tmp_path))
        assert (root / "Source" / "tests").is_dir()

    def test_blank_template_main_content(self, tmp_path):
        from slappyengine.build.scaffolder import scaffold_project
        root = scaffold_project("G", str(tmp_path), template="blank")
        content = (root / "Source" / "main.py").read_text()
        assert "Engine" in content

    def test_2d_template_main_content(self, tmp_path):
        from slappyengine.build.scaffolder import scaffold_project
        root = scaffold_project("G", str(tmp_path), template="2d")
        content = (root / "Source" / "main.py").read_text()
        assert "Scene" in content or "Entity" in content

    def test_3d_template_main_content(self, tmp_path):
        from slappyengine.build.scaffolder import scaffold_project
        root = scaffold_project("G", str(tmp_path), template="3d")
        content = (root / "Source" / "main.py").read_text()
        assert "ibl" in content.lower() or "Engine" in content

    def test_unknown_template_raises(self, tmp_path):
        from slappyengine.build.scaffolder import scaffold_project
        with pytest.raises(ValueError, match="Unknown template"):
            scaffold_project("G", str(tmp_path), template="nonexistent")

    def test_creates_gitignore(self, tmp_path):
        from slappyengine.build.scaffolder import scaffold_project
        root = scaffold_project("G", str(tmp_path))
        assert (root / ".gitignore").exists()

    def test_creates_readme(self, tmp_path):
        from slappyengine.build.scaffolder import scaffold_project
        root = scaffold_project("G", str(tmp_path))
        readme = root / "README.md"
        assert readme.exists()
        assert "G" in readme.read_text()

    def test_project_name_in_manifest(self, tmp_path):
        from slappyengine.build.scaffolder import scaffold_project
        root = scaffold_project("AwesomeGame", str(tmp_path))
        manifest = root / "Config" / "project.yml"
        if manifest.exists():
            content = manifest.read_text()
            assert "AwesomeGame" in content

    def test_idempotent_second_call(self, tmp_path):
        from slappyengine.build.scaffolder import scaffold_project
        scaffold_project("G", str(tmp_path))
        # Second call should not raise
        root2 = scaffold_project("G", str(tmp_path))
        assert root2.is_dir()
