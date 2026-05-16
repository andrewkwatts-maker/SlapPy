from __future__ import annotations
from pathlib import Path
from typing import Any, TYPE_CHECKING
import numpy as np
import wgpu
from slappyengine.entity import Entity
from slappyengine.event_bus import EventBus

if TYPE_CHECKING:
    from slappyengine.camera import Camera
    from slappyengine.gpu.context import GPUContext
    from slappyengine.struct_registry import StructRegistry

class Scene:
    def __init__(self, name: str = "Scene"):
        from slappyengine.collision import CollisionWorld
        self.name = name
        self._entities: dict[str, Entity] = {}   # id → entity
        self.camera: Camera | None = None
        self.post_process: list = []             # scene-wide post-process chain (M10)
        self.post_process_chain = None           # PostProcessChain | None
        self.compute: SceneComputeAPI | None = None
        self.decals: DecalSystem | None = None
        self.region_effects: list = []
        self.landscape = None
        self.collision: CollisionWorld = CollisionWorld()
        self.strata: "StrataWorld | None" = None
        self._z_layers: list = []  # list[ZLayer], ordered by z ascending
        # Fluid simulation reference — set by engine.enable_fluid_sim()
        self.fluid: "GlobalFluidSim | None" = None  # type: ignore[name-defined]
        self.bus: EventBus = EventBus()

    def add(self, entity: Entity) -> Entity:
        self._entities[entity.id] = entity
        entity.scene = self  # back-reference so scripts can reach the scene
        entity.on_create()
        self.bus.publish("entity:created", entity=entity, scene=self)
        return entity

    def remove(self, entity: Entity) -> None:
        self.bus.publish("entity:destroyed", entity=entity, scene=self)
        entity.on_destroy()
        entity.scene = None
        self._entities.pop(entity.id, None)

    def get(self, entity_id: str) -> Entity | None:
        return self._entities.get(entity_id)

    def __len__(self) -> int:
        return len(self._entities)

    def find_by_name(self, name: str) -> list[Entity]:
        return [e for e in self._entities.values() if e.name == name]

    def find_by_tag(self, tag: str) -> list[Entity]:
        return [e for e in self._entities.values() if tag in e.tags]

    @property
    def entities(self) -> list[Entity]:
        return list(self._entities.values())

    def add_z_layer(self, layer) -> None:
        """Add a ZLayer and keep the list sorted by z ascending."""
        self._z_layers.append(layer)
        self._z_layers.sort(key=lambda l: l.z)

    def remove_z_layer(self, layer) -> None:
        if layer in self._z_layers:
            self._z_layers.remove(layer)

    @property
    def z_layers(self) -> list:
        return self._z_layers

    def _tick(self, dt: float) -> None:
        for entity in list(self._entities.values()):
            entity.tick(dt)
        self.collision.tick()
        if self.strata is not None:
            self.strata.tick(dt)

    def save(self, path: str) -> None:
        from slappyengine.asset import Asset
        from slappyengine.residency.slap_format import write_world_slap

        assets = [e for e in self.entities if isinstance(e, Asset)]
        write_world_slap(path, assets)

    def load(self, path: str, *, clear: bool = True) -> None:
        from slappyengine.asset import Asset
        from slappyengine.layer import Layer
        from slappyengine.residency.slap_format import read_world_slap

        records = read_world_slap(path)

        if clear:
            for entity in list(self._entities.values()):
                entity.on_despawn()
            self._entities.clear()

        for rec in records:
            meta = rec.get("meta", {})
            asset = Asset(
                name=meta.get("name", ""),
                position=tuple(meta.get("position", [0.0, 0.0])),
                size=tuple(meta.get("size", [64, 64])),
            )
            asset.z_order = meta.get("z_order", 0)

            for ldata in rec.get("layers", []):
                lmeta = ldata.get("meta", {})
                img = ldata.get("image_data")
                w, h = lmeta.get("size", [64, 64])
                layer = Layer.blank(w, h, name=lmeta.get("name", ""))
                if img is not None:
                    layer._image_data = img
                layer.opacity = lmeta.get("opacity", 1.0)
                layer.visible = lmeta.get("visible", True)
                struct_data = ldata.get("struct_data")
                if struct_data is not None:
                    layer._ram_pixel_data = struct_data
                asset.add_layer(layer)

            self._entities[asset.id] = asset
            asset.on_spawn()

    async def simulate(self, steps: int = 1, dt: float | None = None) -> None:
        # dt falls back to config value — not hardcoded here
        from slappyengine.config import engine_config
        _dt = dt if dt is not None else engine_config().physics.default_dt
        for _ in range(steps):
            self._tick(_dt)


class SceneComputeAPI:
    """Scene-wide compute dispatch. Fully implemented in M4."""
    def __init__(self, scene: Scene, ctx: Any):
        self._scene = scene
        self._ctx = ctx

    def run(self, shader_name: str, assets: list | None = None) -> None:
        # Dispatch the named shader on each specified (or all) asset's compute API
        from slappyengine.asset import Asset
        import asyncio
        from pathlib import Path

        targets = assets if assets is not None else [
            e for e in self._scene.entities if isinstance(e, Asset)
        ]
        shader_dir = Path(__file__).parent.parent.parent / "shaders"
        shader_file = shader_dir / f"{shader_name}.wgsl"

        for asset in targets:
            if asset.compute is not None and shader_file.exists():
                from slappyengine.compute.pipeline import ComputePass
                pass_ = ComputePass.from_wgsl(shader_file)
                asyncio.get_event_loop().run_until_complete(
                    asset.compute.dispatch(pass_)
                )


_BLEND_MODES = {"normal": 0, "multiply": 1, "additive": 2}
_SHADER_PATH = Path(__file__).parent.parent.parent / "shaders" / "decal_paint.wgsl"


class DecalSystem:
    def __init__(self, ctx: "GPUContext",
                 registry: "StructRegistry | None" = None,
                 tex_mgr: Any = None):
        self._ctx = ctx
        self._registry = registry
        self._tex_mgr = tex_mgr

    def paint(self, *, target, decal_texture: str,
              uv_center: tuple[float, float], radius: float,
              blend: str = "normal", channel_writes: dict | None = None) -> None:
        import struct as _struct
        from PIL import Image

        device = self._ctx.device

        img = Image.open(decal_texture).convert("RGBA")
        dw, dh = img.size
        decal_data = np.asarray(img, dtype=np.uint8)

        decal_gpu_tex = device.create_texture(
            size=(dw, dh, 1),
            format=wgpu.TextureFormat.rgba8unorm,
            usage=wgpu.TextureUsage.TEXTURE_BINDING | wgpu.TextureUsage.COPY_DST,
            label="decal:src",
        )
        self._ctx.write_texture(
            {"texture": decal_gpu_tex, "mip_level": 0, "origin": (0, 0, 0)},
            decal_data.tobytes(),
            {"bytes_per_row": dw * 4, "rows_per_image": dh},
            (dw, dh, 1),
        )
        decal_view = decal_gpu_tex.create_view()
        sampler = device.create_sampler(
            mag_filter=wgpu.FilterMode.linear,
            min_filter=wgpu.FilterMode.linear,
            mipmap_filter=wgpu.MipmapFilterMode.nearest,
            address_mode_u=wgpu.AddressMode.clamp_to_edge,
            address_mode_v=wgpu.AddressMode.clamp_to_edge,
        )

        from slappyengine.asset import Asset
        if not isinstance(target, Asset) or not target.layers:
            raise ValueError("target must be an Asset with at least one layer")
        layer = target.layers[0]
        tw, th = layer.size or (1, 1)

        buf_mgr = getattr(target.compute, "_buf_mgr", None) if target.compute is not None else None
        if buf_mgr is None:
            raise RuntimeError("Asset has no BufferManager — run engine first")

        pixel_buf = buf_mgr.get_pixel_buffer(layer)
        if pixel_buf is None:
            pixel_buf = buf_mgr.create_pixel_buffer(layer)

        stride_bytes = self._registry.stride_bytes() if self._registry else 16
        stride_u32s = stride_bytes // 4

        blend_mode = _BLEND_MODES.get(blend, 0)

        ch0_offset = 0xFFFFFFFF
        ch0_delta = 0.0
        ch1_offset = 0xFFFFFFFF
        ch1_delta = 0.0

        if channel_writes and self._registry:
            layout = self._registry._compute_layout()
            items = list(channel_writes.items())
            if len(items) >= 1:
                ch_name, ch_val = items[0]
                if ch_name in layout:
                    ch0_offset = layout[ch_name] // 4
                    ch0_delta = float(ch_val)
            if len(items) >= 2:
                ch_name, ch_val = items[1]
                if ch_name in layout:
                    ch1_offset = layout[ch_name] // 4
                    ch1_delta = float(ch_val)

        params_bytes = _struct.pack(
            "<3fI4IIfIfI3I",
            uv_center[0], uv_center[1], radius, blend_mode,
            tw, th, dw, dh,
            ch0_offset, ch0_delta, ch1_offset, ch1_delta,
            stride_u32s, 0, 0, 0,
        )
        aligned_params = (len(params_bytes) + 255) & ~255
        params_buf = device.create_buffer(
            size=aligned_params,
            usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST,
            label="decal:params",
        )
        self._ctx.write_buffer(params_buf, np.frombuffer(params_bytes, dtype=np.uint8))

        # Temporary storage texture the shader writes blended color into.
        # After dispatch we copy it to the layer's cached render texture (if available).
        visual_tex = device.create_texture(
            size=(tw, th, 1),
            format=wgpu.TextureFormat.rgba8unorm,
            usage=wgpu.TextureUsage.STORAGE_BINDING | wgpu.TextureUsage.COPY_SRC,
            label="decal:visual_out",
        )
        visual_view = visual_tex.create_view()

        shader_src = _SHADER_PATH.read_text(encoding="utf-8")
        module = device.create_shader_module(code=shader_src)
        pipeline = device.create_compute_pipeline(
            layout="auto",
            compute={"module": module, "entry_point": "main"},
        )

        bgl = pipeline.get_bind_group_layout(0)
        bg = device.create_bind_group(
            layout=bgl,
            entries=[
                {"binding": 0, "resource": {"buffer": params_buf, "offset": 0, "size": len(params_bytes)}},
                {"binding": 1, "resource": decal_view},
                {"binding": 2, "resource": sampler},
                {"binding": 3, "resource": {"buffer": pixel_buf}},
                {"binding": 4, "resource": visual_view},
            ],
        )

        encoder = self._ctx.create_encoder("decal_paint")
        cp = encoder.begin_compute_pass()
        cp.set_pipeline(pipeline)
        cp.set_bind_group(0, bg)
        cp.dispatch_workgroups((tw + 7) // 8, (th + 7) // 8, 1)
        cp.end()

        if self._tex_mgr is not None:
            layer_tex = self._tex_mgr._texture_cache.get(id(layer))
            if layer_tex is not None:
                encoder.copy_texture_to_texture(
                    {"texture": visual_tex, "mip_level": 0, "origin": (0, 0, 0)},
                    {"texture": layer_tex, "mip_level": 0, "origin": (0, 0, 0)},
                    (tw, th, 1),
                )

        self._ctx.submit(encoder)

        decal_gpu_tex.destroy()
        params_buf.destroy()
        visual_tex.destroy()
