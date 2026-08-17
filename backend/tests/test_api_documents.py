import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.services.vector_store import get_vector_store

FIXTURES = Path(__file__).parent / "fixtures"


def _create_notebook(client: TestClient) -> str:
    return client.post("/notebooks", json={}).json()["id"]


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


def test_get_document(client: TestClient) -> None:
    notebook_id = _create_notebook(client)
    document_id = _upload(client, notebook_id, "normal.pdf")

    response = client.get(f"/documents/{document_id}")

    assert response.status_code == 200
    assert response.json()["notebook_id"] == notebook_id


def test_get_missing_document_returns_404(client: TestClient) -> None:
    response = client.get("/documents/does-not-exist")
    assert response.status_code == 404


def test_delete_document_removes_file_db_row_and_vectors(client: TestClient, tmp_path: Path) -> None:
    notebook_id = _create_notebook(client)
    document_id = _upload(client, notebook_id, "normal.pdf")
    settled = _poll_until_settled(client, document_id)
    assert settled["status"] == "ready"
    assert (tmp_path / "uploads" / document_id).exists()

    delete_response = client.delete(f"/documents/{document_id}")
    assert delete_response.status_code == 204

    assert client.get(f"/documents/{document_id}").status_code == 404
    assert get_vector_store().count_for_document(document_id) == 0
    # Not just the DB row and vectors — the on-disk file must actually be gone.
    assert not (tmp_path / "uploads" / document_id).exists()


def test_delete_missing_document_returns_404_not_a_crash(client: TestClient) -> None:
    response = client.delete("/documents/does-not-exist")
    assert response.status_code == 404


def test_deleting_a_document_does_not_delete_its_notebook(client: TestClient) -> None:
    notebook_id = _create_notebook(client)
    document_id = _upload(client, notebook_id, "normal.pdf")

    client.delete(f"/documents/{document_id}")

    assert client.get(f"/notebooks/{notebook_id}").status_code == 200
