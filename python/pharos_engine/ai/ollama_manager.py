"""OllamaManager — detect, launch, and provision a local Ollama instance.

Responsibilities
----------------
1. Check whether the Ollama HTTP server is reachable on localhost:11434.
2. Start it via ``ollama serve`` if it is not running.
3. Check whether a specific model is installed.
4. Stream ``ollama pull <model>`` progress to a caller-supplied callback.
5. Orchestrate all of the above via :meth:`ensure_ready`.
6. Persist AI settings to ~/.SlapPyEngine/ai_settings.json.

No GUI code lives here — this module is pure logic so it can be unit-tested
without a DPG context.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

_SETTINGS_DIR  = Path.home() / ".SlapPyEngine"
_SETTINGS_FILE = _SETTINGS_DIR / "ai_settings.json"

_PERCENT_RE = re.compile(r"(\d+)%")


def load_ai_settings() -> dict:
    """Return persisted AI settings, or {} if none saved yet."""
    try:
        return json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_ai_settings(settings: dict) -> None:
    """Persist AI settings dict to ~/.SlapPyEngine/ai_settings.json."""
    _SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    _SETTINGS_FILE.write_text(json.dumps(settings, indent=2), encoding="utf-8")

_OLLAMA_BASE = "http://localhost:11434"
_TAGS_URL = f"{_OLLAMA_BASE}/api/tags"
_SERVER_WAIT_S = 5.0      # seconds to wait for `ollama serve` to become ready
_SERVER_POLL_S = 0.25     # poll interval while waiting


class OllamaManager:
    """Manages the lifecycle of a local Ollama server and its models."""

    DEFAULT_MODEL: str = "qwen2.5-coder:7b"

    # ------------------------------------------------------------------
    # Server probing
    # ------------------------------------------------------------------

    def is_server_running(self) -> bool:
        """Return True if the Ollama HTTP server responds at /api/tags."""
        try:
            req = urllib.request.Request(_TAGS_URL)
            with urllib.request.urlopen(req, timeout=1) as resp:
                return resp.status == 200
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Server launch
    # ------------------------------------------------------------------

    def start_server(self) -> bool:
        """Attempt to start Ollama via ``ollama serve``.

        Spawns the process and polls until the server becomes reachable or
        :data:`_SERVER_WAIT_S` seconds elapse.

        Returns
        -------
        bool
            True if the server became reachable within the timeout.
        """
        try:
            subprocess.Popen(
                ["ollama", "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                # Detach from our process group so it keeps running if the
                # editor exits, matching the behaviour of the Ollama tray app.
                creationflags=(
                    subprocess.CREATE_NEW_PROCESS_GROUP
                    if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP")
                    else 0
                ),
            )
        except FileNotFoundError:
            # `ollama` binary not on PATH
            return False
        except Exception:
            return False

        deadline = time.monotonic() + _SERVER_WAIT_S
        while time.monotonic() < deadline:
            if self.is_server_running():
                return True
            time.sleep(_SERVER_POLL_S)
        return False

    # ------------------------------------------------------------------
    # Binary availability
    # ------------------------------------------------------------------

    def is_ollama_installed(self) -> bool:
        """Return True if the ``ollama`` binary is discoverable on PATH."""
        return shutil.which("ollama") is not None

    # ------------------------------------------------------------------
    # Model probing
    # ------------------------------------------------------------------

    def is_model_installed(self, model: str) -> bool:
        """Return True if *model* appears in the server's installed model list.

        Compares both exact names and the base name (stripping any ``:tag``
        suffix) to handle ``qwen2.5-coder:7b`` vs ``qwen2.5-coder`` etc.
        """
        try:
            req = urllib.request.Request(_TAGS_URL)
            with urllib.request.urlopen(req, timeout=2) as resp:
                data = json.loads(resp.read().decode())
        except Exception:
            return False

        installed = [m.get("name", "") for m in data.get("models", [])]
        model_base = model.split(":")[0]
        for name in installed:
            if name == model or name.split(":")[0] == model_base:
                return True
        return False

    # ------------------------------------------------------------------
    # Model pull
    # ------------------------------------------------------------------

    def pull_model(
        self,
        model: str,
        on_progress: Callable[[str, float], None] | None = None,
        cancel_event=None,
    ) -> bool:
        """Run ``ollama pull <model>`` and stream JSON progress lines.

        Each stdout line produced by ``ollama pull`` is valid JSON, e.g.::

            {"status": "pulling manifest"}
            {"status": "downloading...", "completed": 1234, "total": 5678}
            {"status": "success"}

        Parameters
        ----------
        model:
            Model tag to pull (e.g. ``"qwen2.5-coder:7b"``).
        on_progress:
            Optional callback ``(status_str, fraction)`` where *fraction* is
            in ``[0.0, 1.0]``.  Called for every parsed line.
        cancel_event:
            Optional :class:`threading.Event`.  When set the subprocess is
            terminated and the method returns False.

        Returns
        -------
        bool
            True if the pull completed with a ``"success"`` status line.
        """
        try:
            proc = subprocess.Popen(
                ["ollama", "pull", model],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except Exception:
            return False

        success = False
        try:
            for raw_line in proc.stdout:  # type: ignore[union-attr]
                if cancel_event is not None and cancel_event.is_set():
                    proc.terminate()
                    return False

                line = raw_line.strip()
                if not line:
                    continue

                # --- Try JSON format (older Ollama <=0.1.19) ---
                try:
                    obj = json.loads(line)
                    status = obj.get("status", "")
                    completed = obj.get("completed", 0)
                    total = obj.get("total", 0)
                    fraction = (completed / total) if total > 0 else 0.01
                    if on_progress is not None:
                        on_progress(status, fraction)
                    if status == "success":
                        success = True
                    continue
                except json.JSONDecodeError:
                    pass

                # --- Text format (newer Ollama >=0.1.20) ---
                # e.g. "pulling abc123... 45% ████ 2.1 GB/4.7 GB"
                m = _PERCENT_RE.search(line)
                if m:
                    pct = int(m.group(1))
                    fraction = max(0.01, pct / 100.0)
                    # Condense the line to a short status string
                    label = line[:line.find(m.group(0))].strip().rstrip(".")
                    label = label[:40] if label else "Downloading"
                    if on_progress is not None:
                        on_progress(f"{label}  {pct}%", fraction)
                elif "success" in line.lower():
                    if on_progress is not None:
                        on_progress("Complete!", 1.0)
                    success = True
                else:
                    # Status lines like "pulling manifest", "verifying sha256"
                    if on_progress is not None:
                        on_progress(line[:60], 0.01)
        finally:
            proc.wait()

        return success

    # ------------------------------------------------------------------
    # Orchestration
    # ------------------------------------------------------------------

    def ensure_ready(
        self,
        model: str = DEFAULT_MODEL,
        on_progress: Callable[[str, float], None] | None = None,
        cancel_event=None,
    ) -> bool:
        """Ensure Ollama is running and *model* is available.

        Sequence
        --------
        1. Check if server is already running.
        2. If not, verify ``ollama`` is on PATH; if missing return False
           (caller should tell the user how to install it).
        3. Start the server via :meth:`start_server`; fail if it doesn't
           come up within the timeout.
        4. Check if *model* is already installed.
        5. If not, pull it, streaming progress to *on_progress*.

        Parameters
        ----------
        model:
            Model tag to ensure (default: :data:`DEFAULT_MODEL`).
        on_progress:
            ``(status_str, fraction)`` progress callback, forwarded to
            :meth:`pull_model`.
        cancel_event:
            A :class:`threading.Event` that aborts the operation when set.

        Returns
        -------
        bool
            True when both the server is reachable AND *model* is installed.
        """
        def _progress(status: str, frac: float) -> None:
            if on_progress is not None:
                on_progress(status, frac)

        def _cancelled() -> bool:
            return cancel_event is not None and cancel_event.is_set()

        # 1. Server check
        if not self.is_server_running():
            if _cancelled():
                return False

            # 2. Binary check
            if not self.is_ollama_installed():
                _progress("Ollama is not installed — visit https://ollama.com", 0.0)
                return False

            # 3. Start server
            _progress("Starting Ollama server...", 0.0)
            if not self.start_server():
                _progress("Ollama server did not start in time.", 0.0)
                return False

        if _cancelled():
            return False

        # 4. Model check
        _progress("Checking model...", 0.0)
        if self.is_model_installed(model):
            _progress("Ready.", 1.0)
            return True

        if _cancelled():
            return False

        # 5. Pull model
        _progress(f"Pulling {model}...", 0.0)
        ok = self.pull_model(model, on_progress=on_progress, cancel_event=cancel_event)
        if not ok and not _cancelled():
            _progress(f"Failed to pull {model}.", 0.0)
        return ok
