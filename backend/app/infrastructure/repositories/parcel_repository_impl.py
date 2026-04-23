"""
Concrete Repository: ParcelRepositoryImpl
==========================================
The SQLAlchemy + PostGIS implementation of ``IParcelRepository``.

This class is the *Adapter* in Hexagonal Architecture terminology. It knows
about SQLAlchemy sessions, PostGIS spatial functions, and database-level
error handling — the domain layer knows nothing of any of this.

Design Principles:
    - Constructor-injected ``AsyncSession`` (provided by FastAPI's dependency
      injection system) ensures testability and clean transaction boundaries.
    - All public methods are ``async`` to keep the entire I/O path non-blocking.
    - Domain entities are always returned / accepted — never raw ORM objects.
    - Database errors are caught and re-raised as domain-agnostic exceptions
      to prevent leaking infrastructure details up the call stack.
    - Upsert logic uses ``merge()`` (identity map based), which is correct
      for update-or-insert semantics within a single session.

Transaction Management:
    SQLAlchemy's async session does NOT auto-commit. Callers (Application
    Use Cases or the FastAPI dependency that opens the session) are responsible
    for committing or rolling back. This repository NEVER calls ``commit()``.
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional, Sequence

from geoalchemy2.functions import ST_Intersects, ST_MakeEnvelope
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.parcel import CropType, Parcel, ParcelStatus
from app.domain.interfaces.parcel_repository import IParcelRepository
from app.infrastructure.db.models.parcel_orm import ParcelORM

logger = logging.getLogger(__name__)


class ParcelRepositoryImpl(IParcelRepository):
    """Concrete async SQLAlchemy + PostGIS implementation of ``IParcelRepository``.

    Args:
        session: An injected ``AsyncSession`` managed by the calling context
                 (e.g. FastAPI Depends, or a Celery task context manager).

    Raises:
        ParcelPersistenceError: Wraps SQLAlchemy exceptions so callers stay
            decoupled from infrastructure details.

    Example::

        # Inside a FastAPI route (simplified):
        async with get_db_session() as session:
            repo = ParcelRepositoryImpl(session)
            parcel = await repo.get_by_id(parcel_id)
            if parcel is None:
                raise HTTPException(status_code=404)
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Write Operations
    # ------------------------------------------------------------------

    async def save(self, parcel: Parcel) -> Parcel:
        """Upsert a Parcel (insert if new, update if existing).

        Uses SQLAlchemy's ``Session.merge()`` which checks the identity map
        and issues an INSERT or UPDATE accordingly.

        Args:
            parcel: Domain entity to persist.

        Returns:
            Refreshed domain entity reflecting any server-computed values
            (e.g. ``created_at``, ``updated_at`` from PostgreSQL ``now()``).

        Raises:
            ParcelPersistenceError: On duplicate key violation or DB error.
        """
        logger.debug("Saving parcel id=%s name=%r", parcel.id, parcel.name)
        try:
            orm_model = ParcelORM.from_domain(parcel)
            merged = await self._session.merge(orm_model)
            await self._session.flush()   # Flush to get server defaults back
            await self._session.refresh(merged)
            saved_parcel = merged.to_domain()
            logger.info("Parcel saved: id=%s", saved_parcel.id)
            return saved_parcel
        except IntegrityError as exc:
            logger.error("Integrity error saving parcel id=%s: %s", parcel.id, exc)
            raise ParcelPersistenceError(
                f"Failed to save parcel '{parcel.name}': constraint violation."
            ) from exc
        except SQLAlchemyError as exc:
            logger.error("DB error saving parcel id=%s: %s", parcel.id, exc)
            raise ParcelPersistenceError(
                f"Database error while saving parcel id={parcel.id}."
            ) from exc

    async def delete(self, parcel_id: uuid.UUID) -> bool:
        """Hard-delete a parcel by UUID.

        Args:
            parcel_id: UUID of the parcel to remove.

        Returns:
            ``True`` if deleted, ``False`` if not found.

        Raises:
            ParcelPersistenceError: On unexpected database error.
        """
        logger.debug("Deleting parcel id=%s", parcel_id)
        try:
            orm_obj = await self._session.get(ParcelORM, parcel_id)
            if orm_obj is None:
                logger.warning("Delete requested for non-existent parcel id=%s", parcel_id)
                return False
            await self._session.delete(orm_obj)
            await self._session.flush()
            logger.info("Parcel deleted: id=%s", parcel_id)
            return True
        except SQLAlchemyError as exc:
            logger.error("DB error deleting parcel id=%s: %s", parcel_id, exc)
            raise ParcelPersistenceError(
                f"Database error while deleting parcel id={parcel_id}."
            ) from exc

    # ------------------------------------------------------------------
    # Read Operations
    # ------------------------------------------------------------------

    async def get_by_id(self, parcel_id: uuid.UUID) -> Optional[Parcel]:
        """Retrieve a parcel by its primary key.

        Args:
            parcel_id: UUID of the target parcel.

        Returns:
            Domain entity or ``None``.

        Raises:
            ParcelPersistenceError: On unexpected database error.
        """
        logger.debug("Fetching parcel id=%s", parcel_id)
        try:
            orm_obj = await self._session.get(ParcelORM, parcel_id)
            if orm_obj is None:
                return None
            return orm_obj.to_domain()
        except SQLAlchemyError as exc:
            logger.error("DB error fetching parcel id=%s: %s", parcel_id, exc)
            raise ParcelPersistenceError(
                f"Database error while fetching parcel id={parcel_id}."
            ) from exc

    async def list_by_owner(
        self,
        owner_id: uuid.UUID,
        *,
        status: Optional[ParcelStatus] = None,
        crop_type: Optional[CropType] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[Parcel]:
        """Paginated list of parcels for a given owner, with optional filters.

        Args:
            owner_id:  UUID of the owning user.
            status:    Optional status filter.
            crop_type: Optional crop filter.
            limit:     Page size (max records returned).
            offset:    Pagination offset (records to skip).

        Returns:
            Sequence of domain entities ordered by ``created_at`` DESC.

        Raises:
            ParcelPersistenceError: On unexpected database error.
        """
        try:
            stmt = (
                select(ParcelORM)
                .where(ParcelORM.owner_id == owner_id)
                .order_by(ParcelORM.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            if status is not None:
                stmt = stmt.where(ParcelORM.status == status)
            if crop_type is not None:
                stmt = stmt.where(ParcelORM.crop_type == crop_type)

            result = await self._session.execute(stmt)
            orm_rows = result.scalars().all()
            return [row.to_domain() for row in orm_rows]
        except SQLAlchemyError as exc:
            logger.error("DB error listing parcels for owner=%s: %s", owner_id, exc)
            raise ParcelPersistenceError(
                f"Database error while listing parcels for owner id={owner_id}."
            ) from exc

    async def count_by_owner(
        self,
        owner_id: uuid.UUID,
        *,
        status: Optional[ParcelStatus] = None,
    ) -> int:
        """Count matching parcels for pagination metadata.

        Args:
            owner_id: UUID of the owning user.
            status:   Optional status filter.

        Returns:
            Integer count.

        Raises:
            ParcelPersistenceError: On unexpected database error.
        """
        try:
            stmt = (
                select(func.count())
                .select_from(ParcelORM)
                .where(ParcelORM.owner_id == owner_id)
            )
            if status is not None:
                stmt = stmt.where(ParcelORM.status == status)

            result = await self._session.execute(stmt)
            count = result.scalar_one()
            return count
        except SQLAlchemyError as exc:
            logger.error("DB error counting parcels for owner=%s: %s", owner_id, exc)
            raise ParcelPersistenceError(
                f"Database error while counting parcels for owner id={owner_id}."
            ) from exc

    async def exists(self, parcel_id: uuid.UUID) -> bool:
        """Efficient existence check using ``SELECT 1``.

        Args:
            parcel_id: UUID to check.

        Returns:
            Boolean existence flag.

        Raises:
            ParcelPersistenceError: On unexpected database error.
        """
        try:
            stmt = (
                select(func.count())
                .select_from(ParcelORM)
                .where(ParcelORM.id == parcel_id)
            )
            result = await self._session.execute(stmt)
            return result.scalar_one() > 0
        except SQLAlchemyError as exc:
            logger.error("DB error checking existence of parcel id=%s: %s", parcel_id, exc)
            raise ParcelPersistenceError(
                f"Database error while checking existence of parcel id={parcel_id}."
            ) from exc

    # ------------------------------------------------------------------
    # Geospatial Queries
    # ------------------------------------------------------------------

    async def find_parcels_within_bbox(
        self,
        min_lon: float,
        min_lat: float,
        max_lon: float,
        max_lat: float,
        *,
        owner_id: Optional[uuid.UUID] = None,
        status: Optional[ParcelStatus] = None,
        limit: int = 500,
    ) -> Sequence[Parcel]:
        """PostGIS bounding-box spatial intersection query.

        Uses ``ST_MakeEnvelope`` to build a rectangle from the four
        coordinate bounds, then ``ST_Intersects`` with the GiST-indexed
        geometry column for efficient spatial lookup.

        Args:
            min_lon: Western boundary longitude (WGS84 degrees).
            min_lat: Southern boundary latitude (WGS84 degrees).
            max_lon: Eastern boundary longitude (WGS84 degrees).
            max_lat: Northern boundary latitude (WGS84 degrees).
            owner_id: Optional owner filter.
            status:   Optional status filter.
            limit:    Maximum results to prevent runaway queries.

        Returns:
            Sequence of domain Parcel entities whose geometry overlaps the
            specified bounding box.

        Raises:
            ValueError: If bounding box coordinates are logically invalid.
            ParcelPersistenceError: On database error.
        """
        # Boundary sanity check (domain-level guard)
        if min_lon >= max_lon or min_lat >= max_lat:
            raise ValueError(
                "Invalid bounding box: min values must be strictly less than max values. "
                f"Got: lon=[{min_lon}, {max_lon}], lat=[{min_lat}, {max_lat}]"
            )

        try:
            # ST_MakeEnvelope(xmin, ymin, xmax, ymax, srid) → PostGIS envelope
            bbox = ST_MakeEnvelope(min_lon, min_lat, max_lon, max_lat, 4326)

            stmt = (
                select(ParcelORM)
                .where(ST_Intersects(ParcelORM.geometry, bbox))
                .order_by(ParcelORM.area_ha.desc())   # Largest parcels first
                .limit(limit)
            )
            if owner_id is not None:
                stmt = stmt.where(ParcelORM.owner_id == owner_id)
            if status is not None:
                stmt = stmt.where(ParcelORM.status == status)

            result = await self._session.execute(stmt)
            orm_rows = result.scalars().all()
            logger.debug(
                "Bbox query returned %d parcels for bbox=[%s,%s,%s,%s]",
                len(orm_rows), min_lon, min_lat, max_lon, max_lat,
            )
            return [row.to_domain() for row in orm_rows]
        except SQLAlchemyError as exc:
            logger.error("DB error in bbox spatial query: %s", exc)
            raise ParcelPersistenceError(
                "Database error during bounding-box spatial query."
            ) from exc


# ---------------------------------------------------------------------------
# Repository-Layer Exception
# ---------------------------------------------------------------------------

class ParcelPersistenceError(Exception):
    """Raised by ``ParcelRepositoryImpl`` when a database operation fails.

    This exception is domain-agnostic — it carries no SQLAlchemy types
    so that higher layers remain decoupled from infrastructure details.
    The original exception is always chained (``raise ... from exc``) for
    full traceback visibility in logs without leaking it to HTTP responses.
    """
