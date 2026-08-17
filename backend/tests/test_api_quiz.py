import json
import time
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import Quiz, QuizStatus

FIXTURES = Path(__file__).parent / "fixtures"


class _FakeReadyClient:
    def __init__(self, question_count: int = 1) -> None:
        self._question_count = question_count

    async def generate_json(self, prompt: str, *, temperature: float = 0.2) -> str:
        questions = [
            {
                "question": f"Question {i}?",
                "options": ["A", "B", "C", "D"],
                "correct_index": i % 4,
                "explanation": "Because.",
            }
            for i in range(self._question_count)
        ]
        return json.dumps({"questions": questions})


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


def _poll_quiz_settled(client: TestClient, notebook_id: str, timeout_s: float = 10.0) -> dict:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        response = client.get(f"/notebooks/{notebook_id}/quiz")
        if response.status_code == 404:
            time.sleep(0.05)
            continue
        body = response.json()
        if body["status"] in ("ready", "failed"):
            return body
        time.sleep(0.05)
    raise TimeoutError(f"quiz for notebook {notebook_id} never settled")


def test_get_quiz_404_when_notebook_missing(client: TestClient) -> None:
    response = client.get("/notebooks/does-not-exist/quiz")
    assert response.status_code == 404


def test_get_quiz_404_before_any_generation(client: TestClient) -> None:
    notebook_id = _create_notebook(client)
    response = client.get(f"/notebooks/{notebook_id}/quiz")
    assert response.status_code == 404


def test_generate_quiz_missing_notebook_404(client: TestClient) -> None:
    response = client.post("/notebooks/does-not-exist/quiz/generate")
    assert response.status_code == 404


def test_generate_quiz_requires_a_ready_document(client: TestClient) -> None:
    notebook_id = _create_notebook(client)
    document_id = _upload(client, notebook_id, "corrupted.pdf")
    _poll_document_settled(client, document_id)

    response = client.post(f"/notebooks/{notebook_id}/quiz/generate")
    assert response.status_code == 409


def test_generate_quiz_fails_cleanly_without_ollama(client: TestClient) -> None:
    notebook_id = _create_notebook(client)
    document_id = _upload(client, notebook_id, "normal.pdf")
    _poll_document_settled(client, document_id)

    response = client.post(f"/notebooks/{notebook_id}/quiz/generate")
    assert response.status_code == 202

    # conftest's autouse stub means no real Ollama is reachable here — the
    # important thing is the quiz pipeline still resolves cleanly.
    quiz = _poll_quiz_settled(client, notebook_id)
    assert quiz["status"] == "failed"
    assert quiz["error_reason"] == "ollama_unreachable"
    assert client.get(f"/documents/{document_id}").json()["status"] == "ready"


def test_generate_quiz_ready_with_questions_when_llm_succeeds(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.quiz_generation.OllamaClient", lambda *a, **k: _FakeReadyClient(question_count=3)
    )

    notebook_id = _create_notebook(client)
    document_id = _upload(client, notebook_id, "normal.pdf")
    _poll_document_settled(client, document_id)

    response = client.post(f"/notebooks/{notebook_id}/quiz/generate")
    assert response.status_code == 202

    quiz = _poll_quiz_settled(client, notebook_id)
    assert quiz["status"] == "ready"
    assert len(quiz["questions"]) == 3
    assert quiz["questions"][0]["question"] == "Question 0?"
    assert quiz["questions"][0]["options"] == ["A", "B", "C", "D"]


async def test_generate_quiz_returns_409_when_already_generating(client: TestClient) -> None:
    """TestClient runs background tasks to completion synchronously before a
    request returns, so a real concurrent request can't land mid-generation
    here — instead, force a Quiz row into GENERATING directly (as if a
    background run were still in flight) and confirm the endpoint's guard
    rejects a second generate rather than racing it."""
    notebook_id = _create_notebook(client)
    document_id = _upload(client, notebook_id, "normal.pdf")
    _poll_document_settled(client, document_id)
    client.post(f"/notebooks/{notebook_id}/quiz/generate")
    _poll_quiz_settled(client, notebook_id)

    async with client.test_session_factory() as session:
        result = await session.execute(select(Quiz).where(Quiz.notebook_id == notebook_id))
        quiz = result.scalar_one()
        quiz.status = QuizStatus.GENERATING
        await session.commit()

    response = client.post(f"/notebooks/{notebook_id}/quiz/generate")
    assert response.status_code == 409


def test_regenerating_after_failure_can_succeed(client: TestClient, monkeypatch) -> None:
    notebook_id = _create_notebook(client)
    document_id = _upload(client, notebook_id, "normal.pdf")
    _poll_document_settled(client, document_id)

    first_response = client.post(f"/notebooks/{notebook_id}/quiz/generate")
    assert first_response.status_code == 202
    first = _poll_quiz_settled(client, notebook_id)
    assert first["status"] == "failed"

    monkeypatch.setattr(
        "app.services.quiz_generation.OllamaClient", lambda *a, **k: _FakeReadyClient(question_count=2)
    )

    second_response = client.post(f"/notebooks/{notebook_id}/quiz/generate")
    assert second_response.status_code == 202

    second = _poll_quiz_settled(client, notebook_id)
    assert second["status"] == "ready"
    assert len(second["questions"]) == 2


async def test_deleting_notebook_removes_its_quiz(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr("app.services.quiz_generation.OllamaClient", lambda *a, **k: _FakeReadyClient())

    notebook_id = _create_notebook(client)
    document_id = _upload(client, notebook_id, "normal.pdf")
    _poll_document_settled(client, document_id)
    client.post(f"/notebooks/{notebook_id}/quiz/generate")
    _poll_quiz_settled(client, notebook_id)

    delete_response = client.delete(f"/notebooks/{notebook_id}")
    assert delete_response.status_code == 204

    async with client.test_session_factory() as session:
        result = await session.execute(select(Quiz).where(Quiz.notebook_id == notebook_id))
        assert result.scalar_one_or_none() is None
