"""Helpers for the visual-scripting golden-file round-trip suite.

Two responsibilities:

* :func:`canonicalize_python` — parse ``source`` with :mod:`ast`, unwrap
  a single top-level ``def run(): ...`` (since the codegen emits its
  output wrapped in one), and return :func:`ast.unparse` output. This
  gives a whitespace-normalised representation the tests can compare
  irrespective of trailing newlines, indentation width, or surrounding
  function wrapper.
* :func:`load_golden` — load the ``(source, expected_yaml, output)``
  triple for a named case from ``SlapPyEngineTests/goldens/visual_scripting/``.

The tests also need a *stable* YAML serialisation of the graph produced
by :func:`python_to_graph`, but node IDs are randomly-generated uuids
(see :func:`pharos_engine.visual_scripting.node._gen_id`). To make the
graph comparable across runs, :func:`canonical_graph_yaml` renames node
IDs to positional ``n_0000``, ``n_0001``, ... slugs in insertion order,
then dumps the graph via :meth:`NodeGraph.to_yaml`.
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from .graph import NodeGraph


# Root directory holding the golden triples. Resolved relative to the
# repo layout: ``python/pharos_engine/visual_scripting/golden_utils.py``
# is 4 levels below the repo root, so we walk up and land in
# ``SlapPyEngineTests/goldens/visual_scripting``.
_GOLDENS_ROOT = (
    Path(__file__).resolve().parents[3]
    / "SlapPyEngineTests"
    / "goldens"
    / "visual_scripting"
)


def goldens_root() -> Path:
    """Return the goldens directory as a :class:`~pathlib.Path`.

    Exposed so tests / regeneration scripts don't have to import the
    private module-level constant.
    """
    return _GOLDENS_ROOT


def canonicalize_python(src: str) -> str:
    """Return a whitespace-normalised Python source string.

    Parses ``src`` with :func:`ast.parse`, unwraps a single top-level
    ``def run(): ...`` (the codegen always wraps its output in one, so
    comparing raw sources would spuriously fail on the wrapper), and
    re-emits via :func:`ast.unparse`.
    """
    if not isinstance(src, str):
        raise TypeError(
            f"canonicalize_python: src must be a str; "
            f"got {type(src).__name__}"
        )
    tree = ast.parse(src)
    if (
        len(tree.body) == 1
        and isinstance(tree.body[0], ast.FunctionDef)
        and tree.body[0].name == "run"
        and not tree.body[0].args.args
        and not tree.body[0].args.kwonlyargs
        and not tree.body[0].args.posonlyargs
    ):
        # unwrap the def run(): ... wrapper the codegen adds
        inner = ast.Module(body=tree.body[0].body, type_ignores=[])
        return ast.unparse(inner)
    return ast.unparse(tree)


def load_golden(name: str) -> tuple[str, str, str]:
    """Load the ``(source.py, expected.yaml, output.py)`` triple for ``name``.

    Raises
    ------
    FileNotFoundError
        If any of the three files is missing.
    """
    case_dir = _GOLDENS_ROOT / name
    src_path = case_dir / "source.py"
    yaml_path = case_dir / "expected.yaml"
    out_path = case_dir / "output.py"
    for p in (src_path, yaml_path, out_path):
        if not p.is_file():
            raise FileNotFoundError(
                f"load_golden({name!r}): missing golden file {p}"
            )
    source = src_path.read_text(encoding="utf-8")
    graph_yaml = yaml_path.read_text(encoding="utf-8")
    output = out_path.read_text(encoding="utf-8")
    return source, graph_yaml, output


def canonical_graph_yaml(graph: NodeGraph) -> str:
    """Serialise ``graph`` to YAML with node IDs rewritten to stable slugs.

    Node IDs are minted via ``uuid.uuid4`` (see
    :func:`pharos_engine.visual_scripting.node._gen_id`) so two runs of
    :func:`python_to_graph` on the same source produce different YAML
    even though the topology is identical. This helper walks
    ``graph.nodes`` in insertion order, assigns each node an ``n_0000``
    / ``n_0001`` / ... slug, and rewrites every edge to match. The
    resulting YAML is deterministic across runs and safe to bake as a
    golden.

    The original graph is not mutated — the rewrite operates on
    :meth:`NodeGraph.to_dict` output before it goes through
    :func:`yaml.safe_dump`.
    """
    import yaml

    id_map: dict[str, str] = {
        n.id: f"n_{i:04d}" for i, n in enumerate(graph.nodes)
    }
    data: dict[str, Any] = graph.to_dict()
    for i, node_dict in enumerate(data.get("nodes", [])):
        old = node_dict["id"]
        node_dict["id"] = id_map.get(old, old)
        # rewrite embedded node-id references inside params (branch /
        # loop bodies stash child ids under ``then_body`` / ``else_body``
        # / ``body``).
        params = node_dict.get("params", {})
        for key in ("then_body", "else_body", "body"):
            if key in params and isinstance(params[key], list):
                params[key] = [
                    id_map.get(cid, cid) for cid in params[key]
                ]
    for edge_dict in data.get("edges", []):
        edge_dict["from_node_id"] = id_map.get(
            edge_dict["from_node_id"], edge_dict["from_node_id"],
        )
        edge_dict["to_node_id"] = id_map.get(
            edge_dict["to_node_id"], edge_dict["to_node_id"],
        )
    return yaml.safe_dump(data, sort_keys=False)


__all__ = [
    "canonicalize_python",
    "canonical_graph_yaml",
    "goldens_root",
    "load_golden",
]
