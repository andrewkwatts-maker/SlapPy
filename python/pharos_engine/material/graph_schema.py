from __future__ import annotations

KNOWN_NODE_TYPES: frozenset[str] = frozenset({
    "UV",
    "PixelColor",
    "PixelChannel",
    "Add",
    "Multiply",
    "Lerp",
    "Clamp",
    "Remap",
    "GravityWarp",
    "SampleTexture",
    "FinalColor",
    "Discard",
    # Sim-field / math / output nodes (lowercase to match node factory contract)
    "read_field",
    "write_field",
    "sample_sim_field",
    "sin",
    "cos",
    "pow",
    "remap",
    "length",
    "normalize",
    "dot",
    "noise",
    "world_pos",
    "time",
    "offset_uv",
    "reflect_uv",
    "accumulate",
    "ray_march",
    "force_output",
    "reduce_output",
})

KNOWN_PORT_TYPES: dict[str, dict] = {
    "UV": {"outputs": ["uv"], "inputs": []},
    "GravityWarp": {"outputs": ["out_uv"], "inputs": ["uv"]},
    "SampleTexture": {"outputs": ["color"], "inputs": ["uv"]},
    "FinalColor": {"outputs": [], "inputs": ["color"]},
    "Add": {"outputs": ["out"], "inputs": ["a", "b"]},
    "Multiply": {"outputs": ["out"], "inputs": ["a", "b"]},
    "Lerp": {"outputs": ["out"], "inputs": ["a", "b", "t"]},
    "Clamp": {"outputs": ["out"], "inputs": ["val"]},
    "PixelColor": {"outputs": ["color"], "inputs": []},
    "PixelChannel": {"outputs": ["val"], "inputs": []},
    "Discard": {"outputs": [], "inputs": []},
    "ray_march": {"outputs": ["hit"], "inputs": ["origin", "dir"]},
}


def validate_node_graph(graph_dict: dict) -> list[str]:
    errors: list[str] = []

    if not isinstance(graph_dict, dict):
        return ["graph must be a dict"]

    if "nodes" not in graph_dict:
        errors.append("missing required key 'nodes'")
    if "edges" not in graph_dict:
        errors.append("missing required key 'edges'")

    if errors:
        return errors

    nodes = graph_dict["nodes"]
    edges = graph_dict["edges"]

    if not isinstance(nodes, list):
        errors.append("'nodes' must be a list")
        return errors

    if not isinstance(edges, list):
        errors.append("'edges' must be a list")
        return errors

    seen_ids: set[str] = set()
    valid_node_ids: set[str] = set()

    for i, node in enumerate(nodes):
        prefix = f"node[{i}]"

        if not isinstance(node, dict):
            errors.append(f"{prefix}: must be a dict")
            continue

        node_id = node.get("id")
        node_type = node.get("type")
        node_params = node.get("params")

        if not isinstance(node_id, str) or not node_id:
            errors.append(f"{prefix}: 'id' must be a non-empty string")
        else:
            if node_id in seen_ids:
                errors.append(f"{prefix}: duplicate node id '{node_id}'")
            else:
                seen_ids.add(node_id)
                valid_node_ids.add(node_id)

        if not isinstance(node_type, str) or not node_type:
            errors.append(f"{prefix}: 'type' must be a non-empty string")
        elif node_type not in KNOWN_NODE_TYPES:
            errors.append(f"{prefix}: unknown node type '{node_type}' (warning)")

        if not isinstance(node_params, dict):
            errors.append(f"{prefix}: 'params' must be a dict")

    for i, edge in enumerate(edges):
        prefix = f"edge[{i}]"

        if not isinstance(edge, dict):
            errors.append(f"{prefix}: must be a dict")
            continue

        from_node = edge.get("from_node")
        from_port = edge.get("from_port")
        to_node = edge.get("to_node")
        to_port = edge.get("to_port")

        for field_name, value in [
            ("from_node", from_node),
            ("from_port", from_port),
            ("to_node", to_node),
            ("to_port", to_port),
        ]:
            if not isinstance(value, str) or not value:
                errors.append(f"{prefix}: '{field_name}' must be a non-empty string")

        if isinstance(from_node, str) and from_node and from_node not in valid_node_ids:
            errors.append(f"{prefix}: 'from_node' references unknown node id '{from_node}'")

        if isinstance(to_node, str) and to_node and to_node not in valid_node_ids:
            errors.append(f"{prefix}: 'to_node' references unknown node id '{to_node}'")

    return errors
