"""Engine tests for ai/ subpackage — headless (no httpx/Ollama required)."""
from __future__ import annotations
import pytest
from pathlib import Path


# ---------------------------------------------------------------------------
# ScriptGenerator tests (using a mock LLMClient)
# ---------------------------------------------------------------------------

class _MockLLM:
    def __init__(self, response="class EntityScript:\n    pass"):
        self._response = response

    def generate(self, prompt, system_prompt=None, temperature=0.2):
        return self._response


class TestScriptGeneratorSystemPrompt:
    def test_system_prompt_is_string(self):
        from slappyengine.ai.script_gen import SYSTEM_PROMPT
        assert isinstance(SYSTEM_PROMPT, str)
        assert len(SYSTEM_PROMPT) > 100

    def test_system_prompt_mentions_entity_script(self):
        from slappyengine.ai.script_gen import SYSTEM_PROMPT
        assert "EntityScript" in SYSTEM_PROMPT

    def test_system_prompt_mentions_on_tick(self):
        from slappyengine.ai.script_gen import SYSTEM_PROMPT
        assert "on_tick" in SYSTEM_PROMPT

    def test_system_prompt_mentions_on_spawn(self):
        from slappyengine.ai.script_gen import SYSTEM_PROMPT
        assert "on_spawn" in SYSTEM_PROMPT


class TestScriptGeneratorClean:
    def _gen(self, response="class EntityScript:\n    pass"):
        from slappyengine.ai.script_gen import ScriptGenerator
        g = ScriptGenerator(llm_client=_MockLLM(response))
        return g

    def test_clean_plain_code_unchanged(self):
        gen = self._gen("class EntityScript:\n    pass")
        result = gen._clean("class EntityScript:\n    pass")
        assert result == "class EntityScript:\n    pass"

    def test_clean_strips_markdown_fences(self):
        gen = self._gen()
        code = "```python\nclass EntityScript:\n    pass\n```"
        result = gen._clean(code)
        assert "```" not in result
        assert "class EntityScript" in result

    def test_clean_strips_plain_fences(self):
        gen = self._gen()
        code = "```\nclass EntityScript:\n    pass\n```"
        result = gen._clean(code)
        assert "```" not in result

    def test_clean_strips_whitespace(self):
        gen = self._gen()
        result = gen._clean("  \nclass EntityScript:\n    pass\n  ")
        assert result.startswith("class EntityScript")

    def test_from_prompt_returns_string(self):
        from slappyengine.ai.script_gen import ScriptGenerator
        gen = ScriptGenerator(llm_client=_MockLLM("class EntityScript:\n    pass"))
        result = gen.from_prompt("move right")
        assert isinstance(result, str)

    def test_from_prompt_strips_fences(self):
        from slappyengine.ai.script_gen import ScriptGenerator
        gen = ScriptGenerator(llm_client=_MockLLM("```python\nclass EntityScript:\n    pass\n```"))
        result = gen.from_prompt("test")
        assert "```" not in result


# ---------------------------------------------------------------------------
# code_sync tests
# ---------------------------------------------------------------------------

class TestPromptPathFor:
    def test_returns_path_with_prompt_extension(self):
        from slappyengine.ai.code_sync import prompt_path_for
        result = prompt_path_for("entities/player.py")
        assert result.suffix == ".prompt"

    def test_same_stem_as_script(self):
        from slappyengine.ai.code_sync import prompt_path_for
        result = prompt_path_for("entities/player.py")
        assert result.stem == "player"

    def test_accepts_path_object(self):
        from slappyengine.ai.code_sync import prompt_path_for
        result = prompt_path_for(Path("scripts/enemy.py"))
        assert result.suffix == ".prompt"

    def test_preserves_parent_dir(self):
        from slappyengine.ai.code_sync import prompt_path_for
        result = prompt_path_for("deep/nested/script.py")
        assert "deep" in str(result) or "nested" in str(result)

    def test_constant_extension(self):
        from slappyengine.ai.code_sync import PROMPT_SIDECAR_EXT
        assert PROMPT_SIDECAR_EXT == ".prompt"


class TestWatchedScript:
    def test_init_fields(self):
        from slappyengine.ai.code_sync import WatchedScript
        ws = WatchedScript(
            script_path=Path("a.py"),
            prompt_path=Path("a.prompt"),
        )
        assert ws.script_path == Path("a.py")
        assert ws.prompt_path == Path("a.prompt")
        assert ws.last_script_mtime == pytest.approx(0.0)
        assert ws.last_prompt_mtime == pytest.approx(0.0)
        assert ws.on_code_updated is None
        assert ws.on_prompt_updated is None

    def test_callbacks_stored(self):
        from slappyengine.ai.code_sync import WatchedScript
        cb_code = lambda c: None
        cb_prompt = lambda p: None
        ws = WatchedScript(
            script_path=Path("x.py"),
            prompt_path=Path("x.prompt"),
            on_code_updated=cb_code,
            on_prompt_updated=cb_prompt,
        )
        assert ws.on_code_updated is cb_code
        assert ws.on_prompt_updated is cb_prompt


class TestCodeSyncWatcher:
    def test_init_state(self):
        from slappyengine.ai.code_sync import CodeSyncWatcher
        watcher = CodeSyncWatcher(llm=_MockLLM(), enabled=True)
        assert watcher._enabled is True
        assert watcher._watched == []
        assert watcher._thread is None
        assert not watcher._stop_event.is_set()

    def test_disabled_watcher(self):
        from slappyengine.ai.code_sync import CodeSyncWatcher
        watcher = CodeSyncWatcher(llm=_MockLLM(), enabled=False)
        assert watcher._enabled is False

    def test_watch_adds_entry(self, tmp_path):
        from slappyengine.ai.code_sync import CodeSyncWatcher
        script = tmp_path / "test.py"
        script.write_text("class EntityScript: pass", encoding="utf-8")
        watcher = CodeSyncWatcher(llm=_MockLLM())
        watcher.watch(str(script))
        assert len(watcher._watched) == 1
        assert watcher._watched[0].script_path == script

    def test_unwatch_removes_entry(self, tmp_path):
        from slappyengine.ai.code_sync import CodeSyncWatcher
        script = tmp_path / "test.py"
        script.write_text("class EntityScript: pass", encoding="utf-8")
        watcher = CodeSyncWatcher(llm=_MockLLM())
        watcher.watch(str(script))
        watcher.unwatch(str(script))
        assert len(watcher._watched) == 0

    def test_stop_signals_event(self):
        from slappyengine.ai.code_sync import CodeSyncWatcher
        watcher = CodeSyncWatcher(llm=_MockLLM())
        watcher.stop()
        assert watcher._stop_event.is_set()

    def test_watch_stores_mtime(self, tmp_path):
        from slappyengine.ai.code_sync import CodeSyncWatcher
        script = tmp_path / "test.py"
        script.write_text("class EntityScript: pass", encoding="utf-8")
        watcher = CodeSyncWatcher(llm=_MockLLM())
        watcher.watch(str(script))
        ws = watcher._watched[0]
        assert ws.last_script_mtime == script.stat().st_mtime

    def test_watch_sidecar_mtime_zero_when_absent(self, tmp_path):
        from slappyengine.ai.code_sync import CodeSyncWatcher
        script = tmp_path / "test.py"
        script.write_text("class EntityScript: pass", encoding="utf-8")
        # No .prompt sidecar exists
        watcher = CodeSyncWatcher(llm=_MockLLM())
        watcher.watch(str(script))
        ws = watcher._watched[0]
        assert ws.last_prompt_mtime == pytest.approx(0.0)

    def test_debounce_and_poll_constants(self):
        from slappyengine.ai.code_sync import CodeSyncWatcher
        assert CodeSyncWatcher.DEBOUNCE_SECS > 0
        assert CodeSyncWatcher.POLL_INTERVAL > 0
        assert CodeSyncWatcher.POLL_INTERVAL < CodeSyncWatcher.DEBOUNCE_SECS


class TestAskSync:
    def test_returns_response_from_llm(self):
        from slappyengine.ai.code_sync import _ask_sync
        llm = _MockLLM("hello world")
        result = _ask_sync(llm, "sys", "user")
        assert result == "hello world"

    def test_returns_empty_on_exception(self):
        from slappyengine.ai.code_sync import _ask_sync
        class _BrokenLLM:
            def generate(self, *a, **kw):
                raise RuntimeError("network error")
        result = _ask_sync(_BrokenLLM(), "sys", "user")
        assert result == ""

    def test_strips_whitespace(self):
        from slappyengine.ai.code_sync import _ask_sync
        llm = _MockLLM("  hello  \n")
        result = _ask_sync(llm, "sys", "user")
        assert result == "hello"
