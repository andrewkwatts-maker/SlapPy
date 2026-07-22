"""Headless tests for pharos_engine.ai.llm_client (LLMClient).

httpx is mocked so no network access occurs.
"""
from __future__ import annotations
import os
import sys
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Build a mock httpx with real exception classes so isinstance() checks work
# ---------------------------------------------------------------------------

_mock_httpx = MagicMock()


class _FakeConnectError(Exception):
    pass


class _FakeConnectTimeout(Exception):
    pass


class _FakeHTTPStatusError(Exception):
    pass


_mock_httpx.ConnectError = _FakeConnectError
_mock_httpx.ConnectTimeout = _FakeConnectTimeout
_mock_httpx.HTTPStatusError = _FakeHTTPStatusError

sys.modules.setdefault("httpx", _mock_httpx)


# ===========================================================================
# Module-level constants
# ===========================================================================

class TestLLMClientConstants:
    def test_default_host(self):
        from pharos_engine.ai.llm_client import _DEFAULT_HOST
        assert _DEFAULT_HOST == "http://localhost:11434"

    def test_default_model(self):
        from pharos_engine.ai.llm_client import _DEFAULT_MODEL
        assert _DEFAULT_MODEL == "qwen2.5-coder:7b"


# ===========================================================================
# Instantiation
# ===========================================================================

class TestLLMClientInit:
    def _client(self, **kwargs):
        from pharos_engine.ai.llm_client import LLMClient
        return LLMClient(**kwargs)

    def test_default_host(self):
        c = self._client()
        assert c._host == "http://localhost:11434"

    def test_default_model(self):
        c = self._client()
        assert c._model == "qwen2.5-coder:7b"

    def test_trailing_slash_stripped(self):
        c = self._client(host="http://localhost:11434/")
        assert not c._host.endswith("/")

    def test_custom_host(self):
        c = self._client(host="http://myserver:8080")
        assert c._host == "http://myserver:8080"

    def test_custom_model(self):
        c = self._client(model="llama3:8b")
        assert c._model == "llama3:8b"

    def test_env_host_used(self):
        os.environ["LLM_HOST"] = "http://env-host:9999"
        os.environ["LLM_MODEL"] = "env-model"
        try:
            c = self._client()
            assert c._host == "http://env-host:9999"
            assert c._model == "env-model"
        finally:
            del os.environ["LLM_HOST"]
            del os.environ["LLM_MODEL"]

    def test_explicit_overrides_env(self):
        os.environ["LLM_HOST"] = "http://env-host:9999"
        os.environ["LLM_MODEL"] = "env-model"
        try:
            c = self._client(host="http://explicit:1234", model="explicit-model")
            assert c._host == "http://explicit:1234"
            assert c._model == "explicit-model"
        finally:
            del os.environ["LLM_HOST"]
            del os.environ["LLM_MODEL"]

    def test_http_client_created(self):
        c = self._client()
        assert c._client is not None


# ===========================================================================
# is_available
# ===========================================================================

class TestLLMClientIsAvailable:
    def _client(self):
        from pharos_engine.ai.llm_client import LLMClient
        return LLMClient()

    def test_returns_true_on_200(self):
        c = self._client()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        c._client.get.return_value = mock_resp
        assert c.is_available() is True

    def test_returns_false_on_non_200(self):
        c = self._client()
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        c._client.get.return_value = mock_resp
        assert c.is_available() is False

    def test_returns_false_on_exception(self):
        c = self._client()
        c._client.get.side_effect = Exception("timeout")
        assert c.is_available() is False
        c._client.get.side_effect = None


# ===========================================================================
# list_models
# ===========================================================================

class TestLLMClientListModels:
    def _client(self):
        from pharos_engine.ai.llm_client import LLMClient
        return LLMClient()

    def test_returns_list_of_names(self):
        c = self._client()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "models": [{"name": "qwen2.5-coder:7b"}, {"name": "llama3:8b"}]
        }
        mock_resp.raise_for_status = MagicMock()
        c._client.get.return_value = mock_resp
        result = c.list_models()
        assert result == ["qwen2.5-coder:7b", "llama3:8b"]

    def test_returns_empty_list_on_error(self):
        c = self._client()
        c._client.get.side_effect = Exception("network error")
        assert c.list_models() == []
        c._client.get.side_effect = None

    def test_returns_empty_list_on_missing_key(self):
        c = self._client()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {}
        mock_resp.raise_for_status = MagicMock()
        c._client.get.return_value = mock_resp
        assert c.list_models() == []

    def test_single_model(self):
        c = self._client()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"models": [{"name": "model-only:latest"}]}
        mock_resp.raise_for_status = MagicMock()
        c._client.get.return_value = mock_resp
        result = c.list_models()
        assert result == ["model-only:latest"]


# ===========================================================================
# generate
# ===========================================================================

class TestLLMClientGenerate:
    def _client(self):
        from pharos_engine.ai.llm_client import LLMClient
        return LLMClient()

    def _mock_resp(self, text="hello"):
        r = MagicMock()
        r.json.return_value = {"response": text}
        r.raise_for_status = MagicMock()
        return r

    def test_returns_response_text(self):
        c = self._client()
        c._client.post.return_value = self._mock_resp("answer text")
        assert c.generate("prompt") == "answer text"

    def test_payload_includes_model(self):
        c = self._client()
        c._client.post.return_value = self._mock_resp()
        c.generate("test")
        payload = c._client.post.call_args[1]["json"]
        assert payload["model"] == c._model

    def test_payload_stream_false(self):
        c = self._client()
        c._client.post.return_value = self._mock_resp()
        c.generate("test")
        payload = c._client.post.call_args[1]["json"]
        assert payload["stream"] is False

    def test_system_prompt_included_when_given(self):
        c = self._client()
        c._client.post.return_value = self._mock_resp()
        c.generate("test", system_prompt="be concise")
        payload = c._client.post.call_args[1]["json"]
        assert payload["system"] == "be concise"

    def test_system_prompt_absent_when_empty(self):
        c = self._client()
        c._client.post.return_value = self._mock_resp()
        c.generate("test", system_prompt="")
        payload = c._client.post.call_args[1]["json"]
        assert "system" not in payload

    def test_temperature_forwarded(self):
        c = self._client()
        c._client.post.return_value = self._mock_resp()
        c.generate("test", temperature=0.7)
        payload = c._client.post.call_args[1]["json"]
        assert abs(payload["options"]["temperature"] - 0.7) < 1e-9

    def test_generic_exception_returns_empty(self):
        c = self._client()
        c._client.post.side_effect = Exception("server down")
        assert c.generate("test") == ""
        c._client.post.side_effect = None

    def test_connect_error_raises_connection_error(self):
        import pytest
        c = self._client()
        c._client.post.side_effect = _FakeConnectError("refused")
        with pytest.raises(ConnectionError) as exc_info:
            c.generate("test")
        assert "Ollama" in str(exc_info.value)
        c._client.post.side_effect = None

    def test_connect_timeout_raises_connection_error(self):
        import pytest
        c = self._client()
        c._client.post.side_effect = _FakeConnectTimeout("timed out")
        with pytest.raises(ConnectionError):
            c.generate("test")
        c._client.post.side_effect = None

    def test_missing_response_key_returns_empty(self):
        c = self._client()
        r = MagicMock()
        r.json.return_value = {}
        r.raise_for_status = MagicMock()
        c._client.post.return_value = r
        assert c.generate("test") == ""

    def test_endpoint_is_generate(self):
        c = self._client()
        c._client.post.return_value = self._mock_resp()
        c.generate("test")
        url = c._client.post.call_args[0][0]
        assert "generate" in url
