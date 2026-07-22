use pyo3::prelude::*;

#[derive(Clone, Copy)]
struct Vec2f {
    x: f32,
    y: f32,
}

impl Vec2f {
    #[inline]
    fn dist(&self, other: &Vec2f) -> f32 {
        let dx = self.x - other.x;
        let dy = self.y - other.y;
        (dx * dx + dy * dy).sqrt()
    }

    /// Linear interpolation: self * (1 - t) + other * t
    #[inline]
    fn lerp(&self, other: &Vec2f, t: f32) -> Vec2f {
        Vec2f {
            x: self.x + (other.x - self.x) * t,
            y: self.y + (other.y - self.y) * t,
        }
    }

    /// Move self toward other so the distance from other equals `bone_len`.
    /// Equivalent to: other + (self - other).normalize() * bone_len
    #[inline]
    fn pull_toward(&self, other: &Vec2f, bone_len: f32) -> Vec2f {
        let r = self.dist(other).max(f32::EPSILON);
        let lam = bone_len / r;
        // new = other * (1 - lam) + self * lam
        other.lerp(self, lam)
    }
}

/// Solve a 2D kinematic chain using the FABRIK algorithm.
///
/// Parameters
/// ----------
/// chain_positions : list of (x, y) tuples
///     Joint positions ordered ``[root, j1, j2, ..., end_effector]``.
/// target : (x, y)
///     Desired position for the end effector.
/// lengths : list of float
///     Bone lengths; ``len(lengths)`` must equal ``len(chain_positions) - 1``.
/// max_iter : int, optional
///     Maximum FABRIK iterations (default 10).
/// tolerance : float, optional
///     Convergence distance threshold (default 0.001).
///
/// Returns
/// -------
/// list of (x, y) tuples
///     Solved joint positions in the same order as the input.
#[pyfunction]
#[pyo3(signature = (chain_positions, target, lengths, max_iter=10, tolerance=0.001))]
pub fn solve_ik(
    chain_positions: Vec<(f32, f32)>,
    target: (f32, f32),
    lengths: Vec<f32>,
    max_iter: u32,
    tolerance: f32,
) -> PyResult<Vec<(f32, f32)>> {
    let n = chain_positions.len();

    // Edge cases: nothing to solve.
    if n < 2 {
        return Ok(chain_positions);
    }

    // Validate bone count.
    if lengths.len() != n - 1 {
        return Err(pyo3::exceptions::PyValueError::new_err(format!(
            "lengths must have exactly {} element(s) for a chain of {} joints, got {}",
            n - 1,
            n,
            lengths.len()
        )));
    }

    // Convert to internal representation.
    let mut p: Vec<Vec2f> = chain_positions
        .iter()
        .map(|&(x, y)| Vec2f { x, y })
        .collect();
    let t = Vec2f { x: target.0, y: target.1 };

    let total_len: f32 = lengths.iter().sum();

    // --- Unreachable target: stretch chain fully toward target ---
    if p[0].dist(&t) >= total_len {
        for i in 0..n - 1 {
            let r = p[i].dist(&t).max(f32::EPSILON);
            let lam = lengths[i] / r;
            p[i + 1] = p[i].lerp(&t, lam);
        }
        return Ok(p.iter().map(|v| (v.x, v.y)).collect());
    }

    // Save root position.
    let root = p[0];

    for _ in 0..max_iter {
        // Forward pass: pull end effector to target, then propagate backward.
        p[n - 1] = t;
        for i in (0..n - 1).rev() {
            p[i] = p[i].pull_toward(&p[i + 1], lengths[i]);
        }

        // Backward pass: restore root, then propagate forward.
        p[0] = root;
        for i in 0..n - 1 {
            p[i + 1] = p[i + 1].pull_toward(&p[i], lengths[i]);
        }

        // Convergence check.
        if p[n - 1].dist(&t) < tolerance {
            break;
        }
    }

    Ok(p.iter().map(|v| (v.x, v.y)).collect())
}

/// Compute bone lengths from a sequence of joint positions.
///
/// Returns a list of distances between consecutive joints, with length
/// ``len(positions) - 1``. Returns an empty list for 0- or 1-element input.
#[pyfunction]
pub fn compute_bone_lengths(positions: Vec<(f32, f32)>) -> Vec<f32> {
    if positions.len() < 2 {
        return Vec::new();
    }
    positions
        .windows(2)
        .map(|w| {
            let dx = w[1].0 - w[0].0;
            let dy = w[1].1 - w[0].1;
            (dx * dx + dy * dy).sqrt()
        })
        .collect()
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(solve_ik, m)?)?;
    m.add_function(wrap_pyfunction!(compute_bone_lengths, m)?)?;
    Ok(())
}
