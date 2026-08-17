import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.db as db_module
from app.migrations import migrate_documents_notebook_column, migrate_overview_to_notebook_scope
from app.models import Document, Notebook, Overview, OverviewStatus


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


@pytest.fixture
async def pre_overview_migration_db(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Simulates a real pre-migration database: an `overviews` table in the
    old per-document shape (no `notebook_id` column) with an existing row,
    created without ever importing the current ORM model."""
    db_path = tmp_path / "legacy_overview.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as conn:
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
        await conn.execute(
            text(
                """
                CREATE TABLE overviews (
                    id VARCHAR(36) PRIMARY KEY,
                    document_id VARCHAR(36) NOT NULL UNIQUE,
                    status VARCHAR(20) NOT NULL DEFAULT 'pending',
                    topics_json TEXT,
                    estimated_minutes INTEGER,
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
            text("INSERT INTO overviews (id, document_id, status) VALUES (:id, :document_id, 'ready')"),
            {"id": legacy_id, "document_id": str(uuid.uuid4())},
        )

    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module, "async_session_factory", factory)

    yield {"legacy_overview_id": legacy_id, "session_factory": factory}
    await engine.dispose()


async def test_overview_migration_adds_column_and_clears_legacy_rows(pre_overview_migration_db) -> None:
    await migrate_overview_to_notebook_scope()

    async with pre_overview_migration_db["session_factory"]() as session:
        result = await session.execute(select(Overview))
        assert result.scalars().all() == []


async def test_overview_migration_is_a_noop_on_an_already_migrated_database(
    pre_overview_migration_db,
) -> None:
    await migrate_overview_to_notebook_scope()
    await migrate_overview_to_notebook_scope()  # must not error the second time

    async with pre_overview_migration_db["session_factory"]() as session:
        result = await session.execute(select(Overview))
        assert result.scalars().all() == []


async def test_overview_migration_recovers_from_crash_after_rename_before_create(
    pre_overview_migration_db,
) -> None:
    """Regression test: if the process is killed right after `overviews` is
    renamed to `overviews_legacy` but before the new `overviews` table is
    created, a restart must still finish the migration rather than treating
    the (now-missing) `overviews` table as some unrecognized state."""
    async with db_module.engine.begin() as conn:
        await conn.execute(text("ALTER TABLE overviews RENAME TO overviews_legacy"))
    # No new `overviews` table exists yet — simulates the crash window.

    await migrate_overview_to_notebook_scope()

    async with db_module.engine.begin() as conn:
        result = await conn.execute(text("PRAGMA table_info(overviews)"))
        columns = {row[1] for row in result.fetchall()}
        assert "notebook_id" in columns
        assert "document_id" not in columns

        legacy_exists = await conn.execute(
            text("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'overviews_legacy'")
        )
        assert legacy_exists.first() is None

        index_exists = await conn.execute(
            text("SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = 'ix_overviews_notebook_id'")
        )
        assert index_exists.first() is not None


async def test_overview_migration_recovers_from_crash_after_create_before_drop(
    pre_overview_migration_db,
) -> None:
    """Regression test: if the process is killed after the new `overviews`
    table (and its unique index) are created but before `overviews_legacy`
    is dropped, a restart must still clean up the legacy table rather than
    leaving it lingering forever."""
    async with db_module.engine.begin() as conn:
        await conn.execute(text("ALTER TABLE overviews RENAME TO overviews_legacy"))
    async with db_module.engine.begin() as conn:
        await conn.execute(
            text(
                """
                CREATE TABLE overviews (
                    id VARCHAR(36) NOT NULL,
                    notebook_id VARCHAR(36) NOT NULL,
                    status VARCHAR(10) NOT NULL,
                    topics_json TEXT,
                    estimated_minutes INTEGER,
                    error_reason VARCHAR(64),
                    error_detail TEXT,
                    created_at DATETIME DEFAULT (CURRENT_TIMESTAMP) NOT NULL,
                    updated_at DATETIME DEFAULT (CURRENT_TIMESTAMP) NOT NULL,
                    PRIMARY KEY (id),
                    FOREIGN KEY(notebook_id) REFERENCES notebooks (id) ON DELETE CASCADE
                )
                """
            )
        )
        await conn.execute(
            text("CREATE UNIQUE INDEX IF NOT EXISTS ix_overviews_notebook_id ON overviews (notebook_id)")
        )
    # `overviews_legacy` still exists here — simulates the crash window before it's dropped.

    await migrate_overview_to_notebook_scope()

    async with db_module.engine.begin() as conn:
        legacy_exists = await conn.execute(
            text("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'overviews_legacy'")
        )
        assert legacy_exists.first() is None

        result = await conn.execute(text("PRAGMA table_info(overviews)"))
        columns = {row[1] for row in result.fetchall()}
        assert "notebook_id" in columns


async def test_overview_migration_leaves_notebook_scoped_rows_alone(pre_overview_migration_db) -> None:
    await migrate_overview_to_notebook_scope()

    async with pre_overview_migration_db["session_factory"]() as session:
        notebook = Notebook(name="Test")
        session.add(notebook)
        await session.flush()
        session.add(Overview(notebook_id=notebook.id, status=OverviewStatus.PENDING))
        await session.commit()

        result = await session.execute(select(Overview))
        rows = result.scalars().all()
        assert len(rows) == 1
        assert rows[0].notebook_id == notebook.id
        # Regression check: the rebuilt table's created_at/updated_at columns
        # must carry the same DEFAULT CURRENT_TIMESTAMP that create_all()
        # generates from the model's server_default=func.now() — a
        # hand-written CREATE TABLE that drops the DEFAULT clause would leave
        # these NULL on every insert that (like the ORM) relies on it.
        assert rows[0].created_at is not None
        assert rows[0].updated_at is not None


async def test_overview_migration_on_a_fresh_database_is_a_noop(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'fresh_overview.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(db_module.Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module, "async_session_factory", factory)

    await migrate_overview_to_notebook_scope()  # must not raise on a table that already has the column

    await engine.dispose()
