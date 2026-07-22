//! Constant-folding pass for the Python `MaterialGraph`.
//!
//! Walks nodes with no texture/UV dependency and produces a packed
//! `Vec<f32>` uniform buffer suitable for direct upload as a UBO.
//!
//! This is the bake half of the DDD5 material graph baseline; live shader
//! compilation stays in Python.

use pyo3::prelude::*;
use serde::Deserialize;
use serde_yaml;

#[derive(Debug, Deserialize)]
struct GraphYaml {
    #[serde(default)]
    nodes: Vec<NodeYaml>,
}

#[derive(Debug, Deserialize)]
struct NodeYaml {
    #[serde(rename = "type")]
    node_type: String,
    #[serde(default)]
    params: serde_yaml::Value,
}

/// Pack every constant node's parameters into a flat f32 buffer.
///
/// Dynamic nodes (Texture2D, UV, NormalMap, Fresnel — anything that depends on
/// per-fragment state) are skipped since their values can't be baked at graph
/// compile time.
///
/// Layout: contiguous, node order = YAML order.
///
/// * `ConstFloatNode` → 1 f32 (the value).
/// * `ConstColorNode` → 4 f32 (r, g, b, a).
///
/// Anything else contributes zero floats.
#[pyfunction]
pub fn bake_material_constants(graph_yaml: &str) -> PyResult<Vec<f32>> {
    let graph: GraphYaml = serde_yaml::from_str(graph_yaml)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("bad YAML: {e}")))?;

    let mut out: Vec<f32> = Vec::new();
    for node in &graph.nodes {
        match node.node_type.as_str() {
            "ConstFloatNode" => {
                let v = node
                    .params
                    .get("value")
                    .and_then(|v| v.as_f64())
                    .unwrap_or(0.0) as f32;
                out.push(v);
            }
            "ConstColorNode" => {
                for key in ["r", "g", "b", "a"] {
                    let v = node
                        .params
                        .get(key)
                        .and_then(|v| v.as_f64())
                        .unwrap_or(if key == "a" { 1.0 } else { 0.0 })
                        as f32;
                    out.push(v);
                }
            }
            _ => {
                // Dynamic / structural node — no constant contribution.
            }
        }
    }
    Ok(out)
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(bake_material_constants, m)?)?;
    Ok(())
}
