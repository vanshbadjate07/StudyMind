"""Hits a real local Ollama instance with the real `qwen2.5:3b` model. Marked
`real_ollama` so the default test run (which stubs Ollama for speed and
independence) doesn't touch it — run explicitly with:
    pytest tests/test_overview_integration.py -m real_ollama -v
Skipped automatically if Ollama isn't reachable, rather than failing the
whole suite in an environment without it installed."""

import json
import socket

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.db import Base
from app.models import Chunk, Document, DocumentStatus, Notebook, Overview, OverviewStatus
from app.services.overview_generation import generate_overview

FIXTURE_TEXT_LATER_PAGES = "gradient descent"  # only appears deep in the fixture text


def _ollama_reachable() -> bool:
    host = settings.ollama_host.replace("http://", "").replace("https://", "")
    hostname, _, port = host.partition(":")
    try:
        with socket.create_connection((hostname, int(port or 11434)), timeout=1):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.real_ollama


@pytest.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


@pytest.mark.skipif(not _ollama_reachable(), reason="Ollama not reachable at configured host")
async def test_real_ollama_produces_a_well_formed_overview_covering_the_whole_document(
    session: AsyncSession,
) -> None:
    notebook = Notebook(name="ML Notes")
    session.add(notebook)
    await session.flush()
    doc = Document(
        notebook_id=notebook.id,
        filename="ml-notes.pdf",
        file_path="/tmp/ml-notes.pdf",
        status=DocumentStatus.READY,
    )
    session.add(doc)
    await session.commit()
    await session.refresh(doc)
    document_id = doc.id

    # Large enough (>4000 chars) to force the map-reduce path — the later
    # "section" (gradient descent) must not be dropped by a naive truncation.
    early_section = (
        "Chapter 1: Introduction to Machine Learning. " * 40
        + "Supervised learning uses labeled data, unsupervised learning finds "
        "patterns without labels. " * 40
    )
    late_section = (
        "Chapter 5: Optimization. Training a model typically involves gradient "
        "descent, an iterative algorithm that adjusts parameters to minimize a "
        "loss function. " * 40
    )
    session.add(Chunk(document_id=document_id, chunk_index=0, text=early_section, page_number=1))
    session.add(Chunk(document_id=document_id, chunk_index=1, text=late_section, page_number=10))
    await session.commit()

    await generate_overview(notebook.id, session)

    result = await session.execute(select(Overview).where(Overview.notebook_id == notebook.id))
    row = result.scalar_one_or_none()
    assert row is not None
    assert row.status == OverviewStatus.READY, row.error_detail
    assert row.estimated_minutes is not None and row.estimated_minutes > 0

    topics = json.loads(row.topics_json)
    assert len(topics) > 0
    all_text = " ".join(t["title"] + " " + t["summary"] + " ".join(t["key_concepts"]) for t in topics)
    assert FIXTURE_TEXT_LATER_PAGES.lower() in all_text.lower() or "gradient" in all_text.lower(), (
        "Overview should reference content from later in the document, not just the start"
    )
