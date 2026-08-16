import httpx
import pytest

from app.services.ollama_client import OllamaClient, OllamaTimeoutError, OllamaUnreachableError


async def test_generate_json_returns_the_response_content(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pins the real OllamaClient's contract against the actual `ollama`
    package interface (unlike the autouse stub used elsewhere), so a change
    to that package's response shape or exception types would be caught here
    without needing a real Ollama server."""

    async def fake_chat(self, *, model, messages, format, options):  # noqa: A002
        assert format == "json"
        assert "num_ctx" in options
        return {"message": {"content": '{"ok": true}'}}

    monkeypatch.setattr("ollama.AsyncClient.chat", fake_chat)

    client = OllamaClient(host="http://localhost:11434", model="qwen2.5:3b")
    result = await client.generate_json("some prompt")

    assert result == '{"ok": true}'


async def test_generate_json_raises_unreachable_on_connection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_chat(self, **kwargs):
        raise ConnectionError("Failed to connect to Ollama.")

    monkeypatch.setattr("ollama.AsyncClient.chat", fake_chat)

    client = OllamaClient()
    with pytest.raises(OllamaUnreachableError):
        await client.generate_json("some prompt")


async def test_generate_json_raises_timeout_on_httpx_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_chat(self, **kwargs):
        raise httpx.ReadTimeout("timed out")

    monkeypatch.setattr("ollama.AsyncClient.chat", fake_chat)

    client = OllamaClient()
    with pytest.raises(OllamaTimeoutError):
        await client.generate_json("some prompt")
