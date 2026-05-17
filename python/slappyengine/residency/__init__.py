"""Residency subpackage — lazy-loaded to avoid eager imports."""
from __future__ import annotations

__all__ = [
    "ResidencyManager",
    "compress_array",
    "decompress_array",
    "compress_raw",
    "decompress_raw",
    "write_asset_to_slap",
    "read_asset_from_slap",
    "write_world_slap",
    "read_world_slap",
    "SLAP_MAGIC",
    "SLAP_VERSION",
]

_LAZY_MAP: dict[str, str] = {
    "ResidencyManager": ".manager",
    "compress_array":   ".compression",
    "decompress_array": ".compression",
    "compress_raw":     ".compression",
    "decompress_raw":   ".compression",
    "write_asset_to_slap": ".slap_format",
    "read_asset_from_slap": ".slap_format",
    "write_world_slap": ".slap_format",
    "read_world_slap":  ".slap_format",
    "SLAP_MAGIC":       ".slap_format",
    "SLAP_VERSION":     ".slap_format",
}


def __getattr__(name: str):
    if name in _LAZY_MAP:
        import importlib
        try:
            mod = importlib.import_module(_LAZY_MAP[name], package=__name__)
        except ImportError:
            # Optional Rust-backed modules may not be built yet; return None
            if name not in ("ResidencyManager",):
                globals()[name] = None
                return None
            raise
        val = getattr(mod, name, None)
        globals()[name] = val
        return val
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
