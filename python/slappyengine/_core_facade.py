"""slappyengine._core_facade — Rust-backend bypass facade (HH8, 2026-07-05).

Codifies the user directive of 2026-07-05:

    "ensure framework is PY PYPI Lib, wrapping a Rust Accellerated backend,
     users should be able to bypass the py lib if they want."

This module is a thin, **documentation-first** wrapper around the compiled
PyO3 extension :mod:`slappyengine._core` (built from ``src/*.rs`` via
``maturin``).  It exists so third-party users can:

1. Detect whether the native extension is present without importing anything
   heavy (:func:`has_native`).
2. Introspect the surface exposed by the Rust backend without spelunking
   through the PyO3 pyd (:func:`list_rust_functions`).
3. Reach the Rust kernels **directly**, bypassing the Python wrappers,
   for perf-critical inner loops or custom pipelines.

The engine's Python wrappers (``compute/spatial.py``,
``animation/procedural.py``, ``physics2/``, etc.) always route through
these same symbols; nothing in the wrapper stack is "hidden" from a user
who prefers the direct path.

Design notes
------------

* The compiled ``_core`` module is **flat** — every ``#[pyfunction]`` and
  ``#[pyclass]`` from every ``src/*.rs`` register-fn is deposited into a
  single namespace.  For ergonomics we synthesise **logical sub-modules**
  (``slappyengine._core.hull``, ``.raster``, ``.pbf_solver`` …) that view
  into that flat surface.  The grouping matches the ``src/*.rs`` file
  layout so users who read the Rust source see the same names.
* When the extension is not compiled we install a :class:`_NullCore`
  stub in place of ``_core`` so ``has_native() is False`` remains the
  only branch the caller has to check.  Attribute access on the stub
  raises a helpful :class:`RuntimeError` that tells the user how to
  build the wheel.

See :doc:`docs/rust_bypass_2026_07_05.md` for the full bypass-pattern
walk-through, including per-function signatures and bypass examples.
"""
from __future__ import annotations

import sys
import types
from typing import Any


__all__ = [
    "has_native",
    "list_rust_functions",
    "core",  # the underlying _core module (or _NullCore stub)
    "_NullCore",
    "RUST_MODULE_MAP",
]


# ---------------------------------------------------------------------------
# _NullCore — helpful stub when the extension isn't compiled
# ---------------------------------------------------------------------------


class _NullCoreError(RuntimeError):
    """Raised when Rust bypass code runs without a compiled extension."""


class _NullCore:
    """Attribute-access stub used when :mod:`slappyengine._core` is missing.

    Every attribute lookup raises :class:`_NullCoreError` with a message
    that points the caller at the maturin build command.  This lets
    downstream code do::

        from slappyengine import _core_facade
        if _core_facade.has_native():
            _core_facade.core.convex_hull(pts)
        else:
            # numpy fallback
            ...

    without having to guard every ``core.<x>`` reference with a
    ``try/except ImportError``.
    """

    __name__ = "slappyengine._core (unavailable)"

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return "<_NullCore: slappyengine._core extension not compiled>"

    def __getattr__(self, name: str) -> Any:
        raise _NullCoreError(
            f"slappyengine._core.{name} is unavailable — the Rust "
            "extension was not compiled for this install. Build with: "
            "``maturin develop --release`` from the repo root, or "
            "``pip install slappyengine`` on a supported platform."
        )


# ---------------------------------------------------------------------------
# Soft import of the compiled extension
# ---------------------------------------------------------------------------


try:
    from slappyengine import _core as _real_core  # type: ignore[import-not-found]
    _HAS_NATIVE = True
    core: Any = _real_core
except ImportError:
    _HAS_NATIVE = False
    core = _NullCore()


def has_native() -> bool:
    """Return ``True`` iff the compiled ``_core`` extension imported."""
    return _HAS_NATIVE


# ---------------------------------------------------------------------------
# Canonical Rust module map — one entry per ``src/*.rs`` file
# ---------------------------------------------------------------------------
#
# The compiled ``_core`` module is flat; this map is the authoritative
# grouping of "which flat symbol belongs to which Rust source file".  It
# powers both :func:`list_rust_functions` and the synthetic sub-module
# views registered in ``sys.modules`` below.
#
# Entry format::
#
#     "<module>": {
#         "src": "src/<file>.rs",          # authoritative source path
#         "symbols": ["<sym>", ...],        # names exposed at top of _core
#         "summary": "<one-line purpose>",
#     }

RUST_MODULE_MAP: dict[str, dict[str, Any]] = {
    "hull": {
        "src": "src/hull.rs",
        "symbols": ["convex_hull", "bounding_box", "pixel_edge_points"],
        "summary": "2-D convex hull, bbox, and pixel-edge sampling.",
    },
    "ik_solver": {
        "src": "src/ik_solver.rs",
        "symbols": ["solve_ik", "compute_bone_lengths"],
        "summary": "2-D FABRIK inverse kinematics solver.",
    },
    "math": {
        "src": "src/math.rs",
        "symbols": ["Vec2", "AABB"],
        "summary": "2-D math primitives (Vec2, AABB).",
    },
    "node_compiler": {
        "src": "src/node_compiler.rs",
        "symbols": ["compile_node_graph"],
        "summary": "Material-graph JSON to WGSL shader compiler.",
    },
    "slap_format": {
        "src": "src/slap_format.rs",
        "symbols": ["lz4_compress", "lz4_decompress"],
        "summary": "LZ4 block compression for .slap asset containers.",
    },
    "struct_layout": {
        "src": "src/struct_layout.rs",
        "symbols": ["compute_layout", "generate_wgsl_struct"],
        "summary": "WGSL struct layout computation and codegen.",
    },
    "tile_cache": {
        "src": "src/tile_cache.rs",
        "symbols": ["TileCache"],
        "summary": "LRU tile cache for streaming landscape assets.",
    },
    "physics": {
        "src": "src/physics.rs",
        "symbols": ["BodyType", "RigidBody", "PhysicsWorld"],
        "summary": "3-D rigid-body physics world (used by physics2/).",
    },
    "sdf_collision": {
        "src": "src/sdf_collision.rs",
        "symbols": ["SdfCollider"],
        "summary": "3-D SDF push-out and overlap queries.",
    },
    "math_3d": {
        "src": "src/math_3d.rs",
        "symbols": ["Vec3", "Vec4", "Mat4x4", "Quaternion"],
        "summary": "3-D math primitives (feature=3d).",
    },
    "bvh": {
        "src": "src/bvh.rs",
        "symbols": ["BvhPrimitive", "Bvh"],
        "summary": "3-D BVH build and ray/aabb queries (feature=3d).",
    },
    "sdf": {
        "src": "src/sdf.rs",
        "symbols": ["SdfPrimitive", "SdfScene"],
        "summary": "3-D SDF scene primitives (feature=3d).",
    },
    "gi": {
        "src": "src/gi.rs",
        "symbols": ["RadianceCascadeManager"],
        "summary": "Radiance cascade descriptor bookkeeping (feature=gi).",
    },
    "ibl": {
        "src": "src/ibl.rs",
        "symbols": ["IblSH"],
        "summary": "IBL cubemap spherical-harmonic coefficients (feature=ibl).",
    },
    # ------------------------------------------------------------------
    # Orphan modules: present in src/ and included in the shipping wheel
    # but not tracked by src/lib.rs.  See docs/rust_migration_audit_2026_07_05.md
    # section 1.2 for the tree-hygiene finding.  Their symbols show up
    # in _core when the wheel was built from a working tree that
    # mod-declared them.
    # ------------------------------------------------------------------
    "raster": {
        "src": "src/raster.rs",
        "symbols": [
            "rasterize_lines",
            "rasterize_circles",
            "box_blur_rgb",
            "post_process_rgb",
            "alpha_composite_rgb",
            "rasterize_textured_triangles",
        ],
        "summary": "2-D CPU raster kernels (lines, circles, blur, blit).",
    },
    "softbody_solver": {
        "src": "src/softbody_solver.rs",
        "symbols": [
            "project_distance_constraints",
            "apply_plasticity",
            "mark_breaks",
            "build_contact_pairs",
            "project_node_beam_contacts",
            "project_node_node_pairs",
            "slappyengine_step",
        ],
        "summary": "XPBD softbody solver inner kernels.",
    },
    "pbf_solver": {
        "src": "src/pbf_solver.rs",
        "symbols": [
            "build_neighbour_table",
            "pbf_iter",
            "friction_pass_rs",
            "thermal_step_rs",
            "pbf_step_full",
        ],
        "summary": "Position-based fluids inner kernels.",
    },
    "fluid_shader": {
        "src": "src/fluid_shader.rs",
        "symbols": [
            "turbulence_foam_rs",
            "refraction_warp_rs",
            "godrays_rs",
            "specular_pass_rs",
            "draw_droplet_tails_rs",
            "alpha_composite_hdr_rs",
            "post_process_hdr_rs",
            "rasterize_lines_hdr_rs",
            "sample_density_grid_rs",
            "surface_base_shade_rs",
            "speed_screen_rs",
            "extract_isolines_rs",
        ],
        "summary": "HDR fluid post-process kernels.",
    },
}


# ---------------------------------------------------------------------------
# list_rust_functions — introspect what's actually reachable at runtime
# ---------------------------------------------------------------------------


def list_rust_functions() -> dict[str, list[str]]:
    """Return a mapping of ``{rust_module: [symbol, ...]}`` for symbols
    actually reachable on the running ``_core``.

    Symbols listed in :data:`RUST_MODULE_MAP` that are **not** present on
    the compiled ``_core`` (typically because the wheel was built without
    the corresponding cargo feature, or the orphan module wasn't tracked
    at build time) are silently dropped from the returned dict.  If the
    Rust extension isn't compiled at all, the returned dict is empty.

    Example::

        >>> from slappyengine import _core_facade
        >>> surface = _core_facade.list_rust_functions()
        >>> sorted(surface.get("hull", []))
        ['bounding_box', 'convex_hull', 'pixel_edge_points']
    """
    if not _HAS_NATIVE:
        return {}
    surface: dict[str, list[str]] = {}
    for mod, meta in RUST_MODULE_MAP.items():
        present = [s for s in meta["symbols"] if hasattr(_real_core, s)]
        if present:
            surface[mod] = present
    return surface


# ---------------------------------------------------------------------------
# Synthetic sub-module views under slappyengine._core.<name>
# ---------------------------------------------------------------------------
#
# We register a shim ``types.ModuleType`` in ``sys.modules`` for each
# logical Rust module so users can write::
#
#     from slappyengine._core import raster
#     raster.box_blur_rgb(rgb_bytes, w, h, radius)
#
# without having to know that the compiled ``_core`` is actually flat.
# We only register views for modules whose symbols are actually present
# on the compiled extension — otherwise the import would silently give
# the caller an empty sub-module.


def _install_submodule_views() -> None:
    """Populate ``sys.modules['slappyengine._core.<name>']`` for each
    logical Rust module whose symbols are present at runtime."""
    if not _HAS_NATIVE:
        return
    parent_name = _real_core.__name__  # "slappyengine._core"
    for mod, meta in RUST_MODULE_MAP.items():
        present = [s for s in meta["symbols"] if hasattr(_real_core, s)]
        if not present:
            continue
        full_name = f"{parent_name}.{mod}"
        if full_name in sys.modules:
            continue  # respect any user-registered override
        shim = types.ModuleType(full_name)
        shim.__doc__ = (
            f"View onto Rust symbols from ``{meta['src']}``.\n\n"
            f"{meta['summary']}\n\n"
            "Auto-generated by slappyengine._core_facade — the compiled "
            "_core module is flat, this shim only re-groups the "
            "already-imported symbols by their originating Rust source "
            "file. Use for direct-bypass access to the Rust backend."
        )
        for sym in present:
            setattr(shim, sym, getattr(_real_core, sym))
        shim.__all__ = list(present)  # type: ignore[attr-defined]
        sys.modules[full_name] = shim
        # Also attach as an attribute on the real _core so
        # ``from slappyengine._core import raster`` resolves via the
        # normal attribute-lookup path.
        setattr(_real_core, mod, shim)


_install_submodule_views()
