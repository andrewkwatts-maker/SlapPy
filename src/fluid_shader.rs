//! Fluid surface shader effects (watery polish passes).
//!
//! Mirrors the Python `_draw_surface` polish chain in
//! `python/slappyengine/fluid/render.py`:
//! 1. [`turbulence_foam_rs`] — speed-driven white foam mixed into the HDR
//!    buffer.
//! 2. [`refraction_warp_rs`] — density-gradient driven nearest-neighbour
//!    UV warp.
//! 3. [`godrays_rs`] — per-pixel ray-march backward along the light dir
//!    over the density field, additive contribution.
//! 4. [`specular_pass_rs`] — tight pow-8 specular lobe on the rim.
//! 5. [`draw_droplet_tails_rs`] — velocity-aligned streak + head dot per
//!    particle (small N).
//!
//! All HDR buffers are `(H, W, 3)` row-major `f32` packed in a writable
//! `bytearray` (in-place) or `&[u8]` (read-only). Density / speed grids
//! are `(H, W)` `f32`. Particle attributes are `(N, 2)` or `(N,)` `f32`.
//!
//! The math is intentionally bit-equivalent (within f32 rounding) to the
//! numpy fallback — visual fidelity diffs on the test scene stay
//! well under 2/255.

use bytemuck::cast_slice;
use pyo3::prelude::*;
use pyo3::types::PyByteArray;
use rayon::prelude::*;

const _EPS: f32 = 1e-9;

// ---------------------------------------------------------------------------
// Helpers — cast a writable bytearray to a flat (mut) f32 slice.
// ---------------------------------------------------------------------------

#[inline]
fn check_hdr_len(buf_len: usize, w: usize, h: usize) -> PyResult<()> {
    let need = w * h * 3 * 4;
    if buf_len < need {
        return Err(pyo3::exceptions::PyValueError::new_err(format!(
            "hdr buffer too small: {} < {}",
            buf_len, need
        )));
    }
    Ok(())
}

#[inline]
fn check_grid_len(buf_len: usize, w: usize, h: usize) -> PyResult<()> {
    let need = w * h * 4;
    if buf_len < need {
        return Err(pyo3::exceptions::PyValueError::new_err(format!(
            "grid buffer too small: {} < {}",
            buf_len, need
        )));
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// 1. Turbulence-driven foam.
// ---------------------------------------------------------------------------

/// White-foam pass: per-pixel `col = lerp(col, white_hdr, foam_w)` where
/// `foam_w = smoothstep(speed/v_ref) * turbulence_strength`. Speed grid is
/// precomputed by Python (after density normalisation) so this kernel is
/// trivially data-parallel.
#[pyfunction]
#[pyo3(signature = (
    hdr_rgb, speed_grid, width, height,
    turbulence_speed, turbulence_strength,
))]
pub fn turbulence_foam_rs(
    hdr_rgb: &Bound<'_, PyByteArray>,
    speed_grid: &[u8],
    width: usize,
    height: usize,
    turbulence_speed: f32,
    turbulence_strength: f32,
) -> PyResult<()> {
    check_hdr_len(hdr_rgb.len(), width, height)?;
    check_grid_len(speed_grid.len(), width, height)?;
    if turbulence_strength <= 0.0 {
        return Ok(());
    }
    let speed: &[f32] = cast_slice(speed_grid);
    let v_ref = turbulence_speed.max(_EPS);
    let inv_v = 1.0 / v_ref;
    let white_hdr = 800.0_f32;

    // Safety: PyByteArray is held under the GIL; no other thread mutates it.
    let buf: &mut [u8] = unsafe { hdr_rgb.as_bytes_mut() };
    let hdr: &mut [f32] = bytemuck::cast_slice_mut(buf);

    hdr.par_chunks_exact_mut(3 * width)
        .zip(speed.par_chunks_exact(width))
        .for_each(|(row, srow)| {
            for x in 0..width {
                let s = srow[x];
                let t = (s * inv_v).clamp(0.0, 1.0);
                let foam_t = t * t * (3.0 - 2.0 * t);
                let foam_w = foam_t * turbulence_strength;
                let inv = 1.0 - foam_w;
                let off = 3 * x;
                row[off] = row[off] * inv + white_hdr * foam_w;
                row[off + 1] = row[off + 1] * inv + white_hdr * foam_w;
                row[off + 2] = row[off + 2] * inv + white_hdr * foam_w;
            }
        });
    Ok(())
}

// ---------------------------------------------------------------------------
// 2. Refraction warp.
// ---------------------------------------------------------------------------

/// Refraction warp: per-pixel nearest-neighbour gather from `hdr_in` at
/// the offset position `(x + dx, y + dy)` where the offset is driven by
/// the density gradient (precomputed by Python via central differences).
///
/// `density_grid` is read-only; the offsets are computed on the fly from
/// central differences inside this function to avoid an extra Python
/// allocation. Matches Python: `dx = (gx_d / d_max) * strength`, clamped
/// to `±3 px`.
#[pyfunction]
#[pyo3(signature = (
    hdr_in, hdr_out, density_grid, width, height,
    d_max, refraction_strength,
))]
pub fn refraction_warp_rs(
    hdr_in: &[u8],
    hdr_out: &Bound<'_, PyByteArray>,
    density_grid: &[u8],
    width: usize,
    height: usize,
    d_max: f32,
    refraction_strength: f32,
) -> PyResult<()> {
    check_hdr_len(hdr_in.len(), width, height)?;
    check_hdr_len(hdr_out.len(), width, height)?;
    check_grid_len(density_grid.len(), width, height)?;
    let src: &[f32] = cast_slice(hdr_in);
    let density: &[f32] = cast_slice(density_grid);
    let dst_buf: &mut [u8] = unsafe { hdr_out.as_bytes_mut() };
    let dst: &mut [f32] = bytemuck::cast_slice_mut(dst_buf);

    let inv = 1.0 / d_max.max(_EPS);
    let w = width;
    let h = height;
    let w_i32 = w as i32;
    let h_i32 = h as i32;
    let scale = refraction_strength * inv;

    dst.par_chunks_exact_mut(3 * w)
        .enumerate()
        .for_each(|(y, drow)| {
            // Central-difference gy = (d[y+1] - d[y-1]) * 0.5 (clamped on edges).
            let y_up = if y > 0 { y - 1 } else { y };
            let y_dn = if y + 1 < h { y + 1 } else { y };
            let drow_up = &density[y_up * w..(y_up + 1) * w];
            let drow_dn = &density[y_dn * w..(y_dn + 1) * w];
            let drow_c = &density[y * w..(y + 1) * w];
            for x in 0..w {
                // gx central diff
                let gx = if x == 0 || x + 1 >= w {
                    0.0
                } else {
                    (drow_c[x + 1] - drow_c[x - 1]) * 0.5
                };
                let gy = if y == 0 || y + 1 >= h {
                    0.0
                } else {
                    (drow_dn[x] - drow_up[x]) * 0.5
                };
                let mut dx_px = gx * scale;
                let mut dy_px = gy * scale;
                if dx_px < -3.0 { dx_px = -3.0; }
                if dx_px > 3.0 { dx_px = 3.0; }
                if dy_px < -3.0 { dy_px = -3.0; }
                if dy_px > 3.0 { dy_px = 3.0; }
                let mut sx_f = (x as f32) + dx_px;
                let mut sy_f = (y as f32) + dy_px;
                if sx_f < 0.0 { sx_f = 0.0; }
                if sx_f > (w_i32 - 1) as f32 { sx_f = (w_i32 - 1) as f32; }
                if sy_f < 0.0 { sy_f = 0.0; }
                if sy_f > (h_i32 - 1) as f32 { sy_f = (h_i32 - 1) as f32; }
                let sx_i = sx_f as i32 as usize;
                let sy_i = sy_f as i32 as usize;
                let src_off = (sy_i * w + sx_i) * 3;
                let dst_off = 3 * x;
                drow[dst_off] = src[src_off];
                drow[dst_off + 1] = src[src_off + 1];
                drow[dst_off + 2] = src[src_off + 2];
            }
        });
    Ok(())
}

// ---------------------------------------------------------------------------
// 3. Godrays.
// ---------------------------------------------------------------------------

/// Godrays — per-pixel marching backward along the light direction over
/// the density field. Mirrors Python `_compute_godrays`:
/// ```text
/// for k in 1..=steps:
///     xi = clamp(x - ldx*step*k, 0, W-1)
///     yi = clamp(y - ldy*step*k, 0, H-1)
///     sample = density[yi, xi]
///     accum += max(sample - iso, 0) * iso_inv * (1/k)
/// accum *= strength / steps
/// nearby = clamp(density * iso_inv * 0.7, 0, 1)
/// hdr += accum * nearby * 60
/// ```
#[pyfunction]
#[pyo3(signature = (
    hdr_rgb, density_grid, width, height,
    iso, light_dx, light_dy, steps, step_px, strength,
))]
pub fn godrays_rs(
    hdr_rgb: &Bound<'_, PyByteArray>,
    density_grid: &[u8],
    width: usize,
    height: usize,
    iso: f32,
    light_dx: f32,
    light_dy: f32,
    steps: u32,
    step_px: f32,
    strength: f32,
) -> PyResult<()> {
    check_hdr_len(hdr_rgb.len(), width, height)?;
    check_grid_len(density_grid.len(), width, height)?;
    let steps = steps.max(1) as usize;
    if strength <= 0.0 {
        return Ok(());
    }
    let density: &[f32] = cast_slice(density_grid);
    let buf: &mut [u8] = unsafe { hdr_rgb.as_bytes_mut() };
    let hdr: &mut [f32] = bytemuck::cast_slice_mut(buf);

    let sx = -light_dx * step_px;
    let sy = -light_dy * step_px;
    let iso_inv = 1.0 / iso.max(_EPS);
    let scale = strength / steps as f32;
    let w = width;
    let h = height;
    let wx_max = (w as f32) - 1.0001;
    let hy_max = (h as f32) - 1.0001;

    hdr.par_chunks_exact_mut(3 * w)
        .enumerate()
        .for_each(|(y, row)| {
            let drow = &density[y * w..(y + 1) * w];
            for x in 0..w {
                let mut accum = 0.0_f32;
                let xf = x as f32;
                let yf = y as f32;
                for k in 1..=steps {
                    let kf = k as f32;
                    let mut xi = xf + sx * kf;
                    let mut yi = yf + sy * kf;
                    if xi < 0.0 { xi = 0.0; }
                    if xi > wx_max { xi = wx_max; }
                    if yi < 0.0 { yi = 0.0; }
                    if yi > hy_max { yi = hy_max; }
                    let xi_u = xi as i32 as usize;
                    let yi_u = yi as i32 as usize;
                    let sample = density[yi_u * w + xi_u];
                    let mask = (sample - iso).max(0.0) * iso_inv;
                    accum += mask * (1.0 / kf);
                }
                accum *= scale;
                // Nearby-fluid gate.
                let nearby = (drow[x] * iso_inv * 0.7).clamp(0.0, 1.0);
                let add = accum * nearby * 60.0;
                let off = 3 * x;
                row[off] = (row[off] + add).clamp(0.0, 4095.0);
                row[off + 1] = (row[off + 1] + add).clamp(0.0, 4095.0);
                row[off + 2] = (row[off + 2] + add).clamp(0.0, 4095.0);
            }
        });
    Ok(())
}

// ---------------------------------------------------------------------------
// 4. Specular highlight.
// ---------------------------------------------------------------------------

/// Tight specular lobe on the density rim. Computes:
///   n = -grad(d) normalised
///   spec_dot = clamp(-(n.x*ldx + n.y*ldy), 0, 1)
///   rim = exp(-((d-iso)^2) / (iso*0.25)^2)
///   col += tint * spec_dot^8 * rim * strength * 2.5
#[pyfunction]
#[pyo3(signature = (
    hdr_rgb, density_grid, width, height,
    iso, light_dx, light_dy, tint_r, tint_g, tint_b, strength,
))]
pub fn specular_pass_rs(
    hdr_rgb: &Bound<'_, PyByteArray>,
    density_grid: &[u8],
    width: usize,
    height: usize,
    iso: f32,
    light_dx: f32,
    light_dy: f32,
    tint_r: f32,
    tint_g: f32,
    tint_b: f32,
    strength: f32,
) -> PyResult<()> {
    check_hdr_len(hdr_rgb.len(), width, height)?;
    check_grid_len(density_grid.len(), width, height)?;
    if strength <= 0.0 {
        return Ok(());
    }
    let density: &[f32] = cast_slice(density_grid);
    let buf: &mut [u8] = unsafe { hdr_rgb.as_bytes_mut() };
    let hdr: &mut [f32] = bytemuck::cast_slice_mut(buf);

    let w = width;
    let h = height;
    let rim_denom = (iso * 0.25).powi(2).max(_EPS);
    let mul = strength * 2.5;

    hdr.par_chunks_exact_mut(3 * w)
        .enumerate()
        .for_each(|(y, row)| {
            let drow = &density[y * w..(y + 1) * w];
            let y_up = if y > 0 { y - 1 } else { y };
            let y_dn = if y + 1 < h { y + 1 } else { y };
            let drow_up = &density[y_up * w..(y_up + 1) * w];
            let drow_dn = &density[y_dn * w..(y_dn + 1) * w];
            for x in 0..w {
                let gx = if x == 0 || x + 1 >= w {
                    0.0
                } else {
                    (drow[x + 1] - drow[x - 1]) * 0.5
                };
                let gy = if y == 0 || y + 1 >= h {
                    0.0
                } else {
                    (drow_dn[x] - drow_up[x]) * 0.5
                };
                let mag = (gx * gx + gy * gy).sqrt();
                let (nxv, nyv) = if mag > _EPS {
                    (-gx / mag, -gy / mag)
                } else {
                    (0.0, 0.0)
                };
                let dot = (-(nxv * light_dx + nyv * light_dy)).clamp(0.0, 1.0);
                // pow(8) = sq(sq(sq))
                let d2 = dot * dot;
                let d4 = d2 * d2;
                let d8 = d4 * d4;
                let diff = drow[x] - iso;
                let rim = (-diff * diff / rim_denom).exp();
                let w_sp = d8 * rim * mul;
                let off = 3 * x;
                row[off] += tint_r * w_sp;
                row[off + 1] += tint_g * w_sp;
                row[off + 2] += tint_b * w_sp;
            }
        });
    Ok(())
}

// ---------------------------------------------------------------------------
// 5. Droplet tails — sequential rasteriser.
// ---------------------------------------------------------------------------

#[inline(always)]
fn alpha_over(buf: &mut [f32], off: usize, color: [f32; 3], a: f32) {
    let inv = 1.0 - a;
    buf[off] = buf[off] * inv + color[0] * a;
    buf[off + 1] = buf[off + 1] * inv + color[1] * a;
    buf[off + 2] = buf[off + 2] * inv + color[2] * a;
}

fn draw_streak(
    buf: &mut [f32],
    w: usize,
    h: usize,
    x0: f32,
    y0: f32,
    x1: f32,
    y1: f32,
    color: [f32; 3],
    alpha_scale: f32,
) {
    let r: f32 = 1.2;
    let xmin = ((x0.min(x1) - r).floor() as i32).max(0).min(w as i32 - 1);
    let xmax = ((x0.max(x1) + r).ceil() as i32).max(0).min(w as i32 - 1);
    let ymin = ((y0.min(y1) - r).floor() as i32).max(0).min(h as i32 - 1);
    let ymax = ((y0.max(y1) + r).ceil() as i32).max(0).min(h as i32 - 1);
    if xmax <= xmin || ymax <= ymin {
        return;
    }
    let dx = x1 - x0;
    let dy = y1 - y0;
    let l2 = dx * dx + dy * dy + _EPS;
    let inv_r = 1.0 / r.max(0.5);
    for y in ymin..=ymax {
        let yf = y as f32;
        for x in xmin..=xmax {
            let xf = x as f32;
            let t = ((xf - x0) * dx + (yf - y0) * dy) / l2;
            let t_clip = t.clamp(0.0, 1.0);
            let px = x0 + t_clip * dx;
            let py = y0 + t_clip * dy;
            let ddx = xf - px;
            let ddy = yf - py;
            let d = (ddx * ddx + ddy * ddy).sqrt();
            let d_alpha = (1.0 - d * inv_r).clamp(0.0, 1.0);
            let length_alpha = (1.0 - t_clip).clamp(0.0, 1.0);
            let a = d_alpha * length_alpha * alpha_scale;
            if a <= 0.0 {
                continue;
            }
            let off = ((y as usize) * w + (x as usize)) * 3;
            alpha_over(buf, off, color, a);
        }
    }
}

fn draw_dot(
    buf: &mut [f32],
    w: usize,
    h: usize,
    cx: f32,
    cy: f32,
    color: [f32; 3],
    radius: f32,
    alpha_scale: f32,
) {
    let r = radius.max(0.5);
    let xmin = ((cx - r).floor() as i32).max(0).min(w as i32 - 1);
    let xmax = ((cx + r).ceil() as i32).max(0).min(w as i32 - 1);
    let ymin = ((cy - r).floor() as i32).max(0).min(h as i32 - 1);
    let ymax = ((cy + r).ceil() as i32).max(0).min(h as i32 - 1);
    if xmax <= xmin || ymax <= ymin {
        return;
    }
    let rim = r - 1.0;
    let inv_falloff = 1.0 / 1.4;
    for y in ymin..=ymax {
        let yf = y as f32;
        for x in xmin..=xmax {
            let xf = x as f32;
            let ddx = xf - cx;
            let ddy = yf - cy;
            let d = (ddx * ddx + ddy * ddy).sqrt();
            let a = (1.0 - (d - rim) * inv_falloff).clamp(0.0, 1.0) * alpha_scale;
            if a <= 0.0 {
                continue;
            }
            let off = ((y as usize) * w + (x as usize)) * 3;
            alpha_over(buf, off, color, a);
        }
    }
}

/// Render droplet tails: each particle gets a velocity-aligned streak
/// (alpha fading from full at the head to 0 at the tail tip) and a head
/// dot.  N is small (low-density particles only) so this stays
/// sequential — the work-per-particle is bounded and Rayon overhead would
/// dominate.
#[pyfunction]
#[pyo3(signature = (
    hdr_rgb,
    tail_xy0, tail_xy1, head_xy,
    head_colors, halo_colors, alpha, tail_alpha,
    width, height, head_radius,
))]
pub fn draw_droplet_tails_rs(
    hdr_rgb: &Bound<'_, PyByteArray>,
    tail_xy0: &[u8],     // (N, 2) f32
    tail_xy1: &[u8],     // (N, 2) f32
    head_xy: &[u8],      // (N, 2) f32
    head_colors: &[u8],  // (N, 3) f32
    halo_colors: &[u8],  // (N, 3) f32
    alpha: &[u8],        // (N,) f32 — droplet alpha
    tail_alpha: f32,
    width: usize,
    height: usize,
    head_radius: f32,
) -> PyResult<()> {
    check_hdr_len(hdr_rgb.len(), width, height)?;
    let t0: &[f32] = cast_slice(tail_xy0);
    let t1: &[f32] = cast_slice(tail_xy1);
    let hxy: &[f32] = cast_slice(head_xy);
    let hcol: &[f32] = cast_slice(head_colors);
    let halo: &[f32] = cast_slice(halo_colors);
    let a_s: &[f32] = cast_slice(alpha);
    let n = a_s.len();
    if t0.len() != n * 2 || t1.len() != n * 2 || hxy.len() != n * 2 {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "tail/head xy arrays must be (N, 2) f32",
        ));
    }
    if hcol.len() != n * 3 || halo.len() != n * 3 {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "head/halo color arrays must be (N, 3) f32",
        ));
    }

    let buf: &mut [u8] = unsafe { hdr_rgb.as_bytes_mut() };
    let hdr: &mut [f32] = bytemuck::cast_slice_mut(buf);

    for i in 0..n {
        let a = a_s[i];
        if a <= 0.0 {
            continue;
        }
        let x0 = t0[2 * i];
        let y0 = t0[2 * i + 1];
        let x1 = t1[2 * i];
        let y1 = t1[2 * i + 1];
        // Skip near-zero-length tails to match Python's tail_len > 0.5 gate.
        let dxx = x1 - x0;
        let dyy = y1 - y0;
        if (dxx * dxx + dyy * dyy).sqrt() > 0.5 {
            let halo_col = [
                halo[3 * i],
                halo[3 * i + 1],
                halo[3 * i + 2],
            ];
            draw_streak(hdr, width, height, x0, y0, x1, y1, halo_col, a * tail_alpha);
        }
        let head_col = [hcol[3 * i], hcol[3 * i + 1], hcol[3 * i + 2]];
        let hx = hxy[2 * i];
        let hy = hxy[2 * i + 1];
        draw_dot(hdr, width, height, hx, hy, head_col, head_radius, a);
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// 5b. Alpha composite (HDR over HDR).
// ---------------------------------------------------------------------------

/// `hdr[:] = hdr * (1 - alpha) + col * alpha`, all (H, W, 3) f32.
/// `alpha` is (H, W) f32.
#[pyfunction]
#[pyo3(signature = (hdr_rgb, col_rgb, alpha2d, width, height))]
pub fn alpha_composite_hdr_rs(
    hdr_rgb: &Bound<'_, PyByteArray>,
    col_rgb: &[u8],
    alpha2d: &[u8],
    width: usize,
    height: usize,
) -> PyResult<()> {
    check_hdr_len(hdr_rgb.len(), width, height)?;
    check_hdr_len(col_rgb.len(), width, height)?;
    check_grid_len(alpha2d.len(), width, height)?;
    let col: &[f32] = cast_slice(col_rgb);
    let alpha: &[f32] = cast_slice(alpha2d);
    let buf: &mut [u8] = unsafe { hdr_rgb.as_bytes_mut() };
    let hdr: &mut [f32] = bytemuck::cast_slice_mut(buf);

    hdr.par_chunks_exact_mut(3 * width)
        .zip(col.par_chunks_exact(3 * width))
        .zip(alpha.par_chunks_exact(width))
        .for_each(|((hrow, crow), arow)| {
            for x in 0..width {
                let a = arow[x];
                let inv = 1.0 - a;
                let off = 3 * x;
                hrow[off] = hrow[off] * inv + crow[off] * a;
                hrow[off + 1] = hrow[off + 1] * inv + crow[off + 1] * a;
                hrow[off + 2] = hrow[off + 2] * inv + crow[off + 2] * a;
            }
        });
    Ok(())
}

// ---------------------------------------------------------------------------
// 6. HDR -> u8 tonemap (Reinhard + gamma).
// ---------------------------------------------------------------------------

/// Convert an HDR float32 (H, W, 3) buffer to a u8 (H, W, 3) buffer using
/// the same Reinhard + gamma chain as Python `_post_process`:
///   x = (hdr/255) * exposure
///   x = x / (1 + x)
///   x = clamp(x, 0, 1) ^ (1/gamma)
///   out = u8(x * 255)
#[pyfunction]
#[pyo3(signature = (
    hdr_rgb, out_u8, width, height,
    exposure, gamma,
))]
pub fn post_process_hdr_rs(
    hdr_rgb: &[u8],
    out_u8: &Bound<'_, PyByteArray>,
    width: usize,
    height: usize,
    exposure: f32,
    gamma: f32,
) -> PyResult<()> {
    check_hdr_len(hdr_rgb.len(), width, height)?;
    let need = width * height * 3;
    if out_u8.len() < need {
        return Err(pyo3::exceptions::PyValueError::new_err(format!(
            "out_u8 too small: {} < {}", out_u8.len(), need
        )));
    }
    let src: &[f32] = cast_slice(hdr_rgb);
    let dst: &mut [u8] = unsafe { out_u8.as_bytes_mut() };
    let inv255 = 1.0 / 255.0;
    let inv_gamma = 1.0 / gamma.max(_EPS);
    dst.par_chunks_exact_mut(3 * width)
        .zip(src.par_chunks_exact(3 * width))
        .for_each(|(drow, srow)| {
            for x in 0..width {
                let i = 3 * x;
                let mut r = srow[i] * inv255 * exposure;
                let mut g = srow[i + 1] * inv255 * exposure;
                let mut b = srow[i + 2] * inv255 * exposure;
                // Handle nan/inf (matches np.nan_to_num before u8 cast).
                if !r.is_finite() { r = if r > 0.0 { 1.0 } else { 0.0 }; }
                if !g.is_finite() { g = if g > 0.0 { 1.0 } else { 0.0 }; }
                if !b.is_finite() { b = if b > 0.0 { 1.0 } else { 0.0 }; }
                r = r / (1.0 + r);
                g = g / (1.0 + g);
                b = b / (1.0 + b);
                r = r.clamp(0.0, 1.0).powf(inv_gamma);
                g = g.clamp(0.0, 1.0).powf(inv_gamma);
                b = b.clamp(0.0, 1.0).powf(inv_gamma);
                drow[i] = (r * 255.0).clamp(0.0, 255.0) as u8;
                drow[i + 1] = (g * 255.0).clamp(0.0, 255.0) as u8;
                drow[i + 2] = (b * 255.0).clamp(0.0, 255.0) as u8;
            }
        });
    Ok(())
}

// ---------------------------------------------------------------------------
// 7. Outline pass — anti-aliased lines onto a float HDR buffer.
// ---------------------------------------------------------------------------

fn draw_line_f32(
    buf: &mut [f32],
    w: usize,
    h: usize,
    x0: f32,
    y0: f32,
    x1: f32,
    y1: f32,
    color: [f32; 3],
    thickness: f32,
) {
    let r = thickness.max(0.5);
    let xmin = ((x0.min(x1) - r).floor() as i32).max(0).min(w as i32 - 1);
    let xmax = ((x0.max(x1) + r).ceil() as i32).max(0).min(w as i32 - 1);
    let ymin = ((y0.min(y1) - r).floor() as i32).max(0).min(h as i32 - 1);
    let ymax = ((y0.max(y1) + r).ceil() as i32).max(0).min(h as i32 - 1);
    if xmax <= xmin || ymax <= ymin {
        return;
    }
    let dx = x1 - x0;
    let dy = y1 - y0;
    let l2 = dx * dx + dy * dy + _EPS;
    let rim = r - 1.0;
    let inv_falloff = 1.0 / 1.5;
    for y in ymin..=ymax {
        let yf = y as f32;
        for x in xmin..=xmax {
            let xf = x as f32;
            let t = ((xf - x0) * dx + (yf - y0) * dy) / l2;
            let t = t.clamp(0.0, 1.0);
            let px = x0 + t * dx;
            let py = y0 + t * dy;
            let ddx = xf - px;
            let ddy = yf - py;
            let d = (ddx * ddx + ddy * ddy).sqrt();
            let a = (1.0 - (d - rim) * inv_falloff).clamp(0.0, 1.0);
            if a <= 0.0 {
                continue;
            }
            let off = ((y as usize) * w + (x as usize)) * 3;
            let inv = 1.0 - a;
            buf[off] = buf[off] * inv + color[0] * a;
            buf[off + 1] = buf[off + 1] * inv + color[1] * a;
            buf[off + 2] = buf[off + 2] * inv + color[2] * a;
        }
    }
}

/// Rasterise N anti-aliased line segments onto an HDR float RGB buffer.
/// Matches Python `_line`'s alpha-over semantics with a single colour
/// shared across all segments (used by the surface outline pass).
#[pyfunction]
#[pyo3(signature = (
    hdr_rgb, xa, ya, xb, yb,
    color_r, color_g, color_b,
    width, height, thickness,
))]
pub fn rasterize_lines_hdr_rs(
    hdr_rgb: &Bound<'_, PyByteArray>,
    xa: &[u8],
    ya: &[u8],
    xb: &[u8],
    yb: &[u8],
    color_r: f32,
    color_g: f32,
    color_b: f32,
    width: usize,
    height: usize,
    thickness: f32,
) -> PyResult<()> {
    check_hdr_len(hdr_rgb.len(), width, height)?;
    let xa_f: &[f32] = cast_slice(xa);
    let ya_f: &[f32] = cast_slice(ya);
    let xb_f: &[f32] = cast_slice(xb);
    let yb_f: &[f32] = cast_slice(yb);
    let n = xa_f.len();
    if ya_f.len() != n || xb_f.len() != n || yb_f.len() != n {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "coordinate arrays must have equal length",
        ));
    }
    let buf: &mut [u8] = unsafe { hdr_rgb.as_bytes_mut() };
    let hdr: &mut [f32] = bytemuck::cast_slice_mut(buf);
    let color = [color_r, color_g, color_b];
    for i in 0..n {
        draw_line_f32(hdr, width, height, xa_f[i], ya_f[i], xb_f[i], yb_f[i], color, thickness);
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// 9. Fused base surface shading.
//
// Inputs:
//   density grid (ny, nx) f32, world origin / cell size, world view box,
//   iso, softness, lambert strength, light dir (unit), core/halo colors.
// Outputs (all (H, W) row-major f32 unless noted):
//   d_screen — bilinear-resampled density at pixel centres
//   alpha2d  — smoothstep mask over (iso*(1-soft/2), iso*(1+soft/2))
//   gx_d, gy_d — central differences on d_screen
//   nx_v, ny_v — outward normals (-grad/|grad|)
//   rim2d    — gaussian rim near iso
//   col      — (H, W, 3) base surface color = core*shade + (halo-core)*rim*0.4
//
// Matches Python `_draw_surface` lines 619-697 bit-for-bit.
// ---------------------------------------------------------------------------

/// Build the surface base-shading buffers in one fused pass. Returns
/// arrays via a writable container of bytearrays/PyByteArrays the caller
/// pre-allocated.
#[pyfunction]
#[pyo3(signature = (
    density_grid, nx, ny,
    gx0, gy0, cell_size,
    wx0_w, wy0_w, wx1_w, wy1_w,
    width, height,
    iso, softness, lambert_strength,
    ldx, ldy,
    core_r, core_g, core_b,
    halo_r, halo_g, halo_b,
    col_out, d_screen_out, alpha_out, gx_d_out, gy_d_out,
    nxv_out, nyv_out, rim_out,
))]
pub fn surface_base_shade_rs(
    density_grid: &[u8],
    nx: usize,
    ny: usize,
    gx0: f32,
    gy0: f32,
    cell_size: f32,
    wx0_w: f32,
    wy0_w: f32,
    wx1_w: f32,
    wy1_w: f32,
    width: usize,
    height: usize,
    iso: f32,
    softness: f32,
    lambert_strength: f32,
    ldx: f32,
    ldy: f32,
    core_r: f32,
    core_g: f32,
    core_b: f32,
    halo_r: f32,
    halo_g: f32,
    halo_b: f32,
    col_out: &Bound<'_, PyByteArray>,
    d_screen_out: &Bound<'_, PyByteArray>,
    alpha_out: &Bound<'_, PyByteArray>,
    gx_d_out: &Bound<'_, PyByteArray>,
    gy_d_out: &Bound<'_, PyByteArray>,
    nxv_out: &Bound<'_, PyByteArray>,
    nyv_out: &Bound<'_, PyByteArray>,
    rim_out: &Bound<'_, PyByteArray>,
) -> PyResult<()> {
    check_hdr_len(col_out.len(), width, height)?;
    check_grid_len(d_screen_out.len(), width, height)?;
    check_grid_len(alpha_out.len(), width, height)?;
    check_grid_len(gx_d_out.len(), width, height)?;
    check_grid_len(gy_d_out.len(), width, height)?;
    check_grid_len(nxv_out.len(), width, height)?;
    check_grid_len(nyv_out.len(), width, height)?;
    check_grid_len(rim_out.len(), width, height)?;
    if density_grid.len() < nx * ny * 4 {
        return Err(pyo3::exceptions::PyValueError::new_err("density too small"));
    }
    let density: &[f32] = cast_slice(density_grid);

    // Step 1: bilinear resample density into d_screen and step 2: alpha.
    let w = width;
    let h = height;
    let wf = w as f32;
    let hf = h as f32;
    let view_dx_per_px = (wx1_w - wx0_w) / wf.max(1.0);
    let view_dy_per_px = (wy1_w - wy0_w) / hf.max(1.0);
    let inv_cell = 1.0 / cell_size;

    // Smoothstep edge values.
    let edge0 = iso * (1.0 - softness * 0.5).max(0.05);
    let edge1 = iso * (1.0 + softness * 0.5);
    let denom = (edge1 - edge0).max(_EPS);

    let rim_denom = (iso * 0.25).powi(2).max(_EPS);

    // Grab mut slices.
    let d_screen: &mut [f32] = bytemuck::cast_slice_mut(
        unsafe { d_screen_out.as_bytes_mut() }
    );
    let alpha_buf: &mut [f32] = bytemuck::cast_slice_mut(
        unsafe { alpha_out.as_bytes_mut() }
    );
    let rim_buf: &mut [f32] = bytemuck::cast_slice_mut(
        unsafe { rim_out.as_bytes_mut() }
    );

    // Step 1+2+rim fused (per-pixel parallel).
    d_screen.par_chunks_exact_mut(w)
        .zip(alpha_buf.par_chunks_exact_mut(w))
        .zip(rim_buf.par_chunks_exact_mut(w))
        .enumerate()
        .for_each(|(y, ((drow, arow), rrow))| {
            let wy = wy0_w + (y as f32 + 0.5) * view_dy_per_px;
            let gy_f = (wy - gy0) * inv_cell - 0.5;
            let j0 = (gy_f.floor() as i32).clamp(0, ny as i32 - 2) as usize;
            let fy = gy_f - j0 as f32;
            let row_j0 = j0 * nx;
            let row_j1 = (j0 + 1) * nx;
            for x in 0..w {
                let wx = wx0_w + (x as f32 + 0.5) * view_dx_per_px;
                let gx_f = (wx - gx0) * inv_cell - 0.5;
                let i0 = (gx_f.floor() as i32).clamp(0, nx as i32 - 2) as usize;
                let fx = gx_f - i0 as f32;
                let d00 = density[row_j0 + i0];
                let d10 = density[row_j0 + i0 + 1];
                let d01 = density[row_j1 + i0];
                let d11 = density[row_j1 + i0 + 1];
                let d = d00 * (1.0 - fx) * (1.0 - fy)
                    + d10 * fx * (1.0 - fy)
                    + d01 * (1.0 - fx) * fy
                    + d11 * fx * fy;
                drow[x] = d;

                // Smoothstep alpha
                let t = ((d - edge0) / denom).clamp(0.0, 1.0);
                arow[x] = t * t * (3.0 - 2.0 * t);

                // Rim gaussian
                let diff = d - iso;
                rrow[x] = (-(diff * diff) / rim_denom).exp();
            }
        });

    // Step 3: central differences on d_screen (gx, gy). Edge cells get 0
    // to match the Python np.zeros initialisation + slice assignment.
    let gx_buf: &mut [f32] = bytemuck::cast_slice_mut(
        unsafe { gx_d_out.as_bytes_mut() }
    );
    let gy_buf: &mut [f32] = bytemuck::cast_slice_mut(
        unsafe { gy_d_out.as_bytes_mut() }
    );
    let nxv_buf: &mut [f32] = bytemuck::cast_slice_mut(
        unsafe { nxv_out.as_bytes_mut() }
    );
    let nyv_buf: &mut [f32] = bytemuck::cast_slice_mut(
        unsafe { nyv_out.as_bytes_mut() }
    );
    let col_buf: &mut [f32] = bytemuck::cast_slice_mut(
        unsafe { col_out.as_bytes_mut() }
    );

    let halo_diff = [halo_r - core_r, halo_g - core_g, halo_b - core_b];
    let lam = lambert_strength;
    let do_lambert = lam > 0.0;

    // Combined pass: gradients, normals, lambert, col.
    let gx_ptr = gx_buf.as_mut_ptr() as usize;
    let gy_ptr = gy_buf.as_mut_ptr() as usize;
    let nxv_ptr = nxv_buf.as_mut_ptr() as usize;
    let nyv_ptr = nyv_buf.as_mut_ptr() as usize;
    let col_ptr = col_buf.as_mut_ptr() as usize;
    let d_ptr = d_screen.as_ptr() as usize;
    let rim_ptr = rim_buf.as_ptr() as usize;
    let total = w * h;
    let total3 = total * 3;

    (0..h).into_par_iter().for_each(|y| {
        let gx = unsafe { std::slice::from_raw_parts_mut(gx_ptr as *mut f32, total) };
        let gy = unsafe { std::slice::from_raw_parts_mut(gy_ptr as *mut f32, total) };
        let nxv = unsafe { std::slice::from_raw_parts_mut(nxv_ptr as *mut f32, total) };
        let nyv = unsafe { std::slice::from_raw_parts_mut(nyv_ptr as *mut f32, total) };
        let col = unsafe { std::slice::from_raw_parts_mut(col_ptr as *mut f32, total3) };
        let d = unsafe { std::slice::from_raw_parts(d_ptr as *const f32, total) };
        let rim = unsafe { std::slice::from_raw_parts(rim_ptr as *const f32, total) };

        let row_off = y * w;
        let row_off3 = y * w * 3;
        let row_up = if y > 0 { (y - 1) * w } else { row_off };
        let row_dn = if y + 1 < h { (y + 1) * w } else { row_off };
        for x in 0..w {
            // gx (central diff in x). Edges zero.
            let g_x = if x == 0 || x + 1 >= w {
                0.0
            } else {
                (d[row_off + x + 1] - d[row_off + x - 1]) * 0.5
            };
            // gy (central diff in y). Edges zero.
            let g_y = if y == 0 || y + 1 >= h {
                0.0
            } else {
                (d[row_dn + x] - d[row_up + x]) * 0.5
            };
            gx[row_off + x] = g_x;
            gy[row_off + x] = g_y;

            // Normals.
            let mag = (g_x * g_x + g_y * g_y).sqrt();
            let (nv_x, nv_y) = if mag > _EPS {
                (-g_x / mag, -g_y / mag)
            } else {
                (0.0, 0.0)
            };
            nxv[row_off + x] = nv_x;
            nyv[row_off + x] = nv_y;

            // Lambert.
            let shade = if do_lambert {
                let lam_dot = (-(nv_x * ldx + nv_y * ldy)).clamp(0.0, 1.0);
                1.0 + lam * lam_dot
            } else {
                1.0
            };

            // Base color = core*shade + (halo-core)*rim*0.4.
            let rim_v = rim[row_off + x];
            let m = rim_v * 0.4;
            col[row_off3 + 3 * x] = core_r * shade + halo_diff[0] * m;
            col[row_off3 + 3 * x + 1] = core_g * shade + halo_diff[1] * m;
            col[row_off3 + 3 * x + 2] = core_b * shade + halo_diff[2] * m;
        }
    });

    Ok(())
}

// ---------------------------------------------------------------------------
// 10. Speed-screen builder — bilinearly sample speed grid (after density
// normalisation) onto screen pixels using the same indices as the base
// shading bilinear sampler.
// ---------------------------------------------------------------------------

/// Compute screen-space speed buffer:
///   sp_grid = poly6_splat(positions, speed)
///   sp_norm = sp_grid / (density_grid + 1e-3)
///   sp_screen = bilinear_resample(sp_norm)
///
/// Inputs: density grid + already-built sp_grid (caller computes via
/// `sample_density_grid_rs` with `speed` as the weight). Returns
/// `sp_screen` as a writable (H, W) f32 bytearray.
#[pyfunction]
#[pyo3(signature = (
    sp_grid, density_grid, sp_screen_out,
    nx, ny, gx0, gy0, cell_size,
    wx0_w, wy0_w, wx1_w, wy1_w,
    width, height,
))]
pub fn speed_screen_rs(
    sp_grid: &[u8],
    density_grid: &[u8],
    sp_screen_out: &Bound<'_, PyByteArray>,
    nx: usize,
    ny: usize,
    gx0: f32,
    gy0: f32,
    cell_size: f32,
    wx0_w: f32,
    wy0_w: f32,
    wx1_w: f32,
    wy1_w: f32,
    width: usize,
    height: usize,
) -> PyResult<()> {
    check_grid_len(sp_screen_out.len(), width, height)?;
    if sp_grid.len() < nx * ny * 4 || density_grid.len() < nx * ny * 4 {
        return Err(pyo3::exceptions::PyValueError::new_err("grid too small"));
    }
    let sp: &[f32] = cast_slice(sp_grid);
    let den: &[f32] = cast_slice(density_grid);
    let out: &mut [f32] = bytemuck::cast_slice_mut(
        unsafe { sp_screen_out.as_bytes_mut() }
    );

    let w = width;
    let h = height;
    let wf = w as f32;
    let hf = h as f32;
    let view_dx_per_px = (wx1_w - wx0_w) / wf.max(1.0);
    let view_dy_per_px = (wy1_w - wy0_w) / hf.max(1.0);
    let inv_cell = 1.0 / cell_size;

    out.par_chunks_exact_mut(w).enumerate().for_each(|(y, row)| {
        let wy = wy0_w + (y as f32 + 0.5) * view_dy_per_px;
        let gy_f = (wy - gy0) * inv_cell - 0.5;
        let j0 = (gy_f.floor() as i32).clamp(0, ny as i32 - 2) as usize;
        let fy = gy_f - j0 as f32;
        let row_j0 = j0 * nx;
        let row_j1 = (j0 + 1) * nx;
        for x in 0..w {
            let wx = wx0_w + (x as f32 + 0.5) * view_dx_per_px;
            let gx_f = (wx - gx0) * inv_cell - 0.5;
            let i0 = (gx_f.floor() as i32).clamp(0, nx as i32 - 2) as usize;
            let fx = gx_f - i0 as f32;
            // Divide each cell by density+1e-3 first (matches Python).
            let s00 = sp[row_j0 + i0] / (den[row_j0 + i0] + 1.0e-3);
            let s10 = sp[row_j0 + i0 + 1] / (den[row_j0 + i0 + 1] + 1.0e-3);
            let s01 = sp[row_j1 + i0] / (den[row_j1 + i0] + 1.0e-3);
            let s11 = sp[row_j1 + i0 + 1] / (den[row_j1 + i0 + 1] + 1.0e-3);
            row[x] = s00 * (1.0 - fx) * (1.0 - fy)
                + s10 * fx * (1.0 - fy)
                + s01 * (1.0 - fx) * fy
                + s11 * fx * fy;
        }
    });
    Ok(())
}

// ---------------------------------------------------------------------------
// 8. Poly6 density grid splat — Rust port of `sample_density_grid`.
// ---------------------------------------------------------------------------

/// Splat N particles into a (ny, nx) row-major f32 density grid using the
/// 2D poly6 kernel. Matches Python `sample_density_grid` semantics.
///
/// `positions` is `(N, 2)` f32 bytes; `weights` is `(N,)` f32 bytes (the
/// per-particle mass, or just `1` for the speed-weighted variant). The
/// output is written to `grid` row-major `(ny, nx)` f32.
#[pyfunction]
#[pyo3(signature = (
    positions, weights, grid,
    nx, ny,
    origin_x, origin_y, kernel_radius, cell_size,
))]
pub fn sample_density_grid_rs(
    positions: &[u8],
    weights: &[u8],
    grid: &Bound<'_, PyByteArray>,
    nx: usize,
    ny: usize,
    origin_x: f32,
    origin_y: f32,
    kernel_radius: f32,
    cell_size: f32,
) -> PyResult<()> {
    let pos: &[f32] = cast_slice(positions);
    let w_arr: &[f32] = cast_slice(weights);
    let n = w_arr.len();
    if pos.len() != n * 2 {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "positions must be (N, 2) f32",
        ));
    }
    let need = nx * ny * 4;
    if grid.len() < need {
        return Err(pyo3::exceptions::PyValueError::new_err(format!(
            "grid too small: {} < {}", grid.len(), need
        )));
    }
    let buf: &mut [u8] = unsafe { grid.as_bytes_mut() };
    let g: &mut [f32] = bytemuck::cast_slice_mut(buf);
    for v in g.iter_mut() { *v = 0.0; }

    if n == 0 || kernel_radius <= 0.0 || cell_size <= 0.0 {
        return Ok(());
    }
    let h = kernel_radius;
    let h2 = h * h;
    let h4 = h2 * h2;
    let h8 = h4 * h4;
    let coef = 4.0 / (std::f32::consts::PI * h8);
    let inv_cell = 1.0 / cell_size;
    let r_cells = ((h * inv_cell).ceil() as i32) + 1;

    for p_i in 0..n {
        let px = pos[2 * p_i] - origin_x;
        let py = pos[2 * p_i + 1] - origin_y;
        let cx = (px * inv_cell).floor() as i32;
        let cy = (py * inv_cell).floor() as i32;
        let m_i = w_arr[p_i];
        // Particle world position (un-shifted by origin: positions[i] = px + origin_x).
        let pwx = pos[2 * p_i];
        let pwy = pos[2 * p_i + 1];

        let cx_min = (cx - r_cells).max(0);
        let cx_max = (cx + r_cells).min(nx as i32 - 1);
        let cy_min = (cy - r_cells).max(0);
        let cy_max = (cy + r_cells).min(ny as i32 - 1);
        for ty in cy_min..=cy_max {
            let wy = origin_y + (ty as f32 + 0.5) * cell_size;
            let dy = wy - pwy;
            let dy2 = dy * dy;
            let row_off = (ty as usize) * nx;
            for tx in cx_min..=cx_max {
                let wx = origin_x + (tx as f32 + 0.5) * cell_size;
                let dx = wx - pwx;
                let r2 = dx * dx + dy2;
                if r2 < h2 {
                    let diff = h2 - r2;
                    let k = coef * diff * diff * diff * m_i;
                    g[row_off + tx as usize] += k;
                }
            }
        }
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// 11. Marching squares isoline extraction.
// ---------------------------------------------------------------------------

// Edge endpoints (in (cell_x, cell_y) corner ordering).
// Corners: 0=BL, 1=BR, 2=TR, 3=TL.
// Edges interpolate between two adjacent corners.
// Edge index → (corner_a, corner_b) but we just need the density samples
// at each edge to do linear interp. Python order: BL→BR (edge 0),
// BR→TR (edge 1), TR→TL (edge 2), TL→BL (edge 3).
//
// Each MS case → list of edge-pair segments. Mirrors Python EDGE_TABLE.
const EDGE_TABLE: [&[(u8, u8)]; 16] = [
    &[],                       // 0
    &[(3, 0)],                 // 1
    &[(0, 1)],                 // 2
    &[(3, 1)],                 // 3
    &[(1, 2)],                 // 4
    &[(3, 0), (1, 2)],         // 5
    &[(0, 2)],                 // 6
    &[(3, 2)],                 // 7
    &[(2, 3)],                 // 8
    &[(0, 2)],                 // 9
    &[(0, 1), (2, 3)],         // 10
    &[(1, 2)],                 // 11
    &[(3, 1)],                 // 12
    &[(0, 1)],                 // 13
    &[(0, 3)],                 // 14
    &[],                       // 15
];

#[inline(always)]
fn edge_vertex(
    edge: u8,
    cell_x: i32,
    cell_y: i32,
    d00: f32,
    d10: f32,
    d11: f32,
    d01: f32,
    iso: f32,
    ox: f32,
    oy: f32,
    cell_size: f32,
) -> (f32, f32) {
    // Corners: BL=(cx,cy)=d00, BR=(cx+1,cy)=d10, TR=(cx+1,cy+1)=d11, TL=(cx,cy+1)=d01.
    let bl_x = ox + cell_x as f32 * cell_size;
    let bl_y = oy + cell_y as f32 * cell_size;
    let eps = 1.0e-9_f32;
    match edge {
        0 => {
            // BL → BR (along x at y=BL).
            let v0 = d00; let v1 = d10;
            let denom = v1 - v0;
            let t = if denom.abs() < eps { 0.5 } else { (iso - v0) / denom };
            (bl_x + t * cell_size, bl_y)
        }
        1 => {
            // BR → TR (along y at x=BR).
            let v0 = d10; let v1 = d11;
            let denom = v1 - v0;
            let t = if denom.abs() < eps { 0.5 } else { (iso - v0) / denom };
            (bl_x + cell_size, bl_y + t * cell_size)
        }
        2 => {
            // TR → TL (along x at y=TR, reversed): Python uses (cell_size - t*cell_size).
            let v0 = d11; let v1 = d01;
            let denom = v1 - v0;
            let t = if denom.abs() < eps { 0.5 } else { (iso - v0) / denom };
            (bl_x + cell_size - t * cell_size, bl_y + cell_size)
        }
        3 => {
            // TL → BL (along y at x=TL, reversed).
            let v0 = d01; let v1 = d00;
            let denom = v1 - v0;
            let t = if denom.abs() < eps { 0.5 } else { (iso - v0) / denom };
            (bl_x, bl_y + cell_size - t * cell_size)
        }
        _ => (bl_x, bl_y),
    }
}

/// Extract marching-squares isoline segments. Returns the raw segments
/// as a flat Vec<u8> buffer: each segment is 4 f32s (x0, y0, x1, y1).
///
/// Python expects an (M, 2, 2) array; the wrapper reshapes from
/// `np.frombuffer(bytes(buf), f32).reshape(M, 2, 2)`. Order follows the
/// Python loop: for each code in 0..16, for each edge_pair in EDGE_TABLE,
/// for each non-zero cell, emit (a, b). Reproduces the Python emit order.
#[pyfunction]
#[pyo3(signature = (
    density_grid, nx, ny,
    iso, origin_x, origin_y, cell_size,
))]
pub fn extract_isolines_rs(
    density_grid: &[u8],
    nx: usize,
    ny: usize,
    iso: f32,
    origin_x: f32,
    origin_y: f32,
    cell_size: f32,
    py: Python<'_>,
) -> PyResult<PyObject> {
    use pyo3::types::PyBytes;
    if nx < 2 || ny < 2 || density_grid.len() < nx * ny * 4 {
        return Ok(PyBytes::new_bound(py, &[]).into_py(py));
    }
    let density: &[f32] = cast_slice(density_grid);

    // Precompute the case grid for the (ny-1) x (nx-1) cells.
    let cw = nx - 1;
    let ch = ny - 1;
    let mut case_grid: Vec<u8> = vec![0; cw * ch];
    for cy in 0..ch {
        let row_j0 = cy * nx;
        let row_j1 = (cy + 1) * nx;
        for cx in 0..cw {
            let bl = if density[row_j0 + cx] >= iso { 1u8 } else { 0u8 };
            let br = if density[row_j0 + cx + 1] >= iso { 1u8 } else { 0u8 };
            let tr = if density[row_j1 + cx + 1] >= iso { 1u8 } else { 0u8 };
            let tl = if density[row_j1 + cx] >= iso { 1u8 } else { 0u8 };
            case_grid[cy * cw + cx] = bl | (br << 1) | (tr << 2) | (tl << 3);
        }
    }

    // Match Python: for each code in 0..16, for each edge pair, then
    // sweep the full case grid for cells matching that code. Cells emit
    // in row-major scan order.
    let mut out_f32: Vec<f32> = Vec::with_capacity(64 * 4);
    for code in 0u8..16 {
        let edges = EDGE_TABLE[code as usize];
        if edges.is_empty() {
            continue;
        }
        for &(e_a, e_b) in edges {
            for cy in 0..ch {
                for cx in 0..cw {
                    if case_grid[cy * cw + cx] != code {
                        continue;
                    }
                    let row_j0 = cy * nx;
                    let row_j1 = (cy + 1) * nx;
                    let d00 = density[row_j0 + cx];
                    let d10 = density[row_j0 + cx + 1];
                    let d11 = density[row_j1 + cx + 1];
                    let d01 = density[row_j1 + cx];
                    let (ax, ay) = edge_vertex(
                        e_a, cx as i32, cy as i32,
                        d00, d10, d11, d01, iso,
                        origin_x, origin_y, cell_size,
                    );
                    let (bx, by) = edge_vertex(
                        e_b, cx as i32, cy as i32,
                        d00, d10, d11, d01, iso,
                        origin_x, origin_y, cell_size,
                    );
                    out_f32.push(ax);
                    out_f32.push(ay);
                    out_f32.push(bx);
                    out_f32.push(by);
                }
            }
        }
    }
    let bytes: &[u8] = bytemuck::cast_slice(&out_f32);
    Ok(PyBytes::new_bound(py, bytes).into_py(py))
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(turbulence_foam_rs, m)?)?;
    m.add_function(wrap_pyfunction!(refraction_warp_rs, m)?)?;
    m.add_function(wrap_pyfunction!(godrays_rs, m)?)?;
    m.add_function(wrap_pyfunction!(specular_pass_rs, m)?)?;
    m.add_function(wrap_pyfunction!(draw_droplet_tails_rs, m)?)?;
    m.add_function(wrap_pyfunction!(alpha_composite_hdr_rs, m)?)?;
    m.add_function(wrap_pyfunction!(post_process_hdr_rs, m)?)?;
    m.add_function(wrap_pyfunction!(rasterize_lines_hdr_rs, m)?)?;
    m.add_function(wrap_pyfunction!(sample_density_grid_rs, m)?)?;
    m.add_function(wrap_pyfunction!(surface_base_shade_rs, m)?)?;
    m.add_function(wrap_pyfunction!(speed_screen_rs, m)?)?;
    m.add_function(wrap_pyfunction!(extract_isolines_rs, m)?)?;
    Ok(())
}
