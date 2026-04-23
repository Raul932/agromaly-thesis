"""
Abstract Repository Interface: IParcelRepository
=================================================
Defines the *Port* (in Hexagonal Architecture terminology) for all parcel
persistence operations. This interface lives in the Domain layer and has
absolutely NO knowledge of SQLAlchemy, databases, or any external system.

Design Principles:
    - Program to an interface, not an implementation (Dependency Inversion).
    - All methods are ``async`` to support non-blocking I/O throughout.
    - The interface defines the contract; concrete adapters in the
      infrastructure layer provide the actual implementation.
    - Optional filtering parameters use keyword-only arguments to prevent
      positional confusion at call sites.

Usage:
    Application services (Use Cases) depend on ``IParcelRepository``
    via constructor injection. At runtime, the DI container injects a
    concrete ``ParcelRepositoryImpl`` (SQLAlchemy + PostGIS).

    Example::

        class GetParcelUseCase:
            def __init__(self, repo: IParcelRepository) -> None:
                self._repo = repo

            async def execute(self, parcel_id: uuid.UUID) -> Parcel:
                parcel = await self._repo.get_by_id(parcel_id)
                if parcel is None:
                    raise ParcelNotFoundError(parcel_id)
                return parcel
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from typing import Optional, Sequence

from app.domain.entities.parcel import CropType, Parcel, ParcelStatus


class IParcelRepository(ABC):
    """Abstract base class defining the persistence contract for Parcel aggregates.

    All methods are coroutine-based (``async def``) to ensure that the entire
    vertical slice from presentation → application → domain → infrastructure
    remains non-blocking.

    Raises:
        Any concrete implementation may raise subclasses of
        ``app.core.exceptions.RepositoryError`` for persistence failures,
        but this interface does not mandate a specific exception hierarchy
        to keep the domain layer decoupled.
    """

    # ------------------------------------------------------------------
    # Write Operations
    # ------------------------------------------------------------------

    @abstractmethod
    async def save(self, parcel: Parcel) -> Parcel:
        """Persist a new Parcel or update an existing one (upsert semantics).

        If a Parcel with the same ``id`` already exists, it is updated.
        Otherwise a new record is created.

        Args:
            parcel: The domain entity to persist.

        Returns:
            The persisted Parcel, potentially with updated fields (e.g.
            server-generated timestamps).
        """
        ...

    @abstractmethod
    async def delete(self, parcel_id: uuid.UUID) -> bool:
        """Hard-delete a Parcel record by its primary key.

        Prefer ``Parcel.archive()`` for soft-deletes in business flows.
        This method is reserved for administrative purges (GDPR erasure).

        Args:
            parcel_id: UUID of the parcel to remove.

        Returns:
            ``True`` if the record was found and deleted, ``False`` if it
            did not exist (idempotent — callers should not treat this as
            an error).
        """
        ...

    # ------------------------------------------------------------------
    # Read Operations
    # ------------------------------------------------------------------

    @abstractmethod
    async def get_by_id(self, parcel_id: uuid.UUID) -> Optional[Parcel]:
        """Retrieve a single Parcel by its primary key.

        Args:
            parcel_id: UUID of the target parcel.

        Returns:
            The matching ``Parcel`` domain entity, or ``None`` if not found.
        """
        ...

    @abstractmethod
    async def list_by_owner(
        self,
        owner_id: uuid.UUID,
        *,
        status: Optional[ParcelStatus] = None,
        crop_type: Optional[CropType] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[Parcel]:
        """Retrieve all parcels belonging to a specific user, with optional filters.

        Args:
            owner_id:  UUID of the owning user.
            status:    Optional filter by lifecycle status.
            crop_type: Optional filter by planted crop.
            limit:     Maximum number of records to return (pagination).
            offset:    Number of records to skip (pagination).

        Returns:
            A (possibly empty) sequence of matching ``Parcel`` entities,
            ordered by ``created_at`` descending (newest first).
        """
        ...

    @abstractmethod
    async def count_by_owner(
        self,
        owner_id: uuid.UUID,
        *,
        status: Optional[ParcelStatus] = None,
    ) -> int:
        """Return the total count of parcels for a given owner.

        Primarily used for pagination metadata (``X-Total-Count`` header).

        Args:
            owner_id: UUID of the owning user.
            status:   Optional filter by lifecycle status.

        Returns:
            Integer count of matching parcels.
        """
        ...

    @abstractmethod
    async def exists(self, parcel_id: uuid.UUID) -> bool:
        """Check whether a Parcel with the given ID exists in the store.

        More efficient than ``get_by_id`` when only existence matters,
        as implementations can use a ``SELECT 1`` / ``COUNT`` query.

        Args:
            parcel_id: UUID to check.

        Returns:
            ``True`` if the parcel exists, ``False`` otherwise.
        """
        ...

    # ------------------------------------------------------------------
    # Geospatial Queries
    # ------------------------------------------------------------------

    @abstractmethod
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
        """Spatial query: find all parcels whose geometry intersects a bounding box.

        Uses PostGIS ``ST_Intersects`` for efficient index-backed spatial lookup.

        Args:
            min_lon:  Western boundary longitude (WGS84).
            min_lat:  Southern boundary latitude (WGS84).
            max_lon:  Eastern boundary longitude (WGS84).
            max_lat:  Northern boundary latitude (WGS84).
            owner_id: Optional — restrict results to a single owner.
            status:   Optional lifecycle filter.
            limit:    Maximum number of results (safety cap for large regions).

        Returns:
            Sequence of parcels whose geometry overlaps the supplied bbox.
        """
        ...
