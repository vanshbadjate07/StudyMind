import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db import Base
from app.models import Chunk, Document, DocumentStatus, GoalType, Notebook
from app.schemas import DocumentRead


@pytest.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


async def _create_notebook(session: AsyncSession) -> Notebook:
    notebook = Notebook(name="Test Notebook")
    session.add(notebook)
    await session.commit()
    await session.refresh(notebook)
    return notebook


async def test_notebook_defaults_to_untitled_name_and_no_goal(session: AsyncSession) -> None:
    notebook = Notebook()
    session.add(notebook)
    await session.commit()
    await session.refresh(notebook)

    assert notebook.name == "Untitled"
    assert notebook.goal_type is None
    assert notebook.goal_description is None


async def test_setting_a_notebook_goal(session: AsyncSession) -> None:
    notebook = await _create_notebook(session)
    notebook.goal_type = GoalType.SKILL
    notebook.goal_description = "Learning Python"
    await session.commit()
    await session.refresh(notebook)

    assert notebook.goal_type == GoalType.SKILL
    assert notebook.goal_description == "Learning Python"


async def test_deleting_a_notebook_cascades_its_documents(session: AsyncSession) -> None:
    notebook = await _create_notebook(session)
    session.add(Document(notebook_id=notebook.id, filename="notes.pdf", file_path="/tmp/notes.pdf"))
    await session.commit()
    notebook_id = notebook.id

    await session.delete(notebook)
    await session.commit()

    result = await session.execute(select(Document).where(Document.notebook_id == notebook_id))
    assert result.scalars().all() == []


async def test_create_document_defaults_to_pending(session: AsyncSession) -> None:
    notebook = await _create_notebook(session)
    doc = Document(notebook_id=notebook.id, filename="notes.pdf", file_path="/tmp/notes.pdf")
    session.add(doc)
    await session.commit()
    await session.refresh(doc)

    assert doc.status == DocumentStatus.PENDING
    assert doc.id
    assert doc.created_at is not None


async def test_document_read_schema_serializes_from_orm(session: AsyncSession) -> None:
    notebook = await _create_notebook(session)
    doc = Document(
        notebook_id=notebook.id,
        filename="notes.pdf",
        file_path="/tmp/notes.pdf",
        status=DocumentStatus.READY,
    )
    session.add(doc)
    await session.commit()
    await session.refresh(doc)

    read = DocumentRead.model_validate(doc)

    assert read.filename == "notes.pdf"
    assert read.status == DocumentStatus.READY
    assert read.notebook_id == notebook.id


async def test_deleting_document_cascades_chunks(session: AsyncSession) -> None:
    notebook = await _create_notebook(session)
    doc = Document(notebook_id=notebook.id, filename="notes.pdf", file_path="/tmp/notes.pdf")
    doc.chunks.append(Chunk(chunk_index=0, text="hello world", page_number=1))
    session.add(doc)
    await session.commit()
    doc_id = doc.id

    await session.delete(doc)
    await session.commit()

    result = await session.execute(select(Chunk).where(Chunk.document_id == doc_id))
    assert result.scalars().all() == []
