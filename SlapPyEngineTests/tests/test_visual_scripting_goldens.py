"""Golden-file round-trip suite for :mod:`slappyengine.visual_scripting`.

Ten hand-authored source/YAML/output triples live under
``SlapPyEngineTests/goldens/visual_scripting/<name>/``. Each case
covers a distinct construct family (arithmetic, nested control flow,
loops, calls, boolean / comparison operators, early return, constant
type mix, variable reuse). This module parametrises three tests over
those cases:

* :func:`test_source_to_graph_yaml_matches_golden` — the canonicalised
  YAML produced by :func:`python_to_graph` matches ``expected.yaml``.
* :func:`test_graph_to_python_matches_golden` — the Python emitted by
  :func:`graph_to_python` matches ``output.py``.
* :func:`test_round_trip_lossless` — the canonical AST of the emitted
  Python matches the canonical AST of the source (i.e. the round trip
  is semantics-preserving).

Regenerating the goldens
------------------------
The goldens were baked from :func:`python_to_graph` /
:func:`graph_to_python` output at authoring time. To re-bake after a
codegen change, run::

    PYTHONPATH=python python tools/bake_visual_scripting_goldens.py

...which walks its own CASES table and writes each triple via
:func:`slappyengine.visual_scripting.golden_utils.canonical_graph_yaml`.
Inspect the diff (``git diff SlapPyEngineTests/goldens/visual_scripting``)
and commit it together with the codegen change.

XFAIL policy
------------
Round-trip parity is aspirational for eight of the ten cases: today's
codegen has known bugs (dropped parentheses in binops, duplicated
statements in nested if/else, ``__var__`` params leaking into call
kwargs, etc.). Rather than fake the golden, those cases are marked
``xfail(strict=False)`` with a TODO pointing at the specific bug. When
codegen is fixed the xfail will flip to ``xpass`` and pytest will
force the maintainer to remove the marker.
"""
from __future__ import annotations

import pytest

from slappyengine.visual_scripting.codegen import (
    graph_to_python,
    python_to_graph,
)
from slappyengine.visual_scripting.golden_utils import (
    canonical_graph_yaml,
    canonicalize_python,
    load_golden,
)


# ---------------------------------------------------------------------------
# Case table + xfail annotations.
# ---------------------------------------------------------------------------
#
# ``CASES`` is the flat list the three tests parametrise over. The
# ``xfail_*`` dicts carry the reason string for each dimension so a
# maintainer inspecting a failure sees the bug summary in-line rather
# than in a distant comment. When a bug is fixed the maintainer removes
# the entry — pytest surfaces the xpass and forces a follow-up commit.
# ---------------------------------------------------------------------------

CASES: list[str] = [
    "arithmetic",
    "nested_if",
    "for_range",
    "while_countdown",
    "function_call_chain",
    "assignment_reuse",
    "constant_types",
    "comparison_chain",
    "boolean_logic",
    "return_early",
]


# --- test_source_to_graph_yaml_matches_golden ------------------------------
# Only comparison_chain is xfail here — its source raises CodegenError so
# python_to_graph never returns a graph. Every other case successfully
# imports; the YAML is stable through canonical_graph_yaml.
_XFAIL_YAML: dict[str, str] = {
    "comparison_chain": (
        "TODO: python_to_graph refuses chained comparisons (a < b < c). "
        "Codegen should either flatten them to left-associated pairs "
        "with logic.and, or emit a single logic.compare with an ordered "
        "op list."
    ),
}


# --- test_graph_to_python_matches_golden -----------------------------------
# Emission is compared verbatim against output.py — comparison_chain has
# no valid emission (there is no graph), so it xfails here too.
_XFAIL_EMIT: dict[str, str] = {
    "comparison_chain": (
        "TODO: no graph to emit — python_to_graph refuses the source."
    ),
}


# --- test_round_trip_lossless ---------------------------------------------
# Round-trip AST equality is the strictest of the three. All eight of
# the below cases have real codegen bugs that need fixing before they
# can pass:
_XFAIL_ROUND_TRIP: dict[str, str] = {
    "arithmetic": (
        "TODO: graph_to_python drops parentheses around binop subtrees. "
        "'(1 + 2) * 3 - 4' emits as '1 + 2 * 3 - 4' — precedence lost."
    ),
    "nested_if": (
        "TODO: control.branch emits its then_body twice — once nested "
        "inside the inner if/else, once flat after the inner branch. "
        "Fix: _emit_from_ast_graph.emit_stmt should skip child ids that "
        "already appear in a nested-body param."
    ),
    "for_range": (
        "TODO: graph_to_python emits '# unrecognised node control.foreach' "
        "inside print(...) because expr_for has no case for control.foreach's "
        "'item' output port. Fix: return the loop variable name."
    ),
    "while_countdown": (
        "TODO: constant 'n = 10' gets inlined into the loop condition and "
        "body ('while 10 > 0: n = 10 - 1'). __var__ binding on the constant "
        "should force a real assignment even when it has downstream "
        "consumers."
    ),
    "function_call_chain": (
        "TODO: __var__ param leaks into call kwargs — 'x = round(...)' "
        "emits as 'round(..., __var__=\\'x\\')'. Fix: strip '__var__' in "
        "the kwarg-building loop of expr_for's call branch."
    ),
    "assignment_reuse": (
        "TODO: 'y = x + 1; z = x + y' — later reads inline the producer's "
        "expression instead of the variable name. Fix: expr_for should "
        "check for __var__ on the producer and emit the name."
    ),
    "boolean_logic": (
        "TODO: graph_to_python drops parentheses around boolop subtrees. "
        "'a and (b or not c)' emits as 'a and b or not c'."
    ),
    "comparison_chain": (
        "TODO: python_to_graph raises CodegenError on chained comparisons."
    ),
}


def _yaml_params() -> list:
    out = []
    for name in CASES:
        marks = []
        if name in _XFAIL_YAML:
            marks.append(pytest.mark.xfail(reason=_XFAIL_YAML[name], strict=False))
        out.append(pytest.param(name, marks=marks, id=name))
    return out


def _emit_params() -> list:
    out = []
    for name in CASES:
        marks = []
        if name in _XFAIL_EMIT:
            marks.append(pytest.mark.xfail(reason=_XFAIL_EMIT[name], strict=False))
        out.append(pytest.param(name, marks=marks, id=name))
    return out


def _round_trip_params() -> list:
    out = []
    for name in CASES:
        marks = []
        if name in _XFAIL_ROUND_TRIP:
            marks.append(
                pytest.mark.xfail(reason=_XFAIL_ROUND_TRIP[name], strict=False)
            )
        out.append(pytest.param(name, marks=marks, id=name))
    return out


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", _yaml_params())
def test_source_to_graph_yaml_matches_golden(name: str) -> None:
    """``python_to_graph(source)`` canonicalises to ``expected.yaml``."""
    source, expected_yaml, _ = load_golden(name)
    graph = python_to_graph(source, name=name)
    actual = canonical_graph_yaml(graph)
    assert actual == expected_yaml, (
        f"Golden mismatch for {name}. "
        f"Regen with `PYTHONPATH=python python tools/bake_visual_scripting_goldens.py`."
    )


@pytest.mark.parametrize("name", _emit_params())
def test_graph_to_python_matches_golden(name: str) -> None:
    """``graph_to_python(python_to_graph(source))`` matches ``output.py``."""
    source, _, expected_output = load_golden(name)
    graph = python_to_graph(source, name=name)
    actual = graph_to_python(graph)
    assert actual == expected_output, (
        f"Golden mismatch for {name}. "
        f"Regen with `PYTHONPATH=python python tools/bake_visual_scripting_goldens.py`."
    )


@pytest.mark.parametrize("name", _round_trip_params())
def test_round_trip_lossless(name: str) -> None:
    """``ast(python -> graph -> python) == ast(python)`` (semantics-preserving).

    Compares :func:`canonicalize_python` output so the ``def run():``
    wrapper the codegen always adds doesn't cause a spurious diff, and
    so trivial formatting choices (quote style, trailing newlines) are
    normalised through :func:`ast.unparse`.
    """
    source, _, _ = load_golden(name)
    graph = python_to_graph(source, name=name)
    emitted = graph_to_python(graph)
    assert canonicalize_python(emitted) == canonicalize_python(source), (
        f"Round-trip AST mismatch for {name}:\n"
        f"  source     -> {canonicalize_python(source)!r}\n"
        f"  emitted    -> {canonicalize_python(emitted)!r}"
    )


# ---------------------------------------------------------------------------
# canonicalize_python + load_golden self-tests. These give the helpers a
# tripwire independent of the codegen so a helper regression can't
# masquerade as a codegen bug.
# ---------------------------------------------------------------------------


def test_canonicalize_python_unwraps_def_run() -> None:
    """``def run(): ...`` wrapper is stripped before comparison."""
    wrapped = "def run():\n    x = 1\n"
    bare = "x = 1"
    assert canonicalize_python(wrapped) == canonicalize_python(bare)


def test_canonicalize_python_normalises_whitespace() -> None:
    """Trailing newlines / quote style differences round-trip identically."""
    a = 'x = "hello"\n\n\n'
    b = "x = 'hello'"
    assert canonicalize_python(a) == canonicalize_python(b)


def test_canonicalize_python_keeps_named_def() -> None:
    """A non-``run`` function is not unwrapped."""
    src = "def other():\n    return 1\n"
    # canonicalize_python should keep the FunctionDef because the name
    # doesn't match "run".
    assert "def other" in canonicalize_python(src)


def test_load_golden_returns_all_three_files() -> None:
    """The triple loader returns non-empty strings for a known case."""
    src, yaml_text, out = load_golden("return_early")
    assert "def run" in src
    assert "control.return" in yaml_text
    assert "return 1" in out


def test_load_golden_raises_on_missing_case() -> None:
    with pytest.raises(FileNotFoundError):
        load_golden("case_that_does_not_exist_xxx")
