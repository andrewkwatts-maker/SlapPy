# Contributing to SlapPyEngine

Conventions for contributors working on the engine itself. For
game-side usage see `docs/getting_started.md`, `docs/studio_quickstart.md`,
and `docs/tutorial_build_a_game.md`.

If you are adding a feature that touches more than one subpackage, skim
`docs/roadmap.md` first — the entries there carry source citations and
will tell you whether the work belongs in v0.3.x, v0.4, or v1.0.

---

## Hardening pattern (public-API validation)

Every public-API entry point in the engine carries typed input
validators. The pattern is consistent across the 13 hardening rounds
landed through v0.3.0b0; new public surfaces follow the same shape.

### Where validators live

| Module                                          | Owns                                                                  |
|-------------------------------------------------|------------------------------------------------------------------------|
| `slappyengine._validation`                      | Shared canonical helpers (`validate_str`, `validate_finite_float`, `validate_positive_int`, `validate_finite_2tuple`, `validate_bool`, `validate_callback`, `validate_path`, …). |
| `slappyengine._<module>_validation.py`          | Domain-specific validators that build on the shared helpers (`validate_event_type`, `validate_joint`, `validate_layer_mode`, …). |

The shared helpers enforce canonical rules across the whole engine:

- `str` checks reject `bytes` / `bytearray`.
- `int` checks reject `bool` (Python's `isinstance(True, int)` is True
  but is almost always a bug at a boundary).
- Numeric checks accept Python `int` / `float` *and* numpy scalars
  (`np.integer`, `np.floating`) — the numerics, thermal, zones, and iso
  subsystems pass them through routinely.
- Every error message uses the `"{fn}: {name} ..."` prefix so callers
  can grep the traceback for the call site.

### Validator imports

```python
# Shared canonical helpers — always prefer these
from slappyengine._validation import (
    validate_finite_float,
    validate_str,
    validate_callback,
)

# Domain-specific helpers — only when no shared equivalent exists
from slappyengine._event_bus_validation import validate_event_type
```

If a new shared check is broadly applicable, add it to `_validation.py`
and re-export from the per-subsystem module rather than duplicating it.

### Wire-up at the public boundary

Validators are called *exactly once* at the outermost public method.
Internal helpers trust their inputs.

```python
# python/slappyengine/event_bus.py (excerpt)
class EventBus:
    def subscribe(self, event_type: str, callback) -> None:
        event_type = validate_event_type("event_type", "EventBus.subscribe", event_type)
        callback = validate_callback("callback", "EventBus.subscribe", callback)
        ...
```

### Tests

Every hardening round ships a `SlapPyEngineTests/tests/test_hardening_<module>.py` file
with negative-path coverage only — the positive path is already
exercised by the broader test suite. See
`SlapPyEngineTests/tests/test_hardening_eventbus.py` for the canonical shape.

```python
def test_subscribe_rejects_bytes_event_type():
    bus = EventBus()
    with pytest.raises(TypeError, match="event_type must be a str"):
        bus.subscribe(b"entity:spawn", lambda payload: None)
```

The `match=` substring **must** match the validator error message so the
test pins both the type and the wording. Frame-budget impact is sub-1%
on every realistic workload (see
`benchmarks/baseline_report.md` § Hardening overhead audit) — do **not**
introduce a `_DEBUG_VALIDATE` skip flag.

---

## Documentation conventions

### Hand-authored vs auto-generated

`docs/api/*.md` files are a mix:

- **Auto-generated** — produced by `scripts/gen_subpackage_api_docs.py`
  from the subpackage's `__all__` + docstrings (e.g. `dynamics.md`,
  `tools.md`). Re-run the generator after changing a public surface.
- **Hand-authored** — opted in by the literal marker on line 1:

  ```markdown
  <!-- handauthored: do not regenerate -->
  ```

  The generator skips files with that marker. The conformance test
  `SlapPyEngineTests/tests/test_docs_api_template_conformance.py` asserts every
  hand-authored doc starts with the marker, carries an H1 of the form
  `# slappyengine.<X> — API Reference`, and includes at least one of
  `## Overview`, `## Public surface`, `## Usage`.

The full template lives at `docs/api/_template.md` and documents the
canonical section ordering, the citation format for paper references,
and the cross-link convention (`LBLK`name.md`RBLK(name.md)` relative form
so `SlapPyEngineTests/tests/test_docs_links_resolve_all.py` resolves them — replace `LBLK`
/ `RBLK` with literal `[` / `]` in real docs; `_template.md` uses the
same disguise convention).

### Doc inventory

Every file under `docs/**/*.md` must appear in
`docs/sprint_5_doc_inventory.md`. `SlapPyEngineTests/tests/test_docs_inventory.py`
enforces three invariants:

1. Every doc on disk is indexed.
2. Every indexed entry points at an on-disk file.
3. Every row has a non-empty description.

When you add a doc, add an inventory row in the same commit.

---

## Naming conventions

Engine helper functions split into two categories per Sprint R-D:

| Prefix    | Semantics                                                                  | Example                                                                 |
|-----------|----------------------------------------------------------------------------|-------------------------------------------------------------------------|
| `make_*`  | Pure spec / constructor — returns a dataclass or callable; no side effects. | `make_motor(...)`, `make_spring(...)`, `make_humanoid(...)` (deprecated alias of `build_humanoid`). |
| `build_*` | Mutates the world / scene — adds bodies, joints, or attachments.           | `build_rope(spec, world, ...)`, `build_ragdoll(spec, world, ...)`, `build_flesh_wrap(...)`. |

This is asserted by `SlapPyEngineTests/tests/test_dynamics_builder_conventions.py`. If you
add a new factory, pick the prefix based on whether it mutates an
external object passed in.

---

## Test discipline

- **No leading-underscore exports in `__all__`.** Public surface stays
  public; private helpers stay private. Asserted by the engine-surface
  doc generator + `SlapPyEngineTests/tests/test_docs_engine_surface_complete.py`.
- **Alphabetise `__all__`** within each semantic group so diff churn
  stays minimal.
- **Negative-path hardening tests** live in
  `SlapPyEngineTests/tests/test_hardening_<module>.py` — one file per module, never share
  files across subsystems.
- **Skip / xfail discipline.** Every `skip` / `xfail` / `skipif`
  carries a one-line reason. `docs/sprint_6_test_audit.md` reviewed the
  full inventory; new ones must include a resolve/keep/delete
  recommendation in the marker reason text.

Run the doc-side tripwires before submitting:

```bash
PYTHONPATH=python python -m pytest tests/test_docs*.py --no-header -q
```

---

## Adding a post-process pass

`slappyengine.post_process` uses a declarative base class
(`PostProcessPassBase`) that centralises config loading, UBO packing,
and chain wiring. New passes follow this skeleton:

```python
# python/slappyengine/post_process/<pass_name>.py
from typing import ClassVar
from ._pass_base import PostProcessPassBase
from ._ubo import UboField
from ._validation import validate_unit_interval


class MyPass(PostProcessPassBase):
    label: ClassVar[str] = "my_pass"
    SHADER: ClassVar[str] = "my_pass.wgsl"
    ENTRY:  ClassVar[str] = "main"
    CONFIG_KEY: ClassVar[str] = "rendering.my_pass"
    PARAMS_LAYOUT: ClassVar = [
        UboField("strength", "f32"),
        UboField("radius",   "f32"),
    ]

    def __init__(self, strength: float = 0.5, radius: float = 0.25) -> None:
        self.strength = validate_unit_interval("strength", type(self).__name__, strength)
        self.radius   = validate_unit_interval("radius",   type(self).__name__, radius)
```

The base class supplies `from_config`, `make_pass`, and
`params_to_bytes` for free. Two extra conveniences:

- `BLOB_SIZE` — set this when the packed UBO is not a multiple of 16
  bytes (the std140 round-up would otherwise over-pad).
- `EXTRA_BINDINGS` — tuple of binding names merged into the `params`
  sideband dict by `make_pass` (used by TAA / GTAO for their extra
  texture bindings).

### WGSL companion

Drop the shader at `shaders/<pass_name>.wgsl` with a `main` entry point
(or set `ENTRY` to a different name). Mirror the binary UBO layout your
`PARAMS_LAYOUT` declares — byte-for-byte parity is asserted by
`SlapPyEngineTests/tests/test_post_process_base.py`.

### Tests

Add a `SlapPyEngineTests/tests/test_<pass_name>_pass.py` smoke test exercising:

1. `from_config` with an empty config object (must fall back to defaults).
2. `params_to_bytes()` round-trip against a known-good payload.
3. `apply_cpu()` reference (when shipped) against a 1-pixel oracle.

If the pass has a public `__init__` boundary with numeric params, also
add a `SlapPyEngineTests/tests/test_hardening_postprocess.py` entry for the negative
path.

---

## Pull-request checklist

Before opening a PR:

- [ ] `PYTHONPATH=python python -m pytest tests/test_docs*.py --no-header -q` green.
- [ ] `PYTHONPATH=python python -m pytest tests/test_hardening_*.py --no-header -q` green for any module you touched.
- [ ] New docs indexed in `docs/sprint_5_doc_inventory.md`.
- [ ] Cross-links use the relative `LBLK`name.md`RBLK(name.md)` form (with literal `[` / `]`).
- [ ] `__all__` alphabetised within its semantic group.
- [ ] New deferred work captured in `docs/roadmap.md` with a source
      citation.
