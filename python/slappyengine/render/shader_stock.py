"""Built-in WGSL shader stock — unlit 3D, Phong 3D, sprite 2D, debug lines.

Each shader is exposed as a WGSL string with well-known entry points
``vs_main`` and ``fs_main``. wgpu-first; the numpy fallback path used by
:class:`~slappyengine.render.null_renderer.NullRenderer` skips shader
compilation entirely, so these are text assets, not compiled artefacts.
"""
from __future__ import annotations

from dataclasses import dataclass


# ----------------------------------------------------------------------
# Unlit 3D — base_color only, honours the "defaults are unlit" rule.
# ----------------------------------------------------------------------
UNLIT_3D_WGSL = """// slappyengine unlit_3d
struct Camera { view_proj: mat4x4<f32> };
struct Model  { model: mat4x4<f32>, color: vec4<f32> };

@group(0) @binding(0) var<uniform> cam: Camera;
@group(1) @binding(0) var<uniform> mdl: Model;

struct VSIn {
    @location(0) position: vec3<f32>,
    @location(1) uv: vec2<f32>,
};
struct VSOut {
    @builtin(position) clip: vec4<f32>,
    @location(0) uv: vec2<f32>,
};

@vertex
fn vs_main(in: VSIn) -> VSOut {
    var out: VSOut;
    let world = mdl.model * vec4<f32>(in.position, 1.0);
    out.clip = cam.view_proj * world;
    out.uv = in.uv;
    return out;
}

@fragment
fn fs_main(in: VSOut) -> @location(0) vec4<f32> {
    return mdl.color;
}
"""


# ----------------------------------------------------------------------
# Blinn-Phong 3D — 4 lights + ambient. No PBR fanciness (per user).
# ----------------------------------------------------------------------
PHONG_3D_WGSL = """// slappyengine phong_3d
struct Camera { view_proj: mat4x4<f32>, cam_pos: vec4<f32> };
struct Model  { model: mat4x4<f32>, color: vec4<f32> };
struct LightSlot {
    pos_kind: vec4<f32>,
    dir_range: vec4<f32>,
    color_intensity: vec4<f32>,
    spot_enable_pad: vec4<f32>,
};
struct Lights {
    slots: array<LightSlot, 4>,
    ambient: vec4<f32>,
};

@group(0) @binding(0) var<uniform> cam: Camera;
@group(0) @binding(1) var<uniform> lights: Lights;
@group(1) @binding(0) var<uniform> mdl: Model;

struct VSIn {
    @location(0) position: vec3<f32>,
    @location(1) normal: vec3<f32>,
    @location(2) uv: vec2<f32>,
};
struct VSOut {
    @builtin(position) clip: vec4<f32>,
    @location(0) world_pos: vec3<f32>,
    @location(1) world_normal: vec3<f32>,
    @location(2) uv: vec2<f32>,
};

@vertex
fn vs_main(in: VSIn) -> VSOut {
    var out: VSOut;
    let world = mdl.model * vec4<f32>(in.position, 1.0);
    out.world_pos = world.xyz;
    let nrm4 = mdl.model * vec4<f32>(in.normal, 0.0);
    out.world_normal = normalize(nrm4.xyz);
    out.uv = in.uv;
    out.clip = cam.view_proj * world;
    return out;
}

fn shade_slot(slot: LightSlot, world_pos: vec3<f32>, n: vec3<f32>, view_dir: vec3<f32>, base: vec3<f32>) -> vec3<f32> {
    if (slot.spot_enable_pad.y < 0.5) { return vec3<f32>(0.0); }
    let kind = slot.pos_kind.w;
    var L: vec3<f32>;
    var att: f32 = 1.0;
    if (kind < 0.5) {
        L = -normalize(slot.dir_range.xyz);
    } else {
        let to_light = slot.pos_kind.xyz - world_pos;
        let d = length(to_light);
        L = to_light / max(d, 0.0001);
        let r = max(slot.dir_range.w, 0.0001);
        att = clamp(1.0 - d / r, 0.0, 1.0);
        att = att * att;
        if (kind > 1.5) {
            let spot_axis = -normalize(slot.dir_range.xyz);
            let cs = dot(L, spot_axis);
            if (cs < slot.spot_enable_pad.x) { att = 0.0; }
        }
    }
    let ndl = max(dot(n, L), 0.0);
    let h = normalize(L + view_dir);
    let spec = pow(max(dot(n, h), 0.0), 32.0);
    let intensity = slot.color_intensity.w;
    let color = slot.color_intensity.xyz * intensity * att;
    return (base * ndl + spec * 0.4) * color;
}

@fragment
fn fs_main(in: VSOut) -> @location(0) vec4<f32> {
    let n = normalize(in.world_normal);
    let view_dir = normalize(cam.cam_pos.xyz - in.world_pos);
    let base = mdl.color.rgb;
    var rgb = base * lights.ambient.rgb * lights.ambient.a;
    for (var i: i32 = 0; i < 4; i = i + 1) {
        rgb = rgb + shade_slot(lights.slots[i], in.world_pos, n, view_dir, base);
    }
    return vec4<f32>(rgb, mdl.color.a);
}
"""


# ----------------------------------------------------------------------
# Sprite 2D — textured/tinted quad.
# ----------------------------------------------------------------------
SPRITE_2D_WGSL = """// slappyengine sprite_2d
struct Camera { view_proj: mat4x4<f32> };
struct Sprite { transform: mat4x4<f32>, tint: vec4<f32> };

@group(0) @binding(0) var<uniform> cam: Camera;
@group(1) @binding(0) var<uniform> sprite: Sprite;
@group(1) @binding(1) var tex: texture_2d<f32>;
@group(1) @binding(2) var samp: sampler;

struct VSIn { @location(0) position: vec2<f32>, @location(1) uv: vec2<f32> };
struct VSOut { @builtin(position) clip: vec4<f32>, @location(0) uv: vec2<f32> };

@vertex
fn vs_main(in: VSIn) -> VSOut {
    var out: VSOut;
    let world = sprite.transform * vec4<f32>(in.position, 0.0, 1.0);
    out.clip = cam.view_proj * world;
    out.uv = in.uv;
    return out;
}

@fragment
fn fs_main(in: VSOut) -> @location(0) vec4<f32> {
    let tex_rgba = textureSample(tex, samp, in.uv);
    return tex_rgba * sprite.tint;
}
"""


# ----------------------------------------------------------------------
# Debug lines — anti-aliased thin lines.
# ----------------------------------------------------------------------
LINE_3D_WGSL = """// slappyengine line_3d
struct Camera { view_proj: mat4x4<f32> };
@group(0) @binding(0) var<uniform> cam: Camera;

struct VSIn { @location(0) position: vec3<f32>, @location(1) color: vec4<f32> };
struct VSOut { @builtin(position) clip: vec4<f32>, @location(0) color: vec4<f32> };

@vertex
fn vs_main(in: VSIn) -> VSOut {
    var out: VSOut;
    out.clip = cam.view_proj * vec4<f32>(in.position, 1.0);
    out.color = in.color;
    return out;
}

@fragment
fn fs_main(in: VSOut) -> @location(0) vec4<f32> {
    return in.color;
}
"""


# ----------------------------------------------------------------------
# Depth-only prepass — vertex-only, colour writes off at the pipeline level.
# Reuses the same Camera / Model binding layout as unlit_3d so DepthPrepass
# can share the renderer's camera UBO. JJ7's SHADOW_DEPTH_ONLY_WGSL exists
# in shadows.py but binds its own ``ShadowCam.lvp``; we need the main
# forward camera VP here.
# ----------------------------------------------------------------------
DEPTH_ONLY_WGSL = """// slappyengine depth_only
struct Camera { view_proj: mat4x4<f32> };
struct Model  { model: mat4x4<f32>, color: vec4<f32> };

@group(0) @binding(0) var<uniform> cam: Camera;
@group(1) @binding(0) var<uniform> mdl: Model;

@vertex
fn vs_main(@location(0) position: vec3<f32>) -> @builtin(position) vec4<f32> {
    return cam.view_proj * (mdl.model * vec4<f32>(position, 1.0));
}

// API-validation layers reject depth-only pipelines with no fragment
// entry point, so we emit a nominal stub that's masked off by the
// pipeline's colour write mask.
@fragment
fn fs_main() -> @location(0) vec4<f32> { return vec4<f32>(0.0); }
"""


@dataclass(frozen=True)
class ShaderSource:
    name: str
    wgsl: str
    entry_vs: str = "vs_main"
    entry_fs: str = "fs_main"

    @property
    def byte_size(self) -> int:
        return len(self.wgsl.encode("utf-8"))


STOCK_SHADERS: dict[str, ShaderSource] = {
    "unlit_3d":  ShaderSource("unlit_3d",  UNLIT_3D_WGSL),
    "phong_3d":  ShaderSource("phong_3d",  PHONG_3D_WGSL),
    "sprite_2d": ShaderSource("sprite_2d", SPRITE_2D_WGSL),
    "line_3d":   ShaderSource("line_3d",   LINE_3D_WGSL),
    "depth_only": ShaderSource("depth_only", DEPTH_ONLY_WGSL),
}


def get_shader(name: str) -> ShaderSource:
    if name not in STOCK_SHADERS:
        raise KeyError(f"Unknown stock shader {name!r}; known: {sorted(STOCK_SHADERS)}")
    return STOCK_SHADERS[name]
