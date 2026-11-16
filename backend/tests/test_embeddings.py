"""Tests for the embedding provider switch.

The local path is exercised implicitly by the whole retrieval suite; these
cover the switching logic and the Gemini client's contract, offline, against
a mocked transport.
"""

import httpx
import pytest

from app.config import settings
from app.services import embeddings
from app.services.embeddings import EmbeddingError, GeminiEmbedder, LocalEmbedder, _get_client


@pytest.fixture(autouse=True)
def _clear_provider_cache():
    _get_client.cache_clear()
    yield
    _get_client.cache_clear()


def _mock_transport(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    transport = httpx.MockTransport(handler)
    real_post = httpx.post

    def patched_post(url, **kwargs):
        with httpx.Client(transport=transport) as client:
            return client.post(url, **{k: v for k, v in kwargs.items() if k != "timeout"})

    monkeypatch.setattr(httpx, "post", patched_post)
    assert real_post is not patched_post


def test_local_is_the_default_provider() -> None:
    assert settings.embedding_provider == "local"
    assert isinstance(_get_client(), LocalEmbedder)


def test_gemini_is_selected_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "embedding_provider", "gemini")
    monkeypatch.setattr(settings, "gemini_api_keys", ("key-1",))
    assert isinstance(_get_client(), GeminiEmbedder)


def test_gemini_without_a_key_fails_with_an_actionable_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "gemini_api_keys", ())
    with pytest.raises(EmbeddingError) as excinfo:
        GeminiEmbedder()
    assert "STUDYMIND_GEMINI_API_KEYS" in str(excinfo.value)


def test_gemini_embeds_and_normalizes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Vectors come back unit-length even though the API's truncated output
    is not: every distance threshold downstream assumes unit vectors, same
    as the local provider's normalize_embeddings=True."""
    monkeypatch.setattr(settings, "gemini_api_keys", ("key-1",))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"embeddings": [{"values": [3.0, 4.0]}]})

    _mock_transport(monkeypatch, handler)
    [vector] = GeminiEmbedder().embed(["some text"])
    assert vector == pytest.approx([0.6, 0.8])


def test_gemini_tries_the_next_key_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "gemini_api_keys", ("key-1", "key-2"))
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        key = request.url.params["key"]
        seen.append(key)
        if key == "key-1":
            return httpx.Response(429, text="quota")
        return httpx.Response(200, json={"embeddings": [{"values": [1.0, 0.0]}]})

    _mock_transport(monkeypatch, handler)
    assert GeminiEmbedder().embed(["text"]) == [[1.0, 0.0]]
    assert seen == ["key-1", "key-2"]


def test_gemini_splits_oversized_batches(monkeypatch: pytest.MonkeyPatch) -> None:
    """The API caps a batch call at 100 items; a notebook with more chunks
    than that must not fail its whole upload over the cap."""
    monkeypatch.setattr(settings, "gemini_api_keys", ("key-1",))
    batch_sizes: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        count = len(json.loads(request.content)["requests"])
        batch_sizes.append(count)
        return httpx.Response(200, json={"embeddings": [{"values": [1.0, 0.0]}] * count})

    _mock_transport(monkeypatch, handler)
    vectors = GeminiEmbedder().embed(["text"] * 250)
    assert len(vectors) == 250
    assert batch_sizes == [100, 100, 50]


def test_gemini_rejects_a_count_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "gemini_api_keys", ("key-1",))
    _mock_transport(
        monkeypatch,
        lambda request: httpx.Response(200, json={"embeddings": [{"values": [1.0]}]}),
    )
    with pytest.raises(EmbeddingError) as excinfo:
        GeminiEmbedder().embed(["one", "two"])
    assert "asked for 2" in str(excinfo.value)


def test_missing_local_dependency_is_an_actionable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A slim deployment without torch must fail the local path with advice,
    not an ImportError traceback."""
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "sentence_transformers":
            raise ImportError("not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    LocalEmbedder._get_model.cache_clear()
    with pytest.raises(EmbeddingError) as excinfo:
        LocalEmbedder().embed(["text"])
    assert "STUDYMIND_EMBEDDING_PROVIDER=gemini" in str(excinfo.value)
    LocalEmbedder._get_model.cache_clear()


def test_empty_input_calls_no_provider() -> None:
    assert embeddings.embed_texts([]) == []
