<!-- handauthored: do not regenerate -->
# slappyengine.ai — API Reference

> Hand-written reference for the SlapPyEngine LLM-backed authoring surface.
> Owns the local-Ollama REST client, the entity-script generator, the
> prompt / code bidirectional sync watcher, and the backend Protocol
> that makes all three swappable for tests or third-party providers.
> Sibling references: [`visual_scripting.md`](visual_scripting.md) is the
> deterministic node-graph authoring path; this subpackage is the free-text
> "describe it and let the model write it" path.

## Overview

`slappyengine.ai` gates every LLM-backed authoring feature in the engine
behind a single structural Protocol, :class:`LLMBackendProtocol`, so the
Code Mode panel, the entity-script generator, and the background
prompt/code sync watcher all consume the same three-method interface.
The shipped concrete backend, :class:`LLMClient`, talks to a locally
running Ollama daemon; a two-line swap gets you Anthropic, OpenAI, a
recorded fixture, or a `llama.cpp` process instead.

The subpackage is opt-in — the `httpx` transport dependency ships behind
the `[ai]` extra:

```bash
pip install slappyengine[ai]
```

Symbols other than :class:`LLMBackendProtocol` are lazy-loaded via
`__getattr__`; importing `slappyengine.ai` does **not** import `httpx`,
so an install without the `[ai]` extra can still touch the Protocol
(useful for tests). The `ImportError` with an install hint is raised
inside :meth:`LLMClient.__init__`, not at module import time.

## Public surface

```python
from slappyengine.ai import (
    CodeSyncWatcher,
    LLMBackendProtocol,
    LLMClient,
    ScriptGenerator,
    code_to_prompt,
    prompt_to_code,
)
```

- **Backend contract** — `LLMBackendProtocol` (structural, runtime-checkable).
- **Concrete backend** — `LLMClient` (Ollama REST, requires `[ai]` extra).
- **High-level authoring** — `ScriptGenerator` for one-shot `EntityScript`
  code from a prompt; `code_to_prompt` / `prompt_to_code` for round-trip.
- **Background sync** — `CodeSyncWatcher` polls `.py` + `.prompt` sidecar
  pairs on a debounce timer and drives the AI in whichever direction the
  most recent edit indicates.

## Classes

### `LLMBackendProtocol`

_Protocol — defined in `slappyengine.ai._protocol`_

Runtime-checkable structural type for anything that can drive
:class:`ScriptGenerator`, :class:`CodeSyncWatcher`, or the Code Mode
panel. Requires three methods:

- `generate(prompt: str, system_prompt: str = "", temperature: float = 0.2) -> str`
- `is_available() -> bool`
- `list_models() -> list[str]`

Use `isinstance(backend, LLMBackendProtocol)` in tests to verify a mock
conforms without pulling in the concrete client.

### `LLMClient`

_class — defined in `slappyengine.ai.llm_client`_

Synchronous REST client for a locally running Ollama daemon. Reads
`LLM_HOST` (default `http://localhost:11434`) and `LLM_MODEL` (default
`qwen2.5-coder:7b`) from the environment; constructor arguments
override those.

#### Constructor signature

```python
LLMClient(host: str | None = None, model: str | None = None) -> None
```

Raises `ImportError` if the `[ai]` extra is not installed (deferred to
`__init__`, so the module import stays cheap).

#### Methods

- `generate(prompt, system_prompt="", temperature=0.2) -> str` — synchronous
  text completion; returns `""` on transient HTTP errors, raises
  `ConnectionError` on unreachable host.
- `is_available() -> bool` — cheap `/api/tags` reachability probe (2 s timeout).
- `list_models() -> list[str]` — enumerate installed Ollama models; empty
  list on unreachable host.

### `ScriptGenerator`

_class — defined in `slappyengine.ai.script_gen`_

Wraps any `LLMBackendProtocol` implementer to produce `EntityScript`
Python classes from natural-language prompts. The system prompt is a
locked-in template that constrains the model to the four `EntityScript`
lifecycle hooks (`on_spawn`, `on_tick`, `on_despawn`, `on_collision`)
and the documented `entity.*` attribute surface.

#### Constructor signature

```python
ScriptGenerator(llm_client: LLMBackendProtocol | None = None) -> None
```

Passing `None` constructs a default :class:`LLMClient` on first use.

#### Methods

- `from_prompt(prompt: str) -> str` — return raw Python source for an
  `EntityScript` class. Markdown fences (if the model emits them) are
  stripped before return.

### `CodeSyncWatcher`

_class — defined in `slappyengine.ai.code_sync`_

Background polling thread that watches `.py` + `.prompt` sidecar pairs.
When either file's mtime advances, waits `DEBOUNCE_SECS` (default 2 s)
after the last change, then calls the AI in the direction of the newer
file: `.prompt` newer → rewrite code; `.py` newer → regenerate prompt
description.

#### Constructor signature

```python
CodeSyncWatcher(llm: LLMBackendProtocol, enabled: bool = True) -> None
```

#### Class attributes

- `DEBOUNCE_SECS: float = 2.0` — quiet period before firing.
- `POLL_INTERVAL: float = 0.5` — mtime-poll cadence.

#### Methods

- `start() -> None` — spawn the daemon polling thread (idempotent).
- `stop() -> None` — signal the thread to exit at the next poll boundary.
- `watch(script_path, on_code_updated=None, on_prompt_updated=None) -> None`
  — begin watching a `.py` file and its `.prompt` sidecar with optional
  callback hooks.
- `unwatch(script_path) -> None` — stop watching a script.

## Functions

### `prompt_to_code(prompt: str, current_code: str, llm) -> str` (async)

_defined in `slappyengine.ai.code_sync`_

Rewrite `current_code` so it implements what `prompt` describes. Returns
the new source; falls back to `current_code` on any AI failure.

### `code_to_prompt(code: str, llm) -> str` (async)

_defined in `slappyengine.ai.code_sync`_

Generate a 2–4 sentence plain-English description of what `code` does.
Returns `"(no description)"` on failure.

## Usage

```python
from slappyengine.ai import LLMBackendProtocol, ScriptGenerator

# Test with a hand-rolled backend — no httpx / Ollama required.
class FakeBackend:
    def generate(self, prompt, system_prompt="", temperature=0.2):
        return (
            "class EntityScript:\n"
            "    def on_tick(self, entity, dt):\n"
            "        entity.position[0] += 10.0 * dt\n"
        )
    def is_available(self): return True
    def list_models(self): return ["fake-model"]

assert isinstance(FakeBackend(), LLMBackendProtocol)

gen = ScriptGenerator(llm_client=FakeBackend())
source = gen.from_prompt("move the entity right at 10 px/sec")
assert "class EntityScript" in source
assert "on_tick" in source
```

To run against a real Ollama daemon:

```python
from slappyengine.ai import LLMClient, ScriptGenerator

client = LLMClient()  # reads LLM_HOST + LLM_MODEL from env
if client.is_available():
    gen = ScriptGenerator(client)
    print(gen.from_prompt("wobble in a sine wave along Y"))
```

## Skip the wrapper

`slappyengine.ai` is pure Python. Grep of
`slappyengine._core_facade.RUST_MODULE_MAP` shows **no** `ai` entry — the
subpackage is a thin transport / prompt-templating layer; nothing runs
per-frame, and there is nothing here worth porting to Rust. The
inner loop (Ollama HTTP round-trip) is already dominated by model
inference on the daemon side; a Rust port would move no measurable
authoring-latency needle.

Callers who want to bypass :class:`ScriptGenerator` and drive an LLM
directly can implement :class:`LLMBackendProtocol` against any HTTP or
subprocess transport and hand it to :class:`CodeSyncWatcher` — the
watcher never touches :class:`LLMClient` directly, only the Protocol.

## Conventions

- **Lazy import.** Every symbol other than :class:`LLMBackendProtocol`
  is materialised on first attribute access via the module-level
  `__getattr__`. `import slappyengine.ai` is safe even without the
  `[ai]` extra installed.
- **Async where useful.** The two `code_sync` free functions are `async`
  so the watcher thread can drive them via `asyncio.get_event_loop()`;
  the concrete :class:`LLMClient.generate` is synchronous and gets
  bridged to `async` via `run_in_executor` inside `code_sync._ask`.
- **Fixture-friendly.** Every consumer of an LLM in this subpackage takes
  a `LLMBackendProtocol` — tests inject a hand-rolled backend that
  returns canned responses; no network dependency in the test suite.

## See also

- [`visual_scripting.md`](visual_scripting.md) — deterministic node-graph
  authoring path; complementary to the LLM-backed free-text path here.
- [`ext.md`](ext.md) — the `[ai]` extra ships alongside the other
  opt-in extension groups documented there.
- [`../rust_migration_plan.md`](../rust_migration_plan.md) — Rust ROI
  reference; `slappyengine.ai` is intentionally not on the migration
  roadmap.
