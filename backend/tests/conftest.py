import pytest

from app.services.ollama_client import OllamaUnreachableError


class _StubOllamaClient:
    """Fast, network-free stand-in used everywhere except tests explicitly
    marked `real_ollama`, so the rest of the suite doesn't depend on Ollama
    being installed/running and doesn't pay real LLM latency. Document
    processing must remain fully testable without any LLM available, since
    overview generation failures are never allowed to affect it."""

    async def generate_json(self, prompt: str, *, temperature: float = 0.2) -> str:
        raise OllamaUnreachableError("stub: Ollama not used in this test")


@pytest.fixture(autouse=True)
def _stub_ollama_by_default(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> None:
    if "real_ollama" in request.keywords:
        return
    monkeypatch.setattr(
        "app.services.overview_generation.OllamaClient",
        lambda *args, **kwargs: _StubOllamaClient(),
    )
