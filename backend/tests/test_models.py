import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db import Base
from app.models import Chunk, Document, DocumentStatus
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


async def test_create_document_defaults_to_pending(session: AsyncSession) -> None:
    doc = Document(filename="notes.pdf", file_path="/tmp/notes.pdf")
    session.add(doc)
    await session.commit()
    await session.refresh(doc)

    assert doc.status == DocumentStatus.PENDING
    assert doc.id
    assert doc.created_at is not None


async def test_document_read_schema_serializes_from_orm(session: AsyncSession) -> None:
    doc = Document(filename="notes.pdf", file_path="/tmp/notes.pdf", status=DocumentStatus.READY)
    session.add(doc)
    await session.commit()
    await session.refresh(doc)

    read = DocumentRead.model_validate(doc)

    assert read.filename == "notes.pdf"
    assert read.status == DocumentStatus.READY


async def test_deleting_document_cascades_chunks(session: AsyncSession) -> None:
    doc = Document(filename="notes.pdf", file_path="/tmp/notes.pdf")
    doc.chunks.append(Chunk(chunk_index=0, text="hello world", page_number=1))
    session.add(doc)
    await session.commit()
    doc_id = doc.id

    await session.delete(doc)
    await session.commit()

    result = await session.execute(select(Chunk).where(Chunk.document_id == doc_id))
    assert result.scalars().all() == []
