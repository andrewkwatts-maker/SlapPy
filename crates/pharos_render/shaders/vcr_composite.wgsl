// pharos_render :: VCR Stage 4 — Composite.
//
// Fullscreen post-pass. Reads all K reservoir slots per pixel, evaluates
// each sub-camera's cone (mipped environment lookup with SSR fallback),
// sums via WRS weights, applies Beer-Lambert absorption, and blends
// over the primary G-buffer shading result.
//
// Output goes to the final HDR framebuffer that the tone-mapping /
// bloom chain consumes.

@group(0) @binding(0) var g_base_metal:  texture_2d<f32>;
@group(0) @binding(1) var g_normal_rough: texture_2d<f32>;
@group(0) @binding(2) var g_pos_matid:   texture_2d<f32>;
@group(0) @binding(3) var g_ior_absorb:  texture_2d<f32>;
@group(1) @binding(0) var reservoir:     texture_storage_3d<rgba32float, read>;
@group(2) @binding(0) var env_cube:      texture_cube<f32>;
@group(2) @binding(1) var env_sampler:   sampler;

struct VertexOut {
    @builtin(position) clip: vec4<f32>,
    @location(0) uv: vec2<f32>,
};

@vertex
fn vs_fullscreen(@builtin(vertex_index) vid: u32) -> VertexOut {
    // Trick: 3-vert fullscreen triangle covers [-1,1] via clamped uv.
    var v: VertexOut;
    let x = f32((vid << 1u) & 2u) * 2.0 - 1.0;
    let y = f32(vid & 2u) * 2.0 - 1.0;
    v.clip = vec4<f32>(x, y, 0.0, 1.0);
    v.uv = vec2<f32>((x + 1.0) * 0.5, 1.0 - (y + 1.0) * 0.5);
    return v;
}

@fragment
fn fs_main(in: VertexOut) -> @location(0) vec4<f32> {
    let px = vec2<i32>(in.clip.xy);
    let dims = textureDimensions(g_base_metal);
    if (px.x >= i32(dims.x) || px.y >= i32(dims.y)) { return vec4<f32>(0.0); }

    let base = textureLoad(g_base_metal, px, 0);
    let base_colour = base.rgb;
    let metallic = base.a;
    let normal_rough = textureLoad(g_normal_rough, px, 0);
    let normal = normalize(normal_rough.xyz);
    let roughness = normal_rough.a;
    let ior_absorb = textureLoad(g_ior_absorb, px, 0);
    let absorption = ior_absorb.yzw;

    var reflected_sum = vec3<f32>(0.0);
    var refracted_sum = vec3<f32>(0.0);
    var total_weight  = 0.0;

    for (var k: u32 = 0u; k < VCR_K_SLOTS; k = k + 1u) {
        let lo = textureLoad(reservoir, vec3<i32>(px, i32(k * 2u)));
        let hi = textureLoad(reservoir, vec3<i32>(px, i32(k * 2u + 1u)));
        let slot_dir = hi.xyz;
        let slot_cone = hi.w;
        let slot_matid = lo.w;
        // Sample env cube with LoD proportional to cone half-angle.
        let lod = slot_cone * 6.0;
        let env = textureSampleLevel(env_cube, env_sampler, slot_dir, lod).rgb;
        let weight = 1.0 / (1.0 + f32(k));    // Sprint 7 replaces with true WRS weight
        // Slot 0 = specular, slot 1 = refraction (matches seed shader).
        if (slot_matid < 0.5) {
            reflected_sum = reflected_sum + env * weight;
        } else {
            refracted_sum = refracted_sum + env * weight;
        }
        total_weight = total_weight + weight;
    }
    if (total_weight > 0.0) {
        reflected_sum = reflected_sum / total_weight;
        refracted_sum = refracted_sum / total_weight;
    }

    // Fresnel-lite mix. Full model comes in Sprint 7 with proper GGX.
    let f0 = mix(vec3<f32>(0.04), base_colour, metallic);
    let ndl = max(dot(normal, vec3<f32>(0.4, 0.8, 0.4)), 0.05);
    let diffuse = base_colour * ndl * (1.0 - metallic);
    let specular = f0 * reflected_sum;
    let refr = refracted_sum * exp(-absorption);

    var final_colour = diffuse + specular;
    if (any(absorption > vec3<f32>(0.0))) {
        final_colour = final_colour + refr;
    }
    return vec4<f32>(final_colour, 1.0);
}
