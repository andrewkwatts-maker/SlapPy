"""Negative-path tests for the compute-pipeline + shader-loader +
post-process bind-group validators (hardening round 14).

The compute subpackage's deep wgpu API (``device.create_shader_module``,
``cp.dispatch_workgroups``) raises its own errors but the messages land
deep in the driver and never name the call site. The wrappers exposed
to users — ``ComputePass``, ``ComputePipeline.validate_workgroups``,
``ComputeLibrary.register``, ``PostProcessExecutor.validate_bind_entries``
— had no input validation until this round.

Silent-acceptance bugs caught here:
  * ``ComputePass("", entry_point="")`` silently constructed an unusable
    pass that crashed on the first ``device.create_shader_module`` with
    an opaque WGSL error that did not name the caller.
  * ``ComputePass.from_source(source=b"@compute fn main(){}")`` was
    silently accepted; wgpu later raised ``TypeError: 'bytes' object is
    not str`` from inside the driver.
  * ``ComputeLibrary.register("", source)`` silently replaced any prior
    empty-name entry — every caller of register("") collided silently.
  * Bind-group entries with **duplicate binding indices** were silently
    accepted; wgpu keeps the LAST entry on some backends, so the
    pre-duplicate binding was a dead write that never reached the GPU.
    This is the highest-value silent-acceptance bug in this round.
  * ``cp.dispatch_workgroups(0)`` is a no-op — readback returns empty
    data — and previously slipped through every wrapping helper.
  * ``cp.dispatch_workgroups(True)`` silently dispatched 1 workgroup
    (``True`` is an ``int`` in Python) — a 1-pixel pass that returned
    silently with junk.

Positive paths live in :file:`tests/test_compute_pipeline.py` /
:file:`tests/test_post_process_*.py`. This file only covers the
rejection contract.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "python"))

_SKIP = ""
try:
    import slappyengine  # noqa: F401
    _OK = True
except Exception as exc:
    _OK = False
    _SKIP = str(exc)

pytestmark = pytest.mark.skipif(not _OK, reason=f"slappyengine unavailable: {_SKIP}")


# ---------------------------------------------------------------------------
# validate_workgroup_count — single-axis dispatch validator
# ---------------------------------------------------------------------------


def test_workgroup_count_rejects_zero():
    """dispatch_workgroups(0) is a no-op — refuse at the boundary."""
    from slappyengine.compute._validation import validate_workgroup_count
    with pytest.raises(ValueError, match=">= 1"):
        validate_workgroup_count("workgroup_x", "fn", 0)


def test_workgroup_count_rejects_negative():
    from slappyengine.compute._validation import validate_workgroup_count
    with pytest.raises(ValueError, match=">= 1"):
        validate_workgroup_count("workgroup_x", "fn", -3)


def test_workgroup_count_rejects_nan():
    """NaN -> int silently coerces to 0 on some Pythons — refuse explicitly."""
    from slappyengine.compute._validation import validate_workgroup_count
    with pytest.raises(ValueError, match="NaN"):
        validate_workgroup_count("workgroup_x", "fn", math.nan)


def test_workgroup_count_rejects_inf():
    from slappyengine.compute._validation import validate_workgroup_count
    with pytest.raises(ValueError, match="positive int"):
        validate_workgroup_count("workgroup_x", "fn", math.inf)


def test_workgroup_count_rejects_bool():
    """Silent-acceptance bug: True silently dispatches 1 workgroup."""
    from slappyengine.compute._validation import validate_workgroup_count
    with pytest.raises(TypeError, match="must be an int"):
        validate_workgroup_count("workgroup_x", "fn", True)


def test_workgroup_count_rejects_float_one():
    """Even an integral float should be refused — keep types tight."""
    from slappyengine.compute._validation import validate_workgroup_count
    with pytest.raises(TypeError, match="must be an int"):
        validate_workgroup_count("workgroup_x", "fn", 1.0)


def test_workgroup_count_rejects_string():
    from slappyengine.compute._validation import validate_workgroup_count
    with pytest.raises(TypeError, match="must be an int"):
        validate_workgroup_count("workgroup_x", "fn", "1")


def test_workgroup_count_rejects_oversize():
    """65536 exceeds the WebGPU per-dim limit; backends accept it on
    some drivers but the dispatch then silently never runs on others."""
    from slappyengine.compute._validation import (
        validate_workgroup_count, MAX_WORKGROUPS_PER_DIM,
    )
    with pytest.raises(ValueError, match=f"<= {MAX_WORKGROUPS_PER_DIM}"):
        validate_workgroup_count("workgroup_x", "fn", MAX_WORKGROUPS_PER_DIM + 1)


def test_workgroup_count_accepts_one():
    from slappyengine.compute._validation import validate_workgroup_count
    assert validate_workgroup_count("workgroup_x", "fn", 1) == 1


def test_workgroup_count_accepts_max():
    from slappyengine.compute._validation import (
        validate_workgroup_count, MAX_WORKGROUPS_PER_DIM,
    )
    assert (
        validate_workgroup_count("workgroup_x", "fn", MAX_WORKGROUPS_PER_DIM)
        == MAX_WORKGROUPS_PER_DIM
    )


# ---------------------------------------------------------------------------
# validate_workgroup_3tuple — full (x, y, z) dispatch shape
# ---------------------------------------------------------------------------


def test_workgroup_3tuple_rejects_length_2():
    from slappyengine.compute._validation import validate_workgroup_3tuple
    with pytest.raises(ValueError, match="length 3"):
        validate_workgroup_3tuple("groups", "fn", (8, 8))


def test_workgroup_3tuple_rejects_zero_y():
    from slappyengine.compute._validation import validate_workgroup_3tuple
    with pytest.raises(ValueError, match=r"groups\[1\] must be >= 1"):
        validate_workgroup_3tuple("groups", "fn", (8, 0, 1))


def test_workgroup_3tuple_rejects_string():
    from slappyengine.compute._validation import validate_workgroup_3tuple
    with pytest.raises(TypeError, match="3-tuple"):
        validate_workgroup_3tuple("groups", "fn", "8,8,1")


# ---------------------------------------------------------------------------
# ComputePipeline.validate_workgroups — static API
# ---------------------------------------------------------------------------


def test_pipeline_validate_workgroups_rejects_zero():
    from slappyengine.compute.pipeline import ComputePipeline
    with pytest.raises(ValueError, match=">= 1"):
        ComputePipeline.validate_workgroups(0)


def test_pipeline_validate_workgroups_rejects_nan_y():
    from slappyengine.compute.pipeline import ComputePipeline
    with pytest.raises(ValueError, match="NaN"):
        ComputePipeline.validate_workgroups(8, math.nan, 1)


def test_pipeline_validate_workgroups_accepts_triple():
    from slappyengine.compute.pipeline import ComputePipeline
    assert ComputePipeline.validate_workgroups(8, 4, 2) == (8, 4, 2)


# ---------------------------------------------------------------------------
# ComputePass.__init__ shader source / entry-point / label
# ---------------------------------------------------------------------------


_TRIVIAL_WGSL = "@compute @workgroup_size(1) fn main() {}\n"


def test_compute_pass_rejects_bytes_source():
    """Silent-acceptance bug: bytes source dies deep in wgpu — refuse here."""
    from slappyengine.compute.pipeline import ComputePass
    with pytest.raises(TypeError, match="decode to str"):
        ComputePass(source=_TRIVIAL_WGSL.encode("utf-8"))  # type: ignore[arg-type]


def test_compute_pass_rejects_empty_source():
    from slappyengine.compute.pipeline import ComputePass
    with pytest.raises(ValueError, match="source must be non-empty"):
        ComputePass(source="")


def test_compute_pass_rejects_none_source():
    from slappyengine.compute.pipeline import ComputePass
    with pytest.raises(TypeError, match="source must be a str"):
        ComputePass(source=None)  # type: ignore[arg-type]


def test_compute_pass_rejects_empty_entry_point():
    """Silent-acceptance bug: empty entry_point silently picked the first
    entry in the module — almost never what the caller intended."""
    from slappyengine.compute.pipeline import ComputePass
    with pytest.raises(ValueError, match="entry_point must be non-empty"):
        ComputePass(source=_TRIVIAL_WGSL, entry_point="")


def test_compute_pass_rejects_non_str_entry_point():
    from slappyengine.compute.pipeline import ComputePass
    with pytest.raises(TypeError, match="entry_point must be a str"):
        ComputePass(source=_TRIVIAL_WGSL, entry_point=123)  # type: ignore[arg-type]


def test_compute_pass_rejects_non_str_label():
    from slappyengine.compute.pipeline import ComputePass
    with pytest.raises(TypeError, match="label must be a str"):
        ComputePass(source=_TRIVIAL_WGSL, label=42)  # type: ignore[arg-type]


def test_compute_pass_accepts_empty_label():
    """Label is a debug-only string; empty is fine."""
    from slappyengine.compute.pipeline import ComputePass
    p = ComputePass(source=_TRIVIAL_WGSL, label="")
    assert p.label == ""


def test_compute_pass_from_source_routes_through_validator():
    """from_source delegates to __init__ — the bytes refusal must fire."""
    from slappyengine.compute.pipeline import ComputePass
    with pytest.raises(TypeError, match="decode to str"):
        ComputePass.from_source(source=b"x")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# ComputePass.from_wgsl path validators
# ---------------------------------------------------------------------------


def test_compute_pass_from_wgsl_rejects_missing_path(tmp_path):
    from slappyengine.compute.pipeline import ComputePass
    missing = tmp_path / "does_not_exist.wgsl"
    with pytest.raises(FileNotFoundError, match="not found"):
        ComputePass.from_wgsl(missing)


def test_compute_pass_from_wgsl_rejects_directory(tmp_path):
    from slappyengine.compute.pipeline import ComputePass
    with pytest.raises(FileNotFoundError, match="not a regular file"):
        ComputePass.from_wgsl(tmp_path)


def test_compute_pass_from_wgsl_rejects_empty_path():
    from slappyengine.compute.pipeline import ComputePass
    with pytest.raises(ValueError, match="must not be empty"):
        ComputePass.from_wgsl("")


def test_compute_pass_from_wgsl_rejects_bool_path():
    from slappyengine.compute.pipeline import ComputePass
    with pytest.raises(TypeError, match="must be str or pathlib.Path"):
        ComputePass.from_wgsl(True)  # type: ignore[arg-type]


def test_compute_pass_from_wgsl_loads_existing(tmp_path):
    """Positive sanity: a real file loads."""
    from slappyengine.compute.pipeline import ComputePass
    shader = tmp_path / "t.wgsl"
    shader.write_text(_TRIVIAL_WGSL, encoding="utf-8")
    p = ComputePass.from_wgsl(shader)
    assert p.source.startswith("@compute")


# ---------------------------------------------------------------------------
# ComputeLibrary.register validators
# ---------------------------------------------------------------------------


def test_compute_library_register_rejects_empty_name():
    """Silent-acceptance bug: empty name was a legal dict key and silently
    overwrote any prior empty-name shader."""
    from slappyengine.compute.library import ComputeLibrary
    with pytest.raises(ValueError, match="name must be non-empty"):
        ComputeLibrary.register("", _TRIVIAL_WGSL)


def test_compute_library_register_rejects_none_name():
    from slappyengine.compute.library import ComputeLibrary
    with pytest.raises(TypeError, match="name must be a str"):
        ComputeLibrary.register(None, _TRIVIAL_WGSL)  # type: ignore[arg-type]


def test_compute_library_register_rejects_bytes_source():
    from slappyengine.compute.library import ComputeLibrary
    with pytest.raises(TypeError, match="decode to str"):
        ComputeLibrary.register("x", _TRIVIAL_WGSL.encode("utf-8"))  # type: ignore[arg-type]


def test_compute_library_register_rejects_empty_source():
    from slappyengine.compute.library import ComputeLibrary
    with pytest.raises(ValueError, match="source must be non-empty"):
        ComputeLibrary.register("x", "")


def test_compute_library_register_accepts_real_pair():
    from slappyengine.compute.library import ComputeLibrary
    ComputeLibrary.register("hardening_round14_probe", _TRIVIAL_WGSL)
    assert "hardening_round14_probe" in ComputeLibrary.list_registered()


# ---------------------------------------------------------------------------
# validate_bind_group_entries — duplicate / malformed bindings
# ---------------------------------------------------------------------------


def test_bind_entries_rejects_duplicate_binding():
    """Silent-acceptance bug: wgpu keeps the LAST entry on some backends,
    so the earlier entry is a dead write that never reaches the GPU."""
    from slappyengine.compute._validation import validate_bind_group_entries
    entries = [
        {"binding": 0, "resource": "tex_a"},
        {"binding": 0, "resource": "tex_b"},  # duplicate!
    ]
    with pytest.raises(ValueError, match="duplicate binding index 0"):
        validate_bind_group_entries("entries", "fn", entries)


def test_bind_entries_rejects_negative_binding():
    from slappyengine.compute._validation import validate_bind_group_entries
    with pytest.raises(ValueError, match=r"entries\[0\]\.binding must be >= 0"):
        validate_bind_group_entries(
            "entries", "fn",
            [{"binding": -1, "resource": "tex"}],
        )


def test_bind_entries_rejects_bool_binding():
    """``True`` -> binding=1 silently — refuse."""
    from slappyengine.compute._validation import validate_bind_group_entries
    with pytest.raises(TypeError, match=r"entries\[0\]\.binding must be an int"):
        validate_bind_group_entries(
            "entries", "fn",
            [{"binding": True, "resource": "tex"}],
        )


def test_bind_entries_rejects_missing_binding_key():
    from slappyengine.compute._validation import validate_bind_group_entries
    with pytest.raises(ValueError, match="missing required key 'binding'"):
        validate_bind_group_entries(
            "entries", "fn",
            [{"resource": "tex"}],
        )


def test_bind_entries_rejects_missing_resource_key():
    from slappyengine.compute._validation import validate_bind_group_entries
    with pytest.raises(ValueError, match="missing required key 'resource'"):
        validate_bind_group_entries(
            "entries", "fn",
            [{"binding": 0}],
        )


def test_bind_entries_rejects_non_dict_entry():
    from slappyengine.compute._validation import validate_bind_group_entries
    with pytest.raises(TypeError, match=r"entries\[0\] must be a dict"):
        validate_bind_group_entries(
            "entries", "fn",
            [("binding", 0)],  # type: ignore[list-item]
        )


def test_bind_entries_rejects_none():
    from slappyengine.compute._validation import validate_bind_group_entries
    with pytest.raises(TypeError, match="must not be None"):
        validate_bind_group_entries("entries", "fn", None)


def test_bind_entries_rejects_dict_payload():
    """A bare dict could look like a single entry; refuse explicitly."""
    from slappyengine.compute._validation import validate_bind_group_entries
    with pytest.raises(TypeError, match="must be a list"):
        validate_bind_group_entries(
            "entries", "fn",
            {"binding": 0, "resource": "tex"},
        )


def test_bind_entries_accepts_unique_indices():
    """Positive: three distinct bindings pass through."""
    from slappyengine.compute._validation import validate_bind_group_entries
    out = validate_bind_group_entries(
        "entries", "fn",
        [
            {"binding": 0, "resource": "in"},
            {"binding": 1, "resource": "out"},
            {"binding": 2, "resource": {"buffer": "params"}},
        ],
    )
    assert len(out) == 3


def test_executor_validate_bind_entries_static_method():
    """PostProcessExecutor exposes the same check as a classmethod."""
    from slappyengine.post_process.executor import PostProcessExecutor
    with pytest.raises(ValueError, match="duplicate binding"):
        PostProcessExecutor.validate_bind_entries(
            [
                {"binding": 1, "resource": "a"},
                {"binding": 1, "resource": "b"},
            ],
        )


def test_executor_validate_dispatch_size_rejects_zero():
    from slappyengine.post_process.executor import PostProcessExecutor
    with pytest.raises(ValueError, match=">= 1"):
        PostProcessExecutor.validate_dispatch_size(0, 8, 1)


# ---------------------------------------------------------------------------
# Path validator edge — bytes input
# ---------------------------------------------------------------------------


def test_shader_path_rejects_bytes():
    from slappyengine.compute._validation import validate_shader_path
    with pytest.raises(TypeError, match="must be str or pathlib.Path"):
        validate_shader_path("path", "fn", b"shader.wgsl")  # type: ignore[arg-type]


def test_shader_source_rejects_bytearray():
    """bytearray slips past ``isinstance(x, bytes)`` on some checks — verify."""
    from slappyengine.compute._validation import validate_shader_source
    with pytest.raises(TypeError, match="decode to str"):
        validate_shader_source("source", "fn", bytearray(b"x"))  # type: ignore[arg-type]
