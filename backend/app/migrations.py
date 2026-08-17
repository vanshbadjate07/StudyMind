from sqlalchemy import text

from app import db
from app.models import Notebook


async def migrate_documents_notebook_column() -> None:
    """One-time schema patch for pre-6.3 databases: adds Document.notebook_id
    if it's missing and backfills any existing documents into a default
    notebook, so upgrading doesn't strand or lose documents uploaded before
    notebooks existed. No Alembic yet — a narrow, idempotent patch is
    proportionate for the single column this project has needed to retrofit
    so far; revisit with a real migration tool if this pattern recurs.

    Adding the column and backfilling orphaned rows are two separate
    statements/transactions (SQLite auto-commits DDL, so they can't share
    one). If the process is killed between them, a restart must still finish
    the backfill — so idempotency is checked by "are there still NULL
    notebook_id rows," not by "does the column exist." Checking only the
    latter would silently and permanently strand any document caught mid-
    migration, which is exactly the "never lose the user's documents"
    guarantee this migration exists to uphold.

    Must run after `init_db()` — on a brand-new database, `create_all` already
    creates `documents` with `notebook_id` included, so the ALTER is a no-op
    and there are no rows to backfill.

    Accessed via the `db` module rather than `from app.db import engine,
    async_session_factory` so tests that monkeypatch `db.engine` /
    `db.async_session_factory` to a test database are respected here too."""
    async with db.engine.begin() as conn:
        result = await conn.execute(text("PRAGMA table_info(documents)"))
        columns = {row[1] for row in result.fetchall()}
        if "notebook_id" not in columns:
            await conn.execute(text("ALTER TABLE documents ADD COLUMN notebook_id VARCHAR(36)"))

    async with db.async_session_factory() as session:
        result = await session.execute(text("SELECT id FROM documents WHERE notebook_id IS NULL"))
        orphaned_ids = [row[0] for row in result.fetchall()]
        if not orphaned_ids:
            return

        notebook = Notebook(name="My Documents")
        session.add(notebook)
        await session.flush()
        await session.execute(
            text("UPDATE documents SET notebook_id = :notebook_id WHERE notebook_id IS NULL"),
            {"notebook_id": notebook.id},
        )
        await session.commit()
