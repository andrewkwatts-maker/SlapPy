# SlapPyEngine — Architecture Guide for Claude Code

## Repository Layout

```
SlapPyEngine/
├── python/playslap/          # Python package source
│   └── compute/defaults/         # Default WGSL compute shaders
├── src/                          # Rust extension source (_core crate)
├── shaders/                      # WGSL shader templates
├── config/                       # All default numeric config (YAML)
│   ├── engine.yml                # Window, rendering, physics, compute defaults
│   └── materials.yml             # Material colour-range → behaviour mappings
├── tests/                        # pytest test suite
└── examples/                     # Example projects (may contain *.slap assets)
```

## Key Conventions

- **No magic numbers in Python.** All default numeric values live in `config/*.yml` and are loaded at runtime via `playslap.config`. Never hardcode them in Python source.
- **Shaders** live in two places: `shaders/*.wgsl` (reusable templates) and `python/playslap/compute/defaults/*.wgsl` (default pipeline shaders).
- **Rust extension** (`src/`) is compiled into `playslap._core` via PyO3/maturin. Python code imports from there for performance-critical paths.

## Build

```bash
# Development (editable install, builds Rust extension in debug mode)
maturin develop

# Release wheel
maturin build --release
```

## Tests

```bash
# Requires maturin develop first so _core is importable
pytest tests/
```

## Dependencies

- **Python:** wgpu (GPU), numpy (arrays), Pillow (image I/O), glfw (windowing), pyyaml (config)
- **Rust:** pyo3 (Python bindings), lz4 (asset compression), rayon (parallelism)

## Optional Extras

| Extra     | Purpose                        |
|-----------|--------------------------------|
| `editor`  | In-engine editor (dearpygui)   |
| `video`   | Video decoding (av/PyAV)       |
| `audio`   | Audio I/O (sounddevice + soundfile) |
| `dev`     | pytest + pytest-asyncio        |

## Config Loading Pattern

```python
from playslap.config import load_engine_config, load_materials_config

cfg = load_engine_config()          # reads config/engine.yml
materials = load_materials_config() # reads config/materials.yml
```

## Windows Build Note
If `maturin develop` fails with a Python discovery error, set the PYO3_PYTHON env var:
```
$env:PYO3_PYTHON = "C:\Users\Andrew\AppData\Local\Programs\Python\Python313\python.exe"
maturin develop --extras dev
```
The Windows Store Python stub at `C:\Program Files\WindowsApps\` does not expose the correct headers.
