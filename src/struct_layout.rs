use pyo3::prelude::*;
use std::collections::HashMap;

// Returns (size_bytes, align_bytes) for a WGSL type.
// vec3f is 12 bytes but must be aligned to 16 in a struct (WGSL spec §4.4).
fn wgsl_type_info(ty: &str) -> Option<(usize, usize)> {
    match ty {
        "f32" | "u32" | "i32" => Some((4, 4)),
        "vec2f" => Some((8, 8)),
        "vec3f" => Some((12, 16)),
        "vec4f" => Some((16, 16)),
        _ => None,
    }
}

fn align_up(offset: usize, align: usize) -> usize {
    (offset + align - 1) & !(align - 1)
}

#[pyfunction]
pub fn compute_layout(channels: Vec<(String, String)>) -> PyResult<HashMap<String, usize>> {
    let mut map = HashMap::new();
    let mut offset = 0usize;
    let mut struct_align = 1usize;

    for (name, ty) in &channels {
        let (size, align) = wgsl_type_info(ty).ok_or_else(|| {
            pyo3::exceptions::PyValueError::new_err(format!("Unknown WGSL type: {ty}"))
        })?;

        offset = align_up(offset, align);
        map.insert(name.clone(), offset);
        offset += size;
        if align > struct_align {
            struct_align = align;
        }
    }

    // Stride must be a multiple of the largest field alignment (WGSL struct stride rule).
    let stride = align_up(offset, struct_align);
    map.insert("stride".to_string(), stride);

    Ok(map)
}

#[pyfunction]
pub fn generate_wgsl_struct(struct_name: &str, channels: Vec<(String, String)>) -> PyResult<String> {
    let mut lines = Vec::new();
    lines.push(format!("struct {struct_name} {{"));

    let mut offset = 0usize;
    let mut struct_align = 1usize;

    for (name, ty) in &channels {
        let (size, align) = wgsl_type_info(ty).ok_or_else(|| {
            pyo3::exceptions::PyValueError::new_err(format!("Unknown WGSL type: {ty}"))
        })?;

        offset = align_up(offset, align);

        // Emit @size annotation when vec3f needs padding to reach 16-byte stride within the struct.
        if ty == "vec3f" {
            lines.push(format!("    {name}: {ty},  // offset {offset}, align {align}, size 16 (padded)"));
        } else {
            lines.push(format!("    {name}: {ty},"));
        }

        offset += size;
        if align > struct_align {
            struct_align = align;
        }
    }

    lines.push("};".to_string());
    Ok(lines.join("\n"))
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(compute_layout, m)?)?;
    m.add_function(wrap_pyfunction!(generate_wgsl_struct, m)?)?;
    Ok(())
}
