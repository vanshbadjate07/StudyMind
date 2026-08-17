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


async def _table_exists(conn, name: str) -> bool:
    result = await conn.execute(
        text("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = :name"), {"name": name}
    )
    return result.first() is not None


async def migrate_overview_to_notebook_scope() -> None:
    """One-time schema patch: `overviews` moves from one row per document to
    one row per notebook (a notebook's overview is now synthesized across all
    of its documents, not generated separately for each). An overview is
    derived/regenerable content, not source material, so there's nothing to
    backfill — every notebook just gets a fresh combined overview the next
    time one of its documents is ready.

    The old `document_id` column was NOT NULL and UNIQUE, and SQLite refuses
    to `DROP COLUMN` a column carrying either constraint — so this can't be a
    simple ALTER TABLE like migrate_documents_notebook_column. Instead the
    table is rebuilt: the old table is renamed aside, a fresh `overviews`
    table is created in the new shape, and the old one is dropped (discarding
    its rows, per the plan above).

    Each step is independently idempotent so a crash at any point leaves the
    database in a state this function can still recover on the next startup:
    - rename old -> `overviews_legacy` (skipped if that name already exists,
      i.e. a previous run already got this far)
    - create the new `overviews` and its unique index (each skipped if it
      already exists, checked separately so a crash between the two still
      recovers correctly)
    - drop `overviews_legacy` (a no-op `DROP TABLE IF EXISTS` either way)
    A DB already in the final shape (fresh install via `create_all`, or an
    already-migrated one) short-circuits immediately.

    The table is deliberately created to match what `create_all()` generates
    from the `Overview` model exactly — same column defs, same
    `CREATE UNIQUE INDEX ix_overviews_notebook_id` (as its own statement,
    not an inline `UNIQUE` column constraint) — so a migrated database and a
    fresh-install database end up byte-for-byte equivalent in schema, not
    just equivalent in behavior. Verified by diffing this against
    `Base.metadata.create_all()`'s actual output.

    Must run after `init_db()`. No ordering dependency on
    `migrate_documents_notebook_column()` — they touch disjoint tables."""
    async with db.engine.begin() as conn:
        result = await conn.execute(text("PRAGMA table_info(overviews)"))
        columns = {row[1] for row in result.fetchall()}
        already_final_shape = "notebook_id" in columns and "document_id" not in columns
        legacy_table_exists = await _table_exists(conn, "overviews_legacy")

    if already_final_shape and not legacy_table_exists:
        return

    async with db.engine.begin() as conn:
        if not legacy_table_exists:
            await conn.execute(text("ALTER TABLE overviews RENAME TO overviews_legacy"))

    async with db.engine.begin() as conn:
        if not await _table_exists(conn, "overviews"):
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

    async with db.engine.begin() as conn:
        await conn.execute(
            text("CREATE UNIQUE INDEX IF NOT EXISTS ix_overviews_notebook_id ON overviews (notebook_id)")
        )

    async with db.engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS overviews_legacy"))
