//! Software rasterization kernels for the softbody renderer.
//!
//! Three hot-path operations are exposed to Python:
//! * [`rasterize_lines`] — batched line draw with optional thickness.
//! * [`rasterize_circles`] — batched filled-disk draw for nodes/particles.
//! * [`box_blur_rgb`] — separable cumulative-sum box blur (in-place).
//!
//! The image buffer is a row-major `(H, W, 3)` `u8` RGB buffer passed as a
//! Python `bytearray` (writable). Coordinate / color inputs arrive as raw
//! byte slices (`&[u8]`) reinterpreted as packed `f32`/`u8` arrays via
//! `bytemuck`. The Python side converts numpy arrays via `.tobytes()` (or
//! `np.ascontiguousarray(...).tobytes()` for safety) — this avoids the
//! per-element overhead of `Vec<f32>` list conversion.

use bytemuck::cast_slice;
use pyo3::prelude::*;
use pyo3::types::PyByteArray;
use rayon::prelude::*;

#[inline(always)]
fn put_pixel(buf: &mut [u8], width: usize, height: usize, x: i32, y: i32, c: [u8; 3]) {
    if x < 0 || y < 0 {
        return;
    }
    let (x, y) = (x as usize, y as usize);
    if x >= width || y >= height {
        return;
    }
    let i = (y * width + x) * 3;
    // Safety: bounds check above guarantees i+2 < buf.len() (assuming
    // buf.len() == width * height * 3).
    unsafe {
        let p = buf.as_mut_ptr().add(i);
        *p = c[0];
        *p.add(1) = c[1];
        *p.add(2) = c[2];
    }
}

/// Bresenham-style line draw with `thickness >= 1`. Thickness > 1 stamps
/// precomputed perpendicular pixel offsets at each step.
fn draw_line(
    buf: &mut [u8],
    width: usize,
    height: usize,
    x0f: f32,
    y0f: f32,
    x1f: f32,
    y1f: f32,
    color: [u8; 3],
    thickness: u32,
    offsets: &[(i32, i32)],
) {
    let mut x0 = x0f.round() as i32;
    let mut y0 = y0f.round() as i32;
    let x1 = x1f.round() as i32;
    let y1 = y1f.round() as i32;

    let dx = (x1 - x0).abs();
    let dy = -(y1 - y0).abs();
    let sx: i32 = if x0 < x1 { 1 } else { -1 };
    let sy: i32 = if y0 < y1 { 1 } else { -1 };
    let mut err = dx + dy;

    let thickness = thickness.max(1) as i32;

    loop {
        if thickness == 1 {
            put_pixel(buf, width, height, x0, y0, color);
        } else {
            for &(ox, oy) in offsets {
                put_pixel(buf, width, height, x0 + ox, y0 + oy, color);
            }
        }
        if x0 == x1 && y0 == y1 {
            break;
        }
        let e2 = 2 * err;
        if e2 >= dy {
            err += dy;
            x0 += sx;
        }
        if e2 <= dx {
            err += dx;
            y0 += sy;
        }
    }
}

/// Rasterise `N` line segments into an RGB byte buffer.
///
/// `buffer` is a `(H, W, 3)` row-major `u8` `bytearray`. `xa`/`ya`/`xb`/`yb`
/// are `&[u8]` slices reinterpreted as `&[f32]` (must be 4-byte aligned with
/// length 4*N). `colors_rgb` is `3*N` bytes — one RGB triple per beam.
#[pyfunction]
#[pyo3(signature = (buffer, width, height, xa, ya, xb, yb, colors_rgb, thickness=1))]
pub fn rasterize_lines(
    buffer: &Bound<'_, PyByteArray>,
    width: u32,
    height: u32,
    xa: &[u8],
    ya: &[u8],
    xb: &[u8],
    yb: &[u8],
    colors_rgb: &[u8],
    thickness: u32,
) -> PyResult<()> {
    let w = width as usize;
    let h = height as usize;
    let expected = w * h * 3;
    if buffer.len() < expected {
        return Err(pyo3::exceptions::PyValueError::new_err(format!(
            "buffer too small: {} < {}",
            buffer.len(),
            expected
        )));
    }
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
    if colors_rgb.len() != n * 3 {
        return Err(pyo3::exceptions::PyValueError::new_err(format!(
            "colors_rgb must be 3*N bytes (got {}, expected {})",
            colors_rgb.len(),
            n * 3
        )));
    }

    // Safety: PyByteArray::as_bytes_mut is unsafe because aliasing rules
    // depend on Python not mutating the bytearray on another thread. We
    // hold the GIL and don't yield it inside the loop.
    let buf: &mut [u8] = unsafe { buffer.as_bytes_mut() };

    let t = thickness.max(1) as i32;
    let half = t / 2;

    // Parallelize over beams. ``buf`` is shared mutably across threads
    // via a raw pointer — we accept the same "last-writer-wins" race
    // semantics the numpy fallback already has at beam crossings, and
    // beams are mostly disjoint in screen space so torn-pixel events
    // are rare. Single-threaded fallback if n is small.
    if n > 64 && colors_rgb.len() == n * 3 {
        let buf_ptr = buf.as_mut_ptr() as usize;
        let buf_len = buf.len();
        let xa_p = xa_f.as_ptr() as usize;
        let ya_p = ya_f.as_ptr() as usize;
        let xb_p = xb_f.as_ptr() as usize;
        let yb_p = yb_f.as_ptr() as usize;
        let col_p = colors_rgb.as_ptr() as usize;
        (0..n).into_par_iter().for_each(|i| {
            let buf = unsafe { std::slice::from_raw_parts_mut(buf_ptr as *mut u8, buf_len) };
            let xa_f = unsafe { std::slice::from_raw_parts(xa_p as *const f32, n) };
            let ya_f = unsafe { std::slice::from_raw_parts(ya_p as *const f32, n) };
            let xb_f = unsafe { std::slice::from_raw_parts(xb_p as *const f32, n) };
            let yb_f = unsafe { std::slice::from_raw_parts(yb_p as *const f32, n) };
            let colors_rgb = unsafe { std::slice::from_raw_parts(col_p as *const u8, n * 3) };

            let c = [colors_rgb[3 * i], colors_rgb[3 * i + 1], colors_rgb[3 * i + 2]];
            let xaf = xa_f[i];
            let yaf = ya_f[i];
            let xbf = xb_f[i];
            let ybf = yb_f[i];

            let mut offsets: [(i32, i32); 8] = [(0, 0); 8];
            let n_off = if t == 1 {
                1
            } else {
                let dxf = xbf - xaf;
                let dyf = ybf - yaf;
                let l = (dxf * dxf + dyf * dyf).sqrt();
                let inv_len = if l > 1e-6 { 1.0 / l } else { 0.0 };
                let pxf = -dyf * inv_len;
                let pyf = dxf * inv_len;
                let count = (t as usize).min(offsets.len());
                for k in 0..count {
                    let off = (k as i32) - half;
                    offsets[k] = (
                        (pxf * off as f32).round() as i32,
                        (pyf * off as f32).round() as i32,
                    );
                }
                count
            };
            draw_line(buf, w, h, xaf, yaf, xbf, ybf, c, thickness, &offsets[..n_off]);
        });
        return Ok(());
    }

    for i in 0..n {
        let c = [colors_rgb[3 * i], colors_rgb[3 * i + 1], colors_rgb[3 * i + 2]];
        let xaf = xa_f[i];
        let yaf = ya_f[i];
        let xbf = xb_f[i];
        let ybf = yb_f[i];

        // Build per-beam offset list (small alloc-free Vec on stack).
        let mut offsets: [(i32, i32); 8] = [(0, 0); 8];
        let n_off = if t == 1 {
            1
        } else {
            let dxf = xbf - xaf;
            let dyf = ybf - yaf;
            let l = (dxf * dxf + dyf * dyf).sqrt();
            let inv_len = if l > 1e-6 { 1.0 / l } else { 0.0 };
            let pxf = -dyf * inv_len;
            let pyf = dxf * inv_len;
            let count = (t as usize).min(offsets.len());
            for k in 0..count {
                let off = (k as i32) - half;
                offsets[k] = (
                    (pxf * off as f32).round() as i32,
                    (pyf * off as f32).round() as i32,
                );
            }
            count
        };

        draw_line(
            buf,
            w,
            h,
            xaf,
            yaf,
            xbf,
            ybf,
            c,
            thickness,
            &offsets[..n_off],
        );
    }
    Ok(())
}

/// Rasterise `N` filled disks into an RGB byte buffer.
///
/// Same buffer / array conventions as [`rasterize_lines`]. `cx`/`cy` are
/// `4*N` byte slices reinterpreted as `f32`; `colors_rgb` is `3*N` bytes.
#[pyfunction]
#[pyo3(signature = (buffer, width, height, cx, cy, colors_rgb, radius=1))]
pub fn rasterize_circles(
    buffer: &Bound<'_, PyByteArray>,
    width: u32,
    height: u32,
    cx: &[u8],
    cy: &[u8],
    colors_rgb: &[u8],
    radius: u32,
) -> PyResult<()> {
    let w = width as usize;
    let h = height as usize;
    let expected = w * h * 3;
    if buffer.len() < expected {
        return Err(pyo3::exceptions::PyValueError::new_err(format!(
            "buffer too small: {} < {}",
            buffer.len(),
            expected
        )));
    }
    let cx_f: &[f32] = cast_slice(cx);
    let cy_f: &[f32] = cast_slice(cy);
    let n = cx_f.len();
    if cy_f.len() != n {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "cx/cy must have equal length",
        ));
    }
    if colors_rgb.len() != n * 3 {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "colors_rgb must be 3*N bytes",
        ));
    }
    let buf: &mut [u8] = unsafe { buffer.as_bytes_mut() };

    let r = radius.max(1) as i32;
    let r2 = (r * r) as f32 + 0.5;

    // Precompute disk offsets once.
    let mut disk: Vec<(i32, i32)> = Vec::with_capacity(((2 * r + 1) * (2 * r + 1)) as usize);
    for dy in -r..=r {
        for dx in -r..=r {
            if (dx * dx + dy * dy) as f32 <= r2 {
                disk.push((dx, dy));
            }
        }
    }

    for i in 0..n {
        let c = [colors_rgb[3 * i], colors_rgb[3 * i + 1], colors_rgb[3 * i + 2]];
        let cx = cx_f[i].round() as i32;
        let cy = cy_f[i].round() as i32;
        for &(dx, dy) in &disk {
            put_pixel(buf, w, h, cx + dx, cy + dy, c);
        }
    }
    Ok(())
}

/// Separable box blur (in-place) over an RGB byte buffer.
///
/// Matches the cumulative-sum semantics of the pure-numpy fallback:
/// `out[y, x] = mean(in[y-r..=y+r, x-r..=x+r])` with edge padding. Operates
/// on `u8` input/output for cache-friendliness.
#[pyfunction]
pub fn box_blur_rgb(
    buffer: &Bound<'_, PyByteArray>,
    width: u32,
    height: u32,
    radius: u32,
) -> PyResult<()> {
    let w = width as usize;
    let h = height as usize;
    let r = radius as usize;
    let expected = w * h * 3;
    if buffer.len() < expected {
        return Err(pyo3::exceptions::PyValueError::new_err(format!(
            "buffer too small: {} < {}",
            buffer.len(),
            expected
        )));
    }
    if r == 0 {
        return Ok(());
    }
    let buf: &mut [u8] = unsafe { buffer.as_bytes_mut() };

    let k = 2 * r + 1;
    let kf = k as f32;
    let area = kf * kf;
    let inv_area = 1.0 / area;

    // Horizontal pass using a sliding-window sum (per channel).
    // Working buffer holds the horizontal result as f32 (one row at a
    // time for the vertical pass we keep f32 across the full image to
    // avoid double rounding when the radius is large).
    let mut horiz = vec![0.0f32; w * h * 3];

    for y in 0..h {
        let row_off = y * w * 3;
        // Per-channel running sums, primed with leftmost pixel repeated
        // r+1 times then the first r pixels.
        let mut sum_r = 0.0f32;
        let mut sum_g = 0.0f32;
        let mut sum_b = 0.0f32;
        // Left edge: pixel 0 repeated (r+1) times.
        let p0 = row_off;
        sum_r += buf[p0] as f32 * (r as f32 + 1.0);
        sum_g += buf[p0 + 1] as f32 * (r as f32 + 1.0);
        sum_b += buf[p0 + 2] as f32 * (r as f32 + 1.0);
        for x in 1..=r.min(w - 1) {
            let p = row_off + x * 3;
            sum_r += buf[p] as f32;
            sum_g += buf[p + 1] as f32;
            sum_b += buf[p + 2] as f32;
        }
        if r > w - 1 {
            // Image narrower than r — pad remaining with last pixel.
            let last = row_off + (w - 1) * 3;
            for _ in (w - 1)..r {
                sum_r += buf[last] as f32;
                sum_g += buf[last + 1] as f32;
                sum_b += buf[last + 2] as f32;
            }
        }

        for x in 0..w {
            let off = row_off + x * 3;
            horiz[off] = sum_r;
            horiz[off + 1] = sum_g;
            horiz[off + 2] = sum_b;

            // Advance window: subtract leftmost, add rightmost+1.
            let x_left = if x >= r { x - r } else { 0 };
            let x_right = (x + r + 1).min(w - 1);
            let p_left = row_off + x_left * 3;
            let p_right = row_off + x_right * 3;
            sum_r += buf[p_right] as f32 - buf[p_left] as f32;
            sum_g += buf[p_right + 1] as f32 - buf[p_left + 1] as f32;
            sum_b += buf[p_right + 2] as f32 - buf[p_left + 2] as f32;
        }
    }

    // Vertical pass: same sliding sum but along y, reading the horiz
    // float buffer and writing back to u8 with `/area` normalisation.
    for x in 0..w {
        let mut sum_r = 0.0f32;
        let mut sum_g = 0.0f32;
        let mut sum_b = 0.0f32;
        let col_off0 = x * 3;
        sum_r += horiz[col_off0] * (r as f32 + 1.0);
        sum_g += horiz[col_off0 + 1] * (r as f32 + 1.0);
        sum_b += horiz[col_off0 + 2] * (r as f32 + 1.0);
        for y in 1..=r.min(h - 1) {
            let p = y * w * 3 + x * 3;
            sum_r += horiz[p];
            sum_g += horiz[p + 1];
            sum_b += horiz[p + 2];
        }
        if r > h - 1 {
            let last = (h - 1) * w * 3 + x * 3;
            for _ in (h - 1)..r {
                sum_r += horiz[last];
                sum_g += horiz[last + 1];
                sum_b += horiz[last + 2];
            }
        }

        for y in 0..h {
            let off = y * w * 3 + x * 3;
            // Round to nearest u8.
            let rv = (sum_r * inv_area).round().clamp(0.0, 255.0) as u8;
            let gv = (sum_g * inv_area).round().clamp(0.0, 255.0) as u8;
            let bv = (sum_b * inv_area).round().clamp(0.0, 255.0) as u8;
            buf[off] = rv;
            buf[off + 1] = gv;
            buf[off + 2] = bv;

            let y_top = if y >= r { y - r } else { 0 };
            let y_bot = (y + r + 1).min(h - 1);
            let p_top = y_top * w * 3 + x * 3;
            let p_bot = y_bot * w * 3 + x * 3;
            sum_r += horiz[p_bot] - horiz[p_top];
            sum_g += horiz[p_bot + 1] - horiz[p_top + 1];
            sum_b += horiz[p_bot + 2] - horiz[p_top + 2];
        }
    }

    Ok(())
}

/// Alpha-composite an RGBA overlay onto an RGB destination, in place.
///
/// dst[i].rgb = dst[i].rgb * (1 - a) + src[i].rgb * a, where a = overlay
/// alpha / 255. The alpha channel is consumed from the overlay buffer.
#[pyfunction]
pub fn alpha_composite_rgb(
    dst: &Bound<'_, PyByteArray>,
    overlay_rgba: &[u8],
    width: u32,
    height: u32,
) -> PyResult<()> {
    let w = width as usize;
    let h = height as usize;
    let n_px = w * h;
    if dst.len() < n_px * 3 {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "dst too small",
        ));
    }
    if overlay_rgba.len() < n_px * 4 {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "overlay too small",
        ));
    }
    let buf: &mut [u8] = unsafe { dst.as_bytes_mut() };
    buf.par_chunks_exact_mut(3 * w)
        .zip(overlay_rgba.par_chunks_exact(4 * w))
        .for_each(|(drow, srow)| {
            for x in 0..w {
                let a = srow[4 * x + 3] as u16;
                if a == 0 {
                    continue;
                }
                let inv = 255 - a;
                let dr = drow[3 * x] as u16;
                let dg = drow[3 * x + 1] as u16;
                let db = drow[3 * x + 2] as u16;
                let sr = srow[4 * x] as u16;
                let sg = srow[4 * x + 1] as u16;
                let sb = srow[4 * x + 2] as u16;
                // Fixed-point composite, rounded.
                drow[3 * x] = ((dr * inv + sr * a + 127) / 255) as u8;
                drow[3 * x + 1] = ((dg * inv + sg * a + 127) / 255) as u8;
                drow[3 * x + 2] = ((db * inv + sb * a + 127) / 255) as u8;
            }
        });
    Ok(())
}

/// Fused bloom + Reinhard tonemap + gamma in one pass over the u8 buffer.
///
/// Mirrors the Python `_post_process` semantics:
/// 1. Luminance = 0.299 R + 0.587 G + 0.114 B (on the normalised [0, 1]
///    float values).
/// 2. bright = max(lum - threshold, 0); bright_rgb = rgb * bright.
/// 3. blurred = box_blur(bright_rgb, radius).
/// 4. final = exposure * (rgb + blurred * strength);
///    final = final / (1 + final);
///    final = clamp(final, 0, 1)^(1/gamma);
///    out = u8(final * 255).
///
/// All work happens in place on the input bytearray. Returns Err if the
/// buffer length doesn't match `width * height * 3`.
#[pyfunction]
#[pyo3(signature = (buffer, width, height, bloom_radius, bloom_strength, bloom_threshold, exposure, gamma))]
pub fn post_process_rgb(
    buffer: &Bound<'_, PyByteArray>,
    width: u32,
    height: u32,
    bloom_radius: u32,
    bloom_strength: f32,
    bloom_threshold: f32,
    exposure: f32,
    gamma: f32,
) -> PyResult<()> {
    let w = width as usize;
    let h = height as usize;
    let expected = w * h * 3;
    if buffer.len() < expected {
        return Err(pyo3::exceptions::PyValueError::new_err(format!(
            "buffer too small: {} < {}",
            buffer.len(),
            expected
        )));
    }
    let buf: &mut [u8] = unsafe { buffer.as_bytes_mut() };

    let inv255 = 1.0 / 255.0;
    let inv_gamma = 1.0 / gamma.max(1e-9);

    // Build bright_rgb (f32) only if bloom is active. We downsample to
    // half resolution before blurring — a halo is low-frequency so the
    // perceptual difference vs full-res blur is negligible, while the
    // memory traffic drops 4x.
    let do_bloom = bloom_radius > 0 && bloom_strength > 0.0;
    let bright_rgb_blur: Option<Vec<f32>> = if do_bloom {
        let dw = w / 2;
        let dh = h / 2;
        // Parallel per-2x2-block bright extraction + downsample.
        let mut bright = vec![0.0f32; dw * dh * 3];
        bright
            .par_chunks_exact_mut(3 * dw)
            .enumerate()
            .for_each(|(dy, row)| {
                let y0 = dy * 2;
                let y1 = (y0 + 1).min(h - 1);
                let src0 = &buf[y0 * w * 3..(y0 + 1) * w * 3];
                let src1 = &buf[y1 * w * 3..(y1 + 1) * w * 3];
                for dx in 0..dw {
                    let x0 = dx * 2;
                    let x1 = (x0 + 1).min(w - 1);
                    // 4-pixel box average then bright extract.
                    let r = (src0[3 * x0] as f32 + src0[3 * x1] as f32
                        + src1[3 * x0] as f32 + src1[3 * x1] as f32)
                        * (0.25 * inv255);
                    let g = (src0[3 * x0 + 1] as f32 + src0[3 * x1 + 1] as f32
                        + src1[3 * x0 + 1] as f32 + src1[3 * x1 + 1] as f32)
                        * (0.25 * inv255);
                    let b = (src0[3 * x0 + 2] as f32 + src0[3 * x1 + 2] as f32
                        + src1[3 * x0 + 2] as f32 + src1[3 * x1 + 2] as f32)
                        * (0.25 * inv255);
                    let lum = 0.299 * r + 0.587 * g + 0.114 * b;
                    let bri = (lum - bloom_threshold).max(0.0);
                    row[3 * dx] = r * bri;
                    row[3 * dx + 1] = g * bri;
                    row[3 * dx + 2] = b * bri;
                }
            });
        // Replace the operating dimensions for the blur with the
        // downsampled ones. The variable shadows below.
        let w = dw;
        let h = dh;

        // Separable box blur on the float buffer.
        let r = bloom_radius as usize;
        let k = 2 * r + 1;
        let kf = k as f32;
        let area = kf * kf;
        let inv_area = 1.0 / area;

        // Horizontal pass: per-row independent — parallelize across rows.
        let mut horiz = vec![0.0f32; w * h * 3];
        horiz
            .par_chunks_exact_mut(3 * w)
            .enumerate()
            .for_each(|(y, hrow)| {
                let brow = &bright[y * w * 3..(y + 1) * w * 3];
                let mut sr = brow[0] * (r as f32 + 1.0);
                let mut sg = brow[1] * (r as f32 + 1.0);
                let mut sb_ = brow[2] * (r as f32 + 1.0);
                for x in 1..=r.min(w - 1) {
                    sr += brow[3 * x];
                    sg += brow[3 * x + 1];
                    sb_ += brow[3 * x + 2];
                }
                if r > w - 1 {
                    let last = (w - 1) * 3;
                    for _ in (w - 1)..r {
                        sr += brow[last];
                        sg += brow[last + 1];
                        sb_ += brow[last + 2];
                    }
                }
                for x in 0..w {
                    hrow[3 * x] = sr;
                    hrow[3 * x + 1] = sg;
                    hrow[3 * x + 2] = sb_;
                    let xl = if x >= r { x - r } else { 0 };
                    let xr = (x + r + 1).min(w - 1);
                    sr += brow[3 * xr] - brow[3 * xl];
                    sg += brow[3 * xr + 1] - brow[3 * xl + 1];
                    sb_ += brow[3 * xr + 2] - brow[3 * xl + 2];
                }
            });

        // Vertical pass: per-column independent — parallelize over x.
        // We split the output by columns (strided writes), which is
        // less cache-friendly but Rayon makes it net-positive.
        let mut blurred = vec![0.0f32; w * h * 3];
        // Use unsafe pointer-based mut access so we can write columns
        // in parallel. SAFETY: each task writes disjoint columns.
        let blurred_ptr = blurred.as_mut_ptr() as usize;
        let horiz_ptr = horiz.as_ptr() as usize;
        (0..w).into_par_iter().for_each(|x| {
            let blurred =
                unsafe { std::slice::from_raw_parts_mut(blurred_ptr as *mut f32, w * h * 3) };
            let horiz = unsafe { std::slice::from_raw_parts(horiz_ptr as *const f32, w * h * 3) };
            let mut sr = horiz[3 * x] * (r as f32 + 1.0);
            let mut sg = horiz[3 * x + 1] * (r as f32 + 1.0);
            let mut sb_ = horiz[3 * x + 2] * (r as f32 + 1.0);
            for y in 1..=r.min(h - 1) {
                let p = y * w * 3 + x * 3;
                sr += horiz[p];
                sg += horiz[p + 1];
                sb_ += horiz[p + 2];
            }
            if r > h - 1 {
                let last = (h - 1) * w * 3 + x * 3;
                for _ in (h - 1)..r {
                    sr += horiz[last];
                    sg += horiz[last + 1];
                    sb_ += horiz[last + 2];
                }
            }
            for y in 0..h {
                let off = y * w * 3 + x * 3;
                blurred[off] = sr * inv_area;
                blurred[off + 1] = sg * inv_area;
                blurred[off + 2] = sb_ * inv_area;
                let y_top = if y >= r { y - r } else { 0 };
                let y_bot = (y + r + 1).min(h - 1);
                let p_top = y_top * w * 3 + x * 3;
                let p_bot = y_bot * w * 3 + x * 3;
                sr += horiz[p_bot] - horiz[p_top];
                sg += horiz[p_bot + 1] - horiz[p_top + 1];
                sb_ += horiz[p_bot + 2] - horiz[p_top + 2];
            }
        });
        Some(blurred)
    } else {
        None
    };

    // Final tonemap + gamma + writeback. Parallel over rows.
    let dw = w / 2;
    let dh = h / 2;
    match &bright_rgb_blur {
        Some(blur) => {
            buf.par_chunks_exact_mut(3 * w).enumerate().for_each(|(y, row)| {
                // Upsample bloom: each full-res row uses the half-res
                // row y/2 (nearest-neighbour — good enough since the
                // bloom is already a heavy blur).
                let dy = (y >> 1).min(dh.saturating_sub(1));
                let bslice = &blur[dy * dw * 3..(dy + 1) * dw * 3];
                for x in 0..w {
                    let dx = (x >> 1).min(dw.saturating_sub(1));
                    let mut r = row[3 * x] as f32 * inv255;
                    let mut g = row[3 * x + 1] as f32 * inv255;
                    let mut b = row[3 * x + 2] as f32 * inv255;
                    r += bslice[3 * dx] * bloom_strength;
                    g += bslice[3 * dx + 1] * bloom_strength;
                    b += bslice[3 * dx + 2] * bloom_strength;
                    r *= exposure;
                    g *= exposure;
                    b *= exposure;
                    r = r / (1.0 + r);
                    g = g / (1.0 + g);
                    b = b / (1.0 + b);
                    r = r.clamp(0.0, 1.0).powf(inv_gamma);
                    g = g.clamp(0.0, 1.0).powf(inv_gamma);
                    b = b.clamp(0.0, 1.0).powf(inv_gamma);
                    row[3 * x] = (r * 255.0).clamp(0.0, 255.0).round() as u8;
                    row[3 * x + 1] = (g * 255.0).clamp(0.0, 255.0).round() as u8;
                    row[3 * x + 2] = (b * 255.0).clamp(0.0, 255.0).round() as u8;
                }
            });
        }
        None => {
            buf.par_chunks_exact_mut(3 * w).for_each(|row| {
                for x in 0..w {
                    let mut r = row[3 * x] as f32 * inv255 * exposure;
                    let mut g = row[3 * x + 1] as f32 * inv255 * exposure;
                    let mut b = row[3 * x + 2] as f32 * inv255 * exposure;
                    r = r / (1.0 + r);
                    g = g / (1.0 + g);
                    b = b / (1.0 + b);
                    r = r.clamp(0.0, 1.0).powf(inv_gamma);
                    g = g.clamp(0.0, 1.0).powf(inv_gamma);
                    b = b.clamp(0.0, 1.0).powf(inv_gamma);
                    row[3 * x] = (r * 255.0).clamp(0.0, 255.0).round() as u8;
                    row[3 * x + 1] = (g * 255.0).clamp(0.0, 255.0).round() as u8;
                    row[3 * x + 2] = (b * 255.0).clamp(0.0, 255.0).round() as u8;
                }
            });
        }
    }

    Ok(())
}

/// Rasterise `T` textured triangles into a `(H, W, 3)` u8 RGB buffer.
///
/// For each triangle, sample the texture via barycentric coords from the
/// rest-state UVs of the three vertices. Triangle vertices are screen-space
/// (x, y) floats; the rasteriser computes the triangle's screen bounding
/// box, clips to the framebuffer, and writes any pixel whose barycentric
/// coords are all >= 0.
///
/// Texture sampling is nearest-neighbour: `(u * (tex_w - 1)).floor()` (and
/// likewise for v) — matches the Python fallback's `.astype(np.int32)`
/// semantics.
///
/// Triangles whose denominator (signed 2x area) is below 1e-6 in absolute
/// value are skipped (degenerate). Triangles are rasterised in parallel via
/// rayon; pixel writes within a triangle are disjoint, and the Python
/// fallback's mask-scatter is also "last-writer-wins" at overlapping
/// triangles, so the same benign race is acceptable here.
///
/// Buffer layouts:
///   * `hdr_rgb_u8` — `(H, W, 3)` u8, row-major, mutated in place.
///   * `tri_screen_xy` — `(T, 3, 2)` packed f32, reinterpreted from bytes.
///   * `tri_uvs` — `(T, 3, 2)` packed f32, reinterpreted from bytes.
///   * `texture_rgb` — `(tex_height, tex_width, 3)` u8 source pixels.
#[pyfunction]
pub fn rasterize_textured_triangles(
    hdr_rgb_u8: &Bound<'_, PyByteArray>,
    width: u32,
    height: u32,
    tri_screen_xy: &[u8],
    tri_uvs: &[u8],
    texture_rgb: &[u8],
    tex_width: u32,
    tex_height: u32,
) -> PyResult<()> {
    let w = width as usize;
    let h = height as usize;
    let tex_w = tex_width as usize;
    let tex_h = tex_height as usize;
    let expected = w * h * 3;
    if hdr_rgb_u8.len() < expected {
        return Err(pyo3::exceptions::PyValueError::new_err(format!(
            "hdr_rgb_u8 too small: {} < {}",
            hdr_rgb_u8.len(),
            expected
        )));
    }
    if texture_rgb.len() < tex_w * tex_h * 3 {
        return Err(pyo3::exceptions::PyValueError::new_err(format!(
            "texture_rgb too small: {} < {}",
            texture_rgb.len(),
            tex_w * tex_h * 3
        )));
    }
    let verts: &[f32] = cast_slice(tri_screen_xy);
    let uvs: &[f32] = cast_slice(tri_uvs);
    if verts.len() % 6 != 0 {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "tri_screen_xy length must be a multiple of 6 f32 (T*3*2)",
        ));
    }
    let n_tris = verts.len() / 6;
    if uvs.len() != n_tris * 6 {
        return Err(pyo3::exceptions::PyValueError::new_err(format!(
            "tri_uvs must have T*3*2 f32 (got {}, expected {})",
            uvs.len(),
            n_tris * 6
        )));
    }
    if n_tris == 0 || tex_w == 0 || tex_h == 0 {
        return Ok(());
    }

    // SAFETY: we hold the GIL and do not yield it while writing. Per-
    // triangle pixel writes are within disjoint bboxes for a given
    // triangle; concurrent triangles may overlap, but the race is
    // benign (matches the Python mask-scatter last-writer-wins).
    let buf: &mut [u8] = unsafe { hdr_rgb_u8.as_bytes_mut() };
    let buf_ptr = buf.as_mut_ptr() as usize;
    let buf_len = buf.len();

    let tex_w_m1 = (tex_w as i32 - 1).max(0);
    let tex_h_m1 = (tex_h as i32 - 1).max(0);
    let tex_w_f = tex_w_m1 as f32;
    let tex_h_f = tex_h_m1 as f32;

    let texture_ptr = texture_rgb.as_ptr() as usize;
    let texture_len = texture_rgb.len();
    let verts_ptr = verts.as_ptr() as usize;
    let uvs_ptr = uvs.as_ptr() as usize;

    (0..n_tris).into_par_iter().for_each(|t| {
        // Reconstruct slices from raw pointers (rayon worker scope).
        let buf = unsafe { std::slice::from_raw_parts_mut(buf_ptr as *mut u8, buf_len) };
        let texture = unsafe { std::slice::from_raw_parts(texture_ptr as *const u8, texture_len) };
        let verts = unsafe { std::slice::from_raw_parts(verts_ptr as *const f32, n_tris * 6) };
        let uvs = unsafe { std::slice::from_raw_parts(uvs_ptr as *const f32, n_tris * 6) };

        let base = t * 6;
        let p0x = verts[base];
        let p0y = verts[base + 1];
        let p1x = verts[base + 2];
        let p1y = verts[base + 3];
        let p2x = verts[base + 4];
        let p2y = verts[base + 5];
        let uv0u = uvs[base];
        let uv0v = uvs[base + 1];
        let uv1u = uvs[base + 2];
        let uv1v = uvs[base + 3];
        let uv2u = uvs[base + 4];
        let uv2v = uvs[base + 5];

        // Screen-space bbox clipped to the framebuffer.
        let mut xmin_f = p0x.min(p1x).min(p2x);
        let mut ymin_f = p0y.min(p1y).min(p2y);
        let xmax_f = p0x.max(p1x).max(p2x);
        let ymax_f = p0y.max(p1y).max(p2y);
        if xmin_f < 0.0 { xmin_f = 0.0; }
        if ymin_f < 0.0 { ymin_f = 0.0; }
        let xmin = xmin_f as i32;
        let ymin = ymin_f as i32;
        let mut xmax = (xmax_f as i32) + 1;
        let mut ymax = (ymax_f as i32) + 1;
        if xmax > w as i32 { xmax = w as i32; }
        if ymax > h as i32 { ymax = h as i32; }
        if xmax <= xmin || ymax <= ymin {
            return;
        }

        // Edge function denominator — twice the signed triangle area.
        let denom = (p1x - p0x) * (p2y - p0y) - (p2x - p0x) * (p1y - p0y);
        if denom.abs() < 1e-6 {
            return;
        }
        let inv_denom = 1.0 / denom;

        // Precompute the edge constants used by the per-pixel barys.
        // w1 = ((p2x - p1x) * (y - p1y) - (p2y - p1y) * (x - p1x)) / denom
        // w2 = ((p0x - p2x) * (y - p2y) - (p0y - p2y) * (x - p2x)) / denom
        // Expanding to incremental form along scanlines:
        //   w1(x, y) = a1 * x + b1 * y + c1
        //   w2(x, y) = a2 * x + b2 * y + c2
        let a1 = -(p2y - p1y) * inv_denom;
        let b1 = (p2x - p1x) * inv_denom;
        let c1 = ((p2x - p1x) * (-p1y) - (p2y - p1y) * (-p1x)) * inv_denom;
        let a2 = -(p0y - p2y) * inv_denom;
        let b2 = (p0x - p2x) * inv_denom;
        let c2 = ((p0x - p2x) * (-p2y) - (p0y - p2y) * (-p2x)) * inv_denom;

        let xmin_u = xmin as usize;
        let ymin_u = ymin as usize;
        let xmax_u = xmax as usize;
        let ymax_u = ymax as usize;

        for y in ymin_u..ymax_u {
            let yf = y as f32;
            let mut w1 = a1 * (xmin_u as f32) + b1 * yf + c1;
            let mut w2 = a2 * (xmin_u as f32) + b2 * yf + c2;
            let row_off = y * w * 3;
            for x in xmin_u..xmax_u {
                // Inside-triangle test (all three barys >= 0).
                let w0 = 1.0 - w1 - w2;
                if w0 >= 0.0 && w1 >= 0.0 && w2 >= 0.0 {
                    let u = w0 * uv0u + w1 * uv1u + w2 * uv2u;
                    let v = w0 * uv0v + w1 * uv1v + w2 * uv2v;
                    // Nearest-neighbour sample — int truncation matches
                    // the Python ``.astype(np.int32)`` semantics.
                    let mut tx = (u * tex_w_f) as i32;
                    let mut ty = (v * tex_h_f) as i32;
                    if tx < 0 { tx = 0; } else if tx > tex_w_m1 { tx = tex_w_m1; }
                    if ty < 0 { ty = 0; } else if ty > tex_h_m1 { ty = tex_h_m1; }
                    let ti = (ty as usize * tex_w + tx as usize) * 3;
                    let bi = row_off + x * 3;
                    // SAFETY: bounds were checked above for both buffers.
                    unsafe {
                        let dst = buf.as_mut_ptr().add(bi);
                        let src = texture.as_ptr().add(ti);
                        *dst = *src;
                        *dst.add(1) = *src.add(1);
                        *dst.add(2) = *src.add(2);
                    }
                }
                w1 += a1;
                w2 += a2;
            }
        }
    });

    Ok(())
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(rasterize_lines, m)?)?;
    m.add_function(wrap_pyfunction!(rasterize_circles, m)?)?;
    m.add_function(wrap_pyfunction!(box_blur_rgb, m)?)?;
    m.add_function(wrap_pyfunction!(post_process_rgb, m)?)?;
    m.add_function(wrap_pyfunction!(alpha_composite_rgb, m)?)?;
    m.add_function(wrap_pyfunction!(rasterize_textured_triangles, m)?)?;
    Ok(())
}
