"""Golden-file baker for the visual-scripting round-trip suite.

Writes the canonical golden triples to
``PharosEngineTests/goldens/visual_scripting/<name>/{source.py,
expected.yaml, output.py}`` from the CASES table below.

Regenerate the goldens after a codegen change with::

    PYTHONPATH=python python tools/bake_visual_scripting_goldens.py

Then inspect ``git diff PharosEngineTests/goldens/visual_scripting`` and
commit the delta alongside the codegen change. If a case newly
xpasses / xfails after regen, update the ``_XFAIL_*`` tables in
``PharosEngineTests/tests/test_visual_scripting_goldens.py``.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

from pharos_engine.visual_scripting.codegen import (
    python_to_graph,
    graph_to_python,
)
from pharos_engine.visual_scripting.golden_utils import (
    canonical_graph_yaml,
    goldens_root,
)


CASES: dict[str, str] = {
    "arithmetic": "x = (1 + 2) * 3 - 4\n",
    "nested_if": textwrap.dedent(
        """\
        if a > 0:
            if b > 0:
                x = 1
            else:
                x = 2
        else:
            x = 3
        """
    ),
    "for_range": "for i in range(10):\n    print(i)\n",
    "while_countdown": "n = 10\nwhile n > 0:\n    n = n - 1\n",
    "function_call_chain": "x = round(sqrt(abs(-25)))\n",
    "assignment_reuse": "x = 5\ny = x + 1\nz = x + y\n",
    "constant_types": textwrap.dedent(
        """\
        a = 1
        b = 2.5
        c = True
        d = "hello"
        """
    ),
    "comparison_chain": "x = a < b < c\n",
    "boolean_logic": "x = a and (b or not c)\n",
    "return_early": textwrap.dedent(
        """\
        def run():
            if x > 0:
                return 1
            return 0
        """
    ),
}


def main() -> None:
    root: Path = goldens_root()
    root.mkdir(parents=True, exist_ok=True)
    for name, source in CASES.items():
        case_dir = root / name
        case_dir.mkdir(parents=True, exist_ok=True)
        (case_dir / "source.py").write_text(source, encoding="utf-8")

        # bake YAML + output. Some cases raise CodegenError; write a
        # sentinel expected.yaml + output.py so the tests can xfail
        # cleanly without special-casing missing files.
        try:
            graph = python_to_graph(source, name=name)
            yaml_text = canonical_graph_yaml(graph)
        except Exception as exc:  # pragma: no cover — bake-time only
            yaml_text = f"# python_to_graph raised {type(exc).__name__}: {exc}\n"
            graph = None

        (case_dir / "expected.yaml").write_text(yaml_text, encoding="utf-8")

        if graph is None:
            out_text = f"# no output — {name} does not import cleanly\n"
        else:
            try:
                out_text = graph_to_python(graph)
            except Exception as exc:  # pragma: no cover — bake-time only
                out_text = f"# graph_to_python raised {type(exc).__name__}: {exc}\n"
        (case_dir / "output.py").write_text(out_text, encoding="utf-8")
        print(f"baked {name}")


if __name__ == "__main__":
    main()
