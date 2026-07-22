"""Tripwire suite for :mod:`pharos_engine.config_defaults` — HH6.

Covers the default-config YAML generator + validator:

* Registry sanity — ≥ 50 options, ≥ 6 categories, every option is a
  :class:`ConfigOption`, keys are unique and category-prefixed, defaults
  match their declared ``type_name``, choice values respect ``choices``,
  and ``min <= default <= max`` where bounds are set.
* :func:`generate_default_yaml` — output parses through :func:`yaml.safe_load`
  in both grouped and flat modes, header comment present, category
  restriction works, unknown ``comment_style`` raises.
* :func:`write_default_yaml` — writes on first call, refuses on second
  without ``overwrite``, ``overwrite=True`` is idempotent.
* :func:`load_config_with_defaults` — missing keys filled, user overrides
  respected, non-existent file falls back to defaults, list-valued options
  are replaced wholesale (not merged element-wise), scalar top-level YAML
  is rejected.
* :func:`validate_config` — clean defaults pass, unknown key / wrong type /
  invalid choice / out-of-range / bool-vs-int confusion / correct nested
  structures are each flagged (or not) correctly.
* Look-ups — :func:`list_options` returns a copy, :func:`option_for_key`
  returns ``None`` on unknown keys.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from pharos_engine.config_defaults import (
    DEFAULT_CONFIG_OPTIONS,
    ConfigOption,
    generate_default_yaml,
    list_options,
    load_config_with_defaults,
    option_for_key,
    validate_config,
    write_default_yaml,
)


# ---------------------------------------------------------------------------
# Registry sanity
# ---------------------------------------------------------------------------


REQUIRED_CATEGORIES = {"window", "graphics", "audio", "input", "editor", "runtime"}


def test_registry_has_at_least_fifty_options():
    assert len(DEFAULT_CONFIG_OPTIONS) >= 50, (
        f"only {len(DEFAULT_CONFIG_OPTIONS)} options registered — the user "
        "spec asked for ~50 across categories"
    )


def test_registry_covers_all_required_categories():
    cats = {opt.category for opt in DEFAULT_CONFIG_OPTIONS}
    missing = REQUIRED_CATEGORIES - cats
    assert not missing, f"missing categories: {sorted(missing)}"


def test_registry_has_at_least_six_categories():
    cats = {opt.category for opt in DEFAULT_CONFIG_OPTIONS}
    assert len(cats) >= 6


def test_all_options_are_config_option_instances():
    for opt in DEFAULT_CONFIG_OPTIONS:
        assert isinstance(opt, ConfigOption)


def test_keys_are_unique():
    keys = [opt.key for opt in DEFAULT_CONFIG_OPTIONS]
    assert len(keys) == len(set(keys)), "duplicate ConfigOption.key"


def test_keys_are_category_prefixed():
    for opt in DEFAULT_CONFIG_OPTIONS:
        assert opt.key.startswith(f"{opt.category}."), (
            f"{opt.key} must start with '{opt.category}.'"
        )


def test_defaults_pass_their_own_type_check():
    from pharos_engine.config_defaults import _type_ok
    for opt in DEFAULT_CONFIG_OPTIONS:
        assert _type_ok(opt.default, opt.type_name), (
            f"{opt.key}: default {opt.default!r} not of type_name={opt.type_name}"
        )


def test_choice_defaults_are_in_choices():
    for opt in DEFAULT_CONFIG_OPTIONS:
        if opt.choices is not None:
            assert opt.default in opt.choices, (
                f"{opt.key}: default {opt.default!r} not in choices {opt.choices}"
            )


def test_numeric_defaults_within_declared_range():
    for opt in DEFAULT_CONFIG_OPTIONS:
        if isinstance(opt.default, bool):
            continue
        if isinstance(opt.default, (int, float)):
            if opt.min_value is not None:
                assert opt.default >= opt.min_value, f"{opt.key}: default below min"
            if opt.max_value is not None:
                assert opt.default <= opt.max_value, f"{opt.key}: default above max"


def test_descriptions_are_non_empty_one_liners():
    for opt in DEFAULT_CONFIG_OPTIONS:
        assert opt.description.strip(), f"{opt.key}: empty description"
        assert "\n" not in opt.description, f"{opt.key}: description has newline"


# ---------------------------------------------------------------------------
# Look-up helpers
# ---------------------------------------------------------------------------


def test_list_options_returns_copy():
    a = list_options()
    b = list_options()
    assert a == b
    a.pop()
    assert len(list_options()) == len(b), "list_options() must return a copy"


def test_option_for_key_hits():
    opt = option_for_key("graphics.msaa_samples")
    assert opt is not None
    assert opt.category == "graphics"
    assert opt.type_name == "enum"


def test_option_for_key_misses_return_none():
    assert option_for_key("no.such.key") is None


# ---------------------------------------------------------------------------
# YAML generation
# ---------------------------------------------------------------------------


def test_generate_default_yaml_parses():
    text = generate_default_yaml()
    parsed = yaml.safe_load(text)
    assert isinstance(parsed, dict)
    # every required category surfaces as a top-level mapping
    for cat in REQUIRED_CATEGORIES:
        assert cat in parsed, f"category {cat!r} missing from generated YAML"
        assert isinstance(parsed[cat], dict)


def test_generated_yaml_defaults_survive_roundtrip():
    parsed = yaml.safe_load(generate_default_yaml())
    for opt in DEFAULT_CONFIG_OPTIONS:
        cat, short = opt.key.split(".", 1)
        assert parsed[cat][short] == opt.default, (
            f"{opt.key}: YAML round-trip lost default"
        )


def test_generate_default_yaml_has_header_comment():
    text = generate_default_yaml()
    assert text.startswith("# SlapPyEngine default configuration"), text[:80]


def test_generate_default_yaml_filters_categories():
    text = generate_default_yaml(categories={"window"})
    parsed = yaml.safe_load(text)
    assert set(parsed.keys()) == {"window"}


def test_generate_default_yaml_flat_style_parses():
    text = generate_default_yaml(comment_style="flat")
    parsed = yaml.safe_load(text)
    # flat style emits full dotted keys — every registered key must be present.
    for opt in DEFAULT_CONFIG_OPTIONS:
        assert opt.key in parsed, f"{opt.key} missing from flat YAML"


def test_generate_default_yaml_unknown_style_raises():
    with pytest.raises(ValueError):
        generate_default_yaml(comment_style="wat")


def test_generated_yaml_has_blank_line_between_categories():
    text = generate_default_yaml()
    # A double newline should appear at least (#categories - 1) times.
    cat_count = len({opt.category for opt in DEFAULT_CONFIG_OPTIONS})
    assert text.count("\n\n") >= cat_count - 1


# ---------------------------------------------------------------------------
# write_default_yaml
# ---------------------------------------------------------------------------


def test_write_default_yaml_creates_file(tmp_path: Path):
    dst = tmp_path / "config.yml"
    result = write_default_yaml(dst)
    assert result == dst
    assert dst.exists()
    assert dst.read_text(encoding="utf-8").startswith("# SlapPyEngine")


def test_write_default_yaml_refuses_overwrite_by_default(tmp_path: Path):
    dst = tmp_path / "config.yml"
    write_default_yaml(dst)
    with pytest.raises(FileExistsError):
        write_default_yaml(dst)


def test_write_default_yaml_overwrite_true_is_idempotent(tmp_path: Path):
    dst = tmp_path / "config.yml"
    write_default_yaml(dst)
    first = dst.read_text(encoding="utf-8")
    write_default_yaml(dst, overwrite=True)
    second = dst.read_text(encoding="utf-8")
    assert first == second


def test_write_default_yaml_creates_parent_dirs(tmp_path: Path):
    dst = tmp_path / "nested" / "deeper" / "config.yml"
    write_default_yaml(dst)
    assert dst.exists()


# ---------------------------------------------------------------------------
# load_config_with_defaults
# ---------------------------------------------------------------------------


def test_load_config_with_defaults_fills_missing_keys(tmp_path: Path):
    dst = tmp_path / "user.yml"
    dst.write_text("window:\n  title: 'MyGame'\n", encoding="utf-8")
    merged = load_config_with_defaults(dst)
    assert merged["window"]["title"] == "MyGame"
    # everything else must fall back to the defaults
    assert merged["window"]["size"] == [1280, 720]
    assert merged["graphics"]["backend"] == "wgpu"
    assert merged["audio"]["master_volume"] == 0.8


def test_load_config_with_defaults_missing_file_returns_defaults(tmp_path: Path):
    merged = load_config_with_defaults(tmp_path / "does-not-exist.yml")
    assert merged["window"]["title"] == "SlapPyEngine"
    assert merged["runtime"]["target_fps"] == 60


def test_load_config_with_defaults_user_overrides_win(tmp_path: Path):
    dst = tmp_path / "user.yml"
    dst.write_text(
        "graphics:\n  msaa_samples: 8\n  vsync: false\n", encoding="utf-8"
    )
    merged = load_config_with_defaults(dst)
    assert merged["graphics"]["msaa_samples"] == 8
    assert merged["graphics"]["vsync"] is False
    # untouched sibling keeps default
    assert merged["graphics"]["tonemap_kind"] == "reinhard"


def test_load_config_with_defaults_replaces_lists_wholesale(tmp_path: Path):
    dst = tmp_path / "user.yml"
    dst.write_text("window:\n  size: [1920, 1080]\n", encoding="utf-8")
    merged = load_config_with_defaults(dst)
    assert merged["window"]["size"] == [1920, 1080]


def test_load_config_with_defaults_rejects_non_mapping(tmp_path: Path):
    dst = tmp_path / "user.yml"
    dst.write_text("- 1\n- 2\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_config_with_defaults(dst)


def test_load_config_with_defaults_empty_file_is_ok(tmp_path: Path):
    dst = tmp_path / "user.yml"
    dst.write_text("", encoding="utf-8")
    merged = load_config_with_defaults(dst)
    assert merged["window"]["title"] == "SlapPyEngine"


# ---------------------------------------------------------------------------
# validate_config
# ---------------------------------------------------------------------------


def _clean_defaults() -> dict:
    """Return the built-in defaults as a nested dict."""
    out: dict = {}
    for opt in DEFAULT_CONFIG_OPTIONS:
        head, tail = opt.key.split(".", 1)
        out.setdefault(head, {})[tail] = opt.default
    return out


def test_validate_clean_defaults_no_issues():
    assert validate_config(_clean_defaults()) == []


def test_validate_catches_unknown_key():
    cfg = _clean_defaults()
    cfg["window"]["mystery_knob"] = 42
    issues = validate_config(cfg)
    assert any("unknown key" in msg and "mystery_knob" in msg for msg in issues)


def test_validate_catches_wrong_type_string_where_int_expected():
    cfg = _clean_defaults()
    cfg["audio"]["sample_rate"] = "loud"
    issues = validate_config(cfg)
    assert any("audio.sample_rate" in m and "wrong type" in m for m in issues)


def test_validate_catches_wrong_type_bool_where_int_expected():
    cfg = _clean_defaults()
    # ``True`` is technically an int in Python — the validator must reject it
    # when the option's type_name is "int".
    cfg["graphics"]["max_fps"] = True
    issues = validate_config(cfg)
    assert any("graphics.max_fps" in m and "wrong type" in m for m in issues)


def test_validate_catches_invalid_choice():
    cfg = _clean_defaults()
    cfg["graphics"]["tonemap_kind"] = "gamma3000"
    issues = validate_config(cfg)
    assert any(
        "graphics.tonemap_kind" in m and "not in choices" in m for m in issues
    )


def test_validate_catches_out_of_range_low():
    cfg = _clean_defaults()
    cfg["audio"]["master_volume"] = -0.5
    issues = validate_config(cfg)
    assert any(
        "audio.master_volume" in m and "< min" in m for m in issues
    )


def test_validate_catches_out_of_range_high():
    cfg = _clean_defaults()
    cfg["audio"]["master_volume"] = 5.0
    issues = validate_config(cfg)
    assert any(
        "audio.master_volume" in m and "> max" in m for m in issues
    )


def test_validate_accepts_int_for_float_option():
    # YAML often emits ints when the source has no decimals (0.0 -> 0).
    cfg = _clean_defaults()
    cfg["audio"]["master_volume"] = 1  # int, not 1.0
    assert validate_config(cfg) == []


def test_validate_returns_empty_for_empty_config():
    # No keys, so nothing to validate — empty is trivially valid.
    assert validate_config({}) == []


def test_validate_reports_all_issues_not_just_first():
    cfg = _clean_defaults()
    cfg["window"]["mystery1"] = 1
    cfg["window"]["mystery2"] = 2
    cfg["audio"]["master_volume"] = 99.0  # out of range
    issues = validate_config(cfg)
    # 2 unknowns + 1 range = 3 issues.
    assert len(issues) >= 3


def test_validate_catches_bad_enum_msaa_samples():
    cfg = _clean_defaults()
    cfg["graphics"]["msaa_samples"] = 3  # not a power-of-two multi-sample level
    issues = validate_config(cfg)
    assert any(
        "graphics.msaa_samples" in m and "not in choices" in m for m in issues
    )


# ---------------------------------------------------------------------------
# End-to-end
# ---------------------------------------------------------------------------


def test_generated_yaml_passes_validation():
    """Round-trip: default YAML -> parse -> validate -> zero issues."""
    parsed = yaml.safe_load(generate_default_yaml())
    assert validate_config(parsed) == []


def test_write_then_load_then_validate(tmp_path: Path):
    dst = tmp_path / "config.yml"
    write_default_yaml(dst)
    merged = load_config_with_defaults(dst)
    assert validate_config(merged) == []
