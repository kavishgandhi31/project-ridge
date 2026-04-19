"""Alembic environment script — async-compatible.

Reads the database URL from Hornet settings (not alembic.ini) so
there is one source of truth. Imports the models package so every
mapped class registers on Base.metadata before autogenerate runs.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig
from typing import Any

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from hornet.config import get_settings

# Importing the models package triggers the side-effect registration
# of every ObservationRow-class on Base.metadata. Do NOT remove this
# import even if a linter flags it as unused — it is load-bearing.
from hornet.db import models  # noqa: F401
from hornet.db.base import Base

# The Alembic Config object provides access to values in alembic.ini.
config = context.config

# Interpret the logging config from the ini file.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Override sqlalchemy.url from the application Settings so that the
# database URL lives in exactly one place (the Settings class).
config.set_main_option("sqlalchemy.url", get_settings().db_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Generate SQL without connecting to the database.

    Used for 'alembic upgrade --sql' when you want to dump the
    migration SQL instead of applying it live.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Connect to the database and apply migrations against it."""
    section: dict[str, Any] = config.get_section(config.config_ini_section, {})
    connectable = async_engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
