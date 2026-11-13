"""Speech to text for the voice interview (PRD 6.8).

Mirrors `llm_client`'s shape exactly: a Protocol, two interchangeable
implementations, and one resolver that picks between them from config. The
app's features never learn which one they're talking to.

    Cloud  GroqWhisperClient      free tier, no model download, fast on a
                                  free host's CPU-only tier
    Local  FasterWhisperClient    fully offline, no API key, native ARM64
                                  builds so it runs on Apple Silicon without
                                  Rosetta or CoreML tricks

Cloud is preferred when a Groq key is configured, because the deployed
target (a free container host) transcribes far faster by calling out than by
running a model on a shared CPU. With no key, local transcription keeps the
"everything free and self-hostable" promise intact.

faster-whisper is deliberately NOT in requirements.txt. It pulls in
ctranslate2 and av and downloads ~500MB of model weights on first use, which
is a heavy cost to impose on everyone installing the project when most
people will have a free Groq key set. It lives in requirements-voice.txt and
is imported lazily, so its absence is a clear error on the voice path only
rather than an import failure that takes the whole app down.
"""

import asyncio
import logging
from functools import lru_cache
from pathlib import Path
from typing import Protocol

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class TranscriptionError(Exception):
    """Raised when audio could not be turned into text. `reason` is a stable
    machine-readable code, same convention as the generation errors."""

    def __init__(self, reason: str, detail: str = "") -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}" if detail else reason)


class TranscriptionClient(Protocol):
    """Implemented by both clients, so either can be injected interchangeably
    and tests can pass a deterministic stub."""

    async def transcribe(self, audio: bytes, filename: str) -> str: ...


class GroqWhisperClient:
    """Groq's hosted Whisper, over the OpenAI-compatible audio endpoint.

    Takes a list of API keys and tries them in order, the same way
    `cloud_llm_client` does, so a second free account roughly doubles the
    daily quota rather than requiring a code change.
    """

    def __init__(
        self,
        api_keys: tuple[str, ...],
        model: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self._api_keys = tuple(key for key in api_keys if key)
        if not self._api_keys:
            raise ValueError("GroqWhisperClient needs at least one API key")
        self._model = model or settings.groq_whisper_model
        self._timeout = timeout if timeout is not None else settings.transcription_timeout_seconds

    async def transcribe(self, audio: bytes, filename: str) -> str:
        last_error: TranscriptionError | None = None
        for index, key in enumerate(self._api_keys):
            try:
                return await self._transcribe_with_key(key, audio, filename)
            except TranscriptionError as exc:
                # Keep trying the remaining keys on a quota or availability
                # failure; a bad-audio error would fail identically on every
                # key, so it is re-raised immediately rather than retried.
                if exc.reason == "invalid_audio":
                    raise
                logger.warning("Groq transcription key #%d failed: %s", index + 1, exc)
                last_error = exc
        # The last failure's reason is kept rather than flattened to
        # "unavailable": a timeout and an outage lead the user to different
        # actions ("record something shorter" vs "try again later"), and
        # collapsing them loses the only signal that distinguishes them.
        reason = last_error.reason if last_error is not None else "transcription_unavailable"
        raise TranscriptionError(
            reason, f"All {len(self._api_keys)} Groq keys failed; last error: {last_error}"
        )

    async def _transcribe_with_key(self, key: str, audio: bytes, filename: str) -> str:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    "https://api.groq.com/openai/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {key}"},
                    files={"file": (filename, audio, "application/octet-stream")},
                    data={"model": self._model, "response_format": "json"},
                )
        except httpx.TimeoutException as exc:
            raise TranscriptionError("transcription_timeout", str(exc)) from exc
        except httpx.HTTPError as exc:
            raise TranscriptionError("transcription_unavailable", str(exc)) from exc

        if response.status_code == 400:
            raise TranscriptionError("invalid_audio", response.text[:200])
        if response.status_code >= 400:
            raise TranscriptionError(
                "transcription_unavailable", f"HTTP {response.status_code}: {response.text[:200]}"
            )

        try:
            return response.json()["text"].strip()
        except (KeyError, ValueError) as exc:
            raise TranscriptionError("transcription_unavailable", f"unexpected response: {exc}") from exc


class FasterWhisperClient:
    """Local, offline transcription. The model is loaded once per process and
    reused; the first call downloads weights, which is why the voice UI warns
    about a slow first use when running locally."""

    def __init__(self, model_size: str | None = None) -> None:
        self._model_size = model_size or settings.whisper_model_size

    @staticmethod
    @lru_cache(maxsize=2)
    def _load_model(model_size: str):  # noqa: ANN205 - faster_whisper may not be installed
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise TranscriptionError(
                "transcription_unavailable",
                "Local transcription needs faster-whisper. Install it with "
                "`pip install -r requirements-voice.txt`, or set a Groq API key "
                "to transcribe in the cloud instead.",
            ) from exc
        # int8 on CPU: the only combination that runs at a usable speed on
        # both Apple Silicon and a free host's shared CPU, without a GPU.
        return WhisperModel(model_size, device="cpu", compute_type="int8")

    def _transcribe_sync(self, path: Path) -> str:
        model = self._load_model(self._model_size)
        try:
            segments, _info = model.transcribe(str(path), beam_size=1)
            return " ".join(segment.text for segment in segments).strip()
        except TranscriptionError:
            raise
        except Exception as exc:  # noqa: BLE001 - decode failures surface as invalid audio
            raise TranscriptionError("invalid_audio", str(exc)) from exc

    async def transcribe(self, audio: bytes, filename: str) -> str:
        import tempfile

        suffix = Path(filename).suffix or ".webm"
        # faster-whisper decodes from a path, not a buffer. The temp file is
        # written inside the thread-offloaded call so neither the write nor
        # the transcription blocks the event loop.
        def _run() -> str:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as handle:
                handle.write(audio)
                handle.flush()
                return self._transcribe_sync(Path(handle.name))

        return await asyncio.to_thread(_run)


def get_default_transcription_client() -> TranscriptionClient:
    """Cloud when a Groq key is configured, local otherwise. The single place
    that decides which backend transcribes, matching
    `get_default_llm_client`'s role for text generation."""
    if settings.groq_api_keys:
        return GroqWhisperClient(settings.groq_api_keys)
    return FasterWhisperClient()


def describe_backend() -> str:
    """Which backend will be used, for the UI to state plainly rather than
    leaving the user guessing why a first transcription is slow."""
    return "cloud" if settings.groq_api_keys else "local"
