import time
from pathlib import Path

from fastapi.testclient import TestClient

FIXTURES = Path(__file__).parent / "fixtures"


class _FakeTextClient:
    def __init__(self, text: str = "An answer.") -> None:
        self._text = text
        self.prompts: list[str] = []

    async def generate_text(self, prompt: str, *, temperature: float = 0.3) -> str:
        self.prompts.append(prompt)
        return self._text


def _create_notebook(client: TestClient, name: str = "Test Notebook") -> str:
    response = client.post("/notebooks", json={"name": name})
    assert response.status_code == 201
    return response.json()["id"]


def _upload(client: TestClient, notebook_id: str, fixture_name: str) -> str:
    data = (FIXTURES / fixture_name).read_bytes()
    response = client.post(
        f"/notebooks/{notebook_id}/documents", files={"file": (fixture_name, data, "application/pdf")}
    )
    return response.json()["id"]


def _poll_until_settled(client: TestClient, document_id: str, timeout_s: float = 10.0) -> dict:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        body = client.get(f"/documents/{document_id}").json()
        if body["status"] in ("ready", "failed"):
            return body
        time.sleep(0.05)
    raise TimeoutError(f"document {document_id} never settled")


def _ready_notebook(client: TestClient) -> str:
    notebook_id = _create_notebook(client)
    document_id = _upload(client, notebook_id, "normal.pdf")
    settled = _poll_until_settled(client, document_id)
    assert settled["status"] == "ready"
    return notebook_id


def test_grounded_question_returns_answer_with_citations(client: TestClient, monkeypatch) -> None:
    fake = _FakeTextClient("Backpropagation trains neural networks.")
    monkeypatch.setattr("app.services.chat.OllamaClient", lambda *a, **k: fake)
    notebook_id = _ready_notebook(client)

    response = client.post(
        f"/notebooks/{notebook_id}/chat/messages",
        json={"question": "How are neural networks trained?", "internet_mode": False},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["role"] == "assistant"
    assert body["content"] == "Backpropagation trains neural networks."
    assert body["grounded"] is True
    assert body["used_internet"] is False
    assert len(body["citations"]) > 0
    assert body["citations"][0]["filename"] == "normal.pdf"


def test_irrelevant_question_without_internet_mode_still_gets_a_real_answer(
    client: TestClient, monkeypatch
) -> None:
    # The LLM is always called now, even when nothing relevant was retrieved —
    # there's no fixed canned string anymore, so this must supply a fake
    # client rather than relying on the default (unreachable) stub.
    fake = _FakeTextClient("I don't see a pizza dough recipe in your material.")
    monkeypatch.setattr("app.services.chat.OllamaClient", lambda *a, **k: fake)
    notebook_id = _ready_notebook(client)

    response = client.post(
        f"/notebooks/{notebook_id}/chat/messages",
        json={"question": "What's the best pizza dough recipe?", "internet_mode": False},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["grounded"] is False
    assert body["used_internet"] is False
    assert body["content"] == "I don't see a pizza dough recipe in your material."


def test_irrelevant_question_with_internet_mode_answers_from_general_knowledge(
    client: TestClient, monkeypatch
) -> None:
    fake = _FakeTextClient("Pizza dough needs flour, water, yeast, and salt.")
    monkeypatch.setattr("app.services.chat.OllamaClient", lambda *a, **k: fake)
    notebook_id = _ready_notebook(client)

    response = client.post(
        f"/notebooks/{notebook_id}/chat/messages",
        json={"question": "What's the best pizza dough recipe?", "internet_mode": True},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["grounded"] is False
    assert body["used_internet"] is True
    assert body["content"] == "Pizza dough needs flour, water, yeast, and salt."


def test_ollama_unreachable_returns_503_but_keeps_the_users_question(client: TestClient) -> None:
    # Default stub (from conftest) raises OllamaUnreachableError — a relevant
    # question forces the grounded path, which actually calls it.
    notebook_id = _ready_notebook(client)

    response = client.post(
        f"/notebooks/{notebook_id}/chat/messages",
        json={"question": "How are neural networks trained?", "internet_mode": False},
    )

    assert response.status_code == 503

    history = client.get(f"/notebooks/{notebook_id}/chat/messages").json()["messages"]
    assert len(history) == 1
    assert history[0]["role"] == "user"
    assert history[0]["content"] == "How are neural networks trained?"


def test_ask_question_missing_notebook_404(client: TestClient) -> None:
    response = client.post(
        "/notebooks/does-not-exist/chat/messages", json={"question": "Hi?", "internet_mode": False}
    )
    assert response.status_code == 404


def test_list_messages_missing_notebook_404(client: TestClient) -> None:
    response = client.get("/notebooks/does-not-exist/chat/messages")
    assert response.status_code == 404


def test_list_messages_returns_conversation_in_order(client: TestClient, monkeypatch) -> None:
    fake = _FakeTextClient("An answer.")
    monkeypatch.setattr("app.services.chat.OllamaClient", lambda *a, **k: fake)
    notebook_id = _ready_notebook(client)

    client.post(
        f"/notebooks/{notebook_id}/chat/messages",
        json={"question": "First question?", "internet_mode": False},
    )
    client.post(
        f"/notebooks/{notebook_id}/chat/messages",
        json={"question": "Second question?", "internet_mode": False},
    )

    history = client.get(f"/notebooks/{notebook_id}/chat/messages").json()["messages"]
    assert [m["role"] for m in history] == ["user", "assistant", "user", "assistant"]
    assert history[0]["content"] == "First question?"
    assert history[2]["content"] == "Second question?"


def test_list_messages_empty_for_a_fresh_notebook(client: TestClient) -> None:
    notebook_id = _create_notebook(client)
    history = client.get(f"/notebooks/{notebook_id}/chat/messages").json()["messages"]
    assert history == []


def test_ask_question_rejects_empty_question(client: TestClient) -> None:
    notebook_id = _create_notebook(client)
    response = client.post(
        f"/notebooks/{notebook_id}/chat/messages", json={"question": "", "internet_mode": False}
    )
    assert response.status_code == 422


def test_edit_question_replaces_it_and_drops_everything_after(client: TestClient, monkeypatch) -> None:
    fake = _FakeTextClient("First answer.")
    monkeypatch.setattr("app.services.chat.OllamaClient", lambda *a, **k: fake)
    notebook_id = _ready_notebook(client)

    first = client.post(
        f"/notebooks/{notebook_id}/chat/messages",
        json={"question": "First question?", "internet_mode": False},
    ).json()
    user_message_id = client.get(f"/notebooks/{notebook_id}/chat/messages").json()["messages"][0]["id"]

    fake._text = "Edited answer."
    response = client.put(
        f"/notebooks/{notebook_id}/chat/messages/{user_message_id}",
        json={"question": "Edited question?", "internet_mode": False},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["content"] == "Edited answer."
    assert body["id"] != first["id"]

    history = client.get(f"/notebooks/{notebook_id}/chat/messages").json()["messages"]
    assert [m["content"] for m in history] == ["Edited question?", "Edited answer."]


def test_edit_question_missing_notebook_404(client: TestClient) -> None:
    response = client.put(
        "/notebooks/does-not-exist/chat/messages/does-not-exist",
        json={"question": "Hi?", "internet_mode": False},
    )
    assert response.status_code == 404


def test_edit_question_missing_message_404(client: TestClient) -> None:
    notebook_id = _create_notebook(client)
    response = client.put(
        f"/notebooks/{notebook_id}/chat/messages/does-not-exist",
        json={"question": "Hi?", "internet_mode": False},
    )
    assert response.status_code == 404


def test_edit_question_rejects_editing_an_assistant_message(client: TestClient, monkeypatch) -> None:
    fake = _FakeTextClient("An answer.")
    monkeypatch.setattr("app.services.chat.OllamaClient", lambda *a, **k: fake)
    notebook_id = _ready_notebook(client)

    client.post(
        f"/notebooks/{notebook_id}/chat/messages",
        json={"question": "A question?", "internet_mode": False},
    )
    assistant_message_id = client.get(f"/notebooks/{notebook_id}/chat/messages").json()["messages"][1]["id"]

    response = client.put(
        f"/notebooks/{notebook_id}/chat/messages/{assistant_message_id}",
        json={"question": "Trying to edit the answer instead", "internet_mode": False},
    )

    assert response.status_code == 400
