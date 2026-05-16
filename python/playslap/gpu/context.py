from __future__ import annotations

import logging
from typing import Any, Optional

import wgpu

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Backend selection helpers
# ---------------------------------------------------------------------------

# Map config string → wgpu-native InstanceBackend flag name.
# wgpu 0.31 selects the backend at *instance* creation time via
# set_instance_extras(), not at request_adapter time, so we call that
# function before the first adapter request.
_BACKEND_FLAG_MAP: dict[str, str] = {
    "vulkan":  "Vulkan",
    "metal":   "Metal",
    "dx12":    "DX12",
    "webgpu":  "BrowserWebGPU",
    "gl":      "GL",
    # "auto" → omitted (use wgpu default "All")
}

# Map config underscore form → wgpu hyphenated power-preference string.
_POWER_PREF_MAP: dict[str, str] = {
    "high_performance": "high-performance",
    "low_power":        "low-power",
    "auto":             None,           # type: ignore[dict-item]
}


def _apply_backend_preference(backend: str) -> None:
    """Call set_instance_extras() to restrict wgpu to a single backend.

    Must be invoked before the first call to request_adapter_sync / any
    enumerate_adapters call, because it configures the global wgpu instance.
    Has no effect when backend == "auto".
    """
    flag = _BACKEND_FLAG_MAP.get(backend)
    if flag is None:
        # "auto" — let wgpu pick from all available backends.
        return
    try:
        from wgpu.backends.wgpu_native.extras import set_instance_extras
        set_instance_extras(backends=[flag])
        logger.debug("wgpu: restricting to backend '%s' (flag=%s)", backend, flag)
    except Exception as exc:  # noqa: BLE001
        # Graceful degradation: log a warning and continue with auto selection.
        logger.warning(
            "wgpu: could not restrict backend to '%s': %s — falling back to auto.",
            backend,
            exc,
        )


# ---------------------------------------------------------------------------
# GPUContext
# ---------------------------------------------------------------------------


class GPUContext:
    def __init__(self, canvas: Any):
        """
        canvas: a WgpuCanvas from wgpu.gui.auto
        Call .initialize() before using — it's async-compatible via wgpu's sync request functions.
        """
        self._canvas = canvas
        self.adapter: wgpu.GPUAdapter | None = None
        self.device: wgpu.GPUDevice | None = None
        self.queue: wgpu.GPUQueue | None = None
        self.surface_format: wgpu.TextureFormat | None = None
        self._context: Any = None  # wgpu canvas context

    def initialize(self, cfg: Optional[Any] = None) -> None:
        """Set up the wgpu adapter, device, and surface.

        Parameters
        ----------
        cfg:
            Optional :class:`~playslap.config.Config` object.  When
            provided, ``cfg.rendering.backend`` and
            ``cfg.rendering.power_preference`` drive adapter selection.
        """
        # --- resolve preferences from config (or fall back to sensible defaults)
        backend = "auto"
        power_pref_raw = "high_performance"
        if cfg is not None:
            backend = getattr(cfg.rendering, "backend", "auto")
            power_pref_raw = getattr(cfg.rendering, "power_preference", "high_performance")

        # Apply backend restriction before the wgpu instance is created.
        _apply_backend_preference(backend)

        # Convert underscore config values to the hyphenated strings wgpu expects.
        power_preference = _POWER_PREF_MAP.get(power_pref_raw, "high-performance")

        # Request the adapter.
        self.adapter = wgpu.gpu.request_adapter_sync(
            power_preference=power_preference,
        )

        # Log adapter info so the chosen backend is visible at startup.
        info = self.adapter.info
        logger.info(
            "wgpu adapter selected — device: %s | backend: %s | type: %s",
            info["device"],
            info["backend_type"],
            info["adapter_type"],
        )

        self.device = self.adapter.request_device_sync(
            required_features=[],
            required_limits={},
        )
        self.queue = self.device.queue
        self._context = self._canvas.get_context("wgpu")
        self.surface_format = self._context.get_preferred_format(self.adapter)
        self._context.configure(
            device=self.device,
            format=self.surface_format,
            # COPY_SRC allows the lighting system to copy the rendered frame into
            # its own offscreen texture for compute shader access.
            usage=wgpu.TextureUsage.RENDER_ATTACHMENT | wgpu.TextureUsage.COPY_SRC,
        )

    def get_current_texture(self) -> wgpu.GPUTexture:
        return self._context.get_current_texture()

    def create_encoder(self, label: str = "") -> wgpu.GPUCommandEncoder:
        return self.device.create_command_encoder(label=label)

    def submit(self, *encoders: wgpu.GPUCommandEncoder) -> None:
        self.queue.submit([enc.finish() for enc in encoders])

    @property
    def limits(self) -> dict:
        return self.device.limits

    def create_buffer(
        self,
        *,
        size: int,
        usage: wgpu.BufferUsage,
        label: str = "",
        mapped_at_creation: bool = False,
    ) -> wgpu.GPUBuffer:
        return self.device.create_buffer(
            size=size,
            usage=usage,
            label=label,
            mapped_at_creation=mapped_at_creation,
        )

    def write_buffer(self, buf: wgpu.GPUBuffer, data, offset: int = 0) -> None:
        self.queue.write_buffer(buf, offset, data)

    def write_texture(
        self,
        destination: dict,
        data,
        data_layout: dict,
        size: tuple,
    ) -> None:
        self.queue.write_texture(destination, data, data_layout, size)
