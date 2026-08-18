import httpx
import pytest

from app.services.cloud_llm_client import (
    ChainedLLMClient,
    LLMRateLimitedError,
    OpenAICompatibleProvider,
)
from app.services.llm_errors import LLMTimeoutError, LLMUnreachableError


def _fake_response(status_code: int, json_body: dict | None = None, text: str = "") -> httpx.Response:
    return httpx.Response(status_code, json=json_body, text=text if json_body is None else None)


class TestOpenAICompatibleProvider:
    """Pins the real provider's contract against the actual httpx interface,
    same approach as test_ollama_client.py, so a change to request shape or
    exception mapping is caught here without hitting a real API."""

    async def test_generate_returns_the_message_content(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict = {}

        async def fake_post(self, url, *, headers, json):  # noqa: A002
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return _fake_response(200, {"choices": [{"message": {"content": "hello"}}]})

        monkeypatch.setattr("httpx.AsyncClient.post", fake_post)

        provider = OpenAICompatibleProvider("cerebras", "https://api.cerebras.ai/v1", "key123", "gpt-oss-120b", 30.0)
        result = await provider.generate("some prompt", temperature=0.2, json_mode=False)

        assert result == "hello"
        assert captured["url"] == "https://api.cerebras.ai/v1/chat/completions"
        assert captured["headers"]["Authorization"] == "Bearer key123"
        assert captured["json"]["model"] == "gpt-oss-120b"
        assert captured["json"]["messages"] == [{"role": "user", "content": "some prompt"}]
        assert "response_format" not in captured["json"]

    async def test_json_mode_sets_response_format(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict = {}

        async def fake_post(self, url, *, headers, json):  # noqa: A002
            captured["json"] = json
            return _fake_response(200, {"choices": [{"message": {"content": "{}"}}]})

        monkeypatch.setattr("httpx.AsyncClient.post", fake_post)

        provider = OpenAICompatibleProvider("groq", "https://api.groq.com/openai/v1", "key", "model", 30.0)
        await provider.generate("prompt", temperature=0.2, json_mode=True)

        assert captured["json"]["response_format"] == {"type": "json_object"}

    async def test_429_raises_rate_limited_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def fake_post(self, url, *, headers, json):  # noqa: A002
            return _fake_response(429, text="rate limited")

        monkeypatch.setattr("httpx.AsyncClient.post", fake_post)

        provider = OpenAICompatibleProvider("groq", "https://api.groq.com/openai/v1", "key", "model", 30.0)
        with pytest.raises(LLMRateLimitedError):
            await provider.generate("prompt", temperature=0.2, json_mode=False)

    async def test_server_error_raises_unreachable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def fake_post(self, url, *, headers, json):  # noqa: A002
            return _fake_response(500, text="internal error")

        monkeypatch.setattr("httpx.AsyncClient.post", fake_post)

        provider = OpenAICompatibleProvider("cerebras", "https://api.cerebras.ai/v1", "key", "model", 30.0)
        with pytest.raises(LLMUnreachableError):
            await provider.generate("prompt", temperature=0.2, json_mode=False)

    async def test_httpx_timeout_raises_llm_timeout_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def fake_post(self, url, *, headers, json):  # noqa: A002
            raise httpx.ReadTimeout("timed out")

        monkeypatch.setattr("httpx.AsyncClient.post", fake_post)

        provider = OpenAICompatibleProvider("gemini", "https://generativelanguage.googleapis.com", "key", "m", 30.0)
        with pytest.raises(LLMTimeoutError):
            await provider.generate("prompt", temperature=0.2, json_mode=False)

    async def test_connection_error_raises_unreachable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def fake_post(self, url, *, headers, json):  # noqa: A002
            raise httpx.ConnectError("connection refused")

        monkeypatch.setattr("httpx.AsyncClient.post", fake_post)

        provider = OpenAICompatibleProvider("groq", "https://api.groq.com/openai/v1", "key", "model", 30.0)
        with pytest.raises(LLMUnreachableError):
            await provider.generate("prompt", temperature=0.2, json_mode=False)

    async def test_malformed_response_body_raises_unreachable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def fake_post(self, url, *, headers, json):  # noqa: A002
            return _fake_response(200, {"unexpected": "shape"})

        monkeypatch.setattr("httpx.AsyncClient.post", fake_post)

        provider = OpenAICompatibleProvider("cerebras", "https://api.cerebras.ai/v1", "key", "model", 30.0)
        with pytest.raises(LLMUnreachableError):
            await provider.generate("prompt", temperature=0.2, json_mode=False)


class _FakeProvider:
    """Stand-in for OpenAICompatibleProvider used to test ChainedLLMClient's
    orchestration logic in isolation from real HTTP, the same way
    quiz_generation's tests use a ScriptedClient standing in for OllamaClient."""

    def __init__(self, name: str, outcome: Exception | str) -> None:
        self.name = name
        self._outcome = outcome
        self.calls: list[tuple[str, float, bool]] = []

    async def generate(self, prompt: str, *, temperature: float, json_mode: bool) -> str:
        self.calls.append((prompt, temperature, json_mode))
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return self._outcome


class TestChainedLLMClient:
    async def test_returns_the_first_providers_result_without_calling_the_rest(self) -> None:
        first = _FakeProvider("a", "first result")
        second = _FakeProvider("b", "second result")

        client = ChainedLLMClient([first, second])
        result = await client.generate_text("prompt")

        assert result == "first result"
        assert len(second.calls) == 0

    async def test_falls_through_to_the_next_provider_on_unreachable(self) -> None:
        first = _FakeProvider("a", LLMUnreachableError("down"))
        second = _FakeProvider("b", "fallback result")

        client = ChainedLLMClient([first, second])
        result = await client.generate_text("prompt")

        assert result == "fallback result"

    async def test_falls_through_on_timeout(self) -> None:
        first = _FakeProvider("a", LLMTimeoutError("slow"))
        second = _FakeProvider("b", "fallback result")

        client = ChainedLLMClient([first, second])
        result = await client.generate_text("prompt")

        assert result == "fallback result"

    async def test_falls_through_on_rate_limit(self) -> None:
        first = _FakeProvider("a", LLMRateLimitedError("too many requests"))
        second = _FakeProvider("b", "fallback result")

        client = ChainedLLMClient([first, second])
        result = await client.generate_text("prompt")

        assert result == "fallback result"

    async def test_raises_unreachable_when_every_provider_fails(self) -> None:
        first = _FakeProvider("a", LLMUnreachableError("down"))
        second = _FakeProvider("b", LLMTimeoutError("slow"))

        client = ChainedLLMClient([first, second])
        with pytest.raises(LLMUnreachableError):
            await client.generate_text("prompt")

    def test_construction_with_no_providers_raises(self) -> None:
        with pytest.raises(ValueError):
            ChainedLLMClient([])

    async def test_generate_json_passes_json_mode_true(self) -> None:
        provider = _FakeProvider("a", "{}")
        client = ChainedLLMClient([provider])

        await client.generate_json("prompt", temperature=0.4)

        assert provider.calls == [("prompt", 0.4, True)]

    async def test_generate_text_passes_json_mode_false(self) -> None:
        provider = _FakeProvider("a", "text")
        client = ChainedLLMClient([provider])

        await client.generate_text("prompt", temperature=0.7)

        assert provider.calls == [("prompt", 0.7, False)]
