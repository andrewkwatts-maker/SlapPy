//! Pharos stable C ABI.
//!
//! Language-neutral surface over `pharos_core`. PyO3 is one consumer
//! (via pharos_py's #[pymodule]); Godot GDExtension, Unity native
//! interop, JS/WASM (via wasmtime + wit-bindgen), and any FFI-capable
//! runtime consume the same header.
//!
//! Sprint 10 baseline. Coverage is intentionally narrow — only the
//! functions with a stable API contract get a C ABI hop, so we can
//! evolve the Rust internals freely.
//!
//! Callers should generate a header via `cbindgen`:
//!
//! ```text
//! cbindgen --config cbindgen.toml --crate pharos_c_abi \
//!          --output crates/pharos_c_abi/include/pharos.h
//! ```

use std::os::raw::{c_char, c_int};

/// Returns the Pharos version string as a NUL-terminated C string.
///
/// The pointer is valid for the lifetime of the calling process.
#[no_mangle]
pub extern "C" fn pharos_version() -> *const c_char {
    concat!(env!("CARGO_PKG_VERSION"), "\0").as_ptr() as *const c_char
}

/// Return code convention: 0 = success, negative = domain error.
#[repr(C)]
pub enum PharosStatus {
    Ok = 0,
    InvalidArgument = -1,
    NotImplemented = -2,
    Internal = -3,
}

/// Version-check on the runtime linked-against pharos_core kernels.
/// Returns `PharosStatus::Ok` if the ABI is compatible.
#[no_mangle]
pub extern "C" fn pharos_abi_check(caller_major: c_int, caller_minor: c_int) -> c_int {
    // Sprint 10 ABI: MAJOR=0, MINOR=3. Bump on breaking C changes.
    const ABI_MAJOR: c_int = 0;
    const ABI_MINOR: c_int = 3;
    if caller_major != ABI_MAJOR {
        return PharosStatus::InvalidArgument as c_int;
    }
    if caller_minor > ABI_MINOR {
        return PharosStatus::InvalidArgument as c_int;
    }
    PharosStatus::Ok as c_int
}

/// Placeholder for the softbody-step C entry (Sprint 11 target).
///
/// Signature mirrors pharos_core::softbody_solver::softbody_step_full:
/// (in-place mutation of position + velocity buffers, N iterations,
/// gravity vector, substep dt).
///
/// Returns `PharosStatus::NotImplemented` until the wrapper lands.
#[no_mangle]
pub extern "C" fn pharos_softbody_step(
    _positions: *mut f32,
    _velocities: *mut f32,
    _node_count: c_int,
    _substep_dt: f32,
    _iterations: c_int,
) -> c_int {
    PharosStatus::NotImplemented as c_int
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn version_string_is_nul_terminated() {
        // Round-trip through a &str to prove the pointer is valid.
        let ptr = pharos_version();
        assert!(!ptr.is_null());
        let s = unsafe { std::ffi::CStr::from_ptr(ptr) };
        let text = s.to_str().unwrap();
        assert!(text.starts_with("0.3"), "unexpected version: {text}");
    }

    #[test]
    fn abi_check_accepts_current_version() {
        assert_eq!(pharos_abi_check(0, 3), PharosStatus::Ok as c_int);
    }

    #[test]
    fn abi_check_rejects_wrong_major() {
        assert_eq!(pharos_abi_check(1, 0), PharosStatus::InvalidArgument as c_int);
    }
}
