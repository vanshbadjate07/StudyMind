import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.db as db_module
from app.migrations import migrate_documents_notebook_column
from app.models import Document, Notebook


@pytest.fixture
async def pre_notebook_db(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Simulates a real pre-6.3 database: a `documents` table with no
    `notebook_id` column and an existing row, created without ever importing
    the current ORM model (which already declares notebook_id) — otherwise
    this fixture wouldn't actually reproduce the upgrade scenario."""
    db_path = tmp_path / "legacy.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                CREATE TABLE documents (
                    id VARCHAR(36) PRIMARY KEY,
                    filename VARCHAR(512) NOT NULL,
                    file_path VARCHAR(1024) NOT NULL,
                    status VARCHAR(20) NOT NULL DEFAULT 'ready',
                    page_count INTEGER,
                    char_count INTEGER,
                    chunk_count INTEGER,
                    error_reason VARCHAR(64),
                    error_detail TEXT,
                    created_at DATETIME,
                    updated_at DATETIME
                )
                """
            )
        )
        legacy_id = str(uuid.uuid4())
        await conn.execute(
            text(
                "INSERT INTO documents (id, filename, file_path, status) "
                "VALUES (:id, 'legacy.pdf', '/tmp/legacy.pdf', 'ready')"
            ),
            {"id": legacy_id},
        )
        # `notebooks` table doesn't exist yet either on a real pre-6.3 DB —
        # create_all handles that separately at startup; the migration under
        # test only concerns the documents.notebook_id column.
        await conn.execute(
            text(
                """
                CREATE TABLE notebooks (
                    id VARCHAR(36) PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    goal_type VARCHAR(20),
                    goal_description TEXT,
                    created_at DATETIME,
                    updated_at DATETIME
                )
                """
            )
        )

    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module, "async_session_factory", factory)

    yield {"legacy_document_id": legacy_id, "session_factory": factory}
    await engine.dispose()


async def test_migration_adds_column_and_backfills_existing_documents(pre_notebook_db) -> None:
    await migrate_documents_notebook_column()

    async with pre_notebook_db["session_factory"]() as session:
        document = await session.get(Document, pre_notebook_db["legacy_document_id"])
        assert document is not None
        assert document.notebook_id is not None

        notebook = await session.get(Notebook, document.notebook_id)
        assert notebook is not None
        assert notebook.name == "My Documents"


async def test_migration_is_a_noop_on_an_already_migrated_database(pre_notebook_db) -> None:
    await migrate_documents_notebook_column()
    async with pre_notebook_db["session_factory"]() as session:
        document = await session.get(Document, pre_notebook_db["legacy_document_id"])
        first_notebook_id = document.notebook_id

    await migrate_documents_notebook_column()  # must not error or reassign

    async with pre_notebook_db["session_factory"]() as session:
        document = await session.get(Document, pre_notebook_db["legacy_document_id"])
        assert document.notebook_id == first_notebook_id


async def test_migration_finishes_backfill_interrupted_after_the_column_was_added(
    pre_notebook_db,
) -> None:
    """Regression test for a real bug: adding the column and backfilling rows
    are two separate transactions (SQLite auto-commits DDL). If the process
    is killed between them, a restart must still finish the backfill rather
    than treating "column exists" as "fully migrated" — the earlier version
    of this check did exactly that and permanently orphaned any document
    caught mid-migration."""
    async with db_module.engine.begin() as conn:
        await conn.execute(text("ALTER TABLE documents ADD COLUMN notebook_id VARCHAR(36)"))
    # No backfill has run yet — notebook_id is NULL, simulating the crash window.

    await migrate_documents_notebook_column()

    async with pre_notebook_db["session_factory"]() as session:
        document = await session.get(Document, pre_notebook_db["legacy_document_id"])
        assert document is not None
        assert document.notebook_id is not None


async def test_migration_on_a_fresh_database_is_a_noop(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'fresh.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(db_module.Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module, "async_session_factory", factory)

    await migrate_documents_notebook_column()  # must not raise on a table that already has the column

    await engine.dispose()
