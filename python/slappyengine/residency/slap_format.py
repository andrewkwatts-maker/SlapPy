from __future__ import annotations

import io
import json
import struct
from pathlib import Path

import numpy as np
from PIL import Image

from slappyengine._validation import validate_path_like
from slappyengine.residency.compression import compress_array, decompress_raw

SLAP_MAGIC = b"SLAP"
SLAP_VERSION = 1

_HDR_FMT = "<4sII"   # magic(4s), version(I), count(I)
_HDR_SIZE = struct.calcsize(_HDR_FMT)  # 12


def _pack_u32(v: int) -> bytes:
    return struct.pack("<I", v)


def _pack_u64(v: int) -> bytes:
    return struct.pack("<Q", v)



def _encode_layer(layer) -> bytes:
    buf = io.BytesIO()

    if layer._image_data is not None and layer._image_data.size > 0:
        img_buf = io.BytesIO()
        Image.fromarray(layer._image_data).save(img_buf, format="PNG")
        visual_bytes = img_buf.getvalue()
    else:
        visual_bytes = b""

    buf.write(_pack_u32(len(visual_bytes)))
    buf.write(visual_bytes)

    pixel_data = getattr(layer, "_pixel_data", None) or getattr(layer, "_data_array", None)
    if pixel_data is not None:
        struct_bytes = compress_array(pixel_data)
    else:
        struct_bytes = b""

    buf.write(_pack_u32(len(struct_bytes)))
    buf.write(struct_bytes)

    size = layer.size or (0, 0)
    layer_meta = {
        "name": layer.name,
        "opacity": layer.opacity,
        "visible": layer.visible,
        "size": list(size),
        "channel_map": layer.channel_map,
    }
    layer_meta_bytes = json.dumps(layer_meta).encode("utf-8")
    buf.write(_pack_u32(len(layer_meta_bytes)))
    buf.write(layer_meta_bytes)

    return buf.getvalue()


def _encode_asset_block(asset) -> bytes:
    buf = io.BytesIO()

    asset_meta = {
        "name": asset.name,
        "position": list(asset.position),
        "size": list(asset.size),
        "z_order": asset.z_order,
    }
    meta_bytes = json.dumps(asset_meta).encode("utf-8")
    buf.write(_pack_u32(len(meta_bytes)))
    buf.write(meta_bytes)

    layers = getattr(asset, "layers", [])
    buf.write(_pack_u32(len(layers)))
    for layer in layers:
        buf.write(_encode_layer(layer))

    return buf.getvalue()


def _decode_layer(f: io.BufferedReader) -> dict:
    visual_len = struct.unpack("<I", f.read(4))[0]
    visual_bytes = f.read(visual_len) if visual_len > 0 else b""

    struct_len = struct.unpack("<I", f.read(4))[0]
    struct_bytes = f.read(struct_len) if struct_len > 0 else b""

    layer_meta_len = struct.unpack("<I", f.read(4))[0]
    layer_meta = json.loads(f.read(layer_meta_len).decode("utf-8"))

    image_data = None
    if visual_bytes:
        img = Image.open(io.BytesIO(visual_bytes)).convert("RGBA")
        image_data = np.asarray(img, dtype=np.uint8)

    pixel_data = None
    if struct_bytes:
        raw = decompress_raw(struct_bytes)
        pixel_data = np.frombuffer(raw, dtype=np.float32).copy()
        size = layer_meta.get("size")
        if size and len(size) == 2 and size[0] > 0 and size[1] > 0:
            total = size[0] * size[1]
            if pixel_data.size % total == 0:
                channels = pixel_data.size // total
                pixel_data = pixel_data.reshape(size[1], size[0], channels)

    return {
        "name": layer_meta.get("name", "Layer"),
        "opacity": layer_meta.get("opacity", 1.0),
        "visible": layer_meta.get("visible", True),
        "size": layer_meta.get("size", [0, 0]),
        "channel_map": layer_meta.get("channel_map", {}),
        "image_data": image_data,
        "pixel_data": pixel_data,
    }


def _decode_asset_block(f: io.BufferedReader) -> dict:
    meta_len = struct.unpack("<I", f.read(4))[0]
    meta = json.loads(f.read(meta_len).decode("utf-8"))

    layer_count = struct.unpack("<I", f.read(4))[0]
    layers = [_decode_layer(f) for _ in range(layer_count)]

    return {
        "name": meta.get("name", ""),
        "position": meta.get("position", [0.0, 0.0]),
        "size": meta.get("size", [64, 64]),
        "z_order": meta.get("z_order", 0),
        "meta": meta,
        "layers": layers,
    }


def write_world_slap(path: str | Path, assets: list) -> None:
    """Serialise a list of assets to ``path`` as a ``.slap`` file.

    Raises
    ------
    TypeError
        If ``path`` is not a str/Path or ``assets`` is not a list/tuple.
    ValueError
        If ``path`` is empty.
    """
    path = validate_path_like("path", "write_world_slap", path)
    if isinstance(assets, (str, bytes, dict, set)) or not isinstance(assets, (list, tuple)):
        raise TypeError(
            f"write_world_slap: assets must be a list or tuple; "
            f"got {type(assets).__name__}"
        )
    count = len(assets)

    blocks = [_encode_asset_block(a) for a in assets]

    entry_sizes = []
    for asset in assets:
        name_bytes = asset.name.encode("utf-8")
        entry_sizes.append(4 + len(name_bytes) + 8)

    data_start = _HDR_SIZE + sum(entry_sizes)

    offsets = []
    cursor = data_start
    for block in blocks:
        offsets.append(cursor)
        cursor += len(block)

    with open(path, "wb") as f:
        f.write(struct.pack(_HDR_FMT, SLAP_MAGIC, SLAP_VERSION, count))

        for asset, block, offset in zip(assets, blocks, offsets):
            name_bytes = asset.name.encode("utf-8")
            f.write(_pack_u32(len(name_bytes)))
            f.write(name_bytes)
            f.write(_pack_u64(offset))

        for block in blocks:
            f.write(block)


def read_world_slap(path: str | Path) -> list[dict]:
    """Read a ``.slap`` file and return a list of asset dicts.

    Raises
    ------
    TypeError
        If ``path`` is not a str/Path.
    ValueError
        If ``path`` is empty or the file's magic bytes are wrong.
    """
    path = validate_path_like("path", "read_world_slap", path)
    with open(path, "rb") as f:
        magic, version, count = struct.unpack(_HDR_FMT, f.read(_HDR_SIZE))
        if magic != SLAP_MAGIC:
            raise ValueError(f"Not a .slap file: bad magic {magic!r}")
        if version != SLAP_VERSION:
            raise ValueError(f"Unsupported .slap version: {version}")

        directory = []
        for _ in range(count):
            name_len = struct.unpack("<I", f.read(4))[0]
            name = f.read(name_len).decode("utf-8")
            offset = struct.unpack("<Q", f.read(8))[0]
            directory.append((name, offset))

        results = []
        for name, offset in directory:
            f.seek(offset)
            asset_dict = _decode_asset_block(f)
            results.append(asset_dict)

    return results


def write_asset_to_slap(path: str | Path, asset) -> None:
    """Serialise a single asset to ``path``.

    Raises
    ------
    TypeError
        If ``path`` is not a str/Path or ``asset`` is None.
    """
    validate_path_like("path", "write_asset_to_slap", path)
    if asset is None:
        raise TypeError("write_asset_to_slap: asset must not be None")
    write_world_slap(path, [asset])


def read_asset_from_slap(path: str | Path) -> dict:
    """Read a single-asset ``.slap`` file and return its dict."""
    validate_path_like("path", "read_asset_from_slap", path)
    results = read_world_slap(path)
    if not results:
        raise ValueError(f"No assets found in {path}")
    return results[0]
