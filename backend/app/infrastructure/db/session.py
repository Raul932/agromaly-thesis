"""
Async Database Session Factory
================================
Creates the SQLAlchemy ``AsyncEngine`` and ``async_sessionmaker`` once per
process lifetime, then exposes a ``get_async_session`` FastAPI dependency
that yields a session per HTTP request and guarantees cleanup.

Transaction Strategy:
    - Each request gets its own session.
    - The session is committed only if no exception was raised.
    - On exception, the session is rolled back automatically.
    - Connection is returned to the pool on context-manager exit.
    - ``expire_on_commit=False`` preserves ORM attributes after commit,
      which is required for async sessions (prevents lazy-load errors).
"""

from __future__ import annotations

import logging
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

# CRITICAL: Import all ORM models to register them with SQLAlchemy's mapper
# registry before any relationship string ("NDVIRecordORM", etc.) is resolved.
# Without this, the first ORM operation raises:
#   "expression 'NDVIRecordORM' failed to locate a name"
import app.infrastructure.db.models  # noqa: F401  (import for side-effects)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Engine (one per process)
# ---------------------------------------------------------------------------

_engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,           # Log SQL in development only
    pool_pre_ping=True,            # Test connection liveness before checkout
    pool_size=10,                  # Base connection pool size
    max_overflow=20,               # Extra connections under load
    pool_timeout=30,               # Seconds to wait for a connection
    pool_recycle=1800,             # Recycle connections every 30 minutes
)

# ---------------------------------------------------------------------------
# Session Factory
# ---------------------------------------------------------------------------

AsyncSessionLocal = async_sessionmaker(
    bind=_engine,
    class_=AsyncSession,
    expire_on_commit=False,      # Prevent lazy-load errors after commit
    autocommit=False,
    autoflush=False,             # Services flush explicitly before reads
)


# ---------------------------------------------------------------------------
# FastAPI Dependency
# ---------------------------------------------------------------------------

async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an ``AsyncSession`` for a single HTTP request lifecycle.

    Commit on success, rollback on exception, always close on exit.

    Usage::

        from fastapi import Depends
        from sqlalchemy.ext.asyncio import AsyncSession
        from app.infrastructure.db.session import get_async_session

        @router.post("/example")
        async def create_something(session: AsyncSession = Depends(get_async_session)):
            ...
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
