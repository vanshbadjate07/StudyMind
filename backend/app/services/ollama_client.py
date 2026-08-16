import httpx
from ollama import AsyncClient

from app.config import settings


class OllamaUnreachableError(Exception):
    """Ollama isn't running or isn't reachable at the configured host."""


class OllamaTimeoutError(Exception):
    """Ollama accepted the request but didn't respond within the configured timeout."""


class OllamaClient:
    def __init__(self, host: str | None = None, model: str | None = None) -> None:
        self._client = AsyncClient(
            host=host or settings.ollama_host,
            timeout=settings.overview_llm_timeout_seconds,
        )
        self._model = model or settings.overview_model

    async def generate_json(self, prompt: str, *, temperature: float = 0.2) -> str:
        try:
            response = await self._client.chat(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                format="json",
                options={"temperature": temperature, "num_ctx": settings.overview_context_tokens},
            )
        except ConnectionError as exc:
            raise OllamaUnreachableError(str(exc)) from exc
        except httpx.TimeoutException as exc:
            raise OllamaTimeoutError(str(exc)) from exc
        return response["message"]["content"]
