"""
Alembic Migration Environment
================================
Configured for:
    1. Async SQLAlchemy (asyncpg driver) — uses ``run_async_migrations()``.
    2. PostGIS-safe autogeneration — excludes PostGIS system tables.
    3. Environment-variable-based database URL (no hardcoded credentials).
    4. ``compare_type=True`` — Alembic detects column type changes.
    5. ``compare_server_default=True`` — detects server default changes.

PostGIS Safety:
    The ``include_object`` filter prevents Alembic from touching PostGIS
    internal tables (spatial_ref_sys, geometry_columns, etc.) or any table
    from the 'topology' schema.  Without this, ``--autogenerate`` would try
    to DROP these system tables on every migration run.

Sync vs Async:
    Alembic's built-in migration runner is synchronous.  We use
    ``asyncio.run(run_async_migrations())`` and ``AsyncEngine.sync_engine``
    to bridge the gap without spawning a separate event loop.
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
from logging.config import fileConfig
from typing import Any
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from alembic import context
from sqlalchemy import engine_from_config, pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# ---------------------------------------------------------------------------
# Import all models so Alembic's metadata sees every table.
# IMPORTANT: base.py only defines Base (no model imports) to avoid circular
# imports. We must import every ORM model explicitly here instead.
# ---------------------------------------------------------------------------
from app.infrastructure.db.base import Base  # noqa: F401
from app.infrastructure.db.models.user_orm import UserORM  # noqa: F401
from app.infrastructure.db.models.parcel_orm import ParcelORM  # noqa: F401
from app.infrastructure.db.models.ndvi_record_orm import NDVIRecordORM  # noqa: F401
from app.infrastructure.db.models.weather_forecast_orm import WeatherForecastORM  # noqa: F401
from app.infrastructure.db.models.alert_orm import AlertORM  # noqa: F401

# ---------------------------------------------------------------------------
# Alembic Config Object
# ---------------------------------------------------------------------------
config = context.config

# Configure logging from alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The metadata of all ORM models — used for --autogenerate
target_metadata = Base.metadata

# ---------------------------------------------------------------------------
# Database URL from Environment (Zero Hardcoded Secrets)
# ---------------------------------------------------------------------------
# Priority: environment variable → alembic.ini sqlalchemy.url (for CI overrides)
# The sync psycopg2 URL is used for Alembic (it uses a synchronous connection).

def get_database_url() -> str:
    """Resolve the sync database URL from environment or INI config.

    Returns:
        A psycopg2-compatible URL (postgresql+psycopg2://...).

    Raises:
        RuntimeError: If no database URL can be resolved.
    """
    # Prefer the explicit sync URL if set
    url = os.environ.get("DATABASE_SYNC_URL")
    if url:
        return url

    # Fall back to the async URL but swap the driver for Alembic
    async_url = os.environ.get("DATABASE_URL", "")
    if async_url:
        return async_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")

    # If alembic.ini has sqlalchemy.url configured, use it
    ini_url = config.get_main_option("sqlalchemy.url")
    if ini_url and ini_url != "None":
        return ini_url

    raise RuntimeError(
        "No database URL found. Set DATABASE_SYNC_URL or DATABASE_URL environment variable."
    )

# ---------------------------------------------------------------------------
# PostGIS-Safe Table Filter
# ---------------------------------------------------------------------------

# PostGIS system tables that Alembic must never touch
_POSTGIS_TABLES = frozenset({
    "spatial_ref_sys",
    "geometry_columns",
    "geography_columns",
    "raster_columns",
    "raster_overviews",
})

# PostGIS-related schemas to exclude entirely
_EXCLUDED_SCHEMAS = frozenset({"topology", "tiger", "tiger_data"})


def include_object(
    object: Any,
    name: str | None,
    type_: str,
    reflected: bool,
    compare_to: Any,
) -> bool:
    """Alembic filter callback: exclude PostGIS system objects.

    This is the CRITICAL guard that prevents Alembic from generating DROP
    statements for PostGIS internal tables during --autogenerate.

    Args:
        object:     SQLAlchemy schema object being inspected.
        name:       Object name (table name, index name, etc.).
        type_:      Object type ('table', 'column', 'index', etc.).
        reflected:  True if reflected from DB (not in our models).
        compare_to: Counter-part object for comparison.

    Returns:
        True if Alembic should include this object in migrations.
    """
    if type_ == "table":
        # Exclude PostGIS system tables by name
        if name in _POSTGIS_TABLES:
            return False
        # Exclude tables from PostGIS-specific schemas
        schema = getattr(object, "schema", None)
        if schema in _EXCLUDED_SCHEMAS:
            return False
        # Exclude any reflected table not defined in our models
        # (this catches other PostGIS extension tables not in our whitelist)
        if reflected and name not in target_metadata.tables:
            return False
    return True


# ---------------------------------------------------------------------------
# Migration Runners
# ---------------------------------------------------------------------------

def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (generates SQL without a DB connection).

    Useful for generating migration scripts to review before applying.
    """
    url = get_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Execute migrations using a live DB connection."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Async entry point — creates an async engine and runs migrations.

    Alembic itself is synchronous, so we use ``engine.sync_engine`` to
    run the actual migration logic without async/await friction.
    """
    url = get_database_url()

    url = url.replace("postgresql+psycopg2://", "postgresql+asyncpg://")
    # Build an async engine configuration dict
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = url

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,       # Never pool connections in migration context
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Synchronous wrapper that bridges into the async migration runner."""
    asyncio.run(run_async_migrations())


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
