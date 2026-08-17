import json
import time
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import Overview, OverviewStatus

FIXTURES = Path(__file__).parent / "fixtures"


class _FakeReadyClient:
    def __init__(self, title: str = "T", estimated_minutes: int = 5) -> None:
        self._title = title
        self._estimated_minutes = estimated_minutes

    async def generate_json(self, prompt: str, *, temperature: float = 0.2) -> str:
        return json.dumps(
            {
                "topics": [{"title": self._title, "summary": "s", "key_concepts": ["c"]}],
                "estimated_minutes": self._estimated_minutes,
            }
        )


def _upload(client: TestClient, fixture_name: str) -> str:
    """Creates a fresh notebook and uploads the fixture into it — these tests
    only care about document/overview behavior, not notebook identity."""
    notebook_id = client.post("/notebooks", json={}).json()["id"]
    data = (FIXTURES / fixture_name).read_bytes()
    response = client.post(
        f"/notebooks/{notebook_id}/documents", files={"file": (fixture_name, data, "application/pdf")}
    )
    return response.json()["id"]


def _poll_document_settled(client: TestClient, document_id: str, timeout_s: float = 10.0) -> dict:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        body = client.get(f"/documents/{document_id}").json()
        if body["status"] in ("ready", "failed"):
            return body
        time.sleep(0.05)
    raise TimeoutError(f"document {document_id} never settled")


def _poll_overview_settled(client: TestClient, document_id: str, timeout_s: float = 10.0) -> dict:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        response = client.get(f"/documents/{document_id}/overview")
        if response.status_code == 404:
            time.sleep(0.05)
            continue
        body = response.json()
        if body["status"] in ("ready", "failed"):
            return body
        time.sleep(0.05)
    raise TimeoutError(f"overview for {document_id} never settled")


def test_overview_starts_automatically_and_fails_cleanly_without_ollama(client: TestClient) -> None:
    document_id = _upload(client, "normal.pdf")
    _poll_document_settled(client, document_id)

    # conftest's autouse stub means no real Ollama is reachable here — the
    # important thing is the overview pipeline still resolves cleanly and
    # Document.status is unaffected.
    overview = _poll_overview_settled(client, document_id)
    assert overview["status"] == "failed"
    assert overview["error_reason"] == "ollama_unreachable"
    assert client.get(f"/documents/{document_id}").json()["status"] == "ready"


def test_overview_ready_with_topics_when_llm_succeeds(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.overview_generation.OllamaClient", lambda *a, **k: _FakeReadyClient()
    )

    document_id = _upload(client, "normal.pdf")
    _poll_document_settled(client, document_id)
    overview = _poll_overview_settled(client, document_id)

    assert overview["status"] == "ready"
    assert overview["topics"][0]["title"] == "T"
    assert overview["estimated_minutes"] == 5


def test_get_overview_404_when_document_missing(client: TestClient) -> None:
    response = client.get("/documents/does-not-exist/overview")
    assert response.status_code == 404


def test_get_overview_404_when_document_never_reached_ready(client: TestClient) -> None:
    # A document that fails processing never reaches READY, so no Overview
    # row is ever created for it.
    document_id = _upload(client, "corrupted.pdf")
    _poll_document_settled(client, document_id)

    response = client.get(f"/documents/{document_id}/overview")
    assert response.status_code == 404


def test_regenerate_overview_requires_document_ready(client: TestClient) -> None:
    document_id = _upload(client, "corrupted.pdf")
    _poll_document_settled(client, document_id)

    response = client.post(f"/documents/{document_id}/overview/regenerate")
    assert response.status_code == 409


async def test_regenerate_overview_returns_409_when_already_generating(client: TestClient) -> None:
    """TestClient runs background tasks to completion synchronously before a
    request returns, so a real concurrent request can't land mid-generation
    here — instead, force an Overview row into GENERATING directly (as if a
    background run were still in flight) and confirm the endpoint's guard
    rejects a second regenerate rather than racing it."""
    document_id = _upload(client, "normal.pdf")
    _poll_document_settled(client, document_id)
    _poll_overview_settled(client, document_id)

    async with client.test_session_factory() as session:
        result = await session.execute(select(Overview).where(Overview.document_id == document_id))
        overview = result.scalar_one()
        overview.status = OverviewStatus.GENERATING
        await session.commit()

    response = client.post(f"/documents/{document_id}/overview/regenerate")
    assert response.status_code == 409


def test_regenerate_overview_missing_document_404(client: TestClient) -> None:
    response = client.post("/documents/does-not-exist/overview/regenerate")
    assert response.status_code == 404


def test_regenerate_overview_after_failure_can_succeed(client: TestClient, monkeypatch) -> None:
    document_id = _upload(client, "normal.pdf")
    _poll_document_settled(client, document_id)
    first = _poll_overview_settled(client, document_id)
    assert first["status"] == "failed"

    monkeypatch.setattr(
        "app.services.overview_generation.OllamaClient",
        lambda *a, **k: _FakeReadyClient(title="Recovered", estimated_minutes=8),
    )

    response = client.post(f"/documents/{document_id}/overview/regenerate")
    assert response.status_code == 202

    second = _poll_overview_settled(client, document_id)
    assert second["status"] == "ready"
    assert second["topics"][0]["title"] == "Recovered"


async def test_delete_document_also_removes_its_overview(client: TestClient) -> None:
    document_id = _upload(client, "normal.pdf")
    _poll_document_settled(client, document_id)
    _poll_overview_settled(client, document_id)

    delete_response = client.delete(f"/documents/{document_id}")
    assert delete_response.status_code == 204

    # Not just a 404 through the API (which would pass even if the Overview
    # row were orphaned, since the document-existence check runs first) —
    # confirm the row itself is actually gone from the database.
    async with client.test_session_factory() as session:
        result = await session.execute(select(Overview).where(Overview.document_id == document_id))
        assert result.scalar_one_or_none() is None
