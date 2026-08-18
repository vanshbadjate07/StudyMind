import httpx

from app.services.llm_errors import LLMTimeoutError, LLMUnreachableError


class LLMRateLimitedError(LLMUnreachableError):
    """The provider rejected the request for being rate-limited (HTTP 429).
    Subclasses LLMUnreachableError so a chain simply treats this the same as
    any other "move to the next provider" failure."""


class OpenAICompatibleProvider:
    """One cloud LLM provider speaking the OpenAI-compatible chat completions
    shape. Cerebras, Groq, and Gemini's compatibility endpoint all implement
    this same request/response format, so one implementation covers all
    three rather than writing bespoke per-provider parsing."""

    def __init__(self, name: str, base_url: str, api_key: str, model: str, timeout: float) -> None:
        self.name = name
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._timeout = timeout

    async def generate(self, prompt: str, *, temperature: float, json_mode: bool) -> str:
        payload: dict = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    f"{self._base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json=payload,
                )
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(f"{self.name}: {exc}") from exc
        except httpx.HTTPError as exc:
            raise LLMUnreachableError(f"{self.name}: {exc}") from exc

        if response.status_code == 429:
            raise LLMRateLimitedError(f"{self.name}: rate limited (429)")
        if response.status_code >= 400:
            raise LLMUnreachableError(f"{self.name}: HTTP {response.status_code}: {response.text[:200]}")

        try:
            return response.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError) as exc:
            raise LLMUnreachableError(f"{self.name}: unexpected response shape: {exc}") from exc


class ChainedLLMClient:
    """Same public interface as OllamaClient (generate_json/generate_text) so
    it's a drop-in replacement anywhere an LLM client is injected. Tries each
    configured provider in order and falls through to the next on any
    failure (rate limit, timeout, outage), so one provider being exhausted
    or down doesn't take the feature offline — only raises once every
    configured provider has failed."""

    def __init__(self, providers: list[OpenAICompatibleProvider]) -> None:
        if not providers:
            raise ValueError("ChainedLLMClient needs at least one provider")
        self._providers = providers

    async def generate_json(self, prompt: str, *, temperature: float = 0.2) -> str:
        return await self._generate(prompt, temperature=temperature, json_mode=True)

    async def generate_text(self, prompt: str, *, temperature: float = 0.3) -> str:
        return await self._generate(prompt, temperature=temperature, json_mode=False)

    async def _generate(self, prompt: str, *, temperature: float, json_mode: bool) -> str:
        last_error: Exception | None = None
        for provider in self._providers:
            try:
                return await provider.generate(prompt, temperature=temperature, json_mode=json_mode)
            except (LLMUnreachableError, LLMTimeoutError) as exc:
                last_error = exc
                continue
        raise LLMUnreachableError(
            f"All {len(self._providers)} configured LLM providers failed; last error: {last_error}"
        )
