"""Declarative theme specification dataclasses.

A :class:`ThemeSpec` is a pure-data description of a UI theme: palette
entries, font records, nine-slice borders, SVG icons, and an optional
procedural background shader. It carries no rendering state of its own —
themes are *registered* and *applied* through ``slappyengine.ui.theme``.

The dataclasses defined here are deliberately small so themes round-trip
cleanly through YAML / JSON. Heavier rasterisation work lives in the
sibling modules (:mod:`nine_slice`, :mod:`svg_icon`, :mod:`shader_effects`).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from slappyengine._validation import (
    validate_finite_float,
    validate_non_empty_str,
    validate_non_negative_int,
    validate_positive_int,
    validate_str,
    validate_unit_float,
)


# ---------------------------------------------------------------------------
# Colour
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Color:
    """An sRGB colour with 8-bit per-channel + unit alpha.

    Parameters
    ----------
    r, g, b:
        Channels in ``[0, 255]``.
    a:
        Alpha in ``[0.0, 1.0]``. Float-valued so themes can author
        translucent surfaces without re-scaling to 0..255.
    """

    r: int = 0
    g: int = 0
    b: int = 0
    a: float = 1.0

    def __post_init__(self) -> None:
        fn = "Color"
        r = validate_non_negative_int("r", fn, self.r)
        g = validate_non_negative_int("g", fn, self.g)
        b = validate_non_negative_int("b", fn, self.b)
        for name, value in (("r", r), ("g", g), ("b", b)):
            if value > 255:
                raise ValueError(f"{fn}: {name} must be <= 255; got {value}")
        a = validate_unit_float("a", fn, self.a)
        # frozen=True so we have to use object.__setattr__ to normalise.
        object.__setattr__(self, "r", int(r))
        object.__setattr__(self, "g", int(g))
        object.__setattr__(self, "b", int(b))
        object.__setattr__(self, "a", float(a))

    def as_rgba_tuple(self) -> tuple[int, int, int, int]:
        """Return ``(r, g, b, a)`` with alpha scaled to ``[0, 255]``."""
        return (self.r, self.g, self.b, int(round(self.a * 255)))

    def as_float_tuple(self) -> tuple[float, float, float, float]:
        """Return ``(r, g, b, a)`` with every channel in ``[0, 1]``."""
        return (self.r / 255.0, self.g / 255.0, self.b / 255.0, self.a)


# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------


@dataclass
class Palette:
    """A named bag of :class:`Color` entries.

    The keys are arbitrary semantic role names ("primary", "surface",
    "accent", …). A palette is just a typed dict so it survives YAML
    round-trips without custom loaders.
    """

    name: str = "default"
    entries: dict[str, Color] = field(default_factory=dict)

    def __post_init__(self) -> None:
        fn = "Palette"
        self.name = validate_non_empty_str("name", fn, self.name)
        if not isinstance(self.entries, dict):
            raise TypeError(
                f"{fn}: entries must be a dict; got {type(self.entries).__name__}"
            )
        for key, value in self.entries.items():
            validate_non_empty_str("entries key", fn, key)
            if not isinstance(value, Color):
                raise TypeError(
                    f"{fn}: entries[{key!r}] must be a Color; "
                    f"got {type(value).__name__}"
                )

    def get(self, role: str, default: Color | None = None) -> Color | None:
        return self.entries.get(role, default)


# ---------------------------------------------------------------------------
# Font
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Font:
    """A font record — family name, point size, weight.

    No rasterisation is implied; the theme just *names* a font and
    leaves resolution to the renderer (DPG, PIL, browser, …).
    """

    family: str = "sans-serif"
    size: int = 14
    weight: str = "regular"

    def __post_init__(self) -> None:
        fn = "Font"
        object.__setattr__(
            self, "family", validate_non_empty_str("family", fn, self.family)
        )
        object.__setattr__(
            self, "size", validate_positive_int("size", fn, self.size)
        )
        object.__setattr__(
            self, "weight", validate_non_empty_str("weight", fn, self.weight)
        )


# ---------------------------------------------------------------------------
# Forward declarations — concrete classes live in sibling modules
# ---------------------------------------------------------------------------
#
# ``NineSlice``, ``SVGIcon``, and ``ShaderEffect`` are re-exported from
# the package ``__init__`` so the theme module is a single import target.
# We declare them here only as the type names ThemeSpec quotes; the real
# implementations sit in ``nine_slice.py`` / ``svg_icon.py`` /
# ``shader_effects.py`` so this module stays cheap to import.


@dataclass
class ShaderEffect:
    """A named procedural-texture recipe.

    A ``ShaderEffect`` is just a record: a callable name plus a kwargs
    bag that callers feed into a renderer-side dispatcher
    (typically one of the helpers in :mod:`shader_effects`).

    Parameters
    ----------
    name:
        Identifier of the effect (matches a function name in
        :mod:`shader_effects`, e.g. ``"ruled_paper"``).
    params:
        Plain-Python kwargs bag — numbers, strings, :class:`Color`
        instances. YAML-safe.
    """

    name: str
    params: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        fn = "ShaderEffect"
        self.name = validate_non_empty_str("name", fn, self.name)
        if not isinstance(self.params, dict):
            raise TypeError(
                f"{fn}: params must be a dict; got {type(self.params).__name__}"
            )


# ---------------------------------------------------------------------------
# ThemeSpec
# ---------------------------------------------------------------------------


@dataclass
class ThemeSpec:
    """Top-level declarative theme.

    Themes are immutable in spirit (the registry hands back the same
    instance), but the dataclass itself is mutable so themes can be
    composed at authoring time before registration.
    """

    name: str
    palette: dict[str, "Color"] = field(default_factory=dict)
    fonts: dict[str, Font] = field(default_factory=dict)
    nine_slices: dict[str, Any] = field(default_factory=dict)
    icons: dict[str, Any] = field(default_factory=dict)
    background_shader: ShaderEffect | None = None
    metadata: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        fn = "ThemeSpec"
        self.name = validate_non_empty_str("name", fn, self.name)
        for bag_name, bag in (
            ("palette", self.palette),
            ("fonts", self.fonts),
            ("nine_slices", self.nine_slices),
            ("icons", self.icons),
            ("metadata", self.metadata),
        ):
            if not isinstance(bag, dict):
                raise TypeError(
                    f"{fn}: {bag_name} must be a dict; got {type(bag).__name__}"
                )
            for key in bag:
                validate_str(f"{bag_name} key", fn, key, allow_empty=False)
        if self.background_shader is not None and not isinstance(
            self.background_shader, ShaderEffect
        ):
            raise TypeError(
                f"{fn}: background_shader must be a ShaderEffect or None; "
                f"got {type(self.background_shader).__name__}"
            )

    # ---- YAML round-trip ---------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain-Python dict (YAML/JSON safe).

        :class:`NineSlice` and :class:`SVGIcon` instances are serialised
        through their own ``to_dict`` methods; missing methods fall back
        to ``repr`` so unsupported subclasses still round-trip *something*.
        """
        return {
            "name": self.name,
            "palette": {
                k: [v.r, v.g, v.b, v.a] for k, v in self.palette.items()
            },
            "fonts": {
                k: {"family": v.family, "size": v.size, "weight": v.weight}
                for k, v in self.fonts.items()
            },
            "nine_slices": {
                k: (v.to_dict() if hasattr(v, "to_dict") else repr(v))
                for k, v in self.nine_slices.items()
            },
            "icons": {
                k: (v.to_dict() if hasattr(v, "to_dict") else repr(v))
                for k, v in self.icons.items()
            },
            "background_shader": (
                {"name": self.background_shader.name,
                 "params": dict(self.background_shader.params)}
                if self.background_shader is not None else None
            ),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ThemeSpec":
        """Rebuild a :class:`ThemeSpec` from :meth:`to_dict` output.

        :class:`NineSlice` / :class:`SVGIcon` entries are reconstructed
        only if the dict carries the appropriate marker keys (matching
        each class's :meth:`to_dict`); other entries pass through
        unchanged so callers can author intermediate formats.
        """
        from .nine_slice import NineSlice
        from .svg_icon import SVGIcon

        if not isinstance(data, dict):
            raise TypeError(
                f"ThemeSpec.from_dict: data must be a dict; "
                f"got {type(data).__name__}"
            )
        name = data.get("name", "")
        palette_raw = data.get("palette") or {}
        palette: dict[str, Color] = {}
        for k, v in palette_raw.items():
            if isinstance(v, Color):
                palette[k] = v
            elif isinstance(v, (list, tuple)) and len(v) == 4:
                palette[k] = Color(int(v[0]), int(v[1]), int(v[2]), float(v[3]))
            else:
                raise TypeError(
                    f"ThemeSpec.from_dict: palette[{k!r}] must be Color "
                    f"or 4-sequence; got {type(v).__name__}"
                )
        fonts_raw = data.get("fonts") or {}
        fonts: dict[str, Font] = {}
        for k, v in fonts_raw.items():
            if isinstance(v, Font):
                fonts[k] = v
            elif isinstance(v, dict):
                fonts[k] = Font(
                    family=v.get("family", "sans-serif"),
                    size=int(v.get("size", 14)),
                    weight=v.get("weight", "regular"),
                )
            else:
                raise TypeError(
                    f"ThemeSpec.from_dict: fonts[{k!r}] must be Font "
                    f"or dict; got {type(v).__name__}"
                )
        ns_raw = data.get("nine_slices") or {}
        nine_slices: dict[str, Any] = {}
        for k, v in ns_raw.items():
            if isinstance(v, NineSlice):
                nine_slices[k] = v
            elif isinstance(v, dict) and "insets" in v:
                nine_slices[k] = NineSlice.from_dict(v)
            else:
                nine_slices[k] = v
        icons_raw = data.get("icons") or {}
        icons: dict[str, Any] = {}
        for k, v in icons_raw.items():
            if isinstance(v, SVGIcon):
                icons[k] = v
            elif isinstance(v, dict) and "svg_xml" in v:
                icons[k] = SVGIcon.from_dict(v)
            else:
                icons[k] = v
        bg = data.get("background_shader")
        bg_shader: ShaderEffect | None
        if bg is None:
            bg_shader = None
        elif isinstance(bg, ShaderEffect):
            bg_shader = bg
        elif isinstance(bg, dict):
            bg_shader = ShaderEffect(
                name=bg.get("name", ""), params=dict(bg.get("params", {}))
            )
        else:
            raise TypeError(
                f"ThemeSpec.from_dict: background_shader must be dict "
                f"or ShaderEffect; got {type(bg).__name__}"
            )
        return cls(
            name=name,
            palette=palette,
            fonts=fonts,
            nine_slices=nine_slices,
            icons=icons,
            background_shader=bg_shader,
            metadata=dict(data.get("metadata") or {}),
        )

    def to_yaml(self) -> str:
        """Serialise to a YAML string (requires ``PyYAML``)."""
        try:
            import yaml  # type: ignore[import-untyped]
        except ImportError as exc:  # pragma: no cover - defensive
            raise ImportError(
                "ThemeSpec.to_yaml requires PyYAML: pip install pyyaml"
            ) from exc
        return yaml.safe_dump(self.to_dict(), sort_keys=False)

    @classmethod
    def from_yaml(cls, text: str) -> "ThemeSpec":
        """Parse YAML produced by :meth:`to_yaml`."""
        try:
            import yaml  # type: ignore[import-untyped]
        except ImportError as exc:  # pragma: no cover - defensive
            raise ImportError(
                "ThemeSpec.from_yaml requires PyYAML: pip install pyyaml"
            ) from exc
        validate_str("text", "ThemeSpec.from_yaml", text, allow_empty=False)
        data = yaml.safe_load(text)
        return cls.from_dict(data)


# Re-export the float-validator name for adjacent modules that build on
# this file (no API exposure — keeps the module self-checked).
_ = validate_finite_float


__all__ = [
    "Color",
    "Font",
    "Palette",
    "ShaderEffect",
    "ThemeSpec",
]
