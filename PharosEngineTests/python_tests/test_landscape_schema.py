"""Engine tests for Landscape + TileCoord and NodeGraph schema validation — headless."""
from __future__ import annotations
import tempfile
import pytest
import numpy as np


class TestTileCoord:
    def test_hash_equal_coords(self):
        from pharos_engine.landscape import TileCoord
        a = TileCoord(3, 7)
        b = TileCoord(3, 7)
        assert hash(a) == hash(b)

    def test_hash_different_coords(self):
        from pharos_engine.landscape import TileCoord
        a = TileCoord(1, 2)
        b = TileCoord(2, 1)
        assert hash(a) != hash(b)

    def test_equality(self):
        from pharos_engine.landscape import TileCoord
        assert TileCoord(5, 5) == TileCoord(5, 5)

    def test_inequality(self):
        from pharos_engine.landscape import TileCoord
        assert TileCoord(1, 2) != TileCoord(2, 1)

    def test_usable_as_dict_key(self):
        from pharos_engine.landscape import TileCoord
        d = {TileCoord(0, 0): "origin", TileCoord(1, 0): "right"}
        assert d[TileCoord(0, 0)] == "origin"
        assert d[TileCoord(1, 0)] == "right"

    def test_repr(self):
        from pharos_engine.landscape import TileCoord
        assert "3" in repr(TileCoord(3, 7))
        assert "7" in repr(TileCoord(3, 7))

    def test_usable_in_set(self):
        from pharos_engine.landscape import TileCoord
        s = {TileCoord(0, 0), TileCoord(1, 0), TileCoord(0, 0)}
        assert len(s) == 2


class TestTile:
    def test_tile_coord_stored(self):
        from pharos_engine.landscape import TileCoord, Tile
        coord = TileCoord(2, 3)
        tile = Tile(coord, tile_size=64)
        assert tile.coord == coord

    def test_tile_size_stored(self):
        from pharos_engine.landscape import TileCoord, Tile
        tile = Tile(TileCoord(0, 0), tile_size=128)
        assert tile.tile_size == 128

    def test_initially_not_dirty(self):
        from pharos_engine.landscape import TileCoord, Tile
        tile = Tile(TileCoord(0, 0), tile_size=64)
        assert tile._dirty is False

    def test_mark_dirty(self):
        from pharos_engine.landscape import TileCoord, Tile
        tile = Tile(TileCoord(0, 0), tile_size=32)
        tile.mark_dirty()
        assert tile._dirty is True

    def test_mark_clean(self):
        from pharos_engine.landscape import TileCoord, Tile
        tile = Tile(TileCoord(0, 0), tile_size=32)
        tile.mark_dirty()
        tile.mark_clean()
        assert tile._dirty is False

    def test_position_computed_from_coord(self):
        from pharos_engine.landscape import TileCoord, Tile
        tile = Tile(TileCoord(3, 4), tile_size=256)
        assert tile.position == (3 * 256.0, 4 * 256.0)


class TestLandscape:
    def test_init_creates_tile_dir(self):
        from pharos_engine.landscape import Landscape
        with tempfile.TemporaryDirectory() as tmpdir:
            import os
            subdir = os.path.join(tmpdir, "newdir")
            lnd = Landscape(tile_size=64, tile_dir=subdir)
            assert os.path.isdir(subdir)

    def test_get_tile_none_when_not_loaded(self):
        from pharos_engine.landscape import Landscape
        with tempfile.TemporaryDirectory() as tmpdir:
            lnd = Landscape(tile_size=64, tile_dir=tmpdir)
            assert lnd.get_tile(99, 99) is None

    def test_paint_tile_creates_loaded_tile(self):
        from pharos_engine.landscape import Landscape
        import numpy as np
        with tempfile.TemporaryDirectory() as tmpdir:
            lnd = Landscape(tile_size=32, tile_dir=tmpdir)
            data = np.zeros((32, 32, 4), dtype=np.uint8)
            lnd.paint_tile(0, 0, data)
            tile = lnd.get_tile(0, 0)
            assert tile is not None

    def test_paint_tile_marks_dirty(self):
        from pharos_engine.landscape import Landscape
        import numpy as np
        with tempfile.TemporaryDirectory() as tmpdir:
            lnd = Landscape(tile_size=32, tile_dir=tmpdir)
            data = np.zeros((32, 32, 4), dtype=np.uint8)
            lnd.paint_tile(1, 2, data)
            tile = lnd.get_tile(1, 2)
            assert tile._dirty is True

    def test_tile_paths(self):
        from pharos_engine.landscape import Landscape, TileCoord
        with tempfile.TemporaryDirectory() as tmpdir:
            lnd = Landscape(tile_size=64, tile_dir=tmpdir)
            coord = TileCoord(5, 3)
            png_path = lnd._tile_path_png(coord)
            slap_path = lnd._tile_path_slap(coord)
            assert "tile_5_3.png" in str(png_path)
            assert "tile_5_3.slap" in str(slap_path)

    def test_visible_tiles_empty_initially(self):
        from pharos_engine.landscape import Landscape
        with tempfile.TemporaryDirectory() as tmpdir:
            lnd = Landscape(tile_size=64, tile_dir=tmpdir)
            assert lnd.visible_tiles == []


class TestValidateNodeGraph:
    def _valid_graph(self):
        return {
            "nodes": [
                {"id": "uv", "type": "UV", "params": {}},
                {"id": "tex", "type": "SampleTexture", "params": {"asset": "foo.png"}},
                {"id": "out", "type": "FinalColor", "params": {}},
            ],
            "edges": [
                {"from_node": "uv", "from_port": "uv", "to_node": "tex", "to_port": "uv"},
                {"from_node": "tex", "from_port": "color", "to_node": "out", "to_port": "color"},
            ],
        }

    def test_valid_graph_no_errors(self):
        from pharos_engine.material.graph_schema import validate_node_graph
        errors = validate_node_graph(self._valid_graph())
        assert errors == []

    def test_missing_nodes_key(self):
        from pharos_engine.material.graph_schema import validate_node_graph
        errors = validate_node_graph({"edges": []})
        assert any("nodes" in e for e in errors)

    def test_missing_edges_key(self):
        from pharos_engine.material.graph_schema import validate_node_graph
        errors = validate_node_graph({"nodes": []})
        assert any("edges" in e for e in errors)

    def test_not_a_dict_returns_error(self):
        from pharos_engine.material.graph_schema import validate_node_graph
        errors = validate_node_graph("not a dict")
        assert len(errors) > 0

    def test_duplicate_node_id_error(self):
        from pharos_engine.material.graph_schema import validate_node_graph
        graph = {
            "nodes": [
                {"id": "n1", "type": "UV", "params": {}},
                {"id": "n1", "type": "UV", "params": {}},  # duplicate
            ],
            "edges": [],
        }
        errors = validate_node_graph(graph)
        assert any("duplicate" in e for e in errors)

    def test_unknown_node_type_warning(self):
        from pharos_engine.material.graph_schema import validate_node_graph
        graph = {
            "nodes": [{"id": "n1", "type": "MysteryNode", "params": {}}],
            "edges": [],
        }
        errors = validate_node_graph(graph)
        assert any("unknown node type" in e for e in errors)

    def test_edge_references_unknown_node(self):
        from pharos_engine.material.graph_schema import validate_node_graph
        graph = {
            "nodes": [{"id": "n1", "type": "UV", "params": {}}],
            "edges": [{"from_node": "ghost", "from_port": "uv", "to_node": "n1", "to_port": "uv"}],
        }
        errors = validate_node_graph(graph)
        assert any("from_node" in e and "ghost" in e for e in errors)

    def test_edge_missing_fields(self):
        from pharos_engine.material.graph_schema import validate_node_graph
        graph = {
            "nodes": [{"id": "n1", "type": "UV", "params": {}}],
            "edges": [{"from_node": "n1"}],  # missing to_node, ports
        }
        errors = validate_node_graph(graph)
        assert len(errors) > 0

    def test_node_missing_id(self):
        from pharos_engine.material.graph_schema import validate_node_graph
        graph = {
            "nodes": [{"type": "UV", "params": {}}],
            "edges": [],
        }
        errors = validate_node_graph(graph)
        assert any("id" in e for e in errors)

    def test_node_params_not_dict(self):
        from pharos_engine.material.graph_schema import validate_node_graph
        graph = {
            "nodes": [{"id": "n1", "type": "UV", "params": "not a dict"}],
            "edges": [],
        }
        errors = validate_node_graph(graph)
        assert any("params" in e for e in errors)


class TestKnownNodeTypes:
    def test_final_color_known(self):
        from pharos_engine.material.graph_schema import KNOWN_NODE_TYPES
        assert "FinalColor" in KNOWN_NODE_TYPES

    def test_add_known(self):
        from pharos_engine.material.graph_schema import KNOWN_NODE_TYPES
        assert "Add" in KNOWN_NODE_TYPES

    def test_force_output_known(self):
        from pharos_engine.material.graph_schema import KNOWN_NODE_TYPES
        assert "force_output" in KNOWN_NODE_TYPES

    def test_known_port_types_consistent(self):
        from pharos_engine.material.graph_schema import KNOWN_NODE_TYPES, KNOWN_PORT_TYPES
        # All port types defined should be in known node types
        for node_type in KNOWN_PORT_TYPES:
            assert node_type in KNOWN_NODE_TYPES
