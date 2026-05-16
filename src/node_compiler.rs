use pyo3::prelude::*;
use serde::Deserialize;
use std::collections::{HashMap, HashSet, VecDeque};

// ---------------------------------------------------------------------------
// JSON schema types
// ---------------------------------------------------------------------------

#[derive(Debug, Deserialize)]
struct NodeGraph {
    nodes: Vec<Node>,
    edges: Vec<Edge>,
}

#[derive(Debug, Deserialize)]
struct Node {
    id: String,
    #[serde(rename = "type")]
    node_type: String,
    #[serde(default)]
    params: serde_json::Map<String, serde_json::Value>,
}

#[derive(Debug, Deserialize)]
struct Edge {
    from_node: String,
    from_port: String,
    to_node: String,
    to_port: String,
}

// ---------------------------------------------------------------------------
// Topological sort (Kahn's algorithm)
// ---------------------------------------------------------------------------

/// Returns node IDs in evaluation order, or an error if a cycle is detected.
fn topological_order(nodes: &[Node], edges: &[Edge]) -> Result<Vec<String>, String> {
    let ids: HashSet<&str> = nodes.iter().map(|n| n.id.as_str()).collect();

    // in-degree and adjacency list (from_node -> [to_node])
    let mut in_degree: HashMap<&str, usize> = ids.iter().map(|&id| (id, 0)).collect();
    let mut adj: HashMap<&str, Vec<&str>> = ids.iter().map(|&id| (id, vec![])).collect();

    for edge in edges {
        *in_degree.entry(edge.to_node.as_str()).or_insert(0) += 1;
        adj.entry(edge.from_node.as_str())
            .or_default()
            .push(edge.to_node.as_str());
    }

    let mut queue: VecDeque<&str> = in_degree
        .iter()
        .filter(|(_, &deg)| deg == 0)
        .map(|(&id, _)| id)
        .collect();

    // Deterministic order within the same in-degree level: sort by node
    // position in the original list so output is stable.
    let order_map: HashMap<&str, usize> = nodes
        .iter()
        .enumerate()
        .map(|(i, n)| (n.id.as_str(), i))
        .collect();
    let mut queue_vec: Vec<&str> = queue.drain(..).collect();
    queue_vec.sort_by_key(|id| order_map.get(id).copied().unwrap_or(usize::MAX));
    queue.extend(queue_vec);

    let mut result: Vec<String> = Vec::with_capacity(nodes.len());

    while let Some(id) = queue.pop_front() {
        result.push(id.to_string());
        if let Some(neighbors) = adj.get(id) {
            let mut sorted = neighbors.clone();
            sorted.sort_by_key(|id| order_map.get(id).copied().unwrap_or(usize::MAX));
            for neighbor in sorted {
                let deg = in_degree.get_mut(neighbor).unwrap();
                *deg -= 1;
                if *deg == 0 {
                    queue.push_back(neighbor);
                }
            }
        }
    }

    if result.len() != nodes.len() {
        return Err("Node graph contains a cycle".to_string());
    }

    Ok(result)
}

// ---------------------------------------------------------------------------
// Code generation helpers
// ---------------------------------------------------------------------------

/// Look up the wire name produced by a given (node_id, port) pair.
/// Returns None if no edge feeds that slot (caller handles the missing-input case).
fn resolve_input<'a>(
    to_node: &str,
    to_port: &str,
    edges: &'a [Edge],
) -> Option<String> {
    edges
        .iter()
        .find(|e| e.to_node == to_node && e.to_port == to_port)
        .map(|e| wire_name(&e.from_node, &e.from_port))
}

/// Canonical variable name for the value flowing out of (node, port).
fn wire_name(node_id: &str, port: &str) -> String {
    format!("{}_{}", node_id, port)
}

/// Emit WGSL lines for a single node. Returns an error string on failure.
fn emit_node(
    node: &Node,
    edges: &[Edge],
    lines: &mut Vec<String>,
) -> Result<(), String> {
    let id = &node.id;

    // Helper closures
    let input = |port: &str| -> Option<String> { resolve_input(id, port, edges) };
    let param_f32 = |key: &str| -> Option<f32> {
        node.params.get(key)?.as_f64().map(|v| v as f32)
    };
    let param_str = |key: &str| -> Option<&str> {
        node.params.get(key)?.as_str()
    };

    match node.node_type.as_str() {
        "UV" => {
            lines.push(format!("    let {} = in.uv;", wire_name(id, "uv")));
        }

        "PixelColor" => {
            lines.push(format!(
                "    let {} = textureSample(t_color, s_color, in.uv);",
                wire_name(id, "color")
            ));
        }

        "PixelChannel" => {
            let channel = param_str("channel").unwrap_or("r");
            lines.push(format!(
                "    let {} = textureSample(t_color, s_color, in.uv).{};",
                wire_name(id, "val"),
                channel
            ));
        }

        "Add" => {
            let a = input("a").unwrap_or_else(|| "0.0".to_string());
            let b = input("b").unwrap_or_else(|| "0.0".to_string());
            lines.push(format!(
                "    let {} = {} + {};",
                wire_name(id, "out"),
                a,
                b
            ));
        }

        "Multiply" => {
            let a = input("a").unwrap_or_else(|| "1.0".to_string());
            let b = input("b").unwrap_or_else(|| "1.0".to_string());
            lines.push(format!(
                "    let {} = {} * {};",
                wire_name(id, "out"),
                a,
                b
            ));
        }

        "Lerp" => {
            let a = input("a").unwrap_or_else(|| "0.0".to_string());
            let b = input("b").unwrap_or_else(|| "1.0".to_string());
            let t = input("t").unwrap_or_else(|| "0.5".to_string());
            lines.push(format!(
                "    let {} = mix({}, {}, {});",
                wire_name(id, "out"),
                a,
                b,
                t
            ));
        }

        "Clamp" => {
            let val = input("val").unwrap_or_else(|| "0.0".to_string());
            let min_v = param_f32("min").unwrap_or(0.0);
            let max_v = param_f32("max").unwrap_or(1.0);
            lines.push(format!(
                "    let {} = clamp({}, {:.6}f, {:.6}f);",
                wire_name(id, "out"),
                val,
                min_v,
                max_v
            ));
        }

        "GravityWarp" => {
            let in_uv = input("uv").unwrap_or_else(|| "in.uv".to_string());
            let strength = param_f32("strength").unwrap_or(1.0);
            let radius = param_f32("radius").unwrap_or(0.1);
            lines.push(format!(
                "    let {} = warp_uv({}, {:.6}f, {:.6}f);",
                wire_name(id, "out_uv"),
                in_uv,
                strength,
                radius
            ));
        }

        "SampleTexture" => {
            let in_uv = input("uv").unwrap_or_else(|| "in.uv".to_string());
            lines.push(format!(
                "    let {} = textureSample(t_color, s_color, {});",
                wire_name(id, "color"),
                in_uv
            ));
        }

        "FinalColor" => {
            let color = input("color").unwrap_or_else(|| "vec4<f32>(0.0, 0.0, 0.0, 1.0)".to_string());
            lines.push(format!("    out_color = {};", color));
        }

        "Discard" => {
            lines.push("    discard;".to_string());
        }

        other => {
            return Err(format!("Unknown node type: {}", other));
        }
    }

    Ok(())
}

// ---------------------------------------------------------------------------
// WGSL template
// ---------------------------------------------------------------------------

const WGSL_HEADER: &str = r#"struct VertexOutput {
    @builtin(position) pos: vec4<f32>,
    @location(0) uv: vec2<f32>,
}

@group(0) @binding(0) var t_color: texture_2d<f32>;
@group(0) @binding(1) var s_color: sampler;

fn warp_uv(uv: vec2<f32>, strength: f32, radius: f32) -> vec2<f32> {
    let center = vec2<f32>(0.5, 0.5);
    let delta = uv - center;
    let dist = length(delta);
    let warp = strength * exp(-dist / max(radius, 0.001));
    return uv + normalize(delta) * warp * dist;
}

@fragment
fn fs_main(in: VertexOutput) -> @location(0) vec4<f32> {
    var out_color = vec4<f32>(0.0, 0.0, 0.0, 1.0);
"#;

const WGSL_FOOTER: &str = r#"    return out_color;
}
"#;

// ---------------------------------------------------------------------------
// Public entry point
// ---------------------------------------------------------------------------

#[pyfunction]
pub fn compile_node_graph(node_graph_json: &str) -> PyResult<String> {
    // 1. Parse JSON
    let graph: NodeGraph = serde_json::from_str(node_graph_json)
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(e.to_string()))?;

    // 2. Topological sort
    let order = topological_order(&graph.nodes, &graph.edges)
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(e))?;

    // Build a lookup map so we can iterate in topo order
    let node_map: HashMap<&str, &Node> = graph
        .nodes
        .iter()
        .map(|n| (n.id.as_str(), n))
        .collect();

    // 3. Emit node lines
    let mut body_lines: Vec<String> = Vec::new();
    for id in &order {
        if let Some(node) = node_map.get(id.as_str()) {
            emit_node(node, &graph.edges, &mut body_lines)
                .map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(e))?;
        }
    }

    // 4. Assemble shader
    let mut shader = String::with_capacity(512 + body_lines.iter().map(|l| l.len() + 1).sum::<usize>());
    shader.push_str(WGSL_HEADER);
    for line in &body_lines {
        shader.push_str(line);
        shader.push('\n');
    }
    shader.push_str(WGSL_FOOTER);

    Ok(shader)
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(compile_node_graph, m)?)?;
    Ok(())
}
