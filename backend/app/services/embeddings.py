"""Embeddings, provider-swappable the same way the LLM client is.

    Local   sentence-transformers (all-MiniLM-L6-v2), fully offline. The
            default, and what development and the test suite use.
    Gemini  Google's embedding API, free tier. For deployments on hosts too
            small to run torch: a free 512MB container cannot load the local
            model, but it can call out.

Unlike the LLM client, the provider is chosen by an EXPLICIT setting
(`STUDYMIND_EMBEDDING_PROVIDER`), never inferred from which API keys happen
to be configured. The difference matters: LLM calls are stateless, so
silently switching providers is harmless — but embeddings are compared
against vectors already stored in Chroma, and two models' vectors are
mutually meaningless. A developer with a Gemini key in .env must not have
their local vector store silently poisoned by auto-switching. Changing this
setting on an existing deployment effectively orphans its stored vectors;
re-upload documents after switching.

Everything downstream (vector_store, answer scoring) calls `embed_texts`
and never learns which provider ran, so this file is the single switch
point.
"""

import logging
import math
from functools import lru_cache
from typing import Protocol

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class EmbeddingError(Exception):
    """No configured embedding backend could produce vectors."""


class EmbeddingClient(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class LocalEmbedder:
    """sentence-transformers, imported lazily: a slim deployment that uses
    the Gemini provider does not install torch at all, and a module-level
    import would crash the whole app there rather than just this path."""

    @staticmethod
    @lru_cache(maxsize=1)
    def _get_model():  # noqa: ANN205 - sentence_transformers may not be installed
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise EmbeddingError(
                "The local embedding provider needs sentence-transformers, which "
                "is not installed in this environment. Install the full "
                "requirements.txt, or set STUDYMIND_EMBEDDING_PROVIDER=gemini "
                "with a Gemini API key."
            ) from exc
        return SentenceTransformer(settings.embedding_model_name)

    def embed(self, texts: list[str]) -> list[list[float]]:
        model = self._get_model()
        vectors = model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
        return vectors.tolist()


class GeminiEmbedder:
    """Google's embedding API, over REST with a key list tried in order,
    the same multi-key pattern as the LLM chain and Whisper client."""

    # The API caps batchEmbedContents at 100 items per call.
    MAX_BATCH = 100

    def __init__(self, api_keys: tuple[str, ...] | None = None) -> None:
        keys = api_keys if api_keys is not None else settings.gemini_api_keys
        self._api_keys = tuple(key for key in keys if key)
        if not self._api_keys:
            raise EmbeddingError(
                "STUDYMIND_EMBEDDING_PROVIDER is 'gemini' but no Gemini API key "
                "is configured. Set STUDYMIND_GEMINI_API_KEYS."
            )
        self._model = settings.gemini_embedding_model
        self._dimensions = settings.gemini_embedding_dimensions
        self._timeout = settings.embedding_timeout_seconds

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.MAX_BATCH):
            vectors.extend(self._embed_batch(texts[start : start + self.MAX_BATCH]))
        return vectors

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        last_error: Exception | None = None
        for index, key in enumerate(self._api_keys):
            try:
                return self._embed_with_key(key, texts)
            except EmbeddingError as exc:
                logger.warning("Gemini embedding key #%d failed: %s", index + 1, exc)
                last_error = exc
        raise EmbeddingError(
            f"All {len(self._api_keys)} Gemini keys failed to embed; last error: {last_error}"
        )

    def _embed_with_key(self, key: str, texts: list[str]) -> list[list[float]]:
        payload = {
            "requests": [
                {
                    "model": f"models/{self._model}",
                    "content": {"parts": [{"text": text}]},
                    "outputDimensionality": self._dimensions,
                }
                for text in texts
            ]
        }
        try:
            response = httpx.post(
                "https://generativelanguage.googleapis.com/v1beta/"
                f"models/{self._model}:batchEmbedContents",
                params={"key": key},
                json=payload,
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            raise EmbeddingError(str(exc)) from exc

        if response.status_code >= 400:
            raise EmbeddingError(f"HTTP {response.status_code}: {response.text[:200]}")

        try:
            raw = [item["values"] for item in response.json()["embeddings"]]
        except (KeyError, ValueError) as exc:
            raise EmbeddingError(f"unexpected response shape: {exc}") from exc
        if len(raw) != len(texts):
            raise EmbeddingError(f"asked for {len(texts)} embeddings, got {len(raw)}")

        # Normalized to unit length, matching what the local provider emits.
        # Google only guarantees unit vectors at the model's full
        # dimensionality; at a truncated outputDimensionality they are not,
        # and every distance threshold downstream assumes unit vectors.
        return [_normalize(vector) for vector in raw]


def _normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0.0:
        return vector
    return [value / norm for value in vector]


@lru_cache(maxsize=1)
def _get_client() -> EmbeddingClient:
    if settings.embedding_provider == "gemini":
        return GeminiEmbedder()
    return LocalEmbedder()


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    return _get_client().embed(texts)
