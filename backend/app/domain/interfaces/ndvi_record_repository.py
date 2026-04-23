"""
Abstract Repository Interface: INDVIRecordRepository
======================================================
Defines the persistence Port for NDVIRecord time-series operations.

Key Query Patterns:
    - Bulk insert from satellite ingestion pipeline (batch save).
    - Time-range queries for LSTM model training.
    - Latest N records per parcel for anomaly detection inference.
    - Aggregation queries for dashboard visualisation.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from datetime import date
from typing import Optional, Sequence

from app.domain.entities.ndvi_record import NDVIRecord


class INDVIRecordRepository(ABC):
    """Persistence contract for NDVIRecord time-series data."""

    @abstractmethod
    async def save(self, record: NDVIRecord) -> NDVIRecord:
        """Persist a single NDVI record.

        Args:
            record: Domain entity to save.

        Returns:
            Persisted entity with any server-set fields.
        """
        ...

    @abstractmethod
    async def save_batch(self, records: Sequence[NDVIRecord]) -> Sequence[NDVIRecord]:
        """Bulk-insert a list of NDVI records efficiently.

        Implementations should use ``insert().on_conflict_do_nothing()`` or
        similar to handle re-ingestion of already-stored satellite passes.

        Args:
            records: List of domain entities to insert.

        Returns:
            Sequence of persisted entities.
        """
        ...

    @abstractmethod
    async def get_by_id(self, record_id: uuid.UUID) -> Optional[NDVIRecord]:
        """Retrieve a single record by its primary key."""
        ...

    @abstractmethod
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
        """Retrieve NDVI time series for a parcel within an optional date range.

        Args:
            parcel_id:     UUID of the parent parcel.
            start_date:    Inclusive lower bound for date_captured.
            end_date:      Inclusive upper bound for date_captured.
            only_reliable: If True, exclude interpolated records.
            limit:         Max records (default 365 = one full year).
            offset:        Pagination offset.

        Returns:
            Records ordered by date_captured ascending (chronological).
        """
        ...

    @abstractmethod
    async def get_latest_n(
        self,
        parcel_id: uuid.UUID,
        n: int,
        *,
        only_reliable: bool = False,
    ) -> Sequence[NDVIRecord]:
        """Retrieve the N most recent NDVI records for a parcel.

        Used by the LSTM inference pipeline to build input sequences.

        Args:
            parcel_id:     UUID of the parent parcel.
            n:             Number of most-recent records to retrieve.
            only_reliable: If True, skip cloud-obscured/interpolated records.

        Returns:
            Sequence of up to N records, ordered by date_captured descending.
        """
        ...

    @abstractmethod
    async def delete_by_parcel(self, parcel_id: uuid.UUID) -> int:
        """Delete all NDVI records for a parcel (called on parcel hard-delete).

        Args:
            parcel_id: UUID of the parcel whose records should be purged.

        Returns:
            Number of records deleted.
        """
        ...
