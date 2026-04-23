"""
Concrete Repository: AlertRepositoryImpl
==========================================
SQLAlchemy 2.0 async implementation of IAlertRepository.

Performance Notes:
    - ``list_for_user`` joins through ``parcels`` to filter by owner_id.
      This avoids a second in-Python filtering pass and pushes the work to
      the GiST/B-tree indexed columns in PostgreSQL.
    - ``count_unread`` uses the partial index ``ix_alerts_unread_partial``.
    - ``mark_all_as_read`` issues a single bulk UPDATE for efficiency.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional, Sequence

from sqlalchemy import and_, func, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.alert import Alert, AlertSeverity, AlertType
from app.domain.interfaces.alert_repository import IAlertRepository
from app.infrastructure.db.models.alert_orm import AlertORM
from app.infrastructure.db.models.parcel_orm import ParcelORM

logger = logging.getLogger(__name__)


class AlertRepositoryImpl(IAlertRepository):
    """Concrete async SQLAlchemy implementation of IAlertRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, alert: Alert) -> Alert:
        """Persist a new alert."""
        try:
            orm_model = AlertORM.from_domain(alert)
            merged = await self._session.merge(orm_model)
            await self._session.flush()
            await self._session.refresh(merged)
            logger.info(
                "Alert saved: id=%s parcel=%s type=%s",
                merged.id, merged.parcel_id, merged.alert_type,
            )
            return merged.to_domain()
        except SQLAlchemyError as exc:
            logger.error("DB error saving Alert: %s", exc)
            raise AlertPersistenceError("DB error saving alert.") from exc

    async def get_by_id(self, alert_id: uuid.UUID) -> Optional[Alert]:
        try:
            orm_obj = await self._session.get(AlertORM, alert_id)
            return orm_obj.to_domain() if orm_obj else None
        except SQLAlchemyError as exc:
            raise AlertPersistenceError(f"DB error fetching alert id={alert_id}.") from exc

    async def list_for_user(
        self,
        owner_id: uuid.UUID,
        *,
        unread_only: bool = False,
        alert_type: Optional[AlertType] = None,
        severity: Optional[AlertSeverity] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[Alert]:
        """Fetch alerts for all parcels owned by a user — JOIN through parcels table."""
        try:
            # Join alerts → parcels to filter by owner_id
            stmt = (
                select(AlertORM)
                .join(ParcelORM, AlertORM.parcel_id == ParcelORM.id)
                .where(ParcelORM.owner_id == owner_id)
                .order_by(AlertORM.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            if unread_only:
                stmt = stmt.where(AlertORM.is_read.is_(False))
            if alert_type is not None:
                stmt = stmt.where(AlertORM.alert_type == alert_type)
            if severity is not None:
                stmt = stmt.where(AlertORM.severity == severity)

            result = await self._session.execute(stmt)
            return [row.to_domain() for row in result.scalars().all()]
        except SQLAlchemyError as exc:
            raise AlertPersistenceError(
                f"DB error listing alerts for owner {owner_id}."
            ) from exc

    async def list_for_parcel(
        self,
        parcel_id: uuid.UUID,
        *,
        unread_only: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[Alert]:
        """Fetch all alerts for a specific parcel (parcel detail screen)."""
        try:
            stmt = (
                select(AlertORM)
                .where(AlertORM.parcel_id == parcel_id)
                .order_by(AlertORM.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            if unread_only:
                stmt = stmt.where(AlertORM.is_read.is_(False))
            result = await self._session.execute(stmt)
            return [row.to_domain() for row in result.scalars().all()]
        except SQLAlchemyError as exc:
            raise AlertPersistenceError(
                f"DB error listing alerts for parcel {parcel_id}."
            ) from exc

    async def count_unread(self, owner_id: uuid.UUID) -> int:
        """Badge count: unread alerts across all parcels for a user.

        Hits the partial index ``ix_alerts_unread_partial``.
        """
        try:
            stmt = (
                select(func.count())
                .select_from(AlertORM)
                .join(ParcelORM, AlertORM.parcel_id == ParcelORM.id)
                .where(
                    ParcelORM.owner_id == owner_id,
                    AlertORM.is_read.is_(False),
                )
            )
            result = await self._session.execute(stmt)
            return result.scalar_one()
        except SQLAlchemyError as exc:
            raise AlertPersistenceError(
                f"DB error counting unread alerts for owner {owner_id}."
            ) from exc

    async def mark_as_read(self, alert_id: uuid.UUID) -> Optional[Alert]:
        """Mark a single alert as read."""
        try:
            now = datetime.now(tz=timezone.utc)
            stmt = (
                update(AlertORM)
                .where(AlertORM.id == alert_id, AlertORM.is_read.is_(False))
                .values(is_read=True, read_at=now)
                .returning(AlertORM)
            )
            result = await self._session.execute(stmt)
            orm_obj = result.scalar_one_or_none()
            if orm_obj is None:
                return None
            await self._session.flush()
            return orm_obj.to_domain()
        except SQLAlchemyError as exc:
            raise AlertPersistenceError(
                f"DB error marking alert {alert_id} as read."
            ) from exc

    async def mark_all_as_read(self, owner_id: uuid.UUID) -> int:
        """Bulk-mark all unread alerts as read (single UPDATE statement)."""
        try:
            now = datetime.now(tz=timezone.utc)
            # Get all unread alert IDs for this owner's parcels
            parcel_ids_subq = (
                select(ParcelORM.id)
                .where(ParcelORM.owner_id == owner_id)
                .scalar_subquery()
            )
            stmt = (
                update(AlertORM)
                .where(
                    AlertORM.parcel_id.in_(parcel_ids_subq),
                    AlertORM.is_read.is_(False),
                )
                .values(is_read=True, read_at=now)
            )
            result = await self._session.execute(stmt)
            await self._session.flush()
            count = result.rowcount
            logger.info("Marked %d alerts as read for owner %s", count, owner_id)
            return count
        except SQLAlchemyError as exc:
            raise AlertPersistenceError(
                f"DB error bulk-marking alerts as read for owner {owner_id}."
            ) from exc

    async def delete(self, alert_id: uuid.UUID) -> bool:
        try:
            orm_obj = await self._session.get(AlertORM, alert_id)
            if orm_obj is None:
                return False
            await self._session.delete(orm_obj)
            await self._session.flush()
            return True
        except SQLAlchemyError as exc:
            raise AlertPersistenceError(f"DB error deleting alert {alert_id}.") from exc


class AlertPersistenceError(Exception):
    """Raised when a database operation on Alert fails."""
