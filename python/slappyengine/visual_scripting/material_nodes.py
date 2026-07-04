"""Material-graph WGSL node palette for :mod:`slappyengine.visual_scripting`.

This module adds a *shader-graph style* node palette on top of the generic
visual-scripting backbone. Each node type below subclasses the base
:class:`Node` and adds an :meth:`emit_wgsl` method that returns a WGSL
fragment-shader snippet — the NotebookMaterialEditor compiles a graph
into a full material shader by walking the topologically sorted nodes
and concatenating their WGSL fragments.

Design notes
------------
* Ports use the existing :data:`PORT_KINDS` — the task spec's
  ``float3`` / ``float4`` map to ``vec3`` / ``vec4`` (which are the
  correct WGSL types anyway); ``sampler2d`` is a new port kind added to
  ``PORT_KINDS`` alongside this module. Colours and normals use
  ``vec3``; RGBA and homogeneous coordinates use ``vec4``.
* The task spec references ``input_ports`` / ``output_ports`` on each
  node; those are exposed here as *aliases* over the existing
  ``inputs`` / ``outputs`` fields so this palette drops into the same
  graph / codegen infrastructure without special-casing.
* :func:`register_material_nodes` inserts each prototype into a caller
  supplied :class:`NodeRegistry` under the ``kind="render"`` category —
  the base ``NODE_KINDS`` frozenset already allows ``render`` and it is
  the closest existing category to "material graph".
* :meth:`emit_wgsl` receives a ``context`` object exposing
  ``alloc_symbol(prefix) -> str`` and ``used_uniforms: set[str]``; the
  return value is a string containing one or more WGSL statements. The
  node's *output expression* is the allocated symbol (per convention,
  ``let <sym> = <expr>;``); the compile pass wires downstream nodes by
  substituting the input port's incoming symbol.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from .node import Node, NodePort, NodeRegistry


# ---------------------------------------------------------------------------
# WGSL emit context
# ---------------------------------------------------------------------------


class WgslEmitContext(Protocol):
    """Structural protocol for the ``context`` argument passed to emit_wgsl.

    Any object exposing ``alloc_symbol`` and ``used_uniforms`` will do.
    :class:`DefaultWgslEmitContext` below is the reference implementation
    used by the tests.
    """

    used_uniforms: set[str]

    def alloc_symbol(self, prefix: str) -> str: ...  # pragma: no cover


@dataclass
class DefaultWgslEmitContext:
    """Minimal :class:`WgslEmitContext` implementation.

    ``alloc_symbol`` returns a fresh, unique symbol name built from the
    supplied ``prefix`` and a monotonic counter — safe for concatenating
    fragments from arbitrary nodes without collision.
    """

    used_uniforms: set[str] = field(default_factory=set)
    _counter: int = 0

    def alloc_symbol(self, prefix: str) -> str:
        self._counter += 1
        # sanitise the prefix to a valid WGSL identifier
        safe = "".join(ch if ch.isalnum() or ch == "_" else "_"
                       for ch in str(prefix))
        if not safe:
            safe = "sym"
        return f"{safe}_{self._counter}"


# ---------------------------------------------------------------------------
# MaterialNode base
# ---------------------------------------------------------------------------


class MaterialNode(Node):
    """Base class for every entry in the material node palette.

    Subclasses set ``NODE_TYPE``, ``INPUT_PORTS``, ``OUTPUT_PORTS``, and
    ``DEFAULT_PARAMS`` as class-level constants; ``__init__`` copies
    those into the :class:`Node` dataclass fields so a call like
    ``AddNode()`` produces a fully-formed prototype ready for the
    registry.
    """

    #: Registry key. Subclasses must override.
    NODE_TYPE: str = "material.base"
    #: Human-readable display name (falls back to ``NODE_TYPE``).
    DISPLAY_NAME: str = ""
    #: :class:`NodePort` list for inputs. Subclasses override.
    INPUT_PORTS: tuple[NodePort, ...] = ()
    #: :class:`NodePort` list for outputs. Subclasses override.
    OUTPUT_PORTS: tuple[NodePort, ...] = ()
    #: Default node parameters (``dict`` copied per-instance).
    DEFAULT_PARAMS: dict[str, Any] = {}

    def __init__(self, **overrides: Any) -> None:
        params = dict(self.DEFAULT_PARAMS)
        params.update(overrides.pop("params", {}))
        super().__init__(
            node_type=overrides.pop("node_type", self.NODE_TYPE),
            kind=overrides.pop("kind", "render"),
            inputs=list(overrides.pop("inputs", self._clone_ports(self.INPUT_PORTS))),
            outputs=list(overrides.pop("outputs", self._clone_ports(self.OUTPUT_PORTS))),
            params=params,
            position=overrides.pop("position", (0, 0)),
            name=overrides.pop("name", self.DISPLAY_NAME or self.NODE_TYPE),
            id=overrides.pop("id", ""),
            to_python_template=overrides.pop("to_python_template", ""),
        )
        if overrides:
            raise TypeError(
                f"{type(self).__name__}: unexpected kwargs "
                f"{sorted(overrides)}"
            )

    # ------------------------------------------------------------------
    # task-spec aliases: input_ports / output_ports point at inputs /
    # outputs so callers using the shader-graph vocabulary don't have to
    # remember the underlying Node dataclass field names.
    # ------------------------------------------------------------------

    @property
    def input_ports(self) -> list[NodePort]:
        return self.inputs

    @property
    def output_ports(self) -> list[NodePort]:
        return self.outputs

    @property
    def default_params(self) -> dict[str, Any]:
        return dict(self.DEFAULT_PARAMS)

    # ------------------------------------------------------------------
    # emit_wgsl — subclasses override.
    # ------------------------------------------------------------------

    def emit_wgsl(self, context: WgslEmitContext,
                  inputs: dict[str, str] | None = None) -> str:
        """Emit a WGSL statement (or block) for this node.

        Parameters
        ----------
        context:
            An object exposing ``alloc_symbol(prefix)`` and
            ``used_uniforms: set[str]``. See :class:`DefaultWgslEmitContext`.
        inputs:
            Optional map from input port name to the WGSL expression /
            symbol supplying that port. Missing entries fall back to the
            port's ``default`` (converted to a WGSL literal).

        Returns
        -------
        str
            One or more WGSL statements. The convention is that the last
            allocated symbol (``let <sym> = ...;``) is this node's
            output expression and downstream nodes read from it.
        """
        raise NotImplementedError(  # pragma: no cover
            f"{type(self).__name__}.emit_wgsl must be overridden"
        )

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _clone_ports(ports: tuple[NodePort, ...]) -> list[NodePort]:
        import copy
        return [NodePort(p.name, p.port_kind, copy.deepcopy(p.default))
                for p in ports]

    def _resolve(self, inputs: dict[str, str] | None, name: str,
                 fallback: str) -> str:
        """Return the incoming WGSL expression for input ``name`` or the
        provided ``fallback`` literal if the port is unwired.
        """
        if inputs and name in inputs:
            return str(inputs[name])
        return fallback


# ---------------------------------------------------------------------------
# 1. AddNode
# ---------------------------------------------------------------------------


class AddNode(MaterialNode):
    NODE_TYPE = "material.add"
    DISPLAY_NAME = "Add"
    INPUT_PORTS = (
        NodePort("a", "float", default=0.0),
        NodePort("b", "float", default=0.0),
    )
    OUTPUT_PORTS = (NodePort("out", "float"),)
    DEFAULT_PARAMS = {}

    def emit_wgsl(self, context, inputs=None):
        a = self._resolve(inputs, "a", "0.0")
        b = self._resolve(inputs, "b", "0.0")
        sym = context.alloc_symbol("add")
        return f"let {sym} = ({a}) + ({b});"


# ---------------------------------------------------------------------------
# 2. MultiplyNode
# ---------------------------------------------------------------------------


class MultiplyNode(MaterialNode):
    NODE_TYPE = "material.multiply"
    DISPLAY_NAME = "Multiply"
    INPUT_PORTS = (
        NodePort("a", "float", default=1.0),
        NodePort("b", "float", default=1.0),
    )
    OUTPUT_PORTS = (NodePort("out", "float"),)
    DEFAULT_PARAMS = {}

    def emit_wgsl(self, context, inputs=None):
        a = self._resolve(inputs, "a", "1.0")
        b = self._resolve(inputs, "b", "1.0")
        sym = context.alloc_symbol("mul")
        return f"let {sym} = ({a}) * ({b});"


# ---------------------------------------------------------------------------
# 3. LerpNode
# ---------------------------------------------------------------------------


class LerpNode(MaterialNode):
    NODE_TYPE = "material.lerp"
    DISPLAY_NAME = "Lerp"
    INPUT_PORTS = (
        NodePort("a", "float", default=0.0),
        NodePort("b", "float", default=1.0),
        NodePort("t", "float", default=0.5),
    )
    OUTPUT_PORTS = (NodePort("out", "float"),)
    DEFAULT_PARAMS = {}

    def emit_wgsl(self, context, inputs=None):
        a = self._resolve(inputs, "a", "0.0")
        b = self._resolve(inputs, "b", "1.0")
        t = self._resolve(inputs, "t", "0.5")
        sym = context.alloc_symbol("lerp")
        return f"let {sym} = mix({a}, {b}, {t});"


# ---------------------------------------------------------------------------
# 4. SaturateNode
# ---------------------------------------------------------------------------


class SaturateNode(MaterialNode):
    NODE_TYPE = "material.saturate"
    DISPLAY_NAME = "Saturate"
    INPUT_PORTS = (NodePort("x", "float", default=0.0),)
    OUTPUT_PORTS = (NodePort("out", "float"),)
    DEFAULT_PARAMS = {}

    def emit_wgsl(self, context, inputs=None):
        x = self._resolve(inputs, "x", "0.0")
        sym = context.alloc_symbol("sat")
        return f"let {sym} = clamp({x}, 0.0, 1.0);"


# ---------------------------------------------------------------------------
# 5. ClampNode
# ---------------------------------------------------------------------------


class ClampNode(MaterialNode):
    NODE_TYPE = "material.clamp"
    DISPLAY_NAME = "Clamp"
    INPUT_PORTS = (NodePort("x", "float", default=0.0),)
    OUTPUT_PORTS = (NodePort("out", "float"),)
    DEFAULT_PARAMS = {"min": 0.0, "max": 1.0}

    def emit_wgsl(self, context, inputs=None):
        x = self._resolve(inputs, "x", "0.0")
        lo = float(self.params.get("min", 0.0))
        hi = float(self.params.get("max", 1.0))
        sym = context.alloc_symbol("clamp")
        return f"let {sym} = clamp({x}, {lo}, {hi});"


# ---------------------------------------------------------------------------
# 6. PowerNode
# ---------------------------------------------------------------------------


class PowerNode(MaterialNode):
    NODE_TYPE = "material.power"
    DISPLAY_NAME = "Power"
    INPUT_PORTS = (
        NodePort("base", "float", default=1.0),
        NodePort("exp", "float", default=2.0),
    )
    OUTPUT_PORTS = (NodePort("out", "float"),)
    DEFAULT_PARAMS = {}

    def emit_wgsl(self, context, inputs=None):
        base = self._resolve(inputs, "base", "1.0")
        exp = self._resolve(inputs, "exp", "2.0")
        sym = context.alloc_symbol("pow")
        return f"let {sym} = pow({base}, {exp});"


# ---------------------------------------------------------------------------
# 7. SqrtNode
# ---------------------------------------------------------------------------


class SqrtNode(MaterialNode):
    NODE_TYPE = "material.sqrt"
    DISPLAY_NAME = "Sqrt"
    INPUT_PORTS = (NodePort("x", "float", default=1.0),)
    OUTPUT_PORTS = (NodePort("out", "float"),)
    DEFAULT_PARAMS = {}

    def emit_wgsl(self, context, inputs=None):
        x = self._resolve(inputs, "x", "1.0")
        sym = context.alloc_symbol("sqrt")
        return f"let {sym} = sqrt(max({x}, 0.0));"


# ---------------------------------------------------------------------------
# 8. AbsNode
# ---------------------------------------------------------------------------


class AbsNode(MaterialNode):
    NODE_TYPE = "material.abs"
    DISPLAY_NAME = "Abs"
    INPUT_PORTS = (NodePort("x", "float", default=0.0),)
    OUTPUT_PORTS = (NodePort("out", "float"),)
    DEFAULT_PARAMS = {}

    def emit_wgsl(self, context, inputs=None):
        x = self._resolve(inputs, "x", "0.0")
        sym = context.alloc_symbol("abs")
        return f"let {sym} = abs({x});"


# ---------------------------------------------------------------------------
# 9. DotNode
# ---------------------------------------------------------------------------


class DotNode(MaterialNode):
    NODE_TYPE = "material.dot"
    DISPLAY_NAME = "Dot"
    INPUT_PORTS = (
        NodePort("a", "vec3", default=(0.0, 0.0, 0.0)),
        NodePort("b", "vec3", default=(0.0, 0.0, 0.0)),
    )
    OUTPUT_PORTS = (NodePort("out", "float"),)
    DEFAULT_PARAMS = {}

    def emit_wgsl(self, context, inputs=None):
        a = self._resolve(inputs, "a", "vec3<f32>(0.0, 0.0, 0.0)")
        b = self._resolve(inputs, "b", "vec3<f32>(0.0, 0.0, 0.0)")
        sym = context.alloc_symbol("dot")
        return f"let {sym} = dot({a}, {b});"


# ---------------------------------------------------------------------------
# 10. NormalizeNode
# ---------------------------------------------------------------------------


class NormalizeNode(MaterialNode):
    NODE_TYPE = "material.normalize"
    DISPLAY_NAME = "Normalize"
    INPUT_PORTS = (NodePort("v", "vec3", default=(0.0, 0.0, 1.0)),)
    OUTPUT_PORTS = (NodePort("out", "vec3"),)
    DEFAULT_PARAMS = {}

    def emit_wgsl(self, context, inputs=None):
        v = self._resolve(inputs, "v", "vec3<f32>(0.0, 0.0, 1.0)")
        sym = context.alloc_symbol("nrm")
        return f"let {sym} = normalize({v});"


# ---------------------------------------------------------------------------
# 11. CrossNode
# ---------------------------------------------------------------------------


class CrossNode(MaterialNode):
    NODE_TYPE = "material.cross"
    DISPLAY_NAME = "Cross"
    INPUT_PORTS = (
        NodePort("a", "vec3", default=(1.0, 0.0, 0.0)),
        NodePort("b", "vec3", default=(0.0, 1.0, 0.0)),
    )
    OUTPUT_PORTS = (NodePort("out", "vec3"),)
    DEFAULT_PARAMS = {}

    def emit_wgsl(self, context, inputs=None):
        a = self._resolve(inputs, "a", "vec3<f32>(1.0, 0.0, 0.0)")
        b = self._resolve(inputs, "b", "vec3<f32>(0.0, 1.0, 0.0)")
        sym = context.alloc_symbol("crs")
        return f"let {sym} = cross({a}, {b});"


# ---------------------------------------------------------------------------
# 12. FresnelNode
# ---------------------------------------------------------------------------


class FresnelNode(MaterialNode):
    NODE_TYPE = "material.fresnel"
    DISPLAY_NAME = "Fresnel"
    INPUT_PORTS = (
        NodePort("normal", "vec3", default=(0.0, 0.0, 1.0)),
        NodePort("view", "vec3", default=(0.0, 0.0, 1.0)),
    )
    OUTPUT_PORTS = (NodePort("out", "float"),)
    DEFAULT_PARAMS = {"strength": 1.0}

    def emit_wgsl(self, context, inputs=None):
        normal = self._resolve(inputs, "normal", "vec3<f32>(0.0, 0.0, 1.0)")
        view = self._resolve(inputs, "view", "vec3<f32>(0.0, 0.0, 1.0)")
        strength = float(self.params.get("strength", 1.0))
        sym = context.alloc_symbol("fresnel")
        return (
            f"let {sym} = pow(1.0 - clamp(dot({normal}, {view}), 0.0, 1.0), "
            f"5.0) * {strength};"
        )


# ---------------------------------------------------------------------------
# 13. PerlinNoiseNode
# ---------------------------------------------------------------------------


_PERLIN_HELPERS = """// perlin2d + hash helpers (auto-inserted once per shader)
fn _hash2(p: vec2<f32>) -> f32 {
    var p3 = fract(vec3<f32>(p.xyx) * 0.1031);
    p3 = p3 + dot(p3, p3.yzx + 33.33);
    return fract((p3.x + p3.y) * p3.z);
}
fn perlin2d(p: vec2<f32>) -> f32 {
    let pi = floor(p);
    let pf = fract(p);
    let a = _hash2(pi);
    let b = _hash2(pi + vec2<f32>(1.0, 0.0));
    let c = _hash2(pi + vec2<f32>(0.0, 1.0));
    let d = _hash2(pi + vec2<f32>(1.0, 1.0));
    let u = pf * pf * (3.0 - 2.0 * pf);
    return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
}
"""


class PerlinNoiseNode(MaterialNode):
    NODE_TYPE = "material.perlin_noise"
    DISPLAY_NAME = "Perlin Noise"
    INPUT_PORTS = (NodePort("uv", "vec2", default=(0.0, 0.0)),)
    OUTPUT_PORTS = (NodePort("out", "float"),)
    DEFAULT_PARAMS = {"frequency": 1.0, "octaves": 1}

    def emit_wgsl(self, context, inputs=None):
        uv = self._resolve(inputs, "uv", "vec2<f32>(0.0, 0.0)")
        freq = float(self.params.get("frequency", 1.0))
        octaves = max(1, int(self.params.get("octaves", 1)))
        context.used_uniforms.add("perlin2d")
        sym = context.alloc_symbol("perlin")
        acc = context.alloc_symbol("perlin_acc")
        amp = context.alloc_symbol("perlin_amp")
        f = context.alloc_symbol("perlin_f")
        return (
            f"var {acc}: f32 = 0.0;\n"
            f"var {amp}: f32 = 1.0;\n"
            f"var {f}: f32 = {freq};\n"
            f"for (var i: i32 = 0; i < {octaves}; i = i + 1) {{\n"
            f"    {acc} = {acc} + perlin2d({uv} * {f}) * {amp};\n"
            f"    {f} = {f} * 2.0;\n"
            f"    {amp} = {amp} * 0.5;\n"
            f"}}\n"
            f"let {sym} = {acc};"
        )


# ---------------------------------------------------------------------------
# 14. WorleyNoiseNode
# ---------------------------------------------------------------------------


class WorleyNoiseNode(MaterialNode):
    NODE_TYPE = "material.worley_noise"
    DISPLAY_NAME = "Worley Noise"
    INPUT_PORTS = (NodePort("uv", "vec2", default=(0.0, 0.0)),)
    OUTPUT_PORTS = (NodePort("out", "float"),)
    DEFAULT_PARAMS = {"frequency": 4.0}

    def emit_wgsl(self, context, inputs=None):
        uv = self._resolve(inputs, "uv", "vec2<f32>(0.0, 0.0)")
        freq = float(self.params.get("frequency", 4.0))
        context.used_uniforms.add("worley2d")
        sym = context.alloc_symbol("worley")
        scaled = context.alloc_symbol("worley_uv")
        cell = context.alloc_symbol("worley_cell")
        pf = context.alloc_symbol("worley_pf")
        min_d = context.alloc_symbol("worley_min")
        return (
            f"let {scaled} = {uv} * {freq};\n"
            f"let {cell} = floor({scaled});\n"
            f"let {pf} = fract({scaled});\n"
            f"var {min_d}: f32 = 1.0;\n"
            f"for (var j: i32 = -1; j <= 1; j = j + 1) {{\n"
            f"    for (var i: i32 = -1; i <= 1; i = i + 1) {{\n"
            f"        let neighbour = vec2<f32>(f32(i), f32(j));\n"
            f"        let seed = _hash2({cell} + neighbour);\n"
            f"        let feature = neighbour + vec2<f32>(seed, "
            f"fract(seed * 43.13));\n"
            f"        let d = distance({pf}, feature);\n"
            f"        {min_d} = min({min_d}, d);\n"
            f"    }}\n"
            f"}}\n"
            f"let {sym} = {min_d};"
        )


# ---------------------------------------------------------------------------
# 15. GradientRampNode
# ---------------------------------------------------------------------------


class GradientRampNode(MaterialNode):
    NODE_TYPE = "material.gradient_ramp"
    DISPLAY_NAME = "Gradient Ramp"
    INPUT_PORTS = (NodePort("t", "float", default=0.0),)
    OUTPUT_PORTS = (NodePort("out", "vec4"),)
    DEFAULT_PARAMS = {
        "stops": [
            (0.0, 0.0, 0.0, 1.0),
            (1.0, 1.0, 1.0, 1.0),
        ],
    }

    def emit_wgsl(self, context, inputs=None):
        t = self._resolve(inputs, "t", "0.0")
        stops = list(self.params.get("stops",
                                     self.DEFAULT_PARAMS["stops"]))
        if len(stops) < 2:
            # degenerate ramp — treat as a solid colour
            first = stops[0] if stops else (0.0, 0.0, 0.0, 1.0)
            r, g, b, a = first[1], first[2], first[3], 1.0
            sym = context.alloc_symbol("ramp")
            return (
                f"let {sym} = vec4<f32>({r}, {g}, {b}, {a});"
            )
        stops = sorted(stops, key=lambda s: float(s[0]))
        sym = context.alloc_symbol("ramp")
        result = context.alloc_symbol("ramp_col")
        # Nested mix() chain, one for each adjacent pair of stops.
        lines = [f"var {result}: vec4<f32> = vec4<f32>("
                 f"{stops[0][1]}, {stops[0][2]}, {stops[0][3]}, 1.0);"]
        for i in range(len(stops) - 1):
            t0 = float(stops[i][0])
            t1 = float(stops[i + 1][0])
            span = max(t1 - t0, 1e-6)
            c1 = stops[i + 1]
            lines.append(
                f"if ({t} >= {t0}) {{\n"
                f"    let local = clamp(({t} - {t0}) / {span}, 0.0, 1.0);\n"
                f"    {result} = mix({result}, "
                f"vec4<f32>({c1[1]}, {c1[2]}, {c1[3]}, 1.0), local);\n"
                f"}}"
            )
        lines.append(f"let {sym} = {result};")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# 16. TextureSampleNode
# ---------------------------------------------------------------------------


class TextureSampleNode(MaterialNode):
    NODE_TYPE = "material.texture_sample"
    DISPLAY_NAME = "Texture Sample"
    INPUT_PORTS = (
        NodePort("tex", "sampler2d", default=None),
        NodePort("uv", "vec2", default=(0.0, 0.0)),
    )
    OUTPUT_PORTS = (NodePort("out", "vec4"),)
    DEFAULT_PARAMS = {"texture": "u_texture", "sampler": "u_sampler"}

    def emit_wgsl(self, context, inputs=None):
        uv = self._resolve(inputs, "uv", "vec2<f32>(0.0, 0.0)")
        tex_name = str(self.params.get("texture", "u_texture"))
        smp_name = str(self.params.get("sampler", "u_sampler"))
        tex_expr = self._resolve(inputs, "tex", tex_name)
        # Bind the texture + sampler as required uniforms.
        context.used_uniforms.add(tex_name)
        context.used_uniforms.add(smp_name)
        sym = context.alloc_symbol("tex")
        return f"let {sym} = textureSample({tex_expr}, {smp_name}, {uv});"


# ---------------------------------------------------------------------------
# 17. UVOffsetNode
# ---------------------------------------------------------------------------


class UVOffsetNode(MaterialNode):
    NODE_TYPE = "material.uv_offset"
    DISPLAY_NAME = "UV Offset"
    INPUT_PORTS = (
        NodePort("uv", "vec2", default=(0.0, 0.0)),
        NodePort("offset", "vec2", default=(0.0, 0.0)),
    )
    OUTPUT_PORTS = (NodePort("out", "vec2"),)
    DEFAULT_PARAMS = {}

    def emit_wgsl(self, context, inputs=None):
        uv = self._resolve(inputs, "uv", "vec2<f32>(0.0, 0.0)")
        offset = self._resolve(inputs, "offset", "vec2<f32>(0.0, 0.0)")
        sym = context.alloc_symbol("uv_off")
        return f"let {sym} = {uv} + {offset};"


# ---------------------------------------------------------------------------
# 18. TimeNode
# ---------------------------------------------------------------------------


class TimeNode(MaterialNode):
    NODE_TYPE = "material.time"
    DISPLAY_NAME = "Time"
    INPUT_PORTS = ()
    OUTPUT_PORTS = (NodePort("out", "float"),)
    DEFAULT_PARAMS = {}

    def emit_wgsl(self, context, inputs=None):
        context.used_uniforms.add("u_time")
        sym = context.alloc_symbol("time")
        return f"let {sym} = u_time;"


# ---------------------------------------------------------------------------
# 19. MaterialOutputNode
# ---------------------------------------------------------------------------


class MaterialOutputNode(MaterialNode):
    NODE_TYPE = "material.output"
    DISPLAY_NAME = "Material Output"
    INPUT_PORTS = (
        NodePort("base_color", "vec3", default=(1.0, 1.0, 1.0)),
        NodePort("metallic", "float", default=0.0),
        NodePort("roughness", "float", default=0.5),
        NodePort("emissive", "vec3", default=(0.0, 0.0, 0.0)),
        NodePort("normal", "vec3", default=(0.0, 0.0, 1.0)),
    )
    OUTPUT_PORTS = ()  # graph root — no outward-facing ports
    DEFAULT_PARAMS = {}

    def emit_wgsl(self, context, inputs=None):
        base_color = self._resolve(
            inputs, "base_color", "vec3<f32>(1.0, 1.0, 1.0)")
        metallic = self._resolve(inputs, "metallic", "0.0")
        roughness = self._resolve(inputs, "roughness", "0.5")
        emissive = self._resolve(
            inputs, "emissive", "vec3<f32>(0.0, 0.0, 0.0)")
        normal = self._resolve(inputs, "normal", "vec3<f32>(0.0, 0.0, 1.0)")
        return (
            f"material_output.base_color = {base_color};\n"
            f"material_output.metallic = {metallic};\n"
            f"material_output.roughness = {roughness};\n"
            f"material_output.emissive = {emissive};\n"
            f"material_output.normal = {normal};"
        )


# ---------------------------------------------------------------------------
# Master list + registration
# ---------------------------------------------------------------------------

MATERIAL_NODE_TYPES: list[type[MaterialNode]] = [
    AddNode,
    MultiplyNode,
    LerpNode,
    SaturateNode,
    ClampNode,
    PowerNode,
    SqrtNode,
    AbsNode,
    DotNode,
    NormalizeNode,
    CrossNode,
    FresnelNode,
    PerlinNoiseNode,
    WorleyNoiseNode,
    GradientRampNode,
    TextureSampleNode,
    UVOffsetNode,
    TimeNode,
    MaterialOutputNode,
]

# Canonical category label attached to registered prototypes so a UI can
# render them under a single "Material" panel. This is a string tag,
# distinct from ``Node.kind`` (which uses the existing ``"render"``
# NodeKind so the base validator keeps working).
MATERIAL_CATEGORY = "Material"


def register_material_nodes(registry: NodeRegistry) -> list[str]:
    """Register every material-graph prototype into ``registry``.

    Each entry is stored under its ``NODE_TYPE`` key. Returns the list of
    registered ``node_type`` strings so callers can assert on the count
    without importing :data:`MATERIAL_NODE_TYPES` directly.

    Raises
    ------
    TypeError
        If ``registry`` is not a :class:`NodeRegistry`.
    ValueError
        If any material node type collides with an existing registration.
    """
    if not isinstance(registry, NodeRegistry):
        raise TypeError(
            "register_material_nodes: registry must be a NodeRegistry; "
            f"got {type(registry).__name__}"
        )
    registered: list[str] = []
    for cls in MATERIAL_NODE_TYPES:
        proto = cls()
        # Tag the prototype with its palette category — the editor UI
        # groups nodes by this key. ``params`` is the natural home
        # because the graph serialiser round-trips it for free.
        proto.params.setdefault("_category", MATERIAL_CATEGORY)
        registry.register(proto)
        registered.append(proto.node_type)
    return registered


__all__ = [
    "WgslEmitContext",
    "DefaultWgslEmitContext",
    "MaterialNode",
    "AddNode",
    "MultiplyNode",
    "LerpNode",
    "SaturateNode",
    "ClampNode",
    "PowerNode",
    "SqrtNode",
    "AbsNode",
    "DotNode",
    "NormalizeNode",
    "CrossNode",
    "FresnelNode",
    "PerlinNoiseNode",
    "WorleyNoiseNode",
    "GradientRampNode",
    "TextureSampleNode",
    "UVOffsetNode",
    "TimeNode",
    "MaterialOutputNode",
    "MATERIAL_NODE_TYPES",
    "MATERIAL_CATEGORY",
    "register_material_nodes",
]
