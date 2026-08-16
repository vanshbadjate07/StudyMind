import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.db as db_module
import app.routers.documents as documents_module
from app.main import app
from app.services.vector_store import get_vector_store

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    test_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    test_factory = async_sessionmaker(test_engine, expire_on_commit=False)

    monkeypatch.setattr(db_module, "engine", test_engine)
    monkeypatch.setattr(db_module, "async_session_factory", test_factory)
    monkeypatch.setattr(documents_module, "async_session_factory", test_factory)

    uploads_dir = tmp_path / "uploads"
    uploads_dir.mkdir()
    monkeypatch.setattr(documents_module.settings, "uploads_dir", uploads_dir)
    monkeypatch.setattr(documents_module.settings, "chroma_dir", tmp_path / "chroma")
    monkeypatch.setattr(documents_module.settings, "chroma_collection_name", f"test_{tmp_path.name}")

    get_vector_store.cache_clear()
    with TestClient(app) as test_client:
        yield test_client
    get_vector_store.cache_clear()


def _upload(client: TestClient, fixture_name: str, content_type: str = "application/pdf"):
    data = (FIXTURES / fixture_name).read_bytes()
    return client.post("/documents", files={"file": (fixture_name, data, content_type)})


def _poll_until_settled(client: TestClient, document_id: str, timeout_s: float = 10.0) -> dict:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        body = client.get(f"/documents/{document_id}").json()
        if body["status"] in ("ready", "failed"):
            return body
        time.sleep(0.05)
    raise TimeoutError(f"document {document_id} never settled")


def test_upload_normal_pdf_ends_up_ready(client: TestClient) -> None:
    response = _upload(client, "normal.pdf")
    assert response.status_code == 201
    document_id = response.json()["id"]
    assert response.json()["status"] in ("pending", "processing", "ready")

    settled = _poll_until_settled(client, document_id)

    assert settled["status"] == "ready"
    assert settled["chunk_count"] > 0
    assert settled["page_count"] == 3


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
    client: TestClient, fixture_name: str, expected_reason: str
) -> None:
    response = _upload(client, fixture_name)
    assert response.status_code == 201
    document_id = response.json()["id"]

    settled = _poll_until_settled(client, document_id)

    assert settled["status"] == "failed"
    assert settled["error_reason"] == expected_reason


def test_upload_rejects_non_pdf_extension(client: TestClient) -> None:
    response = client.post(
        "/documents", files={"file": ("notes.txt", b"just some text", "text/plain")}
    )
    assert response.status_code == 400


def test_upload_rejects_content_that_is_not_actually_a_pdf(client: TestClient) -> None:
    response = _upload(client, "not_a_pdf.pdf", content_type="application/pdf")
    assert response.status_code == 400


def test_upload_rejects_oversized_file(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(documents_module.settings, "max_upload_bytes", 1024)
    oversized = b"%PDF-1.4\n" + (b"0" * 2048)

    response = client.post(
        "/documents", files={"file": ("huge.pdf", oversized, "application/pdf")}
    )

    assert response.status_code == 413


def test_list_documents_returns_uploaded_documents(client: TestClient) -> None:
    _upload(client, "normal.pdf")
    _upload(client, "single_page.pdf")

    response = client.get("/documents")

    assert response.status_code == 200
    assert len(response.json()["documents"]) == 2


def test_get_missing_document_returns_404(client: TestClient) -> None:
    response = client.get("/documents/does-not-exist")
    assert response.status_code == 404


def test_delete_document_removes_file_db_row_and_vectors(client: TestClient) -> None:
    upload_response = _upload(client, "normal.pdf")
    document_id = upload_response.json()["id"]
    settled = _poll_until_settled(client, document_id)
    assert settled["status"] == "ready"

    delete_response = client.delete(f"/documents/{document_id}")
    assert delete_response.status_code == 204

    assert client.get(f"/documents/{document_id}").status_code == 404
    assert get_vector_store().count_for_document(document_id) == 0


def test_delete_missing_document_returns_404_not_a_crash(client: TestClient) -> None:
    response = client.delete("/documents/does-not-exist")
    assert response.status_code == 404


def test_upload_rejects_path_traversal_in_filename(client: TestClient, tmp_path: Path) -> None:
    data = (FIXTURES / "normal.pdf").read_bytes()
    malicious_name = "../../evil.pdf"

    response = client.post("/documents", files={"file": (malicious_name, data, "application/pdf")})

    assert response.status_code == 201
    document_id = response.json()["id"]

    assert not (tmp_path / "evil.pdf").exists()
    assert (tmp_path / "uploads" / document_id / "source.pdf").exists()
    assert response.json()["filename"] != malicious_name


def test_upload_ignores_absolute_path_in_filename(client: TestClient, tmp_path: Path) -> None:
    data = (FIXTURES / "normal.pdf").read_bytes()
    absolute_target = tmp_path / "absolute_target_evil.pdf"
    malicious_name = str(absolute_target)

    response = client.post("/documents", files={"file": (malicious_name, data, "application/pdf")})

    assert response.status_code == 201
    document_id = response.json()["id"]

    assert not absolute_target.exists()
    assert (tmp_path / "uploads" / document_id / "source.pdf").exists()
