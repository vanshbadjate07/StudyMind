from typing import Protocol

from app.config import settings
from app.services.cloud_llm_client import ChainedLLMClient, OpenAICompatibleProvider
from app.services.ollama_client import OllamaClient


class LLMClient(Protocol):
    """Shared interface implemented by both OllamaClient and
    ChainedLLMClient — callers depend on this shape, not on either concrete
    class, so either one can be injected interchangeably."""

    async def generate_json(self, prompt: str, *, temperature: float = 0.2) -> str: ...

    async def generate_text(self, prompt: str, *, temperature: float = 0.3) -> str: ...


def _build_cloud_providers() -> list[OpenAICompatibleProvider]:
    """Only providers with an API key configured are included, in priority
    order: Cerebras first (largest free daily token budget, fastest
    inference), then Groq, then Gemini."""
    providers: list[OpenAICompatibleProvider] = []
    timeout = settings.llm_provider_timeout_seconds
    if settings.cerebras_api_key:
        providers.append(
            OpenAICompatibleProvider(
                "cerebras", "https://api.cerebras.ai/v1", settings.cerebras_api_key, settings.cerebras_model, timeout
            )
        )
    if settings.groq_api_key:
        providers.append(
            OpenAICompatibleProvider(
                "groq", "https://api.groq.com/openai/v1", settings.groq_api_key, settings.groq_model, timeout
            )
        )
    if settings.gemini_api_key:
        providers.append(
            OpenAICompatibleProvider(
                "gemini",
                "https://generativelanguage.googleapis.com/v1beta/openai",
                settings.gemini_api_key,
                settings.gemini_model,
                timeout,
            )
        )
    return providers


def get_default_llm_client(
    *, ollama_timeout: float | None = None, ollama_model: str | None = None, ollama_num_ctx: int | None = None
) -> ChainedLLMClient | OllamaClient:
    """Cloud provider chain when any provider API key is configured
    (production); local Ollama otherwise (local dev/CI, where no cloud keys
    are set in the environment). This is the single place that decides which
    backend a feature talks to — features themselves stay unaware of it.

    The ollama_* args only apply to the local-fallback path — the cloud
    chain's per-provider timeout always comes from
    settings.llm_provider_timeout_seconds, deliberately not overridable per
    feature, since the chain's fail-fast-and-try-the-next-provider behavior
    needs to stay independent of any one feature's overall timeout budget."""
    providers = _build_cloud_providers()
    if providers:
        return ChainedLLMClient(providers)
    return OllamaClient(model=ollama_model, timeout=ollama_timeout, num_ctx=ollama_num_ctx)
