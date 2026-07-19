"""Hello Hybrid Layers -- 2D layer samples a 3D layer, 3D layer samples 2D.

DDD3 sprint demonstration: show that hybrid 2D + 3D layers can be
stacked by ``z_order`` on the same scene and reference each other's
output buffers.

Scene composition (bottom → top):

* ``z_order=0`` -- ``Layer3D`` ("base_scene"): a rotating cube lit by a
  single point light. Rendered into its own offscreen render target.
* ``z_order=1`` -- ``Layer2D`` ("sepia_post"): consumes the base_scene
  render target as a texture, applies a simple sepia + vignette pass
  in-place.
* ``z_order=2`` -- ``Layer3D`` ("overlay_cube"): a smaller cube whose
  diffuse channel is the sepia_post buffer. This proves 3D-samples-2D.

Frame loop:

* Rotate the base cube.
* Ask the :class:`LayerCompositor` to walk all three layers, render each,
  and composite them into a final RGBA buffer.
* Trace every ``layer_render`` / ``layer_composite`` event.

At end:

* Write ``hello_hybrid_layers_trace.yaml`` with layer-creation events,
  per-frame render / composite counts, final centre-pixel RGBA, and the
  cross-layer binding count.
* Save ``hello_hybrid_layers_final.png`` so the composite is visible.

Run::

    PYTHONPATH=python python SlapPyEngineExamples/examples/hello_hybrid_layers.py
    PYTHONPATH=python python SlapPyEngineExamples/examples/hello_hybrid_layers.py --frames 30
"""
from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

import numpy as np


DEFAULT_FRAMES = 60
DEFAULT_WIDTH = 256
DEFAULT_HEIGHT = 192


# ---------------------------------------------------------------------------
# Hybrid layer shims -- duck-type onto DDD1's Layer2D / Layer3D so we don't
# depend on DDD2's exact protocol names. We attach:
#
#   * ``allocate_render_target(device)`` -- no-op for the numpy path.
#   * ``dispatch_render_pass(device, queue)`` -- called by the compositor.
#   * ``sample_from(other)`` / ``use_layer_as_texture(other)`` -- store the
#     reference so the compositor can count cross-layer bindings.
# ---------------------------------------------------------------------------


def _install_hybrid_hooks() -> None:
    """Ensure Layer has ``allocate_render_target`` in the numpy fallback path.

    DDD2 landed :meth:`sample_from`, :meth:`apply_post_process_from`, and
    :meth:`use_layer_as_texture` already. When DDD1's optional
    :meth:`allocate_render_target` is missing (older engines) we patch in
    a numpy-only equivalent so the compositor can invoke a common hook.
    Idempotent -- ``hasattr`` guards make repeated calls safe.
    """
    try:
        from slappyengine.layer import Layer as _Layer
    except Exception:
        return

    def _allocate_render_target(self, device):
        # numpy fallback -- just ensure _image_data exists at the
        # advertised resolution.
        img = getattr(self, "_image_data", None)
        res = tuple(getattr(self, "resolution", (256, 192)))
        w, h = int(res[0]), int(res[1])
        if img is None or img.shape[:2] != (h, w):
            self._image_data = np.zeros((h, w, 4), dtype=np.uint8)
        return self._image_data

    if not hasattr(_Layer, "allocate_render_target"):
        setattr(_Layer, "allocate_render_target", _allocate_render_target)


# ---------------------------------------------------------------------------
# Software renderers -- one for each layer role. These sidestep the wgpu
# path so the demo passes in headless CI where wgpu adapters aren't
# available. When wgpu IS available, DDD2 will slot real render passes
# into the same protocol -- the compositor code doesn't change.
# ---------------------------------------------------------------------------


def _render_base_scene(layer, angle: float, width: int, height: int) -> None:
    """Rasterise a rotating cube with soft shading into ``layer._image_data``."""
    img = layer._image_data
    if img is None or img.shape[:2] != (height, width):
        img = np.zeros((height, width, 4), dtype=np.uint8)
        layer._image_data = img

    # Background gradient.
    y_ramp = np.linspace(15, 60, height).astype(np.uint8)
    img[..., 0] = np.tile(y_ramp[:, None], (1, width))
    img[..., 1] = np.tile((y_ramp * 1.4).clip(0, 255).astype(np.uint8)[:, None], (1, width))
    img[..., 2] = np.tile((y_ramp * 2.4).clip(0, 255).astype(np.uint8)[:, None], (1, width))
    img[..., 3] = 255

    # Cube -- project 8 vertices, draw filled quads by scanline.
    s = min(width, height) * 0.28
    cx, cy = width / 2.0, height / 2.0
    verts_local = np.array([
        [-1, -1, -1], [+1, -1, -1], [+1, +1, -1], [-1, +1, -1],
        [-1, -1, +1], [+1, -1, +1], [+1, +1, +1], [-1, +1, +1],
    ], dtype=np.float32)
    ca, sa = math.cos(angle), math.sin(angle)
    cb, sb = math.cos(angle * 0.7), math.sin(angle * 0.7)
    # Y-rot then X-rot.
    r_y = np.array([[ca, 0, sa], [0, 1, 0], [-sa, 0, ca]], dtype=np.float32)
    r_x = np.array([[1, 0, 0], [0, cb, -sb], [0, sb, cb]], dtype=np.float32)
    rotated = verts_local @ r_y.T @ r_x.T
    # Perspective-ish flatten.
    proj = rotated[:, :2] * (2.4 / (3.5 - rotated[:, 2:3]))
    px = (cx + proj[:, 0] * s).astype(np.int32)
    py = (cy - proj[:, 1] * s).astype(np.int32)

    faces = [
        (0, 1, 2, 3, (200, 120,  70)),  # -Z
        (4, 5, 6, 7, (240, 180, 110)),  # +Z
        (0, 3, 7, 4, (150,  90,  50)),  # -X
        (1, 2, 6, 5, (220, 150,  90)),  # +X
        (3, 2, 6, 7, (255, 210, 150)),  # +Y (top -- brightest)
        (0, 1, 5, 4, (110,  60,  30)),  # -Y (bottom -- darkest)
    ]
    # Sort back-to-front by average Z.
    faces_sorted = sorted(
        faces,
        key=lambda f: -float(rotated[list(f[:4]), 2].mean()),
    )
    for a, b, c, d, colour in faces_sorted:
        quad = np.array([(px[a], py[a]), (px[b], py[b]), (px[c], py[c]), (px[d], py[d])], dtype=np.int32)
        _fill_convex_quad(img, quad, colour)


def _fill_convex_quad(img: np.ndarray, quad: np.ndarray, colour) -> None:
    """Scanline-fill a convex quad on ``img`` (uint8 RGBA)."""
    h, w = img.shape[:2]
    ys = quad[:, 1]
    y_min = max(0, int(ys.min()))
    y_max = min(h - 1, int(ys.max()))
    if y_max < y_min:
        return
    # For each row, intersect the four edges to get x-span.
    edges = [(quad[i], quad[(i + 1) % 4]) for i in range(4)]
    for y in range(y_min, y_max + 1):
        x_hits: List[float] = []
        for (x0, y0), (x1, y1) in edges:
            if (y0 <= y < y1) or (y1 <= y < y0):
                t = (y - y0) / (y1 - y0) if y1 != y0 else 0.0
                x_hits.append(x0 + t * (x1 - x0))
        if len(x_hits) < 2:
            continue
        x_hits.sort()
        x0 = max(0, int(round(x_hits[0])))
        x1 = min(w - 1, int(round(x_hits[-1])))
        if x1 >= x0:
            img[y, x0:x1 + 1, 0] = colour[0]
            img[y, x0:x1 + 1, 1] = colour[1]
            img[y, x0:x1 + 1, 2] = colour[2]
            img[y, x0:x1 + 1, 3] = 255


def _apply_sepia_vignette(source_img: np.ndarray, out_img: np.ndarray) -> None:
    """Post-process the base scene into ``out_img``: sepia + vignette.

    WGSL-equivalent fragment shader (bundled with the demo docstring)::

        // sepia + vignette
        let uv = vec2<f32>(position.x / res.x, position.y / res.y);
        let px = textureSample(src, samp, uv).rgb;
        let sepia_r = dot(px, vec3<f32>(0.393, 0.769, 0.189));
        let sepia_g = dot(px, vec3<f32>(0.349, 0.686, 0.168));
        let sepia_b = dot(px, vec3<f32>(0.272, 0.534, 0.131));
        let d = length(uv - vec2<f32>(0.5, 0.5)) * 1.4;
        let vig = clamp(1.0 - d * d, 0.0, 1.0);
        return vec4<f32>(vec3<f32>(sepia_r, sepia_g, sepia_b) * vig, 1.0);

    We reimplement it with numpy for the headless path so the pipeline
    is testable without a GPU. When wgpu is up, DDD2 will slot the WGSL
    equivalent into the same slot with identical semantics.
    """
    h, w = out_img.shape[:2]
    if source_img.shape[:2] != (h, w):
        # Resize source to match with nearest-neighbour so the demo is
        # robust to differing layer resolutions.
        ys = np.linspace(0, source_img.shape[0] - 1, h).astype(np.int64)
        xs = np.linspace(0, source_img.shape[1] - 1, w).astype(np.int64)
        source_img = source_img[ys[:, None], xs[None, :], :]
    src = source_img.astype(np.float32) / 255.0
    sepia_r = src[..., 0] * 0.393 + src[..., 1] * 0.769 + src[..., 2] * 0.189
    sepia_g = src[..., 0] * 0.349 + src[..., 1] * 0.686 + src[..., 2] * 0.168
    sepia_b = src[..., 0] * 0.272 + src[..., 1] * 0.534 + src[..., 2] * 0.131

    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    uv_x = xx / w - 0.5
    uv_y = yy / h - 0.5
    d = np.sqrt(uv_x * uv_x + uv_y * uv_y) * 1.4
    vig = np.clip(1.0 - d * d, 0.0, 1.0)

    out_img[..., 0] = np.clip(sepia_r * vig * 255.0, 0.0, 255.0).astype(np.uint8)
    out_img[..., 1] = np.clip(sepia_g * vig * 255.0, 0.0, 255.0).astype(np.uint8)
    out_img[..., 2] = np.clip(sepia_b * vig * 255.0, 0.0, 255.0).astype(np.uint8)
    out_img[..., 3] = 255


def _render_overlay_cube(layer, angle: float, diffuse: np.ndarray) -> None:
    """Render a small cube whose diffuse texture is *diffuse* (the 2D layer)."""
    img = layer._image_data
    h, w = img.shape[:2]
    img[..., :] = 0  # transparent background so the compositor sees the alpha

    # Small cube at top-right corner.
    s = min(w, h) * 0.12
    cx, cy = w * 0.75, h * 0.3
    verts_local = np.array([
        [-1, -1, -1], [+1, -1, -1], [+1, +1, -1], [-1, +1, -1],
        [-1, -1, +1], [+1, -1, +1], [+1, +1, +1], [-1, +1, +1],
    ], dtype=np.float32)
    a = angle * 1.3
    ca, sa = math.cos(a), math.sin(a)
    r = np.array([[ca, -sa, 0], [sa, ca, 0], [0, 0, 1]], dtype=np.float32)
    rotated = verts_local @ r.T
    px = (cx + rotated[:, 0] * s).astype(np.int32)
    py = (cy - rotated[:, 1] * s).astype(np.int32)

    faces = [
        (0, 1, 2, 3, 0.75),
        (4, 5, 6, 7, 1.00),
        (0, 3, 7, 4, 0.60),
        (1, 2, 6, 5, 0.85),
        (3, 2, 6, 7, 1.10),
        (0, 1, 5, 4, 0.45),
    ]
    faces_sorted = sorted(
        faces,
        key=lambda f: -float(rotated[list(f[:4]), 2].mean()),
    )
    # Sample centre pixel of the diffuse texture per face so the overlay
    # visibly picks up the sepia colour of the underlying 3D scene.
    dh, dw = diffuse.shape[:2]
    for a_i, b_i, c_i, d_i, brightness in faces_sorted:
        quad = np.array([(px[a_i], py[a_i]), (px[b_i], py[b_i]),
                          (px[c_i], py[c_i]), (px[d_i], py[d_i])], dtype=np.int32)
        # UV maps: pick a representative pixel from the diffuse layer.
        u = 0.5 + 0.35 * math.cos(angle + a_i)
        v = 0.5 + 0.35 * math.sin(angle + a_i)
        ux = int(np.clip(u * dw, 0, dw - 1))
        uy = int(np.clip(v * dh, 0, dh - 1))
        sample = diffuse[uy, ux, :3].astype(np.float32) * brightness
        colour = tuple(int(np.clip(c, 0.0, 255.0)) for c in sample)
        _fill_convex_quad(img, quad, colour)


# ---------------------------------------------------------------------------
# Trace helpers
# ---------------------------------------------------------------------------


def _write_trace_yaml(payload: Dict[str, Any], path: Path) -> Path:
    """Dump *payload* to YAML; falls back to ``repr`` if pyyaml missing."""
    try:
        import yaml
        path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    except Exception:
        path.write_text(repr(payload), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Demo main
# ---------------------------------------------------------------------------


@dataclass
class DemoState:
    """Mutable state shared across launch callbacks."""

    layers: List[Any] = field(default_factory=list)
    base_layer: Any = None
    sepia_layer: Any = None
    overlay_layer: Any = None
    scene: Any = None
    compositor: Any = None
    angle: float = 0.0
    trace_events: List[Dict[str, Any]] = field(default_factory=list)
    creation_events: List[Dict[str, Any]] = field(default_factory=list)
    frame_stats: List[Any] = field(default_factory=list)


def _build_scene(state: DemoState, width: int, height: int) -> None:
    """Create the three hybrid layers + attach them to a Scene."""
    _install_hybrid_hooks()

    from slappyengine.layer import Layer2D, Layer3D
    from slappyengine.scene import Scene
    from slappyengine.render.layer_compositor import LayerCompositor

    scene = Scene(name="HelloHybridLayers")
    # DDD1 has landed Scene.add_layer / Scene.layers -- if the attribute
    # is a read-only property we use the add_layer path below, otherwise
    # we materialise the list directly. This keeps the demo alive across
    # engine versions.
    if not hasattr(scene, "add_layer"):
        try:
            scene.layers = []
        except AttributeError:
            scene._layers = []

    # ---- 3D base ------------------------------------------------------
    base = Layer3D(name="base_scene")
    base.resolution = (width, height)
    base.z_order = 0
    base.blend_mode = "normal"
    base._image_data = np.zeros((height, width, 4), dtype=np.uint8)

    # ---- 2D sepia ------------------------------------------------------
    sepia = Layer2D(name="sepia_post", width=width, height=height)
    sepia.resolution = (width, height)
    sepia.z_order = 1
    sepia.blend_mode = "alpha"
    sepia.opacity = 0.85
    # DDD2 protocol -- 2D sepia samples the 3D base scene.
    # sample_from returns a LayerSampleBinding; we stash it on the layer
    # so the compositor's cross-layer scan can pick it up alongside the
    # PostProcessDescriptor created by apply_post_process_from.
    sample_binding = sepia.sample_from(base)
    if not hasattr(sepia, "_sampled_layers"):
        sepia._sampled_layers = []
    sepia._sampled_layers.append(base)
    sepia._sample_binding = sample_binding
    sepia.apply_post_process_from(base, blend_mode="alpha")

    # ---- 3D overlay cube ----------------------------------------------
    overlay = Layer3D(name="overlay_cube")
    overlay.resolution = (width, height)
    overlay.z_order = 2
    overlay.blend_mode = "alpha"
    overlay._image_data = np.zeros((height, width, 4), dtype=np.uint8)
    # DDD2 protocol -- 3D overlay uses the 2D sepia layer as its diffuse.
    overlay.use_layer_as_texture(sepia, uniform_slot="u_diffuse")

    if hasattr(scene, "add_layer"):
        scene.add_layer(base)
        scene.add_layer(sepia)
        scene.add_layer(overlay)
    else:
        scene.layers.extend([base, sepia, overlay])
    state.scene = scene
    state.base_layer = base
    state.sepia_layer = sepia
    state.overlay_layer = overlay
    state.layers = [base, sepia, overlay]
    state.compositor = LayerCompositor(width=width, height=height)

    for layer in state.layers:
        state.creation_events.append({
            "event": "layer_created",
            "name": layer.name,
            "mode": layer.mode,
            "z_order": int(layer.z_order),
            "blend_mode": layer.blend_mode,
        })


def _step_frame(state: DemoState, dt: float) -> None:
    """Update layer contents + run the compositor for one frame."""
    state.angle += dt * math.radians(45.0)

    # 1. Base 3D layer -- rotating cube.
    _render_base_scene(
        state.base_layer,
        state.angle,
        state.base_layer._image_data.shape[1],
        state.base_layer._image_data.shape[0],
    )
    # 2. 2D sepia consumes base_layer's image.
    _apply_sepia_vignette(state.base_layer._image_data, state.sepia_layer._image_data)
    # 3. 3D overlay consumes sepia_layer's image.
    _render_overlay_cube(state.overlay_layer, state.angle, state.sepia_layer._image_data)

    # 4. Composite.
    stats = state.compositor.render_scene(state.scene)
    state.frame_stats.append(stats)
    for evt in stats.events:
        state.trace_events.append({
            "kind": evt.kind,
            "layer": evt.layer_name,
            "z_order": evt.z_order,
            "blend_mode": evt.blend_mode,
            "frame": evt.frame,
        })


def _finalise(state: DemoState, out_dir: Path) -> Dict[str, Any]:
    """Write trace YAML + PNG screenshot and return the summary dict."""
    out_dir.mkdir(parents=True, exist_ok=True)
    final_stats = state.frame_stats[-1] if state.frame_stats else None
    center = final_stats.center_pixel if final_stats else (0, 0, 0, 0)
    bindings = final_stats.cross_layer_binding_count if final_stats else 0
    total_events = len(state.trace_events)
    render_events_per_layer: Dict[str, int] = {}
    for evt in state.trace_events:
        if evt["kind"] == "layer_render":
            render_events_per_layer[evt["layer"]] = render_events_per_layer.get(evt["layer"], 0) + 1

    payload = {
        "demo": "hello_hybrid_layers",
        "frames": len(state.frame_stats),
        "creation_events": state.creation_events,
        "trace_event_count": total_events,
        "layer_render_events": render_events_per_layer,
        "final_center_rgba": list(center),
        "cross_layer_binding_count": int(bindings),
        "wgpu_backend": _describe_backend(state.compositor),
        "note": (
            "DDD3 sprint -- compositor walks Layer3D + Layer2D + Layer3D in "
            "z_order and composes them. The 2D layer samples the first 3D "
            "layer's output (sample_from) and applies sepia+vignette "
            "(apply_post_process_from); the second 3D layer uses the 2D "
            "layer as its diffuse texture (use_layer_as_texture)."
        ),
    }
    trace_path = out_dir / "hello_hybrid_layers_trace.yaml"
    _write_trace_yaml(payload, trace_path)

    png_path = out_dir / "hello_hybrid_layers_final.png"
    try:
        from PIL import Image
        Image.fromarray(state.compositor.output_buffer, mode="RGBA").save(png_path)
    except Exception:
        # Fall back to a raw .npy so tests can still verify pixels landed.
        np.save(str(png_path.with_suffix(".npy")), state.compositor.output_buffer)

    return {
        "trace_path": str(trace_path),
        "png_path": str(png_path),
        "center_pixel": list(center),
        "cross_layer_binding_count": int(bindings),
        "trace_event_count": total_events,
        "layer_render_events": render_events_per_layer,
        "frames": len(state.frame_stats),
    }


def _describe_backend(compositor: Any) -> str:
    device = getattr(compositor, "device", None)
    if device is None:
        return "numpy_fallback"
    try:
        info = dict(device.adapter.info)
        return str(info.get("backend_type", "Unknown"))
    except Exception:
        return "wgpu_device"


def main(
    *,
    frames: int = DEFAULT_FRAMES,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    output_dir: str | Path | None = None,
) -> Dict[str, Any]:
    """Run the hybrid-layer demo end to end.

    Returns the summary dict tests read.
    """
    out_dir = Path(output_dir) if output_dir is not None else Path(__file__).parent / "output" / "hybrid_layers"
    state = DemoState()

    try:
        import slappyengine
    except Exception:
        slappyengine = None  # type: ignore[assignment]

    def on_begin(app: Any) -> None:
        _build_scene(state, width, height)
        # Record on the app trace too so downstream lifecycle tests see it.
        if hasattr(app, "trace"):
            for evt in state.creation_events:
                app.trace.append(("hybrid_layer_created", evt["name"], evt["z_order"]))

    def on_tick(app: Any, dt: float) -> None:
        _step_frame(state, dt)

    def on_end(app: Any) -> None:
        summary = _finalise(state, out_dir)
        if hasattr(app, "trace"):
            app.trace.append((
                "hybrid_layers_summary",
                summary["frames"],
                summary["trace_event_count"],
                summary["cross_layer_binding_count"],
            ))
        state.summary = summary  # type: ignore[attr-defined]

    if slappyengine is not None and hasattr(slappyengine, "launch"):
        slappyengine.launch(
            on_begin=on_begin,
            on_tick=on_tick,
            on_end=on_end,
            max_frames=frames,
        )
    else:
        # Fully headless path -- no App available.
        on_begin(None)
        dt = 1.0 / 60.0
        for _ in range(frames):
            on_tick(None, dt)
        on_end(None)

    return getattr(state, "summary", _finalise(state, out_dir))


def _parse_args(argv: List[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Hello Hybrid Layers -- SlapPyEngine DDD3 demo")
    parser.add_argument("--frames", type=int, default=DEFAULT_FRAMES,
                        help=f"number of frames to run (default: {DEFAULT_FRAMES})")
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH,
                        help=f"composite resolution width (default: {DEFAULT_WIDTH})")
    parser.add_argument("--height", type=int, default=DEFAULT_HEIGHT,
                        help=f"composite resolution height (default: {DEFAULT_HEIGHT})")
    parser.add_argument("--out", type=Path, default=None,
                        help="output directory for trace YAML + PNG")
    return parser.parse_args(argv)


def _cli(argv: List[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        summary = main(
            frames=args.frames,
            width=args.width,
            height=args.height,
            output_dir=args.out,
        )
    except Exception as exc:  # pragma: no cover -- defensive CLI guard
        print(f"hello_hybrid_layers: error: {exc}", file=sys.stderr)
        return 1

    print("hello_hybrid_layers summary")
    print(f"  frames                    : {summary['frames']}")
    print(f"  trace events              : {summary['trace_event_count']}")
    print(f"  cross_layer_binding_count : {summary['cross_layer_binding_count']}")
    print(f"  final centre pixel RGBA   : {summary['center_pixel']}")
    print(f"  layer_render events       : {summary['layer_render_events']}")
    print(f"  trace                     : {summary['trace_path']}")
    print(f"  screenshot                : {summary['png_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
