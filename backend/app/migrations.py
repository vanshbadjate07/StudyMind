"""Schema management.

Alembic owns the schema (see `alembic/versions/`), which is what makes the
same codebase run on SQLite locally and Postgres when deployed. Everything
below exists to get an *existing* database safely onto that path.

Two of the three things here are legacy: hand-rolled SQLite patches written
before Alembic was introduced. They are kept, and still run on SQLite only,
because a database created before them must still be upgradable rather than
abandoned. They do nothing on a fresh install and nothing on Postgres, which
has no pre-Alembic history to carry.
"""

import logging

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from app import db
from app.config import BACKEND_DIR
from app.models import Notebook

logger = logging.getLogger(__name__)

# The revision representing the schema as it stood when Alembic was adopted.
# An existing database is stamped at this revision rather than having it run
# against it, because its tables already exist.
BASELINE_REVISION = "d13daf2fafda"


def _alembic_config() -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return config


def _is_sqlite() -> bool:
    return db.engine.dialect.name == "sqlite"


async def _has_table(name: str) -> bool:
    async with db.engine.begin() as conn:
        return await conn.run_sync(lambda sync_conn: inspect(sync_conn).has_table(name))


async def run_schema_migrations() -> None:
    """Brings the database to the current schema, whatever state it is in.

    Three cases, all handled without ever dropping or rewriting user data:

    1. **Fresh database.** No tables at all: Alembic runs from the baseline
       and creates everything.
    2. **Pre-Alembic database** (the local SQLite file this project used
       before). Tables exist but there is no `alembic_version`. Running the
       baseline against it would fail on tables that already exist, so it is
       *stamped* at the baseline instead. Before stamping, the legacy SQLite
       patches run (to fix up columns), and `create_all` fills in any tables
       added since that database was last opened - without it, a database
       predating a new table would be stamped as if it had one.
    3. **Already managed.** `alembic_version` exists: just upgrade to head.
    """
    has_alembic_version = await _has_table("alembic_version")
    has_app_tables = await _has_table("notebooks")

    if not has_alembic_version and has_app_tables:
        logger.info("Adopting an existing pre-Alembic database at revision %s", BASELINE_REVISION)
        if _is_sqlite():
            await migrate_documents_notebook_column()
            await migrate_overview_to_notebook_scope()
            await migrate_overview_short_summary_column()
        # Idempotent: creates only the tables that are missing, leaving every
        # existing table and all of its rows untouched.
        async with db.engine.begin() as conn:
            await conn.run_sync(db.Base.metadata.create_all)
        async with db.engine.begin() as conn:
            await conn.run_sync(
                lambda sync_conn: _run_alembic(sync_conn, "stamp", BASELINE_REVISION)
            )

    async with db.engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: _run_alembic(sync_conn, "upgrade", "head"))


def _run_alembic(sync_connection, action: str, revision: str) -> None:  # noqa: ANN001
    config = _alembic_config()
    # Hands Alembic the app's own connection rather than letting it build an
    # engine from settings - see the matching note in alembic/env.py for why
    # that distinction is load-bearing for the test suite.
    config.attributes["connection"] = sync_connection
    if action == "stamp":
        command.stamp(config, revision)
    else:
        command.upgrade(config, revision)


# ---------------------------------------------------------------------------
# Legacy SQLite patches, pre-Alembic. Run only when adopting an existing
# SQLite database, never on Postgres and never on a fresh install.
# ---------------------------------------------------------------------------


async def migrate_documents_notebook_column() -> None:
    """One-time schema patch for pre-6.3 databases: adds Document.notebook_id
    if it's missing and backfills any existing documents into a default
    notebook, so upgrading doesn't strand or lose documents uploaded before
    notebooks existed.

    Adding the column and backfilling orphaned rows are two separate
    statements/transactions (SQLite auto-commits DDL, so they can't share
    one). If the process is killed between them, a restart must still finish
    the backfill — so idempotency is checked by "are there still NULL
    notebook_id rows," not by "does the column exist." Checking only the
    latter would silently and permanently strand any document caught mid-
    migration, which is exactly the "never lose the user's documents"
    guarantee this migration exists to uphold.

    Accessed via the `db` module rather than `from app.db import engine,
    async_session_factory` so tests that monkeypatch `db.engine` /
    `db.async_session_factory` to a test database are respected here too."""
    async with db.engine.begin() as conn:
        result = await conn.execute(text("PRAGMA table_info(documents)"))
        columns = {row[1] for row in result.fetchall()}
        if not columns:
            return  # table doesn't exist yet; nothing to patch
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
    database in a state this function can still recover on the next startup."""
    async with db.engine.begin() as conn:
        result = await conn.execute(text("PRAGMA table_info(overviews)"))
        columns = {row[1] for row in result.fetchall()}
        already_final_shape = "notebook_id" in columns and "document_id" not in columns
        legacy_table_exists = await _table_exists(conn, "overviews_legacy")
        # Bail out only when there is nothing here at all (a fresh database).
        # Checking just "does `overviews` exist" would have been wrong: in
        # the crash window this migration is built to survive, `overviews`
        # has been renamed aside and ONLY `overviews_legacy` exists, and the
        # whole point is to rebuild `overviews` from that state.
        if not columns and not legacy_table_exists:
            return

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
                        short_summary TEXT,
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
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_overviews_notebook_id ON overviews (notebook_id)"
            )
        )

    async with db.engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS overviews_legacy"))


async def migrate_overview_short_summary_column() -> None:
    """One-time schema patch: adds `overviews.short_summary` for databases
    that already went through migrate_overview_to_notebook_scope() before
    this column existed on that migration's CREATE TABLE. A plain additive
    `ALTER TABLE ADD COLUMN` is safe here (unlike the notebook_id move) since
    short_summary is nullable with no UNIQUE/NOT NULL constraint to fight
    SQLite's DROP COLUMN restrictions over. Existing rows just get NULL — a
    short summary is regenerable content, not source material."""
    async with db.engine.begin() as conn:
        result = await conn.execute(text("PRAGMA table_info(overviews)"))
        columns = {row[1] for row in result.fetchall()}
        if not columns:
            return
        if "short_summary" not in columns:
            await conn.execute(text("ALTER TABLE overviews ADD COLUMN short_summary TEXT"))
