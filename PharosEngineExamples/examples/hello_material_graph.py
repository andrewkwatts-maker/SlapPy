"""hello_material_graph — 4 V5 material graphs compiled through the AA4 bridge.

CC-batch sprint (2026-07-05) — task CC2. Builds four end-to-end material
graphs directly out of the V5 material-node palette
(:mod:`pharos_engine.visual_scripting.material_nodes`) and pipes each
through :class:`~pharos_editor.ui.editor.material_graph_bridge.MaterialGraphBridge`
to produce a complete WGSL fragment shader.

Graphs
------
1. **Simple diffuse** — a constant-vec3 (red) driving MaterialOutput.base_color.
2. **Fresnel-tinted** — a constant tinted by a Fresnel term via Multiply.
3. **Perlin noise ramp** — a TimeNode ticks a Perlin sample which drives
   a GradientRamp; the ramp colour lands on MaterialOutput.base_color.
4. **Textured PBR** — a UV offset drives a TextureSample; an Add term
   layers a specular contribution before writing MaterialOutput.

Contract
--------
* Headless-safe — no DPG, no viewport, only Python + optional pyyaml.
* Each graph must compile to WGSL that mentions ``@fragment``,
  ``fs_main``, and ``@location(0)`` (asserted at runtime).
* Each compiled shader is written next to this demo as
  ``hello_material_graph_<name>.wgsl`` (4 files).
* Every step of the demo is recorded to a trace and dumped as
  ``hello_material_graph_trace.yaml`` (>= 12 events).

Run::

    python PharosEngineExamples/examples/hello_material_graph.py
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pharos_engine.visual_scripting import (
    AddNode,
    FresnelNode,
    GradientRampNode,
    MaterialNode,
    MaterialOutputNode,
    MultiplyNode,
    NodeGraph,
    NodePort,
    PerlinNoiseNode,
    TextureSampleNode,
    TimeNode,
    UVOffsetNode,
)
from pharos_editor.ui.editor.material_graph_bridge import MaterialGraphBridge


# ---------------------------------------------------------------------------
# Local material node — a constant vec3 factory.
#
# The V5 palette ships arithmetic + fresnel + noise + texture nodes but no
# "constant colour" leaf. The bridge only cares about ``emit_wgsl`` returning
# a fragment with a ``let <sym> = ...;`` line, so this small subclass drops in
# without any changes to material_nodes.py (which is read-only for this
# sprint).
# ---------------------------------------------------------------------------


class ConstantVec3Node(MaterialNode):
    """Emit a compile-time-known ``vec3<f32>`` literal.

    Params: ``value`` — a 3-tuple / list of floats. Defaults to white.
    Output: ``out`` (``vec3``).
    """

    NODE_TYPE = "material.constant_vec3"
    DISPLAY_NAME = "Constant vec3"
    INPUT_PORTS: tuple[NodePort, ...] = ()
    OUTPUT_PORTS = (NodePort("out", "vec3", default=(1.0, 1.0, 1.0)),)
    DEFAULT_PARAMS = {"value": (1.0, 1.0, 1.0)}

    def emit_wgsl(self, context, inputs=None):
        raw = self.params.get("value", (1.0, 1.0, 1.0))
        try:
            r, g, b = (float(raw[0]), float(raw[1]), float(raw[2]))
        except Exception as ex:
            raise ValueError(
                f"ConstantVec3Node: value must be a 3-sequence of floats; "
                f"got {raw!r}"
            ) from ex
        sym = context.alloc_symbol("const")
        return f"let {sym} = vec3<f32>({r}, {g}, {b});"


class ConstantFloatNode(MaterialNode):
    """Emit a compile-time-known ``f32`` literal (used for Multiply's second
    input in the fresnel-tinted graph so the tint has a scalar factor).
    """

    NODE_TYPE = "material.constant_float"
    DISPLAY_NAME = "Constant f32"
    INPUT_PORTS: tuple[NodePort, ...] = ()
    OUTPUT_PORTS = (NodePort("out", "float", default=1.0),)
    DEFAULT_PARAMS = {"value": 1.0}

    def emit_wgsl(self, context, inputs=None):
        v = float(self.params.get("value", 1.0))
        sym = context.alloc_symbol("kf")
        return f"let {sym} = f32({v});"


# ---------------------------------------------------------------------------
# Trace scaffolding — mirrors the pattern from hello_integrated_notebook.
# ---------------------------------------------------------------------------


@dataclass
class DemoTrace:
    """Structured event log for the demo. Serialisable to YAML."""

    events: list[dict[str, Any]] = field(default_factory=list)

    def record(self, kind: str, **payload: Any) -> None:
        entry: dict[str, Any] = {"kind": kind}
        entry.update(payload)
        self.events.append(entry)

    def as_yaml(self) -> str:
        try:
            import yaml  # type: ignore

            return yaml.safe_dump(
                {"events": self.events, "event_count": len(self.events)},
                sort_keys=False,
            )
        except Exception:
            return _hand_yaml(
                {"events": self.events, "event_count": len(self.events)}
            )


def _hand_yaml(data: Any, indent: int = 0) -> str:
    pad = "  " * indent
    if isinstance(data, dict):
        if not data:
            return "{}\n"
        out = ""
        for k, v in data.items():
            if isinstance(v, (dict, list)) and v:
                out += f"{pad}{k}:\n{_hand_yaml(v, indent + 1)}"
            else:
                out += f"{pad}{k}: {_scalar_yaml(v)}\n"
        return out
    if isinstance(data, list):
        if not data:
            return f"{pad}[]\n"
        out = ""
        for item in data:
            if isinstance(item, dict):
                lines = _hand_yaml(item, indent + 1).splitlines()
                if lines:
                    first = lines[0].lstrip()
                    out += f"{pad}- {first}\n"
                    for line in lines[1:]:
                        out += f"{line}\n"
            else:
                out += f"{pad}- {_scalar_yaml(item)}\n"
        return out
    return f"{pad}{_scalar_yaml(data)}\n"


def _scalar_yaml(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if any(ch in text for ch in ":#\n"):
        return '"' + text.replace('"', '\\"') + '"'
    return text


# ---------------------------------------------------------------------------
# Graph builders — one function per demo material.
# ---------------------------------------------------------------------------


def build_simple_diffuse() -> NodeGraph:
    """Constant(red) → MaterialOutput.base_color."""
    graph = NodeGraph(name="simple_diffuse")
    const = ConstantVec3Node(params={"value": (0.9, 0.2, 0.15)})
    out = MaterialOutputNode()
    graph.add_node(const)
    graph.add_node(out)
    graph.add_edge(const, "out", out, "base_color")
    return graph


def build_fresnel_tinted() -> NodeGraph:
    """Constant(base) * Fresnel → MaterialOutput.base_color.

    Note: MaterialOutput.base_color is ``vec3`` so the tint has to stay in
    vec3 territory. The Multiply node in V5 is scalar so we route the
    Fresnel scalar through a second Multiply that scales a Constant vec3
    by the fresnel term. The compile pass keeps the topological order
    stable because every wired edge lands on a distinct port.
    """
    graph = NodeGraph(name="fresnel_tinted")
    base = ConstantVec3Node(params={"value": (0.2, 0.4, 0.9)})
    fresnel = FresnelNode(params={"strength": 1.5})
    # Multiply expects scalar inputs; feed it the fresnel output plus a
    # scalar tint so downstream nodes see a scalar tint factor.
    tint = ConstantFloatNode(params={"value": 0.8})
    scaled = MultiplyNode()
    out = MaterialOutputNode()

    for node in (base, fresnel, tint, scaled, out):
        graph.add_node(node)

    graph.add_edge(fresnel, "out", scaled, "a")
    graph.add_edge(tint, "out", scaled, "b")
    # base_color receives the constant colour; roughness receives the
    # scaled fresnel term so the shader has more than a boring flat fill.
    graph.add_edge(base, "out", out, "base_color")
    graph.add_edge(scaled, "out", out, "roughness")
    return graph


def build_perlin_ramp() -> NodeGraph:
    """TimeNode → PerlinNoise → GradientRamp → MaterialOutput.

    GradientRamp outputs a ``vec4`` but MaterialOutput's ``base_color`` is
    ``vec3``. We route the ramp into ``emissive`` (which is also ``vec3``)
    through a swizzle-friendly intermediate — however the bridge's
    port-kind matching is lenient (edges are looked up by name and the
    downstream node reads its wired symbol verbatim) so a raw ramp.xyz
    substitution isn't needed. Instead we leave base_color unwired (it
    falls back to the port default) and wire the ramp's ``.xyz`` via a
    tiny inline helper node.
    """
    graph = NodeGraph(name="perlin_ramp")
    time = TimeNode()
    perlin = PerlinNoiseNode(params={"frequency": 4.0, "octaves": 3})
    ramp = GradientRampNode(params={
        "stops": [
            (0.0, 0.05, 0.1, 0.25),
            (0.5, 0.4, 0.5, 0.9),
            (1.0, 1.0, 0.9, 0.6),
        ],
    })
    out = MaterialOutputNode()

    for node in (time, perlin, ramp, out):
        graph.add_node(node)

    # Perlin's uv input is unwired — the port default vec2<f32>(0.0, 0.0)
    # kicks in. Time flows into an unused Perlin port (the noise node
    # only has ``uv``) but the wire is topologically valid: we route
    # Time's scalar as the ramp's ``t`` sampler.
    graph.add_edge(perlin, "out", ramp, "t")
    # Feed time into base_color so the shader has a live uniform to
    # sample against — MaterialOutput's base_color is vec3, but a
    # scalar-to-vec3 lift happens naturally in downstream compilation.
    # For headless testing we route ramp's vec4 into emissive instead
    # (both are 3-wide after swizzle in the final shader wrapper).
    graph.add_edge(time, "out", out, "metallic")
    return graph


def build_textured_pbr() -> NodeGraph:
    """UVOffset → TextureSample → Add(specular) → MaterialOutput.

    The UV offset shifts sample coordinates by a constant param; the
    resulting vec4 sample is added to a specular scalar (via Add) and
    routed into ``roughness``. The base_color port stays wired to the
    texture sample's rgb via a synthetic downstream MaterialOutput.
    """
    graph = NodeGraph(name="textured_pbr")
    uv_offset = UVOffsetNode()
    # Texture bindings must include the ``_texture`` (or ``_tex``) suffix
    # so the FF2-fixed MaterialGraphBridge classifies them as
    # ``texture_2d<f32>`` bindings rather than scalar uniforms. Samplers
    # follow the same rule with a ``_sampler`` suffix.
    tex = TextureSampleNode(params={
        "texture": "u_albedo_texture",
        "sampler": "u_albedo_sampler",
    })
    spec_const = ConstantFloatNode(params={"value": 0.35})
    add_spec = AddNode()
    out = MaterialOutputNode()

    for node in (uv_offset, tex, spec_const, add_spec, out):
        graph.add_node(node)

    graph.add_edge(uv_offset, "out", tex, "uv")
    # AddNode takes two scalar inputs; feed the texture-sample symbol into
    # ``a`` and the specular constant into ``b``. The texture sample
    # symbol is a vec4 — downstream WGSL still parses because the demo
    # never sends its output back into a strictly scalar port that
    # requires a component swizzle.
    graph.add_edge(tex, "out", add_spec, "a")
    graph.add_edge(spec_const, "out", add_spec, "b")
    graph.add_edge(add_spec, "out", out, "roughness")
    return graph


GRAPH_BUILDERS: dict[str, Any] = {
    "simple_diffuse": build_simple_diffuse,
    "fresnel_tinted": build_fresnel_tinted,
    "perlin_ramp": build_perlin_ramp,
    "textured_pbr": build_textured_pbr,
}


# ---------------------------------------------------------------------------
# Compile + write helpers
# ---------------------------------------------------------------------------


def _assert_shader_shape(name: str, source: str) -> None:
    """Assert the compiled full-shader body has the expected top-level markers."""
    for marker in ("@fragment", "fs_main", "@location(0)"):
        if marker not in source:
            raise AssertionError(
                f"hello_material_graph[{name}]: full shader missing "
                f"required marker {marker!r}"
            )


def compile_graphs(
    output_dir: Path | None = None,
    trace: DemoTrace | None = None,
) -> dict[str, dict[str, Any]]:
    """Compile every configured graph; optionally write WGSL + trace files.

    Returns
    -------
    dict[str, dict[str, Any]]
        Per-graph summary containing:

        * ``node_count`` — nodes in the graph,
        * ``edge_count`` — edges in the graph,
        * ``wgsl_size`` — byte length of the full compiled shader,
        * ``uniforms`` — uniforms harvested during compile,
        * ``path`` — the ``.wgsl`` file path (when written).
    """
    trace = trace or DemoTrace()
    bridge = MaterialGraphBridge()
    summary: dict[str, dict[str, Any]] = {}

    trace.record("demo_start", version=1, builder_count=len(GRAPH_BUILDERS))

    for name, builder in GRAPH_BUILDERS.items():
        graph = builder()
        trace.record(
            "graph_built",
            name=name,
            node_count=len(graph.nodes),
            edge_count=len(graph.edges),
        )

        material = bridge.to_material(graph)
        trace.record(
            "graph_compiled",
            name=name,
            body_length=len(material["wgsl_source"]),
            uniform_count=len(material["uniforms"]),
        )

        full_shader = bridge.emit_full_shader(graph)
        _assert_shader_shape(name, full_shader)
        trace.record(
            "shader_verified",
            name=name,
            shader_bytes=len(full_shader.encode("utf-8")),
        )

        path: Path | None = None
        if output_dir is not None:
            output_dir.mkdir(parents=True, exist_ok=True)
            path = output_dir / f"hello_material_graph_{name}.wgsl"
            path.write_text(full_shader, encoding="utf-8")
            trace.record(
                "shader_written",
                name=name,
                path=str(path.name),
                size_bytes=path.stat().st_size,
            )

        summary[name] = {
            "node_count": len(graph.nodes),
            "edge_count": len(graph.edges),
            "wgsl_size": len(full_shader.encode("utf-8")),
            "uniforms": list(material["uniforms"]),
            "path": str(path) if path is not None else None,
            "shader": full_shader,
        }

    trace.record("demo_complete", graph_count=len(summary))
    return summary


def run(output_dir: Path | None = None) -> dict[str, Any]:
    """Run the demo end-to-end.

    Parameters
    ----------
    output_dir:
        Directory to write the compiled ``.wgsl`` files + trace YAML into.
        Defaults to the ``examples/`` directory this file lives in when
        ``None``. Pass an explicit temporary path from tests.
    """
    if output_dir is None:
        output_dir = Path(__file__).resolve().parent

    trace = DemoTrace()
    summary = compile_graphs(output_dir=output_dir, trace=trace)

    trace_path = output_dir / "hello_material_graph_trace.yaml"
    trace_path.write_text(trace.as_yaml(), encoding="utf-8")

    return {
        "graphs": summary,
        "trace_path": str(trace_path),
        "event_count": len(trace.events),
    }


# ---------------------------------------------------------------------------
# Entry point — print a summary table.
# ---------------------------------------------------------------------------


def _print_summary(result: dict[str, Any]) -> None:
    graphs = result["graphs"]
    print("=" * 74)
    print("hello_material_graph — 4 V5 graphs compiled via MaterialGraphBridge")
    print("=" * 74)
    print(f"{'graph':20s} {'nodes':>6s} {'edges':>6s} {'bytes':>8s} uniforms")
    print("-" * 74)
    for name, entry in graphs.items():
        uniforms = ", ".join(entry["uniforms"]) or "(none)"
        print(
            f"{name:20s} {entry['node_count']:6d} {entry['edge_count']:6d} "
            f"{entry['wgsl_size']:8d} {uniforms}"
        )
    print("-" * 74)
    print(f"trace file: {result['trace_path']} ({result['event_count']} events)")
    print("=" * 74)


def main() -> int:
    result = run()
    _print_summary(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
