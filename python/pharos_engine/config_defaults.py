"""Default-config YAML generator + validator for SlapPyEngine.

This module is the single source of truth for every user-tunable option the
engine exposes.  It powers three related workflows:

1. **Auto-scaffold** a fresh ``config.yml`` file for a new project — every
   option is written with its default value and a short description so the
   user can discover what is tunable without hunting through source.
2. **Merge** a user's YAML with the built-in defaults so calling code always
   gets a fully-populated dict, even when the user only overrides a handful
   of keys.
3. **Validate** a user's YAML — flag unknown keys, wrong types, out-of-range
   numeric values, and invalid enum choices.

The definitions here are intentionally **separate** from
:mod:`pharos_engine.config` (which parses the small ``engine.yml`` shipped in
``config/``).  This module targets the broader user-facing config surface
(window, graphics, audio, input, editor, runtime) that a game/app built on
SlapPyEngine typically wants to expose to the end-user.

Public API::

    ConfigOption
    DEFAULT_CONFIG_OPTIONS
    list_options()
    option_for_key(key)
    generate_default_yaml(*, categories=None, comment_style="grouped")
    write_default_yaml(path, *, overwrite=False)
    load_config_with_defaults(path)
    validate_config(config)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

import yaml

# ---------------------------------------------------------------------------
# Option descriptor
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConfigOption:
    """One tunable option, self-describing.

    Attributes
    ----------
    key : str
        Dotted path used both in the YAML (as nested mapping keys) and in
        validation error messages, e.g. ``"graphics.msaa_samples"``.
    default : Any
        The out-of-the-box value.  Written verbatim into the generated YAML.
    type_name : str
        One of ``"str" | "int" | "float" | "bool" | "list" | "tuple" | "enum"``.
    choices : list | None
        For ``type_name == "enum"`` (or any option with a restricted set),
        the list of acceptable values.  ``None`` means unrestricted.
    min_value : int | float | None
        Inclusive lower bound for numeric options.  ``None`` means unbounded.
    max_value : int | float | None
        Inclusive upper bound for numeric options.  ``None`` means unbounded.
    units : str | None
        Human-readable unit ("px", "hz", "seconds", "dB", …) surfaced in the
        generated YAML comment.
    description : str
        Single-line description written as a trailing YAML comment.
    category : str
        Grouping used by :func:`generate_default_yaml` to emit blocks.
        One of ``"window" | "graphics" | "audio" | "input" | "editor" |
        "runtime"``.
    """

    key: str
    default: Any
    type_name: str
    description: str
    category: str
    choices: Optional[list] = None
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    units: Optional[str] = None


# ---------------------------------------------------------------------------
# Registry — every default the engine exposes
# ---------------------------------------------------------------------------


def _opt(*args, **kwargs) -> ConfigOption:  # tiny helper to keep the list short
    return ConfigOption(*args, **kwargs)


DEFAULT_CONFIG_OPTIONS: list[ConfigOption] = [
    # -------------------- window --------------------
    _opt("window.title", "SlapPyEngine", "str",
         "Window title bar text.", "window"),
    _opt("window.size", [1280, 720], "list",
         "Window client size in pixels, [width, height].", "window",
         units="px"),
    _opt("window.fullscreen", False, "bool",
         "Start in exclusive fullscreen.", "window"),
    _opt("window.borderless", False, "bool",
         "Remove OS window chrome (title bar + borders).", "window"),
    _opt("window.resizable", True, "bool",
         "Allow the user to resize the window.", "window"),
    _opt("window.cursor_visible", True, "bool",
         "Show the OS cursor while inside the window.", "window"),
    _opt("window.always_on_top", False, "bool",
         "Keep the window above all other windows.", "window"),
    _opt("window.min_size", [320, 240], "list",
         "Smallest allowed window size, [width, height].", "window",
         units="px"),
    _opt("window.max_size", [7680, 4320], "list",
         "Largest allowed window size, [width, height].", "window",
         units="px"),

    # -------------------- graphics --------------------
    _opt("graphics.backend", "wgpu", "enum",
         "Render backend to use.", "graphics",
         choices=["wgpu", "null", "software"]),
    _opt("graphics.vsync", True, "bool",
         "Sync presentation to the monitor refresh.", "graphics"),
    _opt("graphics.msaa_samples", 4, "enum",
         "Multi-sample anti-aliasing sample count.", "graphics",
         choices=[1, 2, 4, 8, 16]),
    _opt("graphics.max_fps", 60, "int",
         "Cap frame-rate; 0 disables the cap.", "graphics",
         min_value=0, max_value=1000, units="fps"),
    _opt("graphics.clear_color", [0.1, 0.1, 0.15, 1.0], "list",
         "RGBA back-buffer clear colour, each channel in [0, 1].", "graphics"),
    _opt("graphics.shadow_resolution", 2048, "int",
         "Shadow-map texel resolution, one side.", "graphics",
         min_value=64, max_value=8192, units="px"),
    _opt("graphics.bloom_enabled", True, "bool",
         "Enable HDR bloom post-process.", "graphics"),
    _opt("graphics.bloom_strength", 0.3, "float",
         "Bloom mix strength, 0 = off, 1 = fully bloomed.", "graphics",
         min_value=0.0, max_value=1.0),
    _opt("graphics.taa_enabled", True, "bool",
         "Enable temporal anti-aliasing.", "graphics"),
    _opt("graphics.tonemap_kind", "reinhard", "enum",
         "Tone-mapping operator applied before display.", "graphics",
         choices=["reinhard", "aces", "uncharted2", "linear"]),
    _opt("graphics.gamma", 2.2, "float",
         "Display gamma used when linearising sRGB output.", "graphics",
         min_value=1.0, max_value=3.0),
    _opt("graphics.exposure", 1.0, "float",
         "Exposure multiplier fed to the tone-mapper.", "graphics",
         min_value=0.0, max_value=16.0),
    _opt("graphics.anisotropic_filtering", 8, "enum",
         "Anisotropic-filter tap count for textures.", "graphics",
         choices=[1, 2, 4, 8, 16]),
    _opt("graphics.ssao_enabled", True, "bool",
         "Enable screen-space ambient occlusion.", "graphics"),
    _opt("graphics.motion_blur_enabled", False, "bool",
         "Enable camera + object motion blur.", "graphics"),

    # -------------------- audio --------------------
    _opt("audio.master_volume", 0.8, "float",
         "Master mixer volume, 0 = silent, 1 = unity.", "audio",
         min_value=0.0, max_value=1.0),
    _opt("audio.music_volume", 0.7, "float",
         "Music bus volume, 0 = silent, 1 = unity.", "audio",
         min_value=0.0, max_value=1.0),
    _opt("audio.sfx_volume", 0.9, "float",
         "Sound-effects bus volume, 0 = silent, 1 = unity.", "audio",
         min_value=0.0, max_value=1.0),
    _opt("audio.mute", False, "bool",
         "Mute all audio output.", "audio"),
    _opt("audio.audio_backend", "auto", "enum",
         "Audio device backend to open.", "audio",
         choices=["auto", "pygame", "pyaudio", "null"]),
    _opt("audio.sample_rate", 44100, "int",
         "Output sample rate.", "audio",
         min_value=8000, max_value=192000, units="hz"),
    _opt("audio.buffer_size", 1024, "int",
         "Audio DMA buffer size in frames; smaller = lower latency.",
         "audio", min_value=64, max_value=8192, units="frames"),
    _opt("audio.channel_count", 32, "int",
         "Maximum simultaneously-playing voices.", "audio",
         min_value=1, max_value=256),
    _opt("audio.doppler_enabled", True, "bool",
         "Enable Doppler-shift on 3D sources.", "audio"),
    _opt("audio.reverb_wet", 0.2, "float",
         "Global reverb wet mix, [0, 1].", "audio",
         min_value=0.0, max_value=1.0),

    # -------------------- input --------------------
    _opt("input.mouse_sensitivity", 1.0, "float",
         "Mouse look-sensitivity multiplier.", "input",
         min_value=0.01, max_value=10.0),
    _opt("input.invert_y", False, "bool",
         "Invert the mouse Y axis.", "input"),
    _opt("input.keyboard_layout", "qwerty", "enum",
         "Physical keyboard layout used for key-remaps.", "input",
         choices=["qwerty", "dvorak", "colemak", "azerty"]),
    _opt("input.gamepad_deadzone", 0.1, "float",
         "Analogue-stick radial deadzone, [0, 1].", "input",
         min_value=0.0, max_value=1.0),
    _opt("input.key_repeat_delay_ms", 500, "int",
         "Delay before a held key starts repeating.", "input",
         min_value=0, max_value=5000, units="ms"),
    _opt("input.key_repeat_rate_ms", 30, "int",
         "Interval between repeats once repeating.", "input",
         min_value=1, max_value=1000, units="ms"),
    _opt("input.gamepad_enabled", True, "bool",
         "Poll gamepads and route their events to the input bus.", "input"),
    _opt("input.mouse_smoothing", 0.0, "float",
         "Blend factor between raw and smoothed mouse deltas.", "input",
         min_value=0.0, max_value=1.0),

    # -------------------- editor --------------------
    _opt("editor.enable_editor", False, "bool",
         "Boot into the in-game editor overlay.", "editor"),
    _opt("editor.theme", "teengirl_notebook", "enum",
         "Editor UI theme.", "editor",
         choices=[
             "teengirl_notebook", "nova3d_dark", "nova3d_light",
             "diary", "corporate", "high_contrast",
         ]),
    _opt("editor.autosave_interval_seconds", 60, "int",
         "How often the editor writes an autosave snapshot.", "editor",
         min_value=5, max_value=3600, units="seconds"),
    _opt("editor.autosave_max_snapshots", 20, "int",
         "Rolling number of autosave snapshots to keep.", "editor",
         min_value=1, max_value=1000),
    _opt("editor.show_grid", True, "bool",
         "Show the reference grid in the viewport.", "editor"),
    _opt("editor.gizmo_size", 1.0, "float",
         "Screen-relative size multiplier for editor gizmos.", "editor",
         min_value=0.1, max_value=5.0),

    # -------------------- runtime --------------------
    _opt("runtime.target_fps", 60, "int",
         "Nominal simulation target frame-rate.", "runtime",
         min_value=1, max_value=1000, units="fps"),
    _opt("runtime.fixed_dt", False, "bool",
         "Use a fixed-timestep loop instead of variable dt.", "runtime"),
    _opt("runtime.physics_step_hz", 60, "int",
         "Physics substep rate.", "runtime",
         min_value=10, max_value=480, units="hz"),
    _opt("runtime.log_level", "info", "enum",
         "Global logger verbosity threshold.", "runtime",
         choices=["debug", "info", "warn", "error"]),
    _opt("runtime.telemetry_enabled", True, "bool",
         "Emit anonymous performance telemetry.", "runtime"),
    _opt("runtime.save_dir", "~/.pharos_engine/saves", "str",
         "Directory where save-game files are written.", "runtime"),
    _opt("runtime.cache_dir", "~/.pharos_engine/cache", "str",
         "Directory used for baked assets and temporary files.", "runtime"),
]


# ---------------------------------------------------------------------------
# Small lookup helpers
# ---------------------------------------------------------------------------


def list_options() -> list[ConfigOption]:
    """Return a *copy* of every registered default option."""
    return list(DEFAULT_CONFIG_OPTIONS)


def option_for_key(key: str) -> Optional[ConfigOption]:
    """Return the :class:`ConfigOption` for *key* or ``None`` if unknown."""
    for opt in DEFAULT_CONFIG_OPTIONS:
        if opt.key == key:
            return opt
    return None


def _categories_in_order() -> list[str]:
    """Preserve the order categories first appear in :data:`DEFAULT_CONFIG_OPTIONS`."""
    seen: list[str] = []
    for opt in DEFAULT_CONFIG_OPTIONS:
        if opt.category not in seen:
            seen.append(opt.category)
    return seen


# ---------------------------------------------------------------------------
# YAML emission
# ---------------------------------------------------------------------------


def _format_default(value: Any) -> str:
    """Render *value* as a single-line YAML scalar / flow collection.

    :func:`yaml.safe_dump` appends a document-end marker (``...``) for bare
    scalars, which would corrupt in-line entries, so we hand-format the
    common cases and only fall back to ``safe_dump`` for containers.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        # Quote strings that could otherwise parse as another YAML type
        # (bool, null, numbers, or contain YAML-special characters).
        needs_quote = (
            not value
            or value.lower() in {"true", "false", "yes", "no", "null", "~"}
            or any(c in value for c in ":#&*!|>%@`,[]{}")
            or value != value.strip()
        )
        try:
            float(value)
            needs_quote = True
        except ValueError:
            pass
        if needs_quote:
            escaped = value.replace("\\", "\\\\").replace('"', '\\"')
            return f'"{escaped}"'
        return value
    # lists / tuples / dicts → flow style, single line.
    dumped = yaml.safe_dump(
        list(value) if isinstance(value, tuple) else value,
        default_flow_style=True,
        width=10 ** 9,
    ).strip()
    # safe_dump adds a trailing "\n...\n" for some scalar-like inputs; strip.
    if dumped.endswith("\n..."):
        dumped = dumped[:-4]
    return dumped


def _comment_for(opt: ConfigOption) -> str:
    """Build the trailing ``# ...`` annotation for an option line."""
    bits = [opt.description]
    bits.append(f"[type={opt.type_name}]")
    if opt.choices is not None:
        choices_str = "/".join(str(c) for c in opt.choices)
        bits.append(f"[choices={choices_str}]")
    if opt.min_value is not None or opt.max_value is not None:
        lo = "-inf" if opt.min_value is None else str(opt.min_value)
        hi = "+inf" if opt.max_value is None else str(opt.max_value)
        bits.append(f"[range={lo}..{hi}]")
    if opt.units:
        bits.append(f"[units={opt.units}]")
    return " ".join(bits)


def generate_default_yaml(
    *,
    categories: Optional[Iterable[str]] = None,
    comment_style: str = "grouped",
) -> str:
    """Return a YAML string that lists every option with its default.

    Parameters
    ----------
    categories : iterable of str, optional
        Restrict output to these category names.  ``None`` = all categories.
    comment_style : {"grouped", "flat"}
        * ``"grouped"`` — emit a nested block per category (``window:\\n  title:
          ...``).  This is the recommended, human-friendly form.
        * ``"flat"`` — emit every option on its own top-level line using its
          full dotted key (``window.title: ...``).  Useful for diffing.
    """
    if comment_style not in ("grouped", "flat"):
        raise ValueError(f"unknown comment_style={comment_style!r}")

    wanted = set(categories) if categories is not None else None
    lines: list[str] = [
        "# SlapPyEngine default configuration",
        "# ----------------------------------",
        "# This file was generated by pharos_engine.config_defaults.",
        "# Every option is listed with its default value and description.",
        "# Delete or edit any line to override the built-in default.",
        "",
    ]

    for cat in _categories_in_order():
        if wanted is not None and cat not in wanted:
            continue
        opts = [o for o in DEFAULT_CONFIG_OPTIONS if o.category == cat]
        if not opts:
            continue

        lines.append(f"# --- {cat} ---")
        if comment_style == "grouped":
            lines.append(f"{cat}:")
            for opt in opts:
                # Strip the "<cat>." prefix for the nested form.
                assert opt.key.startswith(f"{cat}."), opt.key
                short_key = opt.key[len(cat) + 1:]
                lines.append(
                    f"  {short_key}: {_format_default(opt.default)}"
                    f"  # {_comment_for(opt)}"
                )
        else:  # flat
            for opt in opts:
                lines.append(
                    f"{opt.key}: {_format_default(opt.default)}"
                    f"  # {_comment_for(opt)}"
                )
        lines.append("")  # blank line between categories

    return "\n".join(lines).rstrip() + "\n"


def write_default_yaml(path: str | Path, *, overwrite: bool = False) -> Path:
    """Write the default YAML to *path*.

    Raises :class:`FileExistsError` when the target already exists and
    ``overwrite`` is ``False``.  Returns the resolved :class:`Path`.
    """
    p = Path(path).expanduser()
    if p.exists() and not overwrite:
        raise FileExistsError(f"{p} already exists (pass overwrite=True to replace)")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(generate_default_yaml(), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Merge + validation
# ---------------------------------------------------------------------------


def _defaults_dict() -> dict[str, Any]:
    """Build a nested mapping of {category: {short_key: default}}."""
    out: dict[str, Any] = {}
    for opt in DEFAULT_CONFIG_OPTIONS:
        head, _, tail = opt.key.partition(".")
        out.setdefault(head, {})[tail] = opt.default
    return out


def _deep_merge(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    """Return a new dict where *overrides* replaces matching leaf entries in *base*.

    Nested dicts are merged recursively.  Lists are *replaced wholesale* — this
    mirrors what a game/app config typically wants (e.g. overriding
    ``clear_color`` should set the whole colour, not element-wise).
    """
    merged: dict[str, Any] = {}
    all_keys = set(base) | set(overrides)
    for k in all_keys:
        if k in overrides and k in base:
            bv, ov = base[k], overrides[k]
            if isinstance(bv, dict) and isinstance(ov, dict):
                merged[k] = _deep_merge(bv, ov)
            else:
                merged[k] = ov
        elif k in overrides:
            merged[k] = overrides[k]
        else:
            merged[k] = base[k]
    return merged


def load_config_with_defaults(path: str | Path) -> dict[str, Any]:
    """Read *path* and merge it on top of the built-in defaults.

    Missing sections and missing individual keys are filled from
    :data:`DEFAULT_CONFIG_OPTIONS`.  Keys present in the file but unknown to
    the defaults are preserved verbatim (validation is a separate step —
    see :func:`validate_config`).  If *path* does not exist the function
    returns the raw defaults, so first-run bootstrapping is trivial.
    """
    p = Path(path).expanduser()
    if p.exists():
        with p.open("r", encoding="utf-8") as fh:
            user = yaml.safe_load(fh) or {}
    else:
        user = {}
    if not isinstance(user, dict):
        raise ValueError(f"{p}: top-level YAML must be a mapping, got {type(user).__name__}")
    return _deep_merge(_defaults_dict(), user)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


# Map ConfigOption.type_name → callable(value) -> bool.  Booleans are checked
# *before* int because ``bool`` is a subclass of ``int`` in Python.
def _type_ok(value: Any, type_name: str) -> bool:
    if type_name == "bool":
        return isinstance(value, bool)
    if type_name == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if type_name == "float":
        # Accept ints as valid floats — YAML often omits the trailing ".0".
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if type_name == "str":
        return isinstance(value, str)
    if type_name == "list":
        return isinstance(value, list)
    if type_name == "tuple":
        return isinstance(value, (list, tuple))  # YAML has no tuple literal
    if type_name == "enum":
        # Enum values may be any scalar; the choice check below carries the load.
        return True
    return False


def _flatten(cfg: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """Flatten nested dicts into ``{"a.b.c": value}`` form."""
    out: dict[str, Any] = {}
    for k, v in cfg.items():
        key = f"{prefix}{k}" if not prefix else f"{prefix}.{k}"
        if isinstance(v, dict):
            out.update(_flatten(v, key))
        else:
            out[key] = v
    return out


def validate_config(config: dict[str, Any]) -> list[str]:
    """Validate *config* against :data:`DEFAULT_CONFIG_OPTIONS`.

    Returns a list of human-readable issue strings; an empty list means the
    configuration is fully valid.  The following classes of problem are
    detected:

    * ``unknown key: <k>`` — key not present in the registry.
    * ``<k>: wrong type ...`` — value's Python type doesn't match ``type_name``.
    * ``<k>: value ... not in choices ...`` — enum / choice violation.
    * ``<k>: value ... < min ...`` / ``> max ...`` — out-of-range numeric.
    """
    issues: list[str] = []
    flat = _flatten(config)
    known = {opt.key: opt for opt in DEFAULT_CONFIG_OPTIONS}

    for key, value in flat.items():
        opt = known.get(key)
        if opt is None:
            issues.append(f"unknown key: {key}")
            continue

        if not _type_ok(value, opt.type_name):
            issues.append(
                f"{key}: wrong type, expected {opt.type_name}, "
                f"got {type(value).__name__}"
            )
            # Skip the range/choice checks on a type mismatch — the message
            # would be redundant / potentially misleading.
            continue

        if opt.choices is not None and value not in opt.choices:
            issues.append(
                f"{key}: value {value!r} not in choices {opt.choices}"
            )

        if opt.min_value is not None and isinstance(value, (int, float)) \
                and not isinstance(value, bool) and value < opt.min_value:
            issues.append(f"{key}: value {value} < min {opt.min_value}")
        if opt.max_value is not None and isinstance(value, (int, float)) \
                and not isinstance(value, bool) and value > opt.max_value:
            issues.append(f"{key}: value {value} > max {opt.max_value}")

    return issues


__all__ = [
    "ConfigOption",
    "DEFAULT_CONFIG_OPTIONS",
    "list_options",
    "option_for_key",
    "generate_default_yaml",
    "write_default_yaml",
    "load_config_with_defaults",
    "validate_config",
]
