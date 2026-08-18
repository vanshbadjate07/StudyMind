import json
import time
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import Presentation, PresentationStatus

FIXTURES = Path(__file__).parent / "fixtures"


class _FakeReadyClient:
    def __init__(self, slide_count: int = 1) -> None:
        self._slide_count = slide_count
        self.prompts: list[str] = []

    async def generate_json(self, prompt: str, *, temperature: float = 0.2) -> str:
        self.prompts.append(prompt)
        slides = [
            {
                "layout": "bullets",
                "title": f"Slide {i}",
                "lines": ["Point one", "Point two"],
                "columns": [],
                "quote": None,
                "attribution": None,
            }
            for i in range(self._slide_count)
        ]
        return json.dumps({"slides": slides})


def _create_notebook(client: TestClient, name: str = "Test Notebook") -> str:
    return client.post("/notebooks", json={"name": name}).json()["id"]


def _upload(client: TestClient, notebook_id: str, fixture_name: str) -> str:
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


def _poll_presentation_settled(client: TestClient, notebook_id: str, timeout_s: float = 10.0) -> dict:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        response = client.get(f"/notebooks/{notebook_id}/presentation")
        if response.status_code == 404:
            time.sleep(0.05)
            continue
        body = response.json()
        if body["status"] in ("ready", "failed"):
            return body
        time.sleep(0.05)
    raise TimeoutError(f"presentation for notebook {notebook_id} never settled")


def test_get_presentation_404_when_notebook_missing(client: TestClient) -> None:
    response = client.get("/notebooks/does-not-exist/presentation")
    assert response.status_code == 404


def test_get_presentation_404_before_any_generation(client: TestClient) -> None:
    notebook_id = _create_notebook(client)
    response = client.get(f"/notebooks/{notebook_id}/presentation")
    assert response.status_code == 404


def test_generate_presentation_missing_notebook_404(client: TestClient) -> None:
    response = client.post("/notebooks/does-not-exist/presentation/generate")
    assert response.status_code == 404


def test_generate_presentation_requires_a_ready_document(client: TestClient) -> None:
    notebook_id = _create_notebook(client)
    document_id = _upload(client, notebook_id, "corrupted.pdf")
    _poll_document_settled(client, document_id)

    response = client.post(f"/notebooks/{notebook_id}/presentation/generate")
    assert response.status_code == 409


def test_generate_presentation_fails_cleanly_without_ollama(client: TestClient) -> None:
    notebook_id = _create_notebook(client)
    document_id = _upload(client, notebook_id, "normal.pdf")
    _poll_document_settled(client, document_id)

    response = client.post(f"/notebooks/{notebook_id}/presentation/generate")
    assert response.status_code == 202

    presentation = _poll_presentation_settled(client, notebook_id)
    assert presentation["status"] == "failed"
    assert presentation["error_reason"] == "llm_unreachable"
    assert client.get(f"/documents/{document_id}").json()["status"] == "ready"


def test_generate_presentation_ready_when_llm_succeeds(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.llm_client.OllamaClient", lambda *a, **k: _FakeReadyClient(slide_count=3)
    )

    notebook_id = _create_notebook(client)
    document_id = _upload(client, notebook_id, "normal.pdf")
    _poll_document_settled(client, document_id)

    response = client.post(f"/notebooks/{notebook_id}/presentation/generate")
    assert response.status_code == 202

    presentation = _poll_presentation_settled(client, notebook_id)
    assert presentation["status"] == "ready"
    assert presentation["slide_count"] == 4  # 3 body slides + 1 title slide


def test_generate_presentation_passes_customization_options_to_the_prompt(client: TestClient, monkeypatch) -> None:
    fake = _FakeReadyClient(slide_count=5)
    monkeypatch.setattr("app.services.llm_client.OllamaClient", lambda *a, **k: fake)

    notebook_id = _create_notebook(client)
    document_id = _upload(client, notebook_id, "normal.pdf")
    _poll_document_settled(client, document_id)

    response = client.post(
        f"/notebooks/{notebook_id}/presentation/generate",
        json={"slide_count": 6, "style": "exam_focused", "focus": "neural networks"},
    )
    assert response.status_code == 202

    presentation = _poll_presentation_settled(client, notebook_id)
    assert presentation["status"] == "ready"

    # Document upload also triggers overview generation, which shares this
    # same patched client — pick out the presentation prompt by its own
    # content rather than assuming index 0.
    prompt = next(p for p in fake.prompts if "structuring a presentation" in p.lower()).lower()
    assert "5 body slides" in prompt  # slide_count (6) minus the title slide
    assert "most likely to be tested" in prompt  # exam-focused clause
    assert "focus especially on: neural networks" in prompt


def test_generate_presentation_rejects_out_of_range_slide_count(client: TestClient) -> None:
    notebook_id = _create_notebook(client)
    document_id = _upload(client, notebook_id, "normal.pdf")
    _poll_document_settled(client, document_id)

    response = client.post(f"/notebooks/{notebook_id}/presentation/generate", json={"slide_count": 2})
    assert response.status_code == 422


async def test_generate_presentation_returns_409_when_already_generating(client: TestClient) -> None:
    notebook_id = _create_notebook(client)
    document_id = _upload(client, notebook_id, "normal.pdf")
    _poll_document_settled(client, document_id)
    client.post(f"/notebooks/{notebook_id}/presentation/generate")
    _poll_presentation_settled(client, notebook_id)

    async with client.test_session_factory() as session:
        result = await session.execute(select(Presentation).where(Presentation.notebook_id == notebook_id))
        presentation = result.scalar_one()
        presentation.status = PresentationStatus.GENERATING
        await session.commit()

    response = client.post(f"/notebooks/{notebook_id}/presentation/generate")
    assert response.status_code == 409


def test_download_404_before_ready(client: TestClient) -> None:
    notebook_id = _create_notebook(client)
    response = client.get(f"/notebooks/{notebook_id}/presentation/download")
    assert response.status_code == 404


def test_download_returns_the_pptx_file_once_ready(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.llm_client.OllamaClient", lambda *a, **k: _FakeReadyClient(slide_count=2)
    )

    notebook_id = _create_notebook(client)
    document_id = _upload(client, notebook_id, "normal.pdf")
    _poll_document_settled(client, document_id)
    client.post(f"/notebooks/{notebook_id}/presentation/generate")
    _poll_presentation_settled(client, notebook_id)

    response = client.get(f"/notebooks/{notebook_id}/presentation/download")
    assert response.status_code == 200
    assert response.headers["content-type"] == (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    )
    assert len(response.content) > 0


async def test_deleting_notebook_removes_its_presentation(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr("app.services.llm_client.OllamaClient", lambda *a, **k: _FakeReadyClient())

    notebook_id = _create_notebook(client)
    document_id = _upload(client, notebook_id, "normal.pdf")
    _poll_document_settled(client, document_id)
    client.post(f"/notebooks/{notebook_id}/presentation/generate")
    _poll_presentation_settled(client, notebook_id)

    delete_response = client.delete(f"/notebooks/{notebook_id}")
    assert delete_response.status_code == 204

    async with client.test_session_factory() as session:
        result = await session.execute(select(Presentation).where(Presentation.notebook_id == notebook_id))
        assert result.scalar_one_or_none() is None
