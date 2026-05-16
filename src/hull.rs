use pyo3::prelude::*;

/// Convex hull via Graham scan. Input: list of (x, y) f32 tuples.
/// Returns ordered boundary points (counter-clockwise).
#[pyfunction]
pub fn convex_hull(points: Vec<(f32, f32)>) -> PyResult<Vec<(f32, f32)>> {
    if points.len() < 3 {
        return Ok(points);
    }
    let mut pts = points.clone();

    // Find bottom-most (then left-most) point
    let pivot_idx = pts.iter().enumerate()
        .min_by(|(_, a), (_, b)| {
            a.1.partial_cmp(&b.1).unwrap()
                .then(a.0.partial_cmp(&b.0).unwrap())
        })
        .map(|(i, _)| i)
        .unwrap();
    pts.swap(0, pivot_idx);
    let pivot = pts[0];

    // Sort by polar angle relative to pivot
    pts[1..].sort_by(|a, b| {
        let ca = cross(pivot, *a, *b);
        if ca.abs() < 1e-9 {
            let da = dist2(pivot, *a);
            let db = dist2(pivot, *b);
            da.partial_cmp(&db).unwrap()
        } else {
            (-ca).partial_cmp(&0.0_f32).unwrap()  // clockwise → negative → sort first
        }
    });

    let mut hull: Vec<(f32, f32)> = Vec::new();
    for p in &pts {
        while hull.len() >= 2 {
            let n = hull.len();
            if cross(hull[n - 2], hull[n - 1], *p) <= 0.0 {
                hull.pop();
            } else {
                break;
            }
        }
        hull.push(*p);
    }
    Ok(hull)
}

/// Axis-aligned bounding box of a point set.
/// Returns (min_x, min_y, max_x, max_y).
#[pyfunction]
pub fn bounding_box(points: Vec<(f32, f32)>) -> PyResult<(f32, f32, f32, f32)> {
    if points.is_empty() {
        return Ok((0.0, 0.0, 0.0, 0.0));
    }
    let mut min_x = f32::MAX;
    let mut min_y = f32::MAX;
    let mut max_x = f32::MIN;
    let mut max_y = f32::MIN;
    for (x, y) in &points {
        if *x < min_x { min_x = *x; }
        if *y < min_y { min_y = *y; }
        if *x > max_x { max_x = *x; }
        if *y > max_y { max_y = *y; }
    }
    Ok((min_x, min_y, max_x, max_y))
}

fn cross(o: (f32, f32), a: (f32, f32), b: (f32, f32)) -> f32 {
    (a.0 - o.0) * (b.1 - o.1) - (a.1 - o.1) * (b.0 - o.0)
}

fn dist2(a: (f32, f32), b: (f32, f32)) -> f32 {
    let dx = b.0 - a.0;
    let dy = b.1 - a.1;
    dx * dx + dy * dy
}

/// Extract edge pixel coordinates from a flat buffer of PixelData structs.
///
/// pixel_data: flat list of f32 values (stride_floats per pixel)
/// pixel_count: number of pixels
/// stride_floats: number of f32 values per pixel
/// channel_offset_f32: which f32 index within stride is the filter channel
/// threshold: pixels with channel_value > threshold are considered "active"
/// width: image width (to compute 2D coords)
///
/// Returns list of (x, y) edge pixel coordinates (pixels adjacent to inactive pixels).
#[pyfunction]
pub fn pixel_edge_points(
    pixel_data: Vec<f32>,
    pixel_count: usize,
    stride_floats: usize,
    channel_offset_f32: usize,
    threshold: f32,
    width: usize,
) -> PyResult<Vec<(f32, f32)>> {
    if width == 0 || stride_floats == 0 {
        return Ok(vec![]);
    }
    let height = (pixel_count + width - 1) / width;

    let active = |idx: usize| -> bool {
        if idx >= pixel_count {
            return false;
        }
        let val = pixel_data.get(idx * stride_floats + channel_offset_f32).copied().unwrap_or(0.0);
        val > threshold
    };

    let mut edges = Vec::new();
    for y in 0..height {
        for x in 0..width {
            let idx = y * width + x;
            if !active(idx) {
                continue;
            }
            // Check 4-neighbours — if any is inactive, this pixel is an edge
            let is_edge = (x == 0 || !active(idx - 1))
                || (x + 1 >= width || !active(idx + 1))
                || (y == 0 || !active(idx - width))
                || (y + 1 >= height || !active(idx + width));
            if is_edge {
                edges.push((x as f32, y as f32));
            }
        }
    }
    Ok(edges)
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(convex_hull, m)?)?;
    m.add_function(wrap_pyfunction!(bounding_box, m)?)?;
    m.add_function(wrap_pyfunction!(pixel_edge_points, m)?)?;
    Ok(())
}
