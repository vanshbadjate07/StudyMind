import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.db as db_module
import app.routers.notebooks as notebooks_module
from app.main import app
from app.services.llm_errors import LLMUnreachableError
from app.services.vector_store import get_vector_store


class _StubLLMClient:
    """Fast, network-free stand-in used everywhere except tests explicitly
    marked `real_ollama`, so the rest of the suite doesn't depend on Ollama
    being installed/running and doesn't pay real LLM latency. Document
    processing must remain fully testable without any LLM available, since
    overview generation failures are never allowed to affect it."""

    async def generate_json(self, prompt: str, *, temperature: float = 0.2) -> str:
        raise LLMUnreachableError("stub: no LLM backend used in this test")

    async def generate_text(self, prompt: str, *, temperature: float = 0.3) -> str:
        raise LLMUnreachableError("stub: no LLM backend used in this test")


@pytest.fixture(autouse=True)
def _stub_ollama_by_default(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> None:
    if "real_ollama" in request.keywords:
        return
    # All three services resolve their default client through
    # app.services.llm_client.get_default_llm_client(), which — with no
    # cloud provider API keys configured (true in tests) — constructs
    # OllamaClient. Patching it here, at its one source, covers all three
    # services in a single patch instead of one per service.
    monkeypatch.setattr(
        "app.services.llm_client.OllamaClient",
        lambda *args, **kwargs: _StubLLMClient(),
    )


@pytest.fixture
def client(tmp_path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Shared API test client: an isolated SQLite file + upload dir + Chroma
    collection per test. Only `db_module.engine`/`db_module.async_session_factory`
    need patching — every consumer (routers, background-task helpers, the
    startup migration) reads them via `from app import db` + `db.<name>` at
    call time rather than capturing a direct `from`-import, so a single patch
    point is enough. See app/main.py's lifespan comment for why that pattern
    matters here."""
    test_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    test_factory = async_sessionmaker(test_engine, expire_on_commit=False)

    monkeypatch.setattr(db_module, "engine", test_engine)
    monkeypatch.setattr(db_module, "async_session_factory", test_factory)

    uploads_dir = tmp_path / "uploads"
    uploads_dir.mkdir()
    monkeypatch.setattr(notebooks_module.settings, "uploads_dir", uploads_dir)
    monkeypatch.setattr(notebooks_module.settings, "chroma_dir", tmp_path / "chroma")
    monkeypatch.setattr(notebooks_module.settings, "chroma_collection_name", f"test_{tmp_path.name}")
    # Same shared settings singleton every service reads, so patching it here
    # (rather than per-service) keeps generated .pptx files out of the real
    # backend/data/presentations/ directory during test runs.
    monkeypatch.setattr(notebooks_module.settings, "presentations_dir", tmp_path / "presentations")

    get_vector_store.cache_clear()
    with TestClient(app) as test_client:
        test_client.test_session_factory = test_factory  # for tests that need to inspect the DB directly
        yield test_client
    get_vector_store.cache_clear()
