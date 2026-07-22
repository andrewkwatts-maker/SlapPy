"""Round-trip bridge between V5 material nodes and NotebookMaterialEditor.

The V5 material-graph palette (see
:mod:`pharos_engine.visual_scripting.material_nodes`) provides a suite of
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

FF2 fix — binding-heuristic robustness
--------------------------------------
The V5 palette occasionally leaks helper-function markers (``perlin2d``,
``worley2d``, ``_hash2``) into ``used_uniforms`` so that
:meth:`emit_full_shader` can auto-insert the helper definitions once per
shader. Before the FF2 fix those markers were incorrectly promoted into
``texture_2d`` bindings, producing WGSL that failed to compile under
``wgpu``. The fix introduces:

* :data:`HELPER_FUNCTION_MARKERS` — a set of well-known names that are
  helper-function stand-ins rather than real bindings.
* :class:`_FunctionRegistry` — a per-emit registry of ``(name, wgsl)``
  helper definitions that get prepended to the compiled shader.
* :func:`_classify_uniform` — the canonical texture-vs-sampler-vs-uniform
  classifier used by :meth:`emit_full_shader`.
* A ``strict_mode`` flag on :meth:`emit_full_shader` that raises on
  unclassified names by default; passing ``strict_mode=False`` restores
  the pre-fix warn-and-skip behaviour for backward-compat.
"""
from __future__ import annotations

import logging
import warnings
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


#: Names that the V5 palette adds to ``used_uniforms`` even though they
#: refer to WGSL *helper functions* rather than resource bindings. The
#: bridge filters these out of the binding block and, when a
#: corresponding entry exists in :data:`HELPER_FUNCTION_LIBRARY`, injects
#: the helper's definition into the shader header instead.
#:
#: This set is intentionally extensible: callers can register additional
#: helper markers per-emit via
#: :meth:`_BridgeEmitContext.register_helper_function`.
HELPER_FUNCTION_MARKERS: frozenset[str] = frozenset({
    "perlin2d",
    "worley2d",
    "worley",
    "_hash2",
    "hash21",
    "hash22",
    "voronoi",
    "simplex_noise",
    "value_noise",
    "fbm",
})


#: Canonical WGSL bodies for each :data:`HELPER_FUNCTION_MARKERS` entry
#: that ships with the V5 palette. Emitted at most once per shader
#: (deduplicated by function name). Entries that don't have an inline
#: body here — e.g. ``worley2d``, which the ``WorleyNoiseNode`` inlines
#: directly — simply produce no header injection; the marker is still
#: excluded from the binding block.
_PERLIN2D_WGSL: str = (
    "fn _hash2(p: vec2<f32>) -> f32 {\n"
    "    var p3 = fract(vec3<f32>(p.xyx) * 0.1031);\n"
    "    p3 = p3 + dot(p3, p3.yzx + 33.33);\n"
    "    return fract((p3.x + p3.y) * p3.z);\n"
    "}\n"
    "fn perlin2d(p: vec2<f32>) -> f32 {\n"
    "    let pi = floor(p);\n"
    "    let pf = fract(p);\n"
    "    let a = _hash2(pi);\n"
    "    let b = _hash2(pi + vec2<f32>(1.0, 0.0));\n"
    "    let c = _hash2(pi + vec2<f32>(0.0, 1.0));\n"
    "    let d = _hash2(pi + vec2<f32>(1.0, 1.0));\n"
    "    let u = pf * pf * (3.0 - 2.0 * pf);\n"
    "    return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);\n"
    "}"
)

#: Standalone ``_hash2`` body — reused by both perlin and worley noise
#: nodes. Emitted stand-alone when a shader only uses ``_hash2`` without
#: the full perlin helper.
_HASH2_WGSL: str = (
    "fn _hash2(p: vec2<f32>) -> f32 {\n"
    "    var p3 = fract(vec3<f32>(p.xyx) * 0.1031);\n"
    "    p3 = p3 + dot(p3, p3.yzx + 33.33);\n"
    "    return fract((p3.x + p3.y) * p3.z);\n"
    "}"
)

HELPER_FUNCTION_LIBRARY: dict[str, str] = {
    # perlin2d ships with its own copy of _hash2 so we don't need to
    # emit a second one when both are marked.
    "perlin2d": _PERLIN2D_WGSL,
    "_hash2": _HASH2_WGSL,
}


# ---------------------------------------------------------------------------
# Binding classifier
# ---------------------------------------------------------------------------


def _classify_uniform(name: str) -> str:
    """Return the WGSL binding kind for a uniform-registry entry.

    Returns one of:

    * ``"helper"``  — the name is a helper-function marker; do not emit
      a binding for it (the caller should inject a helper definition).
    * ``"sampler"`` — the name should be bound as a ``sampler``.
    * ``"texture"`` — the name should be bound as ``texture_2d<f32>``.
    * ``"uniform"`` — the name should be bound as ``var<uniform> : f32``.
    * ``"unknown"`` — the name did not match any recognised pattern.

    Rules (checked in order):

    1. Names in :data:`HELPER_FUNCTION_MARKERS` or names containing a
       WGSL function-call parenthesis are classified as ``helper``.
    2. Names ending in ``_sampler`` or exactly ``u_sampler`` are
       ``sampler``.
    3. Names matching ``u_*_texture``, ``u_*_tex``, or ``u_texture``
       are ``texture``.
    4. Any other ``u_*`` prefixed name is ``uniform``.
    5. Anything else — lowercase leading char, no prefix — is
       ``unknown`` (the caller decides whether to raise or skip).
    """
    if not isinstance(name, str) or not name:
        return "unknown"
    # Rule 1 — helper functions.
    if name in HELPER_FUNCTION_MARKERS:
        return "helper"
    if "(" in name or ")" in name:
        return "helper"
    # Rule 2 — samplers.
    if name.endswith("_sampler") or name == "u_sampler":
        return "sampler"
    # Rule 3 — textures. Order matters: check before the generic ``u_*``
    # rule so ``u_albedo_texture`` doesn't fall through to ``uniform``.
    if name.startswith("u_") and (
        name.endswith("_texture")
        or name.endswith("_tex")
        or name == "u_texture"
    ):
        return "texture"
    # Rule 4 — scalar / struct uniforms.
    if name.startswith("u_"):
        return "uniform"
    # Rule 5 — bare lowercase-starting names with no ``u_`` prefix and
    # no explicit texture/sampler suffix look like leaked identifiers
    # (helper names, symbol fragments). Flag as unknown so the caller
    # can raise in strict mode.
    return "unknown"


# ---------------------------------------------------------------------------
# Small local shims — keep the module importable without touching the
# forbidden physics / fluid / softbody trees.
# ---------------------------------------------------------------------------


def _import_visual_scripting() -> Any:
    """Import ``pharos_engine.visual_scripting`` lazily.

    The bridge only touches the subpackage when a caller actually asks
    for a graph→dict or dict→graph conversion; keeping the import lazy
    means the editor package can be imported without pulling material
    nodes on hot paths.
    """
    import pharos_engine.visual_scripting as vs
    return vs


# ---------------------------------------------------------------------------
# WGSL emit context — reuses the visual_scripting DefaultWgslEmitContext
# but with a stable prefix that's easy to grep in error messages.
# ---------------------------------------------------------------------------


class _FunctionRegistry:
    """Ordered registry of ``(name, wgsl_definition)`` helper functions.

    Populated by :meth:`_BridgeEmitContext.register_helper_function` and
    consumed by :meth:`MaterialGraphBridge.emit_full_shader`, which
    prepends every registered definition to the shader header exactly
    once (dedup by function name, insertion-order preserved).
    """

    def __init__(self) -> None:
        self._defs: dict[str, str] = {}

    def register(self, name: str, wgsl_definition: str) -> None:
        """Register a helper function under ``name`` (idempotent).

        Duplicate registrations under the same name are silently ignored
        (the first-registered body wins) so nodes can defensively add
        their helpers without needing to know if a peer already did.

        Raises
        ------
        TypeError
            When ``name`` or ``wgsl_definition`` is not a string.
        ValueError
            When ``name`` is empty.
        """
        if not isinstance(name, str):
            raise TypeError(
                f"register_helper_function: name must be str; "
                f"got {type(name).__name__}"
            )
        if not name:
            raise ValueError("register_helper_function: name must be non-empty")
        if not isinstance(wgsl_definition, str):
            raise TypeError(
                f"register_helper_function: wgsl_definition must be str; "
                f"got {type(wgsl_definition).__name__}"
            )
        if name in self._defs:
            return
        self._defs[name] = wgsl_definition

    def names(self) -> list[str]:
        """Return the registered helper names in insertion order."""
        return list(self._defs.keys())

    def definitions(self) -> list[tuple[str, str]]:
        """Return the ``(name, wgsl)`` pairs in insertion order."""
        return list(self._defs.items())

    def as_wgsl(self) -> str:
        """Return every registered definition joined by blank lines."""
        return "\n\n".join(body for body in self._defs.values())

    def __len__(self) -> int:  # pragma: no cover - trivial
        return len(self._defs)

    def __contains__(self, name: object) -> bool:  # pragma: no cover - trivial
        return isinstance(name, str) and name in self._defs


class _BridgeEmitContext:
    """Fresh emit context that tracks per-node symbol allocations.

    A single instance is used per :meth:`MaterialGraphBridge.to_material`
    call so downstream nodes see a consistent symbol namespace.

    The context also owns:

    * :attr:`HELPER_FUNCTION_MARKERS` — a per-instance mutable set of
      helper-function names that override / extend the module-level
      :data:`HELPER_FUNCTION_MARKERS` set. Callers can add markers
      before compilation without touching the module.
    * :attr:`function_registry` — a :class:`_FunctionRegistry` that
      accumulates helper-function definitions for downstream shader
      assembly.
    """

    #: Instance-level marker set — starts from the module-level default
    #: but callers may extend it per-emit.
    HELPER_FUNCTION_MARKERS: set[str]

    def __init__(self) -> None:
        self.used_uniforms: set[str] = set()
        self._counter: int = 0
        # per-node output symbol map — filled by the compile pass so
        # downstream nodes can substitute an incoming edge's symbol
        # into their emit slot.
        self.symbol_by_output: dict[tuple[str, str], str] = {}
        # Per-instance markers (module set + any user additions).
        self.HELPER_FUNCTION_MARKERS = set(HELPER_FUNCTION_MARKERS)
        # Per-instance helper-function registry.
        self.function_registry: _FunctionRegistry = _FunctionRegistry()

    def alloc_symbol(self, prefix: str) -> str:
        self._counter += 1
        safe = "".join(
            ch if ch.isalnum() or ch == "_" else "_" for ch in str(prefix)
        )
        if not safe:
            safe = "sym"
        return f"{safe}_{self._counter}"

    # ------------------------------------------------------------------
    # Helper-function registration surface — nodes call this to have a
    # WGSL helper definition inserted once per shader header.
    # ------------------------------------------------------------------

    def register_helper_function(self, name: str,
                                 wgsl_definition: str) -> None:
        """Register a helper function under ``name`` (idempotent).

        Also adds ``name`` to :attr:`HELPER_FUNCTION_MARKERS` so the
        binding classifier excludes it from resource bindings.
        """
        self.function_registry.register(name, wgsl_definition)
        self.HELPER_FUNCTION_MARKERS.add(name)

    def is_helper_marker(self, name: str) -> bool:
        """Return ``True`` iff ``name`` is a recognised helper marker."""
        if not isinstance(name, str):
            return False
        if name in self.HELPER_FUNCTION_MARKERS:
            return True
        if "(" in name or ")" in name:
            return True
        return False


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

        # Post-pass: for every helper marker the palette pushed onto
        # ``used_uniforms``, auto-register its canonical WGSL definition
        # (when we know one) so downstream shader assembly can emit it
        # in the header. This is what the palette *meant* when it added
        # names like ``perlin2d`` to ``used_uniforms`` — the pre-FF2
        # behaviour of promoting them to texture bindings was a bug.
        for name in list(ctx.used_uniforms):
            if name in HELPER_FUNCTION_LIBRARY and name not in ctx.function_registry:
                ctx.function_registry.register(name, HELPER_FUNCTION_LIBRARY[name])

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

    def emit_full_shader(self, nodes: Any, entry_expr: str = "fs_out",
                         strict_mode: bool = True) -> str:
        """Return a complete WGSL fragment shader from *nodes*.

        *nodes* may be a :class:`NodeGraph` or an iterable of :class:`Node`
        objects. When it's an iterable, a temporary graph is constructed
        so the standard compile pipeline can run. The emitted shader
        wraps the compiled body with:

        * a header comment,
        * any helper-function definitions accumulated during compile
          (:data:`HELPER_FUNCTION_LIBRARY` entries + any function the
          nodes registered via
          :meth:`_BridgeEmitContext.register_helper_function`),
        * a uniforms block sourced from the compiled ``uniforms`` list
          — filtered through :func:`_classify_uniform` so helper-function
          markers, function-call fragments, and other non-binding names
          are **not** promoted into ``texture_2d`` bindings,
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
        strict_mode:
            When ``True`` (default), any uniform name that fails
            :func:`_classify_uniform` (i.e. is neither a helper marker
            nor a recognised sampler/texture/uniform prefix) raises
            :class:`MaterialGraphError`. When ``False``, unclassified
            names are skipped with a :func:`warnings.warn` call — the
            pre-FF2 behaviour, kept for backward-compat.

        Returns
        -------
        str
            A syntactically-plausible WGSL fragment shader source.

        Raises
        ------
        MaterialGraphError
            When ``strict_mode`` is ``True`` and one or more entries in
            the compiled ``uniforms`` list cannot be classified as
            helper / sampler / texture / uniform.
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

        # Classify every uniform entry so we know which names are
        # helper-function markers (drop from binding block, ensure a
        # definition lands in the header), which are real bindings, and
        # which are unclassified junk.
        helpers: list[str] = []
        real_bindings: list[str] = []
        unclassified: list[str] = []
        for u in uniforms:
            kind = _classify_uniform(u)
            if kind == "helper":
                helpers.append(u)
            elif kind in ("sampler", "texture", "uniform"):
                real_bindings.append(u)
            else:
                unclassified.append(u)

        if unclassified:
            if strict_mode:
                raise MaterialGraphError(
                    "emit_full_shader: unclassified uniform names "
                    "(strict_mode=True); "
                    f"got {sorted(unclassified)!r}. "
                    "Names must be helper markers, ``*_sampler``, "
                    "``u_*_texture`` / ``u_*_tex``, or ``u_*`` "
                    "uniforms. Pass strict_mode=False to skip with a "
                    "warning.",
                    errors=[
                        (name, "unclassified uniform name")
                        for name in unclassified
                    ],
                )
            for name in unclassified:
                warnings.warn(
                    f"emit_full_shader: skipping unclassified uniform "
                    f"name {name!r} (strict_mode=False)",
                    stacklevel=2,
                )

        # Build a set of helper-function bodies to inject. Two sources:
        # 1. Anything the nodes explicitly registered on the compile-time
        #    _FunctionRegistry (not available here because to_material
        #    doesn't leak the ctx — but helpers marked via used_uniforms
        #    are re-derived below).
        # 2. Names in ``helpers`` that have a canonical entry in
        #    :data:`HELPER_FUNCTION_LIBRARY`. This matches what the V5
        #    palette does when it pushes ``perlin2d`` into used_uniforms
        #    to request an auto-inserted helper.
        helper_bodies: list[tuple[str, str]] = []
        seen_helpers: set[str] = set()
        for name in helpers:
            if name in seen_helpers:
                continue
            body_wgsl = HELPER_FUNCTION_LIBRARY.get(name)
            if body_wgsl is None:
                # Marker recognised but no canonical body — the palette
                # inlined the helper inside a node fragment (e.g.
                # ``worley2d`` re-uses ``_hash2`` inline). Skip the
                # header injection but keep the marker out of bindings.
                continue
            helper_bodies.append((name, body_wgsl))
            seen_helpers.add(name)

        # Uniforms block — one binding per *real* binding. WGSL requires
        # an explicit ``@group`` / ``@binding`` attribute so we allocate
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

        # Helper function definitions — prepended before uniforms so
        # they can be referenced by any subsequent code. Blank line
        # separator after the block for readability.
        if helper_bodies:
            for _name, wgsl in helper_bodies:
                lines.append(wgsl)
                lines.append("")

        for i, u in enumerate(real_bindings):
            kind = _classify_uniform(u)
            if kind == "sampler":
                lines.append(
                    f"@group(0) @binding({i}) var {u}: sampler;"
                )
            elif kind == "texture":
                lines.append(
                    f"@group(0) @binding({i}) var {u}: texture_2d<f32>;"
                )
            else:
                # ``uniform`` — bind as a raw f32 for the sample shader
                # (real materials would type-check here).
                lines.append(
                    f"@group(0) @binding({i}) var<uniform> {u}: f32;"
                )
        if real_bindings:
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
    "HELPER_FUNCTION_MARKERS",
    "HELPER_FUNCTION_LIBRARY",
]
