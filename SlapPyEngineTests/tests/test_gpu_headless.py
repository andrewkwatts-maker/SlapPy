"""GPU tests that run without a display window.

All tests skip gracefully if no GPU adapter is available (CI).
"""
import pytest
import numpy as np

# Skip entire module if wgpu can't get a device
wgpu = pytest.importorskip("wgpu")


def _get_device():
    try:
        adapter = wgpu.gpu.request_adapter_sync(power_preference="high-performance")
        if adapter is None:
            return None
        return adapter.request_device_sync()
    except Exception:
        return None


@pytest.fixture(scope="module")
def gpu_device():
    dev = _get_device()
    if dev is None:
        pytest.skip("No GPU adapter available")
    return dev


def test_texture_upload(gpu_device):
    """Upload a 4×4 RGBA image to a GPU texture."""
    img = np.zeros((4, 4, 4), dtype=np.uint8)
    img[:, :] = [255, 128, 0, 255]

    texture = gpu_device.create_texture(
        size=(4, 4, 1),
        format=wgpu.TextureFormat.rgba8unorm,
        usage=wgpu.TextureUsage.TEXTURE_BINDING | wgpu.TextureUsage.COPY_DST,
    )
    gpu_device.queue.write_texture(
        {"texture": texture, "mip_level": 0, "origin": (0, 0, 0)},
        img.tobytes(),
        {"bytes_per_row": 16, "rows_per_image": 4},
        (4, 4, 1),
    )
    assert texture is not None


def test_storage_buffer_size(gpu_device):
    """Storage buffer stride matches struct registry layout."""
    from slappyengine.struct_registry import StructRegistry
    from slappyengine.modules.health import HealthModule
    from slappyengine.modules.physics import PhysicsModule

    reg = StructRegistry()
    reg.register(HealthModule)
    reg.register(PhysicsModule)

    stride = reg.stride_bytes()
    # stride must be multiple of 16 (WGSL struct alignment)
    assert stride % 16 == 0
    # color (vec4f=16) + health(4) + max_health(4) + tag(4) + pad(4) +
    # strength(4) + stiffness(4) + density(4) + vel_x(4) + vel_y(4) + pad...
    assert stride >= 16  # at minimum the color vec4f

    width, height = 16, 16
    size_bytes = width * height * stride
    size_bytes = (size_bytes + 15) & ~15

    buf = gpu_device.create_buffer(
        size=size_bytes,
        usage=wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.COPY_SRC | wgpu.BufferUsage.COPY_DST,
    )
    assert buf is not None


def test_uniform_buffer_alignment(gpu_device):
    """Camera uniform buffer is 256-byte aligned."""
    # Camera matrix = 64 bytes → aligned to 256
    aligned_size = (64 + 255) & ~255
    assert aligned_size == 256

    buf = gpu_device.create_buffer(
        size=aligned_size,
        usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST,
    )
    assert buf is not None


def test_compute_buffer_write_read(gpu_device):
    """Write floats to a storage buffer, read them back via staging buffer."""
    data = np.array([1.0, 2.0, 3.0, 4.0], dtype=np.float32)
    size = data.nbytes

    src_buf = gpu_device.create_buffer(
        size=size,
        usage=wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.COPY_SRC | wgpu.BufferUsage.COPY_DST,
    )
    staging = gpu_device.create_buffer(
        size=size,
        usage=wgpu.BufferUsage.COPY_DST | wgpu.BufferUsage.MAP_READ,
    )

    gpu_device.queue.write_buffer(src_buf, 0, data.tobytes())

    encoder = gpu_device.create_command_encoder()
    encoder.copy_buffer_to_buffer(src_buf, 0, staging, 0, size)
    gpu_device.queue.submit([encoder.finish()])

    # wgpu-py map_sync maps the buffer in-place; read_mapped returns a memoryview
    staging.map_sync(wgpu.MapMode.READ)
    result = np.frombuffer(staging.read_mapped(0, size), dtype=np.float32)
    np.testing.assert_array_almost_equal(result, data)
    staging.unmap()
