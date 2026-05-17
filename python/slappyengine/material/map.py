from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import yaml


@dataclass
class ColorRange:
    r: tuple[int, int] = (0, 255)
    g: tuple[int, int] = (0, 255)
    b: tuple[int, int] = (0, 255)

    def matches(self, r: int, g: int, b: int) -> bool:
        return (self.r[0] <= r <= self.r[1] and
                self.g[0] <= g <= self.g[1] and
                self.b[0] <= b <= self.b[1])


@dataclass
class MaterialDef:
    name: str
    color_range: ColorRange
    alpha_meaning: str = "opacity"
    behaviors: list[str] = field(default_factory=list)
    params: dict = field(default_factory=dict)


class MaterialMap:
    def __init__(self):
        self._materials: list[MaterialDef] = []

    def add(self, name: str, color_range: ColorRange,
            alpha_meaning: str = "opacity",
            behaviors: list[str] | None = None,
            params: dict | None = None) -> MaterialDef:
        m = MaterialDef(
            name=name,
            color_range=color_range,
            alpha_meaning=alpha_meaning,
            behaviors=behaviors or [],
            params=params or {},
        )
        self._materials.append(m)
        return m

    def match(self, r: int, g: int, b: int) -> MaterialDef | None:
        for m in self._materials:
            if m.color_range.matches(r, g, b):
                return m
        return None

    @classmethod
    def from_yaml(cls, path: str | Path) -> "MaterialMap":
        with open(path) as f:
            data = yaml.safe_load(f)
        inst = cls()
        for m in data.get("materials", []):
            cr_data = m["color_range"]
            cr = ColorRange(
                r=tuple(cr_data["r"]),
                g=tuple(cr_data["g"]),
                b=tuple(cr_data["b"]),
            )
            inst.add(
                name=m["name"],
                color_range=cr,
                alpha_meaning=m.get("alpha_meaning", "opacity"),
                behaviors=m.get("behaviors", []),
                params=m.get("params", {}),
            )
        return inst

    @classmethod
    def load_defaults(cls) -> "MaterialMap":
        config_dir = Path(__file__).parent.parent.parent.parent / "config"
        yml_path = config_dir / "materials.yml"
        if yml_path.exists():
            return cls.from_yaml(yml_path)
        return cls()
