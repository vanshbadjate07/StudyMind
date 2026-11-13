"""Tests for speech to text (PRD 6.8).

No real audio and no network: the clients are exercised against a mocked
HTTP transport and a stubbed model, the same way the LLM clients are, so the
suite stays fast and offline.
"""

import httpx
import pytest

from app.config import settings
from app.services import transcription
from app.services.transcription import (
    FasterWhisperClient,
    GroqWhisperClient,
    TranscriptionError,
    describe_backend,
    get_default_transcription_client,
)

AUDIO = b"fake-webm-bytes"


def _mock_transport(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    """Swaps httpx's transport so no request leaves the process."""
    transport = httpx.MockTransport(handler)
    original_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = transport
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)


# ---------------------------------------------------------------------------
# Backend resolution
# ---------------------------------------------------------------------------


def test_cloud_is_preferred_when_a_groq_key_is_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "groq_api_keys", ("key-1",))
    assert describe_backend() == "cloud"
    assert isinstance(get_default_transcription_client(), GroqWhisperClient)


def test_local_is_used_when_no_key_is_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "groq_api_keys", ())
    assert describe_backend() == "local"
    assert isinstance(get_default_transcription_client(), FasterWhisperClient)


def test_groq_client_refuses_to_be_built_without_a_key() -> None:
    with pytest.raises(ValueError):
        GroqWhisperClient(())


def test_blank_keys_are_ignored() -> None:
    with pytest.raises(ValueError):
        GroqWhisperClient(("", ""))


# ---------------------------------------------------------------------------
# Groq hosted Whisper
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_groq_returns_the_transcript(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer key-1"
        return httpx.Response(200, json={"text": "  a hash function computes an index  "})

    _mock_transport(monkeypatch, handler)
    client = GroqWhisperClient(("key-1",))

    assert await client.transcribe(AUDIO, "answer.webm") == "a hash function computes an index"


@pytest.mark.asyncio
async def test_groq_tries_the_next_key_when_one_is_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same multi-key behaviour as the LLM chain: a second free account
    roughly doubles the daily quota without a code change."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        key = request.headers["Authorization"].removeprefix("Bearer ")
        seen.append(key)
        if key == "key-1":
            return httpx.Response(429, text="rate limited")
        return httpx.Response(200, json={"text": "second key worked"})

    _mock_transport(monkeypatch, handler)
    client = GroqWhisperClient(("key-1", "key-2"))

    assert await client.transcribe(AUDIO, "answer.webm") == "second key worked"
    assert seen == ["key-1", "key-2"]


@pytest.mark.asyncio
async def test_groq_raises_once_every_key_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_transport(monkeypatch, lambda request: httpx.Response(500, text="boom"))
    client = GroqWhisperClient(("key-1", "key-2"))

    with pytest.raises(TranscriptionError) as excinfo:
        await client.transcribe(AUDIO, "answer.webm")
    assert excinfo.value.reason == "transcription_unavailable"


@pytest.mark.asyncio
async def test_bad_audio_is_not_retried_against_every_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Audio the provider rejects as unreadable will be rejected identically
    by every key, so burning the rest of the quota on it is pure waste."""
    attempts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(request.headers["Authorization"])
        return httpx.Response(400, text="could not decode audio")

    _mock_transport(monkeypatch, handler)
    client = GroqWhisperClient(("key-1", "key-2", "key-3"))

    with pytest.raises(TranscriptionError) as excinfo:
        await client.transcribe(AUDIO, "answer.webm")
    assert excinfo.value.reason == "invalid_audio"
    assert len(attempts) == 1


@pytest.mark.asyncio
async def test_groq_timeout_is_reported_as_a_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    _mock_transport(monkeypatch, handler)
    client = GroqWhisperClient(("key-1",))

    with pytest.raises(TranscriptionError) as excinfo:
        await client.transcribe(AUDIO, "answer.webm")
    assert excinfo.value.reason == "transcription_timeout"


@pytest.mark.asyncio
async def test_an_unexpected_response_shape_is_handled(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_transport(monkeypatch, lambda request: httpx.Response(200, json={"nope": 1}))
    client = GroqWhisperClient(("key-1",))

    with pytest.raises(TranscriptionError) as excinfo:
        await client.transcribe(AUDIO, "answer.webm")
    assert excinfo.value.reason == "transcription_unavailable"


# ---------------------------------------------------------------------------
# Local faster-whisper
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_local_client_says_how_to_install_when_faster_whisper_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The dependency is optional on purpose, so its absence has to produce
    an actionable message rather than an ImportError traceback."""

    def explode(model_size: str):
        raise TranscriptionError(
            "transcription_unavailable",
            "Local transcription needs faster-whisper. Install it with "
            "`pip install -r requirements-voice.txt`, or set a Groq API key "
            "to transcribe in the cloud instead.",
        )

    monkeypatch.setattr(FasterWhisperClient, "_load_model", staticmethod(explode))
    client = FasterWhisperClient()

    with pytest.raises(TranscriptionError) as excinfo:
        await client.transcribe(AUDIO, "answer.webm")
    assert "requirements-voice.txt" in excinfo.value.detail


@pytest.mark.asyncio
async def test_local_client_joins_the_segments(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeSegment:
        def __init__(self, text: str) -> None:
            self.text = text

    class FakeModel:
        def transcribe(self, path: str, beam_size: int = 1):
            return [FakeSegment("A hash function"), FakeSegment(" computes an index")], None

    monkeypatch.setattr(FasterWhisperClient, "_load_model", staticmethod(lambda size: FakeModel()))
    client = FasterWhisperClient()

    assert await client.transcribe(AUDIO, "answer.webm") == "A hash function  computes an index"


@pytest.mark.asyncio
async def test_local_decode_failure_is_reported_as_invalid_audio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeModel:
        def transcribe(self, path: str, beam_size: int = 1):
            raise RuntimeError("could not decode")

    monkeypatch.setattr(FasterWhisperClient, "_load_model", staticmethod(lambda size: FakeModel()))
    client = FasterWhisperClient()

    with pytest.raises(TranscriptionError) as excinfo:
        await client.transcribe(AUDIO, "answer.webm")
    assert excinfo.value.reason == "invalid_audio"


# ---------------------------------------------------------------------------
# The HTTP endpoint
# ---------------------------------------------------------------------------


class _StubTranscriber:
    def __init__(self, text: str = "a transcribed answer") -> None:
        self.text = text
        self.calls: list[tuple[bytes, str]] = []

    async def transcribe(self, audio: bytes, filename: str) -> str:
        self.calls.append((audio, filename))
        return self.text


def test_transcribe_endpoint_returns_the_text(client, monkeypatch: pytest.MonkeyPatch) -> None:
    stub = _StubTranscriber()
    monkeypatch.setattr(
        "app.routers.interview.get_default_transcription_client", lambda: stub
    )

    response = client.post(
        "/interview/transcribe", files={"file": ("answer.webm", AUDIO, "audio/webm")}
    )

    assert response.status_code == 200
    assert response.json()["text"] == "a transcribed answer"
    assert stub.calls == [(AUDIO, "answer.webm")]


def test_transcribe_endpoint_rejects_an_empty_recording(client) -> None:
    response = client.post("/interview/transcribe", files={"file": ("answer.webm", b"", "audio/webm")})
    assert response.status_code == 400


def test_transcribe_endpoint_rejects_an_oversized_recording(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(transcription.settings, "max_audio_bytes", 10)
    response = client.post(
        "/interview/transcribe", files={"file": ("answer.webm", b"x" * 50, "audio/webm")}
    )
    assert response.status_code == 413


def test_unreadable_audio_is_a_422_so_the_client_knows_not_to_retry(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Broken:
        async def transcribe(self, audio: bytes, filename: str) -> str:
            raise TranscriptionError("invalid_audio", "could not decode")

    monkeypatch.setattr("app.routers.interview.get_default_transcription_client", lambda: Broken())

    response = client.post(
        "/interview/transcribe", files={"file": ("answer.webm", AUDIO, "audio/webm")}
    )
    assert response.status_code == 422


def test_an_unavailable_backend_is_a_503_so_retrying_makes_sense(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Down:
        async def transcribe(self, audio: bytes, filename: str) -> str:
            raise TranscriptionError("transcription_unavailable", "all keys failed")

    monkeypatch.setattr("app.routers.interview.get_default_transcription_client", lambda: Down())

    response = client.post(
        "/interview/transcribe", files={"file": ("answer.webm", AUDIO, "audio/webm")}
    )
    assert response.status_code == 503


def test_voice_capability_reports_cloud_when_a_key_is_set(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "groq_api_keys", ("key-1",))
    body = client.get("/interview/meta/voice").json()
    assert body == {"available": True, "backend": "cloud", "detail": None}


def test_voice_capability_explains_how_to_enable_local_transcription(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Checked up front so the UI can hide voice mode, rather than failing
    after the user has already recorded an answer."""
    monkeypatch.setattr(settings, "groq_api_keys", ())
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "faster_whisper":
            raise ImportError("not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    body = client.get("/interview/meta/voice").json()
    assert body["available"] is False
    assert body["backend"] == "local"
    assert "requirements-voice.txt" in body["detail"]
