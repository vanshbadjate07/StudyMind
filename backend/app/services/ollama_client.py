import httpx
from ollama import AsyncClient

from app.config import settings


class OllamaUnreachableError(Exception):
    """Ollama isn't running or isn't reachable at the configured host."""


class OllamaTimeoutError(Exception):
    """Ollama accepted the request but didn't respond within the configured timeout."""


class OllamaClient:
    """Generic chat-completion client. Defaults match the overview feature's
    settings (the first caller of this class); other callers (e.g. chat)
    pass their own `model`/`timeout`/`num_ctx` explicitly rather than relying
    on those defaults, since a shared client shouldn't hardcode one specific
    feature's config."""

    def __init__(
        self,
        host: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
        num_ctx: int | None = None,
    ) -> None:
        self._client = AsyncClient(
            host=host or settings.ollama_host,
            timeout=timeout if timeout is not None else settings.overview_llm_timeout_seconds,
        )
        self._model = model or settings.overview_model
        self._num_ctx = num_ctx if num_ctx is not None else settings.overview_context_tokens

    async def generate_json(self, prompt: str, *, temperature: float = 0.2) -> str:
        """Constrains the model to emit valid JSON — for callers that parse
        the response into a structured schema (overview generation, notebook
        auto-titling)."""
        return await self._generate(prompt, temperature=temperature, json_mode=True)

    async def generate_text(self, prompt: str, *, temperature: float = 0.3) -> str:
        """Free-form prose, no format constraint — for callers producing
        conversational text (chat answers) rather than structured data."""
        return await self._generate(prompt, temperature=temperature, json_mode=False)

    async def _generate(self, prompt: str, *, temperature: float, json_mode: bool) -> str:
        try:
            response = await self._client.chat(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                format="json" if json_mode else None,
                options={"temperature": temperature, "num_ctx": self._num_ctx},
            )
        except ConnectionError as exc:
            raise OllamaUnreachableError(str(exc)) from exc
        except httpx.TimeoutException as exc:
            raise OllamaTimeoutError(str(exc)) from exc
        return response["message"]["content"]
