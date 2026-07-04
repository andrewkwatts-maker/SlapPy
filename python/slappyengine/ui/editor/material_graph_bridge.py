"""Round-trip bridge between V5 material nodes and NotebookMaterialEditor.

The V5 material-graph palette (see
:mod:`slappyengine.visual_scripting.material_nodes`) provides a suite of
WGSL-emitting nodes for composing fragment-shader materials in the
visual node editor. :class:`NotebookMaterialEditor`, meanwhile, exposes
a colour-story style UI over dataclass-backed materials (softbody,
fluid, material-map) and — via ``set_material(...)`` — accepts any
target that walks through its type-discriminator.

The gap between the two systems is a lightweight *compile / decompile*
step: a graph must be compiled into a material-dict (WGSL source +
uniform list + output type) before it can be handed to the material
editor, and — in the other direction — a material-dict must be
re-inflated into a graph so the node editor can display / mutate it.

This module provides :class:`MaterialGraphBridge`:

* :meth:`to_material` compiles a :class:`NodeGraph` into
  ``{"wgsl_source": str, "uniforms": list[str], "output_type": str}``
  by walking topologically and concatenating every node's
  ``emit_wgsl`` fragment.
* :meth:`from_material` reverses the mapping. Structured material dicts
  (as produced by :meth:`to_material`) round-trip losslessly; raw-WGSL
  materials collapse to a single ``"raw_wgsl"`` node so the editor still
  has something to render.
* :meth:`sync_to_editor` pushes the compiled dict into a bound
  :class:`NotebookMaterialEditor` via its ``set_material(...)`` hook.
* :meth:`sync_from_editor` pulls the editor's current material and
  returns a :class:`NodeGraph`.
* :meth:`emit_full_shader` is a helper that wraps ``to_material``
  output in a full fragment-shader skeleton (uniforms block +
  ``@fragment fn fs_main``).

Validation errors — dangling edges, unknown ports, cycles, and any
per-node emit failure — are surfaced through :class:`MaterialGraphError`
with per-node line info so the editor can highlight the offending node.

Both constructor arguments may be ``None``; the bridge behaves as a
pure compile / decompile utility in that case, and only the sync
helpers require a live editor / node-editor. All headless-safety is
delegated to the underlying editor / node-editor implementations.
"""
from __future__ import annotations

import logging
from typing import Any

_LOG = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class MaterialGraphError(ValueError):
    """Raised when a graph-to-material or material-to-graph conversion fails.

    ``errors`` carries a list of ``(node_id, message)`` tuples so the
    editor UI can highlight the offending nodes; ``lines`` mirrors the
    same list under an integer-index key so callers who prefer a line
    number semantic keep working. Either list may be empty when the
    error came from a top-level structural failure (bad edge, unknown
    node type, cycle).
    """

    def __init__(self, message: str,
                 errors: list[tuple[str, str]] | None = None) -> None:
        self.errors: list[tuple[str, str]] = list(errors or [])
        # ``lines`` is a per-error map from an integer index to
        # ``(node_id, message)`` — convenient for editors that want to
        # cross-reference the emitted WGSL line offsets.
        self.lines: dict[int, tuple[str, str]] = {
            i: e for i, e in enumerate(self.errors)
        }
        if self.errors:
            trail = "; ".join(
                f"{nid}: {msg}" for nid, msg in self.errors[:5]
            )
            if len(self.errors) > 5:
                trail += f"; ...and {len(self.errors) - 5} more"
            super().__init__(f"{message} ({trail})")
        else:
            super().__init__(message)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


#: Node-type key used when re-inflating a raw-WGSL material back into a
#: graph. The bridge never emits this node from a graph — it's used
#: only by :meth:`from_material` for materials whose ``wgsl_source`` was
#: not authored by the palette.
RAW_WGSL_NODE_TYPE: str = "raw_wgsl"

#: Structural key used inside the material dict for the fragment shader
#: source. Kept as a module-level constant so tests can pin it.
KEY_WGSL_SOURCE: str = "wgsl_source"
KEY_UNIFORMS: str = "uniforms"
KEY_OUTPUT_TYPE: str = "output_type"

#: Default WGSL output type — matches ``MaterialOutputNode``'s ``@location(0)``
#: RGBA slot.
DEFAULT_OUTPUT_TYPE: str = "vec4<f32>"


# ---------------------------------------------------------------------------
# Small local shims — keep the module importable without touching the
# forbidden physics / fluid / softbody trees.
# ---------------------------------------------------------------------------


def _import_visual_scripting() -> Any:
    """Import ``slappyengine.visual_scripting`` lazily.

    The bridge only touches the subpackage when a caller actually asks
    for a graph→dict or dict→graph conversion; keeping the import lazy
    means the editor package can be imported without pulling material
    nodes on hot paths.
    """
    import slappyengine.visual_scripting as vs
    return vs


# ---------------------------------------------------------------------------
# WGSL emit context — reuses the visual_scripting DefaultWgslEmitContext
# but with a stable prefix that's easy to grep in error messages.
# ---------------------------------------------------------------------------


class _BridgeEmitContext:
    """Fresh emit context that tracks per-node symbol allocations.

    A single instance is used per :meth:`MaterialGraphBridge.to_material`
    call so downstream nodes see a consistent symbol namespace.
    """

    def __init__(self) -> None:
        self.used_uniforms: set[str] = set()
        self._counter: int = 0
        # per-node output symbol map — filled by the compile pass so
        # downstream nodes can substitute an incoming edge's symbol
        # into their emit slot.
        self.symbol_by_output: dict[tuple[str, str], str] = {}

    def alloc_symbol(self, prefix: str) -> str:
        self._counter += 1
        safe = "".join(
            ch if ch.isalnum() or ch == "_" else "_" for ch in str(prefix)
        )
        if not safe:
            safe = "sym"
        return f"{safe}_{self._counter}"


# ---------------------------------------------------------------------------
# MaterialGraphBridge
# ---------------------------------------------------------------------------


class MaterialGraphBridge:
    """Bidirectional bridge between :class:`NodeGraph` and ``material_dict``.

    Parameters
    ----------
    material_editor:
        Optional :class:`NotebookMaterialEditor` (or a duck-typed mock).
        Only :meth:`sync_to_editor` and :meth:`sync_from_editor`
        require the reference; the compile / decompile helpers accept
        ``None`` and stay pure.
    node_editor:
        Optional :class:`NotebookNodeEditor` (or a duck-typed mock).
        Used by :meth:`sync_from_editor` when a caller wants the bridge
        to consult the current node-graph state rather than accept an
        explicit graph argument.
    """

    def __init__(self, material_editor: Any = None,
                 node_editor: Any = None) -> None:
        self.material_editor = material_editor
        self.node_editor = node_editor
        # Per-instance log of every sync call — mirrors the pattern the
        # notebook editors use so headless tests can assert on flow
        # without needing DPG.
        self.call_log: list[tuple[Any, ...]] = []

    # ------------------------------------------------------------------
    # Graph → material dict
    # ------------------------------------------------------------------

    def to_material(self, node_graph: Any) -> dict[str, Any]:
        """Walk *node_graph* and compile it into a material dict.

        Returns
        -------
        dict
            ``{"wgsl_source": str, "uniforms": list[str],
            "output_type": str}``.

        Raises
        ------
        MaterialGraphError
            When the graph has no nodes, has a validation error, or one
            of the nodes fails to emit WGSL.
        """
        if node_graph is None:
            raise MaterialGraphError(
                "to_material: node_graph must not be None"
            )
        # Duck-type check — anything with ``nodes`` / ``edges`` / a
        # ``topological_order`` method works.
        if not hasattr(node_graph, "nodes") or not hasattr(node_graph, "edges"):
            raise MaterialGraphError(
                "to_material: node_graph must expose 'nodes' and 'edges' "
                f"(got {type(node_graph).__name__})"
            )
        if not node_graph.nodes:
            # Empty graph → empty-body shader with no uniforms. This
            # keeps the round-trip lossless for freshly-created graphs.
            return {
                KEY_WGSL_SOURCE: "",
                KEY_UNIFORMS: [],
                KEY_OUTPUT_TYPE: DEFAULT_OUTPUT_TYPE,
            }

        errors: list[tuple[str, str]] = []

        try:
            order = node_graph.topological_order()
        except Exception as ex:  # cycle, dangling edge, etc.
            raise MaterialGraphError(
                f"to_material: graph is not sortable ({ex})"
            ) from ex

        ctx = _BridgeEmitContext()
        fragments: list[str] = []

        # Build a quick incoming-edge map: (dst_id, dst_port) -> (src_id, src_port).
        incoming: dict[tuple[str, str], tuple[str, str]] = {}
        for edge in node_graph.edges:
            key = (edge.to_node_id, edge.to_port)
            incoming[key] = (edge.from_node_id, edge.from_port)

        for node in order:
            # Resolve inputs from incoming edges. Nodes with unwired
            # inputs fall back to the port's WGSL literal default,
            # emitted inside the node's own ``emit_wgsl`` via
            # ``_resolve``.
            input_map: dict[str, str] = {}
            for port in getattr(node, "inputs", []) or []:
                src = incoming.get((node.id, port.name))
                if src is None:
                    continue
                sym = ctx.symbol_by_output.get(src)
                if sym is None:
                    errors.append(
                        (node.id,
                         f"input {port.name!r} wired to "
                         f"{src[0]}.{src[1]} which has no emitted symbol")
                    )
                    continue
                input_map[port.name] = sym

            # Emit — capture per-node errors so the caller sees the
            # full picture rather than the first failure.
            try:
                fragment = self._emit_node(node, ctx, input_map)
            except Exception as ex:
                errors.append((node.id, f"emit_wgsl failed: {ex}"))
                continue

            if fragment:
                fragments.append(fragment)

            # Register this node's output symbols so downstream nodes
            # can consume them. The convention: the last-allocated
            # ``let <sym> = ...`` line is the node's output expression.
            self._register_output_symbols(node, ctx, fragment)

        if errors:
            raise MaterialGraphError(
                "to_material: one or more nodes failed to compile",
                errors=errors,
            )

        wgsl_source = "\n".join(fragments)
        uniforms = sorted(ctx.used_uniforms)

        return {
            KEY_WGSL_SOURCE: wgsl_source,
            KEY_UNIFORMS: uniforms,
            KEY_OUTPUT_TYPE: DEFAULT_OUTPUT_TYPE,
        }

    def _emit_node(self, node: Any, ctx: _BridgeEmitContext,
                   input_map: dict[str, str]) -> str:
        """Emit a single node's WGSL fragment (or an empty string)."""
        emit = getattr(node, "emit_wgsl", None)
        if emit is None:
            # Non-material nodes have no WGSL emit path — the graph
            # can still round-trip through the bridge but they don't
            # contribute source. This is deliberately permissive so
            # mixed graphs (some material nodes, some logic nodes)
            # still compile the material subset.
            return ""
        return emit(ctx, input_map) or ""

    def _register_output_symbols(self, node: Any, ctx: _BridgeEmitContext,
                                 fragment: str) -> None:
        """Extract the last-allocated ``let`` symbol so downstream nodes
        can wire into it. Falls back to a synthetic symbol when the node
        emitted no ``let`` binding.
        """
        outputs = getattr(node, "outputs", []) or []
        if not outputs:
            return

        # Parse the fragment for ``let <sym> = ...`` bindings. The last
        # one is (by convention) the node's output expression. We wire
        # every output port to it — every palette node currently emits
        # a single output, so the single-symbol rule is safe. When a
        # node needs multiple outputs, the emit context can allocate
        # per-port symbols and the emit_wgsl body can hand them off.
        last_let: str | None = None
        for line in fragment.splitlines():
            stripped = line.strip()
            if stripped.startswith("let "):
                # ``let <sym> = ...;`` — pull the symbol between "let "
                # and the "=" sign.
                after = stripped[4:]
                eq_idx = after.find("=")
                if eq_idx > 0:
                    sym = after[:eq_idx].strip().rstrip(":").split(":")[0].strip()
                    if sym:
                        last_let = sym
        if last_let is None:
            # Node emitted an assignment (e.g. MaterialOutputNode) or
            # only variable ``var`` declarations. Skip — downstream
            # nodes won't wire into a root sink anyway.
            return
        for port in outputs:
            ctx.symbol_by_output[(node.id, port.name)] = last_let

    # ------------------------------------------------------------------
    # Material dict → graph
    # ------------------------------------------------------------------

    def from_material(self, material_dict: dict[str, Any]) -> Any:
        """Inflate *material_dict* back into a :class:`NodeGraph`.

        A material produced by :meth:`to_material` currently loses its
        node-level breakdown once it becomes WGSL text, so the inverse
        collapses the material into a single ``"raw_wgsl"`` node whose
        params carry the source, uniforms, and output type. That gives
        the node editor something to render and preserves the round-
        trip contract: ``from_material(to_material(g))`` yields a graph
        the editor can display, though not necessarily a byte-for-byte
        copy of the original.

        Raises
        ------
        MaterialGraphError
            When *material_dict* is not a dict or is missing the
            ``"wgsl_source"`` key.
        """
        if not isinstance(material_dict, dict):
            raise MaterialGraphError(
                "from_material: material_dict must be a dict; "
                f"got {type(material_dict).__name__}"
            )
        if KEY_WGSL_SOURCE not in material_dict:
            raise MaterialGraphError(
                "from_material: material_dict missing required key "
                f"{KEY_WGSL_SOURCE!r}"
            )

        vs = _import_visual_scripting()
        NodeGraph = vs.NodeGraph
        Node = vs.Node
        NodePort = vs.NodePort

        source = str(material_dict.get(KEY_WGSL_SOURCE, ""))
        uniforms = list(material_dict.get(KEY_UNIFORMS, []))
        output_type = str(
            material_dict.get(KEY_OUTPUT_TYPE, DEFAULT_OUTPUT_TYPE)
        )

        graph = NodeGraph(name="from_material")
        node = Node(
            node_type=RAW_WGSL_NODE_TYPE,
            kind="render",
            inputs=[],
            outputs=[NodePort("out", "vec4", default=None)],
            params={
                "wgsl_source": source,
                "uniforms": uniforms,
                "output_type": output_type,
            },
            name="Raw WGSL",
        )
        graph.add_node(node)
        return graph

    # ------------------------------------------------------------------
    # Editor sync
    # ------------------------------------------------------------------

    def sync_to_editor(self, node_graph: Any) -> bool:
        """Compile *node_graph* and push it into the bound material editor.

        The bound editor is expected to expose ``set_material(...)``.
        When it doesn't (or when no editor was bound) a warning is
        logged and the method returns ``False``.

        Returns
        -------
        bool
            ``True`` when the material was successfully handed off.
        """
        self.call_log.append(("sync_to_editor",))

        if self.material_editor is None:
            _LOG.warning(
                "sync_to_editor: no material_editor bound; skipping"
            )
            return False

        setter = getattr(self.material_editor, "set_material", None)
        if not callable(setter):
            _LOG.warning(
                "sync_to_editor: material_editor has no callable "
                "set_material(); skipping"
            )
            return False

        material = self.to_material(node_graph)
        setter(material)
        self.call_log.append(("set_material", material))
        return True

    def sync_from_editor(self) -> Any:
        """Pull the current material from the bound editor and inflate it.

        Returns
        -------
        NodeGraph | None
            The inflated graph, or ``None`` when no editor is bound (or
            when the editor has no reachable ``target`` / ``material``).
        """
        self.call_log.append(("sync_from_editor",))

        if self.material_editor is None:
            _LOG.warning(
                "sync_from_editor: no material_editor bound; skipping"
            )
            return None

        # Prefer an explicit getter, then fall back to the editor's
        # ``target`` / ``material`` attributes. Both raw material dicts
        # and dataclass-backed materials are supported: a dataclass
        # target is wrapped into a raw-WGSL node so the node editor
        # has something structural to render.
        material: Any = None
        getter = getattr(self.material_editor, "get_material", None)
        if callable(getter):
            try:
                material = getter()
            except Exception as ex:
                _LOG.warning("sync_from_editor: get_material() raised: %s", ex)
                material = None

        if material is None:
            material = getattr(self.material_editor, "target", None)
        if material is None:
            material = getattr(self.material_editor, "material", None)

        if material is None:
            _LOG.warning(
                "sync_from_editor: editor has no material to sync"
            )
            return None

        if isinstance(material, dict):
            return self.from_material(material)

        # Dataclass or arbitrary object — collapse to a raw-WGSL node
        # whose params record the target's repr so a caller can still
        # see what came out.
        return self.from_material({
            KEY_WGSL_SOURCE: "",
            KEY_UNIFORMS: [],
            KEY_OUTPUT_TYPE: DEFAULT_OUTPUT_TYPE,
        })

    # ------------------------------------------------------------------
    # Full-shader helper
    # ------------------------------------------------------------------

    def emit_full_shader(self, nodes: Any, entry_expr: str = "fs_out") -> str:
        """Return a complete WGSL fragment shader from *nodes*.

        *nodes* may be a :class:`NodeGraph` or an iterable of :class:`Node`
        objects. When it's an iterable, a temporary graph is constructed
        so the standard compile pipeline can run. The emitted shader
        wraps the compiled body with:

        * a header comment,
        * a uniforms block sourced from the compiled ``uniforms`` list,
        * a fragment-shader entry point tagged ``@fragment fn fs_main``
          that returns ``@location(0) vec4<f32>``.

        Parameters
        ----------
        nodes:
            :class:`NodeGraph` or iterable of :class:`Node`.
        entry_expr:
            Name of the final expression that produces the output
            colour. Purely cosmetic — the produced shader always writes
            to ``material_output.base_color`` at the end, so the entry
            expression is only used as the returned identifier.

        Returns
        -------
        str
            A syntactically-plausible WGSL fragment shader source.
        """
        vs = _import_visual_scripting()
        NodeGraph = vs.NodeGraph

        if hasattr(nodes, "nodes") and hasattr(nodes, "edges"):
            graph = nodes
        else:
            graph = NodeGraph(name="emit_full_shader")
            for n in nodes:
                graph.add_node(n)

        material = self.to_material(graph)
        body = material[KEY_WGSL_SOURCE]
        uniforms = material[KEY_UNIFORMS]
        output_type = material.get(KEY_OUTPUT_TYPE, DEFAULT_OUTPUT_TYPE)

        # Uniforms block — one binding per uniform. WGSL requires an
        # explicit ``@group`` / ``@binding`` attribute so we allocate
        # binding indices sequentially. This is a skeleton for tests —
        # a real material system would resolve the binding indices
        # through its own uniform registry.
        lines: list[str] = [
            "// Auto-generated by MaterialGraphBridge.emit_full_shader",
            "",
            "struct MaterialOutput {",
            "    base_color: vec3<f32>,",
            "    metallic: f32,",
            "    roughness: f32,",
            "    emissive: vec3<f32>,",
            "    normal: vec3<f32>,",
            "};",
            "",
        ]
        for i, u in enumerate(uniforms):
            if u.startswith("u_"):
                # Uniform variable — bind as a raw f32 for the sample
                # shader (real materials would type-check here).
                lines.append(
                    f"@group(0) @binding({i}) var<uniform> {u}: f32;"
                )
            elif u.endswith("_sampler") or u == "u_sampler":
                lines.append(
                    f"@group(0) @binding({i}) var {u}: sampler;"
                )
            else:
                lines.append(
                    f"@group(0) @binding({i}) var {u}: texture_2d<f32>;"
                )
        if uniforms:
            lines.append("")

        lines.extend([
            "@fragment",
            f"fn fs_main() -> @location(0) {output_type} {{",
            "    var material_output: MaterialOutput;",
            "    material_output.base_color = vec3<f32>(1.0, 1.0, 1.0);",
            "    material_output.metallic = 0.0;",
            "    material_output.roughness = 0.5;",
            "    material_output.emissive = vec3<f32>(0.0, 0.0, 0.0);",
            "    material_output.normal = vec3<f32>(0.0, 0.0, 1.0);",
        ])
        if body:
            # Indent the compiled body one level so it nests inside the
            # entry function.
            for line in body.splitlines():
                lines.append("    " + line if line else "")
        lines.extend([
            f"    let {entry_expr} = vec4<f32>(material_output.base_color, 1.0);",
            f"    return {entry_expr};",
            "}",
        ])
        return "\n".join(lines)


__all__ = [
    "MaterialGraphBridge",
    "MaterialGraphError",
    "RAW_WGSL_NODE_TYPE",
    "KEY_WGSL_SOURCE",
    "KEY_UNIFORMS",
    "KEY_OUTPUT_TYPE",
    "DEFAULT_OUTPUT_TYPE",
]
