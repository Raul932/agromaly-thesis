"""
Concrete Repository: NDVIRecordRepositoryImpl
==============================================
SQLAlchemy 2.0 async implementation of INDVIRecordRepository.

Batch Insert Strategy:
    ``save_batch`` uses PostgreSQL's ``INSERT … ON CONFLICT DO NOTHING``
    (via SQLAlchemy's ``insert().on_conflict_do_nothing()``) to silently
    skip records that already exist (idempotent satellite re-ingestion).
"""

from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import Optional, Sequence

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.ndvi_record import NDVIRecord
from app.domain.interfaces.ndvi_record_repository import INDVIRecordRepository
from app.infrastructure.db.models.ndvi_record_orm import NDVIRecordORM

logger = logging.getLogger(__name__)


class NDVIRecordRepositoryImpl(INDVIRecordRepository):
    """Concrete async SQLAlchemy implementation of INDVIRecordRepository.

    Args:
        session: Injected AsyncSession.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, record: NDVIRecord) -> NDVIRecord:
        """Persist a single NDVI record."""
        try:
            orm_model = NDVIRecordORM.from_domain(record)
            merged = await self._session.merge(orm_model)
            await self._session.flush()
            await self._session.refresh(merged)
            return merged.to_domain()
        except SQLAlchemyError as exc:
            logger.error("DB error saving NDVIRecord id=%s: %s", record.id, exc)
            raise NDVIRecordPersistenceError(
                f"DB error saving NDVIRecord for parcel {record.parcel_id}."
            ) from exc

    async def save_batch(self, records: Sequence[NDVIRecord]) -> Sequence[NDVIRecord]:
        """Bulk-insert NDVI records, skipping duplicates via ON CONFLICT DO NOTHING.

        Uses the natural unique constraint (parcel_id, date_captured, source).
        """
        if not records:
            return []
        try:
            rows = [
                {
                    "id": r.id,
                    "parcel_id": r.parcel_id,
                    "date_captured": r.date_captured,
                    "mean_ndvi": r.mean_ndvi,
                    "cloud_coverage": r.cloud_coverage,
                    "pixel_count": r.pixel_count,
                    "is_interpolated": r.is_interpolated,
                    "source": r.source,
                    "created_at": r.created_at,
                }
                for r in records
            ]
            stmt = pg_insert(NDVIRecordORM).values(rows)
            stmt = stmt.on_conflict_do_nothing(
                index_elements=["parcel_id", "date_captured", "source"]
            )
            await self._session.execute(stmt)
            await self._session.flush()
            logger.info("Batch-inserted %d NDVI records (duplicates skipped).", len(rows))
            # Re-fetch to return domain entities with server-set fields
            parcel_ids = list({r.parcel_id for r in records})
            dates = [r.date_captured for r in records]
            fetch_stmt = select(NDVIRecordORM).where(
                NDVIRecordORM.parcel_id.in_(parcel_ids),
                NDVIRecordORM.date_captured.in_(dates),
            )
            result = await self._session.execute(fetch_stmt)
            return [row.to_domain() for row in result.scalars().all()]
        except SQLAlchemyError as exc:
            logger.error("DB error batch-saving NDVI records: %s", exc)
            raise NDVIRecordPersistenceError("DB error during NDVI batch insert.") from exc

    async def get_by_id(self, record_id: uuid.UUID) -> Optional[NDVIRecord]:
        try:
            orm_obj = await self._session.get(NDVIRecordORM, record_id)
            return orm_obj.to_domain() if orm_obj else None
        except SQLAlchemyError as exc:
            raise NDVIRecordPersistenceError(f"DB error fetching NDVIRecord id={record_id}.") from exc

    async def list_by_parcel(
        self,
        parcel_id: uuid.UUID,
        *,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        only_reliable: bool = False,
        limit: int = 365,
        offset: int = 0,
    ) -> Sequence[NDVIRecord]:
        """Time-series query for a parcel with optional date bounds and reliability filter."""
        try:
            stmt = (
                select(NDVIRecordORM)
                .where(NDVIRecordORM.parcel_id == parcel_id)
                .order_by(NDVIRecordORM.date_captured.asc())
                .limit(limit)
                .offset(offset)
            )
            if start_date:
                stmt = stmt.where(NDVIRecordORM.date_captured >= start_date)
            if end_date:
                stmt = stmt.where(NDVIRecordORM.date_captured <= end_date)
            if only_reliable:
                stmt = stmt.where(
                    NDVIRecordORM.cloud_coverage < 20.0,
                    NDVIRecordORM.is_interpolated.is_(False),
                )
            result = await self._session.execute(stmt)
            return [row.to_domain() for row in result.scalars().all()]
        except SQLAlchemyError as exc:
            raise NDVIRecordPersistenceError(
                f"DB error listing NDVI records for parcel {parcel_id}."
            ) from exc

    async def get_latest_n(
        self,
        parcel_id: uuid.UUID,
        n: int,
        *,
        only_reliable: bool = False,
    ) -> Sequence[NDVIRecord]:
        """Fetch the N most recent records for LSTM inference input."""
        try:
            stmt = (
                select(NDVIRecordORM)
                .where(NDVIRecordORM.parcel_id == parcel_id)
                .order_by(NDVIRecordORM.date_captured.desc())
                .limit(n)
            )
            if only_reliable:
                stmt = stmt.where(
                    NDVIRecordORM.cloud_coverage < 20.0,
                    NDVIRecordORM.is_interpolated.is_(False),
                )
            result = await self._session.execute(stmt)
            return [row.to_domain() for row in result.scalars().all()]
        except SQLAlchemyError as exc:
            raise NDVIRecordPersistenceError(
                f"DB error fetching latest {n} NDVI records for parcel {parcel_id}."
            ) from exc

    async def delete_by_parcel(self, parcel_id: uuid.UUID) -> int:
        """Delete all NDVI records for a parcel (cascade safety net)."""
        try:
            stmt = delete(NDVIRecordORM).where(NDVIRecordORM.parcel_id == parcel_id)
            result = await self._session.execute(stmt)
            await self._session.flush()
            count = result.rowcount
            logger.info("Deleted %d NDVI records for parcel %s", count, parcel_id)
            return count
        except SQLAlchemyError as exc:
            raise NDVIRecordPersistenceError(
                f"DB error deleting NDVI records for parcel {parcel_id}."
            ) from exc


class NDVIRecordPersistenceError(Exception):
    """Raised when a database operation on NDVIRecord fails."""
