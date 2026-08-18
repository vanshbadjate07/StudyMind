import json
from pathlib import Path

import pytest
from pptx import Presentation as PptxPresentation
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.db import Base
from app.models import Chunk, Document, DocumentStatus, Notebook, Presentation, PresentationStatus
from app.schemas import PresentationGenerateRequest, PresentationStyle
from app.services.ollama_client import OllamaUnreachableError
from app.services.presentation_generation import generate_presentation


@pytest.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


@pytest.fixture(autouse=True)
def _isolated_presentations_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "presentations_dir", tmp_path)


class ScriptedClient:
    """Returns each response in order, one per call to generate_json."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls: list[str] = []

    async def generate_json(self, prompt: str, *, temperature: float = 0.2) -> str:
        self.calls.append(prompt)
        return self._responses.pop(0)


class UnreachableClient:
    async def generate_json(self, prompt: str, *, temperature: float = 0.2) -> str:
        raise OllamaUnreachableError("connection refused")


def _slide(layout: str = "bullets", **overrides) -> dict:
    base = {
        "layout": layout,
        "title": "A slide",
        "lines": [],
        "columns": [],
        "quote": None,
        "attribution": None,
        "nodes": [],
        "edges": [],
        "caption": None,
    }
    if layout == "bullets":
        base["lines"] = ["Point one", "Point two"]
    elif layout in ("two_column", "comparison"):
        base["columns"] = [
            {"heading": "Left", "lines": ["A"]},
            {"heading": "Right", "lines": ["B"]},
        ]
    elif layout == "quote":
        base["quote"] = "A memorable statement."
    elif layout == "diagram":
        base["nodes"] = [{"label": "Input"}, {"label": "Output"}]
        base["edges"] = [{"from_index": 0, "to_index": 1, "label": None}]
    base.update(overrides)
    return base


async def _create_notebook_with_ready_document(
    session: AsyncSession, chunk_texts: list[str], notebook_name: str = "Test Notebook"
) -> Notebook:
    notebook = Notebook(name=notebook_name)
    session.add(notebook)
    await session.flush()
    doc = Document(
        notebook_id=notebook.id,
        filename="notes.pdf",
        file_path="/tmp/notes.pdf",
        status=DocumentStatus.READY,
    )
    session.add(doc)
    await session.commit()
    await session.refresh(doc)
    for i, text in enumerate(chunk_texts):
        session.add(Chunk(document_id=doc.id, chunk_index=i, text=text, page_number=1))
    await session.commit()
    return notebook


async def _get_presentation_row(session: AsyncSession, notebook_id: str) -> Presentation | None:
    result = await session.execute(select(Presentation).where(Presentation.notebook_id == notebook_id))
    return result.scalar_one_or_none()


class TestGeneratePresentation:
    async def test_success_produces_ready_presentation_with_a_real_file(self, session: AsyncSession) -> None:
        notebook = await _create_notebook_with_ready_document(session, ["Some study content about biology."])
        notebook_id = notebook.id
        response = json.dumps({"slides": [_slide(title="Cells"), _slide(title="DNA")]})
        client = ScriptedClient([response])

        await generate_presentation(notebook_id, session, client)

        row = await _get_presentation_row(session, notebook_id)
        assert row.status == PresentationStatus.READY
        # 2 body slides + 1 deterministic title slide prepended
        assert row.slide_count == 3
        assert row.file_path is not None
        file_path = Path(row.file_path)
        assert file_path.exists()
        deck = PptxPresentation(str(file_path))
        assert len(deck.slides) == 3

    async def test_title_slide_uses_the_notebook_name(self, session: AsyncSession) -> None:
        notebook = await _create_notebook_with_ready_document(
            session, ["Some content."], notebook_name="Intro to Machine Learning"
        )
        notebook_id = notebook.id
        client = ScriptedClient([json.dumps({"slides": [_slide()]})])

        await generate_presentation(notebook_id, session, client)

        row = await _get_presentation_row(session, notebook_id)
        deck = PptxPresentation(str(row.file_path))
        first_slide_text = "\n".join(
            shape.text_frame.text for shape in deck.slides[0].shapes if shape.has_text_frame
        )
        assert "Intro to Machine Learning" in first_slide_text

    async def test_a_structurally_incomplete_slide_is_dropped_not_shown(self, session: AsyncSession) -> None:
        notebook = await _create_notebook_with_ready_document(session, ["Some content."])
        notebook_id = notebook.id
        response = json.dumps(
            {
                "slides": [
                    _slide(title="Good slide"),
                    _slide(layout="two_column", title="Broken", columns=[{"heading": "Only one", "lines": ["x"]}]),
                ]
            }
        )
        client = ScriptedClient([response])

        await generate_presentation(notebook_id, session, client)

        row = await _get_presentation_row(session, notebook_id)
        assert row.status == PresentationStatus.READY
        assert row.slide_count == 2  # title + the one good body slide, broken one dropped

    async def test_diagram_slide_with_no_nodes_is_dropped_not_shown(self, session: AsyncSession) -> None:
        notebook = await _create_notebook_with_ready_document(session, ["Some content."])
        notebook_id = notebook.id
        response = json.dumps(
            {
                "slides": [
                    _slide(title="Good slide"),
                    _slide(layout="diagram", title="Empty diagram", nodes=[], edges=[]),
                ]
            }
        )
        client = ScriptedClient([response])

        await generate_presentation(notebook_id, session, client)

        row = await _get_presentation_row(session, notebook_id)
        assert row.status == PresentationStatus.READY
        assert row.slide_count == 2  # title + the one good body slide, empty diagram dropped

    async def test_diagram_slide_with_out_of_range_edge_still_renders(self, session: AsyncSession) -> None:
        """An edge referencing a node index that doesn't exist shouldn't sink
        the whole slide — build_diagram_svg already skips that one edge
        silently, so the slide (and its valid nodes) still renders."""
        notebook = await _create_notebook_with_ready_document(session, ["Some content."])
        notebook_id = notebook.id
        response = json.dumps(
            {
                "slides": [
                    _slide(
                        layout="diagram",
                        title="Diagram with a bad edge",
                        nodes=[{"label": "A"}, {"label": "B"}],
                        edges=[{"from_index": 0, "to_index": 99, "label": None}],
                    )
                ]
            }
        )
        client = ScriptedClient([response])

        await generate_presentation(notebook_id, session, client)

        row = await _get_presentation_row(session, notebook_id)
        assert row.status == PresentationStatus.READY
        assert row.slide_count == 2  # title + the diagram slide

    async def test_creates_the_presentation_row_itself_when_none_exists_yet(self, session: AsyncSession) -> None:
        notebook = await _create_notebook_with_ready_document(session, ["Some content."])
        notebook_id = notebook.id
        assert await _get_presentation_row(session, notebook_id) is None
        client = ScriptedClient([json.dumps({"slides": [_slide()]})])

        await generate_presentation(notebook_id, session, client)

        assert await _get_presentation_row(session, notebook_id) is not None

    async def test_ollama_unreachable_marks_presentation_failed(self, session: AsyncSession) -> None:
        notebook = await _create_notebook_with_ready_document(session, ["Some content."])
        notebook_id = notebook.id

        await generate_presentation(notebook_id, session, UnreachableClient())

        row = await _get_presentation_row(session, notebook_id)
        assert row.status == PresentationStatus.FAILED
        assert row.error_reason == "llm_unreachable"

    async def test_invalid_llm_response_marks_presentation_failed_after_retrying(
        self, session: AsyncSession
    ) -> None:
        notebook = await _create_notebook_with_ready_document(session, ["Some content."])
        notebook_id = notebook.id
        client = ScriptedClient(["not json", "still not json"])

        await generate_presentation(notebook_id, session, client)

        row = await _get_presentation_row(session, notebook_id)
        assert row.status == PresentationStatus.FAILED
        assert row.error_reason == "invalid_llm_response"
        assert len(client.calls) == 2  # MAX_RETRIES

    async def test_retries_once_and_succeeds_on_the_second_attempt(self, session: AsyncSession) -> None:
        notebook = await _create_notebook_with_ready_document(session, ["Some content."])
        notebook_id = notebook.id
        good = json.dumps({"slides": [_slide()]})
        client = ScriptedClient(["not json", good])

        await generate_presentation(notebook_id, session, client)

        row = await _get_presentation_row(session, notebook_id)
        assert row.status == PresentationStatus.READY

    async def test_slide_count_is_capped_at_the_requested_target(self, session: AsyncSession) -> None:
        notebook = await _create_notebook_with_ready_document(session, ["Some content."])
        notebook_id = notebook.id
        response = json.dumps({"slides": [_slide(title=f"S{i}") for i in range(6)]})
        client = ScriptedClient([response])

        await generate_presentation(
            notebook_id, session, client, options=PresentationGenerateRequest(slide_count=5)
        )

        row = await _get_presentation_row(session, notebook_id)
        assert row.slide_count == 5  # 4 body slides (capped) + 1 title

    async def test_default_slide_count_matches_the_settings_default(self, session: AsyncSession) -> None:
        notebook = await _create_notebook_with_ready_document(session, ["Some content."])
        notebook_id = notebook.id
        response = json.dumps({"slides": [_slide(title=f"S{i}") for i in range(12)]})
        client = ScriptedClient([response])

        await generate_presentation(notebook_id, session, client)

        row = await _get_presentation_row(session, notebook_id)
        assert row.slide_count == 10  # PresentationGenerateRequest's default slide_count

    async def test_style_and_focus_reach_the_prompt(self, session: AsyncSession) -> None:
        notebook = await _create_notebook_with_ready_document(session, ["Some content."])
        notebook_id = notebook.id
        client = ScriptedClient([json.dumps({"slides": [_slide()]})])

        await generate_presentation(
            notebook_id,
            session,
            client,
            options=PresentationGenerateRequest(style=PresentationStyle.EXAM_FOCUSED, focus="chapter 3"),
        )

        prompt = client.calls[0].lower()
        assert "most likely to be tested" in prompt  # exam-focused clause
        assert "focus especially on: chapter 3" in prompt

    async def test_style_and_focus_are_persisted_on_the_row(self, session: AsyncSession) -> None:
        notebook = await _create_notebook_with_ready_document(session, ["Some content."])
        notebook_id = notebook.id
        client = ScriptedClient([json.dumps({"slides": [_slide()]})])

        await generate_presentation(
            notebook_id,
            session,
            client,
            options=PresentationGenerateRequest(style=PresentationStyle.VISUAL_HEAVY, focus="neural nets"),
        )

        row = await _get_presentation_row(session, notebook_id)
        assert row.style == "visual_heavy"
        assert row.focus == "neural nets"

    async def test_combines_chunks_from_multiple_documents_in_the_notebook(self, session: AsyncSession) -> None:
        notebook = Notebook(name="Test Notebook")
        session.add(notebook)
        await session.flush()
        doc_a = Document(
            notebook_id=notebook.id, filename="a.pdf", file_path="/tmp/a.pdf", status=DocumentStatus.READY
        )
        doc_b = Document(
            notebook_id=notebook.id, filename="b.pdf", file_path="/tmp/b.pdf", status=DocumentStatus.READY
        )
        session.add_all([doc_a, doc_b])
        await session.commit()
        await session.refresh(doc_a)
        await session.refresh(doc_b)
        session.add(Chunk(document_id=doc_a.id, chunk_index=0, text="unique-marker-from-a", page_number=1))
        session.add(Chunk(document_id=doc_b.id, chunk_index=0, text="unique-marker-from-b", page_number=1))
        await session.commit()
        notebook_id = notebook.id

        client = ScriptedClient([json.dumps({"slides": [_slide()]})])

        await generate_presentation(notebook_id, session, client)

        assert "unique-marker-from-a" in client.calls[0]
        assert "unique-marker-from-b" in client.calls[0]
        row = await _get_presentation_row(session, notebook_id)
        assert row.status == PresentationStatus.READY

    async def test_notebook_with_no_ready_documents_fails_with_no_content(self, session: AsyncSession) -> None:
        notebook = Notebook(name="Empty Notebook")
        session.add(notebook)
        await session.commit()
        await session.refresh(notebook)
        notebook_id = notebook.id
        client = ScriptedClient([])

        await generate_presentation(notebook_id, session, client)

        row = await _get_presentation_row(session, notebook_id)
        assert row.status == PresentationStatus.FAILED
        assert row.error_reason == "no_content"
