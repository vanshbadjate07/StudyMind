"""Alembic environment.

Reads the database URL from the app's own settings rather than alembic.ini,
so a migration can never run against a different database than the one the
app uses. Handles both SQLite (local) and Postgres (deployed) from the same
migrations - which is the point of moving off the hand-rolled PRAGMA
patches this replaces.
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy import pool

from app.config import settings
from app.db import Base

# Imported for the side effect of registering every model on Base.metadata,
# which is what autogenerate diffs against.
import app.models  # noqa: F401

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _configure(connection) -> None:  # noqa: ANN001
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # SQLite cannot ALTER most columns in place. Batch mode rewrites the
        # table instead, which is what makes one set of migrations work on
        # both backends rather than needing a SQLite-specific path.
        render_as_batch=connection.dialect.name == "sqlite",
        compare_type=True,
    )


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run(connection) -> None:  # noqa: ANN001
    _configure(connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(_do_run)
    await connectable.dispose()


# The app runs migrations at startup over its OWN engine, handed in here as
# config.attributes["connection"]. That matters for more than tidiness: the
# test suite points the app at a temporary database by patching db.engine,
# and an Alembic run that built its own engine from settings would migrate
# the real database instead, destroying test isolation.
_existing_connection = config.attributes.get("connection")

if _existing_connection is not None:
    _do_run(_existing_connection)
elif context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
