# Cargo / Rust Workspace Audit — 2026-06-02

Audit of `Cargo.toml`, `Cargo.lock`, and `src/` for the `_core` PyO3 extension.

## Crate at a Glance

- Package: `slappyengine` v0.3.0-beta.0
- Library name: `_core`, crate-type `cdylib`
- Edition: 2021
- Python module: `slappyengine._core` (built via maturin)
- Target wheel size today: `_core.dll` ~ 798 KiB (release, before strip), `_core.pdb` ~ 1.0 MiB

## Public Surface (registered in `src/lib.rs`)

The `_core` PyO3 module exports the following sub-modules:

| Sub-module          | File                  | Always-on | Feature gate |
| ------------------- | --------------------- | --------- | ------------ |
| `hull`              | `hull.rs`             | yes       | —            |
| `ik_solver`         | `ik_solver.rs`        | yes       | —            |
| `math`              | `math.rs`             | yes       | —            |
| `node_compiler`     | `node_compiler.rs`    | yes       | —            |
| `slap_format`       | `slap_format.rs`      | yes       | —            |
| `struct_layout`     | `struct_layout.rs`    | yes       | —            |
| `tile_cache`        | `tile_cache.rs`       | yes       | —            |
| `physics`           | `physics.rs`          | yes       | —            |
| `sdf_collision`     | `sdf_collision.rs`    | yes       | —            |
| `math_3d`           | `math_3d.rs`          | no        | `3d`         |
| `sdf`               | `sdf.rs`              | no        | `3d`         |
| `gi`                | `gi.rs`               | no        | `gi`         |
| `ibl`               | `ibl.rs`              | no        | `ibl`        |

Files **physically present** in `src/` but **not wired** into `lib.rs` (orphan source, not in the built artifact):

- `raster.rs`
- `softbody_solver.rs`
- `pbf_solver.rs`
- `fluid_shader.rs`

These appear to be in-flight or staged Rust kernels from the migration plan. They are
excluded from the current `_core` build (no `mod` declarations) but still occupy disk
in the repo. Worth re-wiring or moving to a `_staged/` folder for clarity, but doing so
is out of scope (constraint: do not modify `src/*.rs`).

## Dependency Audit

`[dependencies]` from `Cargo.toml`:

| Crate         | Version  | Used in registered modules?                 | Verdict                              |
| ------------- | -------- | ------------------------------------------- | ------------------------------------ |
| `pyo3`        | 0.22     | every module                                | **keep — load-bearing**              |
| `lz4`         | 1.25     | `slap_format.rs`                            | **keep**                             |
| `rayon`       | 1.10     | `physics.rs`, `ibl.rs`                      | **keep**                             |
| `serde`       | 1        | `node_compiler.rs` (`Deserialize`)          | **keep**                             |
| `serde_json`  | 1        | `node_compiler.rs`                          | **keep**                             |
| `bytemuck`    | 1        | only orphan files (raster, pbf, softbody)   | **orphan today** (needed once those re-wire) |
| `rand`        | 0.8      | not referenced anywhere in `src/`           | **ORPHAN — removable**               |
| `half`        | 2        | not referenced anywhere in `src/`           | **ORPHAN — removable**               |

Confirmed via `cargo tree`:

```
slappyengine v0.3.0-beta.0
├── bytemuck v1.25.0
├── half v2.7.1
├── lz4 v1.28.1
├── pyo3 v0.22.6
├── rand v0.8.6
├── rayon v1.12.0
├── serde v1.0.228
└── serde_json v1.0.149
```

`rand` and `half` pull in `zerocopy`, `zerocopy-derive`, `getrandom`, `ppv-lite86`,
`rand_chacha`, `rand_core`, `crunchy`, `wasi` transitively — that's a fair amount of
compile time and a small wheel-size hit for crates that are not referenced from any
module included in the build.

> **Note**: `pbf_solver.rs` references `use wide::{f32x4, …};` but `wide` is **not** in
> `Cargo.toml` or `Cargo.lock`. Confirms `pbf_solver.rs` is not currently compiled.
> Re-wiring it will require adding `wide` as a dep.

## Feature Flag Audit

```toml
[features]
default = ["3d"]
3d = []
gi = ["3d"]
ibl = ["3d"]
```

- `default = ["3d"]` means `pip install slappy-engine` (which runs maturin with the
  crate's default features) ships the `3d`, but not `gi` or `ibl`, gated modules.
- The Python-side `[project.optional-dependencies] 3d = []` is a no-op; the docstring
  says the gating is build-time via `maturin build --features 3d` — but `3d` is already
  in the **default** features, so the user does **not** need that flag.
- `gi` and `ibl` will require `maturin build --features gi,ibl` to be enabled in a
  wheel. PyPI ships only one wheel today, so `gi` / `ibl` users would need to build
  from source. Consider documenting this or shipping a "full" wheel with all features.
- No dev-only deps leak into the default feature set. Good.

## Build Profile

`Cargo.toml`:

```toml
[profile.release]
opt-level = 3
lto = true
codegen-units = 1
strip = true
```

All four levers are already at the recommended PyPI-release values:

- `opt-level = 3` — max throughput.
- `lto = true` — equivalent to `lto = "fat"`. Slowest link but smallest + fastest binary.
- `codegen-units = 1` — best inlining across the crate.
- `strip = true` — strips debug symbols from the produced cdylib.

No change needed here.

## `pyproject.toml` / `[tool.maturin]`

**Before** (today):

```toml
[tool.maturin]
python-source = "python"
module-name = "slappyengine._core"
features = ["pyo3/extension-module"]
exclude = [
    "**/__pycache__",
    "**/*.pyc",
    "**/*.pyo",
    "**/tests",
    "**/examples",
    "**/.pytest_cache",
]
```

`strip = true` was **missing** from `[tool.maturin]`. Even though Cargo's profile
strip kicks in, maturin's own strip pass handles the wheel-side post-link strip on
some platforms (e.g. Linux glibc, where `cargo`'s strip is a no-op without
`strip = "symbols"`). Adding it is the single safest size win.

**This sprint**: added `strip = true` to `[tool.maturin]`. No other changes.

## Recommendations (future sprints)

Ranked by impact / safety:

1. **Drop `rand` and `half`** (low risk, modest win). Neither is referenced from any
   module in the current build. Saves transitive deps `zerocopy`, `getrandom`,
   `rand_chacha`, `rand_core`, `crunchy`, `ppv-lite86`. **Verify** by `cargo check
   --release` after removing. Skipped this sprint per the "one small change" rule.
2. **Decide on the orphan `.rs` files** (`raster.rs`, `softbody_solver.rs`,
   `pbf_solver.rs`, `fluid_shader.rs`). Either:
   - Re-wire them into `lib.rs` (and add `wide` as a dep for `pbf_solver`), or
   - Move them to `src/_staged/` with a top-level README explaining their status.
   Either path eliminates dev confusion about which kernels ship in `_core`.
3. **Make `gi` and `ibl` part of the default wheel**. They are small modules; the
   marginal binary cost is dwarfed by the wgpu Python wheel. Set
   `default = ["3d", "gi", "ibl"]` so PyPI users get the full surface out of the box.
   Alternative: ship a `slappy-engine-full` variant. Verify with a wheel-size diff.
4. **Consider `panic = "abort"`** in `[profile.release]`. Saves a small amount of
   unwinding metadata in the cdylib. PyO3 catches panics at the FFI boundary anyway,
   so end-to-end behaviour from Python is unchanged. ~5-10% size win is common.
5. **Try `lto = "thin"`** as a CI-only build to compare wheel size + runtime. `"fat"`
   is the right call for releases, but `"thin"` shaves ~30-50% off link time during
   release-mode CI runs and the runtime hit is usually < 5%.
6. **Investigate `wasi` in the dep graph**. `wasi` shouldn't be needed on a
   Windows/Linux/macOS-only build target — it's pulled in by `getrandom` via `rand`.
   Dropping `rand` (recommendation #1) eliminates it.

## Verification

Tried `cargo check --release` in-session — failed on a sandbox-local PyO3
Python-interpreter discovery error (`os error 3` resolving the system Python). The
edit in this sprint is to `pyproject.toml` only and cannot affect Cargo's behaviour,
but the wheel-strip impact should be **measured out-of-session** with:

```
maturin build --release
ls -lh target/wheels/*.whl
```

Compare against a `git stash` of the pyproject change for the before/after delta.

## Files Touched This Sprint

- `pyproject.toml` — added `strip = true` to `[tool.maturin]`.
- `docs/cargo_audit_2026_06_02.md` — this document.

No Rust source modified. No Cargo dependencies removed (orphan removal deferred to a
dedicated sprint with cargo-check verification).
