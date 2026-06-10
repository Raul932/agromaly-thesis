"""
FastAPI Dependency Factories
==============================
Provides ``Depends``-compatible factory functions that wire the concrete
repository implementations into the application services for each request.

Design:
    Each factory creates a fresh repository / service for every request, using
    the request-scoped ``AsyncSession`` from ``get_async_session``. This ensures:
        - No shared mutable state between requests.
        - Clean transaction boundaries per request.
        - Testability via dependency_overrides.

Usage in endpoints::

    @router.post("/example")
    async def example(
        service: UserService = Depends(get_user_service),
    ):
        ...
"""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from typing import Optional

from app.application.services.analysis_service import AnalysisService
from app.application.services.parcel_service import ParcelService
from app.application.services.rag_service import RagService, get_rag_service as _get_rag
from app.application.services.user_service import UserService
from app.infrastructure.db.session import get_async_session
from app.infrastructure.repositories.ndvi_record_repository_impl import NDVIRecordRepositoryImpl
from app.infrastructure.repositories.parcel_repository_impl import ParcelRepositoryImpl
from app.infrastructure.repositories.user_repository_impl import UserRepositoryImpl


def get_user_repo(
    session: AsyncSession = Depends(get_async_session),
) -> UserRepositoryImpl:
    """Create a UserRepositoryImpl for the current request's session."""
    return UserRepositoryImpl(session)


def get_parcel_repo(
    session: AsyncSession = Depends(get_async_session),
) -> ParcelRepositoryImpl:
    """Create a ParcelRepositoryImpl for the current request's session."""
    return ParcelRepositoryImpl(session)


def get_ndvi_repo(
    session: AsyncSession = Depends(get_async_session),
) -> NDVIRecordRepositoryImpl:
    """Create an NDVIRecordRepositoryImpl for the current request's session."""
    return NDVIRecordRepositoryImpl(session)


def get_user_service(
    repo: UserRepositoryImpl = Depends(get_user_repo),
) -> UserService:
    """Create a UserService backed by the request-scoped UserRepository."""
    return UserService(user_repo=repo)


def get_parcel_service(
    repo: ParcelRepositoryImpl = Depends(get_parcel_repo),
) -> ParcelService:
    """Create a ParcelService backed by the request-scoped ParcelRepository."""
    return ParcelService(parcel_repo=repo)


def get_analysis_service(
    parcel_repo: ParcelRepositoryImpl = Depends(get_parcel_repo),
    ndvi_repo: NDVIRecordRepositoryImpl = Depends(get_ndvi_repo),
) -> AnalysisService:
    """Create an AnalysisService with both parcel and NDVI repos injected."""
    return AnalysisService(parcel_repo=parcel_repo, ndvi_repo=ndvi_repo)


def get_rag_service() -> Optional[RagService]:
    """Return the singleton RagService (or None if not configured)."""
    return _get_rag()

