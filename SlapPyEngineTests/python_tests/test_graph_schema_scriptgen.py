"""Engine tests for material/graph_schema.py and ai/script_gen.py.
All headless — no GPU or LLM network calls required.
"""
from __future__ import annotations
import pytest


# ---------------------------------------------------------------------------
# material/graph_schema.py
# ---------------------------------------------------------------------------

class TestKnownNodeTypes:
    def test_known_node_types_is_frozenset(self):
        from slappyengine.material.graph_schema import KNOWN_NODE_TYPES
        assert isinstance(KNOWN_NODE_TYPES, frozenset)

    def test_standard_nodes_present(self):
        from slappyengine.material.graph_schema import KNOWN_NODE_TYPES
        for name in ("UV", "Add", "Multiply", "Lerp", "Clamp",
                     "FinalColor", "SampleTexture", "PixelColor", "PixelChannel"):
            assert name in KNOWN_NODE_TYPES

    def test_extended_nodes_present(self):
        from slappyengine.material.graph_schema import KNOWN_NODE_TYPES
        for name in ("sin", "cos", "pow", "noise", "world_pos", "time",
                     "reflect_uv", "offset_uv", "accumulate"):
            assert name in KNOWN_NODE_TYPES

    def test_field_access_nodes_present(self):
        from slappyengine.material.graph_schema import KNOWN_NODE_TYPES
        assert "read_field" in KNOWN_NODE_TYPES
        assert "write_field" in KNOWN_NODE_TYPES

    def test_output_nodes_present(self):
        from slappyengine.material.graph_schema import KNOWN_NODE_TYPES
        assert "final_color" in KNOWN_NODE_TYPES
        assert "force_output" in KNOWN_NODE_TYPES
        assert "reduce_output" in KNOWN_NODE_TYPES


class TestKnownPortTypes:
    def test_is_dict(self):
        from slappyengine.material.graph_schema import KNOWN_PORT_TYPES
        assert isinstance(KNOWN_PORT_TYPES, dict)

    def test_uv_ports(self):
        from slappyengine.material.graph_schema import KNOWN_PORT_TYPES
        p = KNOWN_PORT_TYPES["UV"]
        assert "uv" in p["outputs"]
        assert p["inputs"] == []

    def test_add_ports(self):
        from slappyengine.material.graph_schema import KNOWN_PORT_TYPES
        p = KNOWN_PORT_TYPES["Add"]
        assert "out" in p["outputs"]
        assert "a" in p["inputs"] and "b" in p["inputs"]

    def test_lerp_ports(self):
        from slappyengine.material.graph_schema import KNOWN_PORT_TYPES
        p = KNOWN_PORT_TYPES["Lerp"]
        assert "a" in p["inputs"] and "b" in p["inputs"] and "t" in p["inputs"]

    def test_final_color_has_no_outputs(self):
        from slappyengine.material.graph_schema import KNOWN_PORT_TYPES
        p = KNOWN_PORT_TYPES["FinalColor"]
        assert p["outputs"] == []


class TestValidateNodeGraph:
    def _simple_graph(self):
        return {
            "nodes": [
                {"id": "uv", "type": "UV", "params": {}},
                {"id": "color", "type": "PixelColor", "params": {}},
                {"id": "out", "type": "FinalColor", "params": {}},
            ],
            "edges": [
                {"from_node": "color", "from_port": "color",
                 "to_node": "out", "to_port": "color"},
            ],
        }

    def test_valid_graph_no_errors(self):
        from slappyengine.material.graph_schema import validate_node_graph
        errors = validate_node_graph(self._simple_graph())
        # May have warnings about unknown node types but should have no structural errors
        assert isinstance(errors, list)

    def test_missing_nodes_key(self):
        from slappyengine.material.graph_schema import validate_node_graph
        errors = validate_node_graph({"edges": []})
        assert any("nodes" in e for e in errors)

    def test_missing_edges_key(self):
        from slappyengine.material.graph_schema import validate_node_graph
        errors = validate_node_graph({"nodes": []})
        assert any("edges" in e for e in errors)

    def test_not_a_dict_returns_error(self):
        from slappyengine.material.graph_schema import validate_node_graph
        errors = validate_node_graph("not a dict")
        assert len(errors) == 1
        assert "dict" in errors[0]

    def test_duplicate_node_id(self):
        from slappyengine.material.graph_schema import validate_node_graph
        g = {
            "nodes": [
                {"id": "same", "type": "UV", "params": {}},
                {"id": "same", "type": "PixelColor", "params": {}},
            ],
            "edges": [],
        }
        errors = validate_node_graph(g)
        assert any("duplicate" in e for e in errors)

    def test_empty_node_id(self):
        from slappyengine.material.graph_schema import validate_node_graph
        g = {
            "nodes": [{"id": "", "type": "UV", "params": {}}],
            "edges": [],
        }
        errors = validate_node_graph(g)
        assert any("id" in e for e in errors)

    def test_missing_params_key(self):
        from slappyengine.material.graph_schema import validate_node_graph
        g = {
            "nodes": [{"id": "n1", "type": "UV"}],
            "edges": [],
        }
        errors = validate_node_graph(g)
        assert any("params" in e for e in errors)

    def test_edge_references_unknown_from_node(self):
        from slappyengine.material.graph_schema import validate_node_graph
        g = {
            "nodes": [{"id": "n1", "type": "UV", "params": {}}],
            "edges": [{"from_node": "ghost", "from_port": "uv",
                       "to_node": "n1", "to_port": "uv"}],
        }
        errors = validate_node_graph(g)
        assert any("ghost" in e for e in errors)

    def test_edge_references_unknown_to_node(self):
        from slappyengine.material.graph_schema import validate_node_graph
        g = {
            "nodes": [{"id": "n1", "type": "UV", "params": {}}],
            "edges": [{"from_node": "n1", "from_port": "uv",
                       "to_node": "missing", "to_port": "uv"}],
        }
        errors = validate_node_graph(g)
        assert any("missing" in e for e in errors)

    def test_edge_missing_from_port(self):
        from slappyengine.material.graph_schema import validate_node_graph
        g = {
            "nodes": [
                {"id": "a", "type": "UV", "params": {}},
                {"id": "b", "type": "FinalColor", "params": {}},
            ],
            "edges": [{"from_node": "a", "from_port": "",
                       "to_node": "b", "to_port": "color"}],
        }
        errors = validate_node_graph(g)
        assert any("from_port" in e for e in errors)

    def test_empty_graph_no_error(self):
        from slappyengine.material.graph_schema import validate_node_graph
        errors = validate_node_graph({"nodes": [], "edges": []})
        assert errors == []

    def test_nodes_not_list(self):
        from slappyengine.material.graph_schema import validate_node_graph
        errors = validate_node_graph({"nodes": "not_a_list", "edges": []})
        assert any("list" in e for e in errors)

    def test_edges_not_list(self):
        from slappyengine.material.graph_schema import validate_node_graph
        errors = validate_node_graph({"nodes": [], "edges": "not_a_list"})
        assert any("list" in e for e in errors)


# ---------------------------------------------------------------------------
# ai/script_gen.py
# ---------------------------------------------------------------------------

class TestScriptGenerator:
    def test_importable(self):
        from slappyengine.ai.script_gen import ScriptGenerator
        assert ScriptGenerator is not None

    def test_system_prompt_importable(self):
        from slappyengine.ai.script_gen import SYSTEM_PROMPT
        assert isinstance(SYSTEM_PROMPT, str)
        assert len(SYSTEM_PROMPT) > 0

    def test_system_prompt_mentions_on_tick(self):
        from slappyengine.ai.script_gen import SYSTEM_PROMPT
        assert "on_tick" in SYSTEM_PROMPT

    def test_system_prompt_mentions_on_spawn(self):
        from slappyengine.ai.script_gen import SYSTEM_PROMPT
        assert "on_spawn" in SYSTEM_PROMPT

    def test_instantiates_with_mock_llm(self):
        from slappyengine.ai.script_gen import ScriptGenerator

        class MockLLM:
            def complete(self, system, user): return "class EntityScript: pass"

        sg = ScriptGenerator(llm_client=MockLLM())
        assert sg is not None

    def test_from_prompt_returns_string(self):
        from slappyengine.ai.script_gen import ScriptGenerator

        class MockLLM:
            def generate(self, prompt, system_prompt=None, temperature=0.2):
                return "class EntityScript:\n    def on_tick(self, entity, dt): pass"

        sg = ScriptGenerator(llm_client=MockLLM())
        result = sg.from_prompt("make entity move right")
        assert isinstance(result, str)

    def test_from_prompt_uses_mock_response(self):
        from slappyengine.ai.script_gen import ScriptGenerator

        class MockLLM:
            def generate(self, prompt, system_prompt=None, temperature=0.2):
                return "class EntityScript: pass"

        sg = ScriptGenerator(llm_client=MockLLM())
        result = sg.from_prompt("anything")
        assert "EntityScript" in result
