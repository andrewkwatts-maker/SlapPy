"""Regression tests for the default `MeshPipeline` shader / layout contract.

Failure mode this test guards against: the WGSL fragment shader declares an
`@group/@binding` decoration that the Python pipeline-layout builder does not
advertise.  When that happens, wgpu raises `GPUValidationError: Shader global
ResourceBinding { group: X, binding: Y } is not available in the pipeline
layout` and the whole 3D layer stack dies at `MeshPipeline._build_pipeline`.

Sprint 6G smoke audit (commit 106faea) found exactly this for
`hello_3d_layer.py` and `hello_bake.py`.

The static parser does NOT need a GPU adapter — it reads both the WGSL source
the pipeline loads and the Python source that lists the bind-group entries,
then asserts equality of the declared @group/@binding pairs.

A second test exercises the real pipeline against an adapter when one is
available; otherwise it skips so CI remains green.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PIPELINE_PY = REPO_ROOT / "python" / "slappyengine" / "gpu" / "mesh_pipeline.py"
SHADER_DIR = REPO_ROOT / "shaders"

# Matches `@group(N) @binding(M)` with arbitrary whitespace.
_BIND_RE = re.compile(r"@group\s*\(\s*(\d+)\s*\)\s*@binding\s*\(\s*(\d+)\s*\)")


def _shader_bindings(wgsl_text: str) -> set[tuple[int, int]]:
    """Return the set of (group, binding) pairs declared in a WGSL source."""
    return {(int(g), int(b)) for g, b in _BIND_RE.findall(wgsl_text)}


def _pipeline_layout_bindings(py_text: str) -> set[tuple[int, int]]:
    """Approximate the declared (group, binding) pairs from mesh_pipeline.py.

    Strategy: each `create_bind_group_layout` call corresponds to one group
    (indexed in the order they're passed to `create_pipeline_layout` —
    `[camera_bgl, material_bgl]` here gives group 0 then group 1).  Every
    ``"binding": N`` entry inside such a block is a binding within that group.

    This is intentionally tiny rather than a real WGSL parser: when somebody
    adds a third bind-group, they must update both this test's expectations
    and the production pipeline, which is the contract we want enforced.
    """
    pairs: set[tuple[int, int]] = set()

    # Find the bind-group layout literal names in pipeline-layout order.
    m = re.search(
        r"create_pipeline_layout\s*\([^)]*?bind_group_layouts\s*=\s*\[([^\]]+)\]",
        py_text,
        flags=re.DOTALL,
    )
    if not m:
        return pairs
    bgls_in_order = [
        name.strip().lstrip("self._").rstrip(",")
        for name in m.group(1).split(",")
        if name.strip()
    ]

    # For each `self._<name> = device.create_bind_group_layout(...)` block,
    # capture every `"binding": N` literal it contains.
    for group_idx, attr_name in enumerate(bgls_in_order):
        pattern = (
            r"self\._" + re.escape(attr_name) +
            r"\s*=\s*device\.create_bind_group_layout\s*\((.*?)\)\s*\n"
        )
        block_match = re.search(pattern, py_text, flags=re.DOTALL)
        if not block_match:
            continue
        block = block_match.group(1)
        for binding_match in re.finditer(r'"binding"\s*:\s*(\d+)', block):
            pairs.add((group_idx, int(binding_match.group(1))))

    return pairs


# ---------------------------------------------------------------------------
# Static regression: shader vs pipeline layout
# ---------------------------------------------------------------------------

def test_default_pipeline_shader_matches_layout():
    """Every @group/@binding the default mesh shader declares must appear in
    the Python pipeline-layout builder.

    Guards against the Sprint 6G failure where `mesh_frag_pbr.wgsl` declared
    group(1) bindings 1..4 (textures, sampler, lights) but the layout only
    advertised group(1) binding(0).
    """
    py_text = PIPELINE_PY.read_text(encoding="utf-8")

    # Pull both shader paths the pipeline actually loads.
    shader_paths: list[Path] = []
    for m in re.finditer(r'SHADER_DIR\s*/\s*"([^"]+\.wgsl)"', py_text):
        shader_paths.append(SHADER_DIR / m.group(1))
    assert shader_paths, "Could not find any SHADER_DIR / '*.wgsl' references"

    shader_bindings: set[tuple[int, int]] = set()
    for path in shader_paths:
        assert path.exists(), f"Shader referenced but missing on disk: {path}"
        shader_bindings |= _shader_bindings(path.read_text(encoding="utf-8"))

    layout_bindings = _pipeline_layout_bindings(py_text)
    assert layout_bindings, (
        "Static parser failed to extract any bindings from mesh_pipeline.py — "
        "the parser may be out of sync with the production code."
    )

    missing = shader_bindings - layout_bindings
    assert not missing, (
        f"Shader declares @group/@binding {sorted(missing)} that the pipeline "
        f"layout does not advertise.  This is the wgpu validation error "
        f"`Shader global ResourceBinding ... is not available in the pipeline "
        f"layout`.  Either drop the binding from the WGSL source or add the "
        f"matching entry to the pipeline-layout builder.\n"
        f"  shader bindings : {sorted(shader_bindings)}\n"
        f"  layout bindings : {sorted(layout_bindings)}"
    )


def test_pipeline_loads_simple_pbr_shader():
    """The default `MeshPipeline` must load `mesh_frag_pbr_simple.wgsl`, not
    the full `mesh_frag_pbr.wgsl` whose group(1)/group(2) extras are wired by
    other pipelines.  Locks in the Sprint 6G fix.
    """
    py_text = PIPELINE_PY.read_text(encoding="utf-8")
    assert 'mesh_frag_pbr_simple.wgsl' in py_text, (
        "mesh_pipeline.py should load the slimmed-down 'mesh_frag_pbr_simple.wgsl' "
        "whose bindings match the (camera + material) pipeline layout."
    )


# ---------------------------------------------------------------------------
# Live-adapter sanity: actually build the pipeline if a GPU is available
# ---------------------------------------------------------------------------

wgpu = pytest.importorskip("wgpu")


def _maybe_device():
    try:
        adapter = wgpu.gpu.request_adapter_sync(power_preference="high-performance")
        if adapter is None:
            return None
        return adapter.request_device_sync()
    except Exception:
        return None


def test_mesh_pipeline_builds_on_real_adapter():
    """If a real wgpu adapter is reachable, building the default MeshPipeline
    must NOT raise `GPUValidationError`.
    """
    device = _maybe_device()
    if device is None:
        pytest.skip("No GPU adapter available")

    from slappyengine.gpu.mesh_pipeline import MeshPipeline

    # `rgba8unorm` is the universal swap-chain format; works on every backend.
    pipeline = MeshPipeline(device, output_format="rgba8unorm")
    assert pipeline.pipeline is not None
    assert pipeline.camera_bgl is not None
    assert pipeline.material_bgl is not None
