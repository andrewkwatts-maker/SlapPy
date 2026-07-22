"""Project manifest for the Pharos Engine exporter (LL6).

A ``ProjectManifest`` is a small YAML file (``pharosproject.yaml``) that
lives at the project root and describes the ship-time metadata the
exporter needs: name, version, author, main script, additional asset
directories, and Python compatibility range.

The file is optional — when it is missing the exporter fabricates a
manifest from ``config.yaml`` + directory conventions so that legacy
projects still export cleanly.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


__all__ = ["ProjectManifest", "MANIFEST_FILENAME", "load_manifest"]


MANIFEST_FILENAME = "pharosproject.yaml"


@dataclass
class ProjectManifest:
    """Ship-time project metadata.

    ``assets_dirs`` are paths *relative to the project root* — the
    exporter walks each of these when bundling.  ``main_script`` is the
    entry-point filename (default ``main.py``).  ``python_requires`` uses
    PEP 440 syntax (e.g. ``">=3.10"``).
    """

    name: str = "untitled"
    version: str = "0.1.0"
    author: str = ""
    main_script: str = "main.py"
    assets_dirs: list[str] = field(default_factory=lambda: ["assets", "scenes"])
    python_requires: str = ">=3.10"

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_yaml(self) -> str:
        try:
            import yaml
        except ImportError:  # pragma: no cover - pyyaml is a hard dep
            # Minimal hand-rolled YAML good enough for round-trip
            lines: list[str] = []
            for k, v in self.to_dict().items():
                if isinstance(v, list):
                    lines.append(f"{k}:")
                    for item in v:
                        lines.append(f"  - {item}")
                else:
                    lines.append(f"{k}: {v}")
            return "\n".join(lines) + "\n"
        return yaml.safe_dump(self.to_dict(), sort_keys=False)

    @classmethod
    def from_yaml(cls, text: str) -> "ProjectManifest":
        try:
            import yaml
            data = yaml.safe_load(text) or {}
        except ImportError:  # pragma: no cover
            data = _mini_yaml_load(text)
        if not isinstance(data, dict):
            raise ValueError("manifest YAML must decode to a mapping")
        # Filter to known fields to be forward-compatible
        known = {f.name for f in cls.__dataclass_fields__.values()}
        clean = {k: v for k, v in data.items() if k in known}
        return cls(**clean)

    # ------------------------------------------------------------------
    # Filesystem helpers
    # ------------------------------------------------------------------
    @classmethod
    def load(cls, project_dir: Path | str) -> "ProjectManifest":
        """Read ``pharosproject.yaml`` from *project_dir* or synthesise defaults."""
        project_dir = Path(project_dir)
        manifest_path = project_dir / MANIFEST_FILENAME
        if manifest_path.is_file():
            return cls.from_yaml(manifest_path.read_text(encoding="utf-8"))
        return cls._from_project_dir(project_dir)

    @classmethod
    def _from_project_dir(cls, project_dir: Path) -> "ProjectManifest":
        """Best-effort manifest built from ``config.yaml`` + folder layout."""
        name = project_dir.name or "untitled"
        version = "0.1.0"
        author = ""
        assets = []
        cfg = project_dir / "config.yaml"
        if cfg.is_file():
            try:
                import yaml
                data = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
                project_block = data.get("project", {}) if isinstance(data, dict) else {}
                if isinstance(project_block, dict):
                    name = str(project_block.get("name", name))
                    version = str(project_block.get("version", version))
                    author = str(project_block.get("author", author))
                assets_block = data.get("assets", {}) if isinstance(data, dict) else {}
                if isinstance(assets_block, dict):
                    paths = assets_block.get("paths") or []
                    assets = [str(p).rstrip("/") for p in paths]
            except Exception:
                pass
        # Fold in scenes/ + assets/ conventions
        for candidate in ("assets", "scenes"):
            if (project_dir / candidate).is_dir() and candidate not in assets:
                assets.append(candidate)
        if not assets:
            assets = ["assets", "scenes"]
        return cls(
            name=name,
            version=version,
            author=author,
            main_script="main.py",
            assets_dirs=assets,
            python_requires=">=3.10",
        )

    def write(self, project_dir: Path | str) -> Path:
        project_dir = Path(project_dir)
        target = project_dir / MANIFEST_FILENAME
        target.write_text(self.to_yaml(), encoding="utf-8")
        return target


def load_manifest(project_dir: Path | str) -> ProjectManifest:
    """Convenience wrapper for :meth:`ProjectManifest.load`."""
    return ProjectManifest.load(project_dir)


# ---------------------------------------------------------------------------
# Minimal YAML fallback
# ---------------------------------------------------------------------------


def _mini_yaml_load(text: str) -> dict[str, Any]:  # pragma: no cover
    """Extremely small YAML subset good enough for our manifest fields."""
    out: dict[str, Any] = {}
    current_key: str | None = None
    current_list: list[Any] | None = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        if line.startswith("  - ") and current_list is not None:
            current_list.append(line[4:].strip())
            continue
        if ":" in line:
            k, _, v = line.partition(":")
            k = k.strip()
            v = v.strip()
            if not v:
                current_list = []
                out[k] = current_list
                current_key = k
            else:
                out[k] = v
                current_list = None
                current_key = k
    return out
