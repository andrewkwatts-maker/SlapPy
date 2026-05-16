"""code_sync — bidirectional AI reconciliation between prompt and Python code.

The AI syncs in the direction of whichever was edited most recently:
  - Prompt newer  → rewrite code to implement the prompt
  - Code newer    → update prompt to describe the code

Background file-watching is provided by :class:`CodeSyncWatcher`.
"""
from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


PROMPT_SIDECAR_EXT = ".prompt"  # sidecar file sits next to the .py file


def prompt_path_for(script_path: str | Path) -> Path:
    """Return the .prompt sidecar path for a given .py script."""
    return Path(script_path).with_suffix(PROMPT_SIDECAR_EXT)


# ── AI calls (thin wrapper around LLMClient.generate) ─────────────────────────

def _ask_sync(llm, system: str, user: str) -> str:
    """Synchronous call to LLMClient.generate.  Returns stripped text."""
    try:
        result = llm.generate(user, system_prompt=system, temperature=0.2)
        return (result or "").strip()
    except Exception:
        return ""


async def _ask(llm, system: str, user: str) -> str:
    """Async wrapper: runs the synchronous LLMClient.generate in a thread pool."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: _ask_sync(llm, system, user))


async def prompt_to_code(prompt: str, current_code: str, llm) -> str:
    """Rewrite *current_code* so it implements what *prompt* describes."""
    system = (
        "You are a Python code assistant embedded in a game engine editor. "
        "Rewrite the provided Python code so it implements the given description. "
        "Return ONLY valid Python code. No markdown fences, no explanation."
    )
    user = f"Description:\n{prompt}\n\nCurrent code:\n{current_code}"
    result = await _ask(llm, system, user)
    # Strip markdown fences if the model added them anyway
    if result.startswith("```"):
        lines = result.splitlines()
        result = "\n".join(l for l in lines if not l.startswith("```")).strip()
    return result or current_code


async def code_to_prompt(code: str, llm) -> str:
    """Generate a concise plain-English description of what *code* does."""
    system = (
        "You are a documentation assistant. "
        "Describe what the given Python code does in 2-4 sentences of plain English. "
        "Focus on behavior and purpose. Return ONLY the description, no code."
    )
    user = f"Code:\n{code}"
    return await _ask(llm, system, user) or "(no description)"


# ── File-watching background sync ─────────────────────────────────────────────

@dataclass
class WatchedScript:
    script_path: Path
    prompt_path: Path
    last_script_mtime: float = 0.0
    last_prompt_mtime: float = 0.0
    on_code_updated: Callable[[str], None] | None = None
    on_prompt_updated: Callable[[str], None] | None = None


class CodeSyncWatcher:
    """Background thread that watches .py + .prompt sidecar pairs.

    When either file changes, waits for a debounce period then calls the AI
    to sync in the correct direction.

    Usage::

        watcher = CodeSyncWatcher(llm_client)
        watcher.start()
        watcher.watch(
            "entities/player.py",
            on_code_updated=lambda code: refresh_editor(code),
            on_prompt_updated=lambda p: refresh_prompt(p),
        )
        # …
        watcher.stop()
    """

    DEBOUNCE_SECS = 2.0   # wait this long after last change before calling AI
    POLL_INTERVAL = 0.5   # how often to check file mtimes (seconds)

    def __init__(self, llm, enabled: bool = True) -> None:
        self._llm = llm
        self._enabled = enabled
        self._watched: list[WatchedScript] = []
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        # Pending syncs: script_path → (fire_at_monotonic, direction)
        self._pending: dict[Path, tuple[float, str]] = {}

    def start(self) -> None:
        """Start the background polling thread (idempotent)."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="CodeSyncWatcher"
        )
        self._thread.start()

    def stop(self) -> None:
        """Signal the background thread to stop."""
        self._stop_event.set()

    def watch(
        self,
        script_path: str | Path,
        on_code_updated: Callable | None = None,
        on_prompt_updated: Callable | None = None,
    ) -> None:
        """Begin watching *script_path* and its .prompt sidecar."""
        sp = Path(script_path)
        pp = prompt_path_for(sp)
        ws = WatchedScript(
            script_path=sp,
            prompt_path=pp,
            last_script_mtime=sp.stat().st_mtime if sp.exists() else 0.0,
            last_prompt_mtime=pp.stat().st_mtime if pp.exists() else 0.0,
            on_code_updated=on_code_updated,
            on_prompt_updated=on_prompt_updated,
        )
        with self._lock:
            self._watched.append(ws)

    def unwatch(self, script_path: str | Path) -> None:
        """Stop watching *script_path*."""
        sp = Path(script_path)
        with self._lock:
            self._watched = [w for w in self._watched if w.script_path != sp]

    # ── Internal ──────────────────────────────────────────────────────────────

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        while not self._stop_event.is_set():
            try:
                self._poll(loop)
            except Exception:
                pass
            time.sleep(self.POLL_INTERVAL)
        loop.close()

    def _poll(self, loop: asyncio.AbstractEventLoop) -> None:
        now = time.monotonic()
        with self._lock:
            watched = list(self._watched)

        for ws in watched:
            script_mtime = ws.script_path.stat().st_mtime if ws.script_path.exists() else 0.0
            prompt_mtime = ws.prompt_path.stat().st_mtime if ws.prompt_path.exists() else 0.0

            script_changed = script_mtime > ws.last_script_mtime + 0.01
            prompt_changed = prompt_mtime > ws.last_prompt_mtime + 0.01

            if not (script_changed or prompt_changed):
                # Check if a pending debounce is ready to fire
                if ws.script_path in self._pending:
                    fire_at, direction = self._pending[ws.script_path]
                    if now >= fire_at:
                        del self._pending[ws.script_path]
                        loop.run_until_complete(self._do_sync(ws, direction))
                continue

            # Determine direction: whichever file is newer wins
            if prompt_changed and (not script_changed or prompt_mtime >= script_mtime):
                direction = "prompt_to_code"
                ws.last_prompt_mtime = prompt_mtime
            else:
                direction = "code_to_prompt"
                ws.last_script_mtime = script_mtime

            # Schedule with debounce (reset timer on each new change)
            self._pending[ws.script_path] = (now + self.DEBOUNCE_SECS, direction)

    async def _do_sync(self, ws: WatchedScript, direction: str) -> None:
        if not self._enabled or self._llm is None:
            return
        if direction == "prompt_to_code":
            prompt_text = ws.prompt_path.read_text(encoding="utf-8") if ws.prompt_path.exists() else ""
            code_text = ws.script_path.read_text(encoding="utf-8") if ws.script_path.exists() else ""
            if not prompt_text.strip():
                return
            new_code = await prompt_to_code(prompt_text, code_text, self._llm)
            if new_code and new_code != code_text:
                ws.script_path.write_text(new_code, encoding="utf-8")
                ws.last_script_mtime = ws.script_path.stat().st_mtime
                if ws.on_code_updated:
                    ws.on_code_updated(new_code)
        else:  # code_to_prompt
            code_text = ws.script_path.read_text(encoding="utf-8") if ws.script_path.exists() else ""
            if not code_text.strip():
                return
            new_prompt = await code_to_prompt(code_text, self._llm)
            if new_prompt:
                ws.prompt_path.write_text(new_prompt, encoding="utf-8")
                ws.last_prompt_mtime = ws.prompt_path.stat().st_mtime
                if ws.on_prompt_updated:
                    ws.on_prompt_updated(new_prompt)
