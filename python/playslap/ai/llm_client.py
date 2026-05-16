"""LLMClient — synchronous Ollama REST client for SlapPyEngine AI features.

Environment variables:
  LLM_HOST   — Ollama base URL  (default: http://localhost:11434)
  LLM_MODEL  — model name       (default: qwen2.5-coder:7b)
"""
from __future__ import annotations

import os

_DEFAULT_HOST = "http://localhost:11434"
_DEFAULT_MODEL = "qwen2.5-coder:7b"


def _require_httpx():
    """Import httpx or raise a helpful ImportError."""
    try:
        import httpx  # noqa: F401
        return httpx
    except ImportError:
        raise ImportError(
            "httpx is required for LLMClient.\n"
            "Install it with: pip install playslap[ai]"
        )


class LLMClient:
    """Synchronous REST client for a locally-running Ollama instance.

    Parameters
    ----------
    host:
        Base URL of the Ollama server.  Overrides the ``LLM_HOST`` env var.
        Defaults to ``http://localhost:11434``.
    model:
        Model name to use for generation.  Overrides the ``LLM_MODEL`` env
        var.  Defaults to ``qwen2.5-coder:7b``.

    Notes
    -----
    The class is importable without ``httpx`` installed.  The ``ImportError``
    with an install hint is only raised when the class is actually
    instantiated.
    """

    def __init__(
        self,
        host: str | None = None,
        model: str | None = None,
    ) -> None:
        # Raise here (not at import time) so the module is always importable.
        httpx = _require_httpx()

        self._host = (host or os.getenv("LLM_HOST", _DEFAULT_HOST)).rstrip("/")
        self._model = model or os.getenv("LLM_MODEL", _DEFAULT_MODEL)
        self._client = httpx.Client(base_url=self._host, timeout=120.0)

    # ------------------------------------------------------------------
    # Availability probe
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """Return True if the Ollama server is reachable at ``/api/tags``."""
        try:
            resp = self._client.get("/api/tags", timeout=2.0)
            return resp.status_code == 200
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Core generation
    # ------------------------------------------------------------------

    def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        temperature: float = 0.2,
    ) -> str:
        """Generate text from *prompt* using the configured model.

        Parameters
        ----------
        prompt:
            User-facing prompt text.
        system_prompt:
            Optional system prompt prepended to the conversation.
        temperature:
            Sampling temperature (lower = more deterministic).

        Returns
        -------
        str
            Generated text, or an empty string if the request fails.

        Raises
        ------
        ConnectionError
            If the Ollama server cannot be reached.
        """
        payload: dict = {
            "model": self._model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature},
        }
        if system_prompt:
            payload["system"] = system_prompt

        try:
            resp = self._client.post("/api/generate", json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data.get("response", "")
        except Exception as exc:
            # Distinguish connection failures from other HTTP errors
            import httpx
            if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
                raise ConnectionError(
                    f"Cannot reach Ollama at {self._host}. "
                    "Ensure Ollama is running: https://ollama.com"
                ) from exc
            # Other errors (4xx/5xx, JSON decode, etc.) return empty string
            return ""

    # ------------------------------------------------------------------
    # Model listing
    # ------------------------------------------------------------------

    def list_models(self) -> list[str]:
        """Return a list of model names available on the Ollama server.

        Returns an empty list if the server is unreachable or returns an
        unexpected payload.
        """
        try:
            resp = self._client.get("/api/tags", timeout=5.0)
            resp.raise_for_status()
            data = resp.json()
            return [m["name"] for m in data.get("models", [])]
        except Exception:
            return []
