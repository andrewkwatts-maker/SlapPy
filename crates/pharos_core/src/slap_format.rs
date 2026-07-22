use pyo3::prelude::*;

/// Compress bytes using lz4 block format.
/// The original size is prepended as a 4-byte header, so decompression
/// does not need the caller to supply it separately.
#[pyfunction]
pub fn lz4_compress(data: &[u8]) -> PyResult<Vec<u8>> {
    lz4::block::compress(data, None, true)
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))
}

/// Decompress lz4 bytes that were compressed with lz4_compress.
/// The original size is read from the 4-byte header prepended during compression.
#[pyfunction]
pub fn lz4_decompress(data: &[u8]) -> PyResult<Vec<u8>> {
    lz4::block::decompress(data, None)
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(lz4_compress, m)?)?;
    m.add_function(wrap_pyfunction!(lz4_decompress, m)?)?;
    Ok(())
}
