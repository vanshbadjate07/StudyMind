import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.routers.notebooks as notebooks_module
from app.services.vector_store import get_vector_store

FIXTURES = Path(__file__).parent / "fixtures"


def _create_notebook(client: TestClient, name: str | None = None) -> str:
    body = {"name": name} if name else {}
    response = client.post("/notebooks", json=body)
    assert response.status_code == 201
    return response.json()["id"]


def _upload(client: TestClient, notebook_id: str, fixture_name: str, content_type: str = "application/pdf"):
    data = (FIXTURES / fixture_name).read_bytes()
    return client.post(
        f"/notebooks/{notebook_id}/documents", files={"file": (fixture_name, data, content_type)}
    )


def _poll_until_settled(client: TestClient, document_id: str, timeout_s: float = 10.0) -> dict:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        body = client.get(f"/documents/{document_id}").json()
        if body["status"] in ("ready", "failed"):
            return body
        time.sleep(0.05)
    raise TimeoutError(f"document {document_id} never settled")


class TestNotebookCrud:
    def test_create_notebook_defaults_to_untitled(self, client: TestClient) -> None:
        response = client.post("/notebooks", json={})
        assert response.status_code == 201
        body = response.json()
        assert body["name"] == "Untitled Notebook"
        assert body["goal_type"] is None

    def test_create_notebook_with_a_name(self, client: TestClient) -> None:
        response = client.post("/notebooks", json={"name": "Learning Python"})
        assert response.json()["name"] == "Learning Python"

    def test_list_notebooks(self, client: TestClient) -> None:
        _create_notebook(client, "Python")
        _create_notebook(client, "Biology")

        response = client.get("/notebooks")

        assert response.status_code == 200
        names = {n["name"] for n in response.json()["notebooks"]}
        assert names == {"Python", "Biology"}

    def test_get_missing_notebook_404(self, client: TestClient) -> None:
        assert client.get("/notebooks/does-not-exist").status_code == 404

    def test_rename_notebook(self, client: TestClient) -> None:
        notebook_id = _create_notebook(client, "Old Name")

        response = client.patch(f"/notebooks/{notebook_id}", json={"name": "New Name"})

        assert response.status_code == 200
        assert response.json()["name"] == "New Name"

    def test_rename_missing_notebook_404(self, client: TestClient) -> None:
        response = client.patch("/notebooks/does-not-exist", json={"name": "X"})
        assert response.status_code == 404


class TestNotebookGoal:
    def test_set_goal_with_preset_type(self, client: TestClient) -> None:
        notebook_id = _create_notebook(client)

        response = client.post(f"/notebooks/{notebook_id}/goal", json={"goal_type": "skill"})

        assert response.status_code == 200
        assert response.json()["goal_type"] == "skill"

    def test_set_goal_with_custom_description(self, client: TestClient) -> None:
        notebook_id = _create_notebook(client)

        response = client.post(
            f"/notebooks/{notebook_id}/goal",
            json={"goal_type": "custom", "goal_description": "Preparing for a MongoDB certification"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["goal_type"] == "custom"
        assert body["goal_description"] == "Preparing for a MongoDB certification"

    def test_set_goal_rejects_invalid_goal_type(self, client: TestClient) -> None:
        notebook_id = _create_notebook(client)

        response = client.post(f"/notebooks/{notebook_id}/goal", json={"goal_type": "not-a-real-type"})

        assert response.status_code == 422

    def test_set_goal_missing_notebook_404(self, client: TestClient) -> None:
        response = client.post("/notebooks/does-not-exist/goal", json={"goal_type": "exam"})
        assert response.status_code == 404


class TestNotebookDelete:
    def test_delete_notebook_cascades_documents_and_vectors(
        self, client: TestClient, tmp_path: Path
    ) -> None:
        notebook_id = _create_notebook(client)
        upload_response = _upload(client, notebook_id, "normal.pdf")
        document_id = upload_response.json()["id"]
        _poll_until_settled(client, document_id)
        assert (tmp_path / "uploads" / document_id).exists()

        delete_response = client.delete(f"/notebooks/{notebook_id}")

        assert delete_response.status_code == 204
        assert client.get(f"/notebooks/{notebook_id}").status_code == 404
        assert client.get(f"/documents/{document_id}").status_code == 404
        assert get_vector_store().count_for_document(document_id) == 0
        # Not just the DB rows and vectors — the on-disk file must be gone too.
        assert not (tmp_path / "uploads" / document_id).exists()

    def test_delete_notebook_with_no_documents(self, client: TestClient) -> None:
        notebook_id = _create_notebook(client)

        response = client.delete(f"/notebooks/{notebook_id}")

        assert response.status_code == 204
        assert client.get(f"/notebooks/{notebook_id}").status_code == 404

    def test_delete_missing_notebook_404(self, client: TestClient) -> None:
        assert client.delete("/notebooks/does-not-exist").status_code == 404


class TestNotebookUpload:
    def test_upload_requires_an_existing_notebook(self, client: TestClient) -> None:
        data = (FIXTURES / "normal.pdf").read_bytes()
        response = client.post(
            "/notebooks/does-not-exist/documents",
            files={"file": ("normal.pdf", data, "application/pdf")},
        )
        assert response.status_code == 404

    def test_upload_normal_pdf_ends_up_ready(self, client: TestClient) -> None:
        notebook_id = _create_notebook(client)

        response = _upload(client, notebook_id, "normal.pdf")

        assert response.status_code == 201
        body = response.json()
        assert body["notebook_id"] == notebook_id
        settled = _poll_until_settled(client, body["id"])
        assert settled["status"] == "ready"
        assert settled["chunk_count"] > 0

    @pytest.mark.parametrize(
        ("fixture_name", "expected_reason"),
        [
            ("empty.pdf", "empty_document"),
            ("blank_page.pdf", "no_extractable_text"),
            ("corrupted.pdf", "invalid_pdf"),
            ("password.pdf", "password_protected"),
            ("scanned.pdf", "scanned_or_image_only"),
        ],
    )
    def test_upload_bad_fixture_ends_up_failed_with_reason(
        self, client: TestClient, fixture_name: str, expected_reason: str
    ) -> None:
        notebook_id = _create_notebook(client)

        response = _upload(client, notebook_id, fixture_name)
        document_id = response.json()["id"]

        settled = _poll_until_settled(client, document_id)
        assert settled["status"] == "failed"
        assert settled["error_reason"] == expected_reason

    def test_upload_rejects_non_pdf_extension(self, client: TestClient) -> None:
        notebook_id = _create_notebook(client)
        response = client.post(
            f"/notebooks/{notebook_id}/documents",
            files={"file": ("notes.txt", b"just some text", "text/plain")},
        )
        assert response.status_code == 400

    def test_upload_rejects_content_that_is_not_actually_a_pdf(self, client: TestClient) -> None:
        notebook_id = _create_notebook(client)
        response = _upload(client, notebook_id, "not_a_pdf.pdf")
        assert response.status_code == 400

    def test_upload_rejects_oversized_file(self, client: TestClient, monkeypatch) -> None:
        monkeypatch.setattr(notebooks_module.settings, "max_upload_bytes", 1024)
        notebook_id = _create_notebook(client)
        oversized = b"%PDF-1.4\n" + (b"0" * 2048)

        response = client.post(
            f"/notebooks/{notebook_id}/documents",
            files={"file": ("huge.pdf", oversized, "application/pdf")},
        )

        assert response.status_code == 413

    def test_upload_rejects_path_traversal_in_filename(self, client: TestClient, tmp_path: Path) -> None:
        notebook_id = _create_notebook(client)
        data = (FIXTURES / "normal.pdf").read_bytes()
        malicious_name = "../../evil.pdf"

        response = client.post(
            f"/notebooks/{notebook_id}/documents",
            files={"file": (malicious_name, data, "application/pdf")},
        )

        assert response.status_code == 201
        document_id = response.json()["id"]

        assert not (tmp_path / "evil.pdf").exists()
        assert (tmp_path / "uploads" / document_id / "source.pdf").exists()
        assert response.json()["filename"] != malicious_name

    def test_upload_ignores_absolute_path_in_filename(self, client: TestClient, tmp_path: Path) -> None:
        notebook_id = _create_notebook(client)
        data = (FIXTURES / "normal.pdf").read_bytes()
        absolute_target = tmp_path / "absolute_target_evil.pdf"
        malicious_name = str(absolute_target)

        response = client.post(
            f"/notebooks/{notebook_id}/documents",
            files={"file": (malicious_name, data, "application/pdf")},
        )

        assert response.status_code == 201
        document_id = response.json()["id"]

        assert not absolute_target.exists()
        assert (tmp_path / "uploads" / document_id / "source.pdf").exists()


class TestNotebookDocumentList:
    def test_list_documents_scoped_to_notebook(self, client: TestClient) -> None:
        notebook_a = _create_notebook(client, "A")
        notebook_b = _create_notebook(client, "B")
        _upload(client, notebook_a, "normal.pdf")
        _upload(client, notebook_a, "single_page.pdf")
        _upload(client, notebook_b, "normal.pdf")

        response = client.get(f"/notebooks/{notebook_a}/documents")

        assert response.status_code == 200
        assert len(response.json()["documents"]) == 2

    def test_list_documents_missing_notebook_404(self, client: TestClient) -> None:
        assert client.get("/notebooks/does-not-exist/documents").status_code == 404
