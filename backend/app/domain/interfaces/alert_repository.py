"""
Abstract Repository Interface: IAlertRepository
=================================================
Defines the persistence Port for Alert notifications.

Key Query Patterns:
    - List unread alerts for a user (mobile notification feed).
    - Batch-mark alerts as read.
    - Count unread alerts (badge count in mobile UI).
    - List by parcel for the parcel detail screen.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from typing import Optional, Sequence

from app.domain.entities.alert import Alert, AlertSeverity, AlertType


class IAlertRepository(ABC):
    """Persistence contract for Alert notifications."""

    @abstractmethod
    async def save(self, alert: Alert) -> Alert:
        """Persist a new Alert.

        Args:
            alert: Domain entity to save.

        Returns:
            Saved entity with server-set fields populated.
        """
        ...

    @abstractmethod
    async def get_by_id(self, alert_id: uuid.UUID) -> Optional[Alert]:
        """Retrieve a single alert by primary key."""
        ...

    @abstractmethod
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
        """Retrieve alerts for all parcels owned by a user.

        Requires a JOIN through the parcels table to filter by owner.

        Args:
            owner_id:   UUID of the farmer/user.
            unread_only: Return only unread alerts if True.
            alert_type:  Optional type filter (ANOMALY | WEATHER).
            severity:    Optional severity filter.
            limit:       Page size.
            offset:      Pagination offset.

        Returns:
            Alerts ordered by created_at descending (newest first).
        """
        ...

    @abstractmethod
    async def list_for_parcel(
        self,
        parcel_id: uuid.UUID,
        *,
        unread_only: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[Alert]:
        """Retrieve all alerts for a specific parcel.

        Args:
            parcel_id:   UUID of the affected parcel.
            unread_only: Return only unread alerts if True.
            limit / offset: Pagination.

        Returns:
            Alerts ordered by created_at descending.
        """
        ...

    @abstractmethod
    async def count_unread(self, owner_id: uuid.UUID) -> int:
        """Count unread alerts across all parcels for a user.

        Used for mobile badge count (e.g. "3 new alerts").

        Args:
            owner_id: UUID of the owning user.

        Returns:
            Integer count of unread alerts.
        """
        ...

    @abstractmethod
    async def mark_as_read(self, alert_id: uuid.UUID) -> Optional[Alert]:
        """Mark a single alert as read.

        Args:
            alert_id: UUID of the alert to mark.

        Returns:
            Updated Alert entity, or None if the alert was not found.
        """
        ...

    @abstractmethod
    async def mark_all_as_read(self, owner_id: uuid.UUID) -> int:
        """Mark all unread alerts for a user as read (bulk operation).

        Args:
            owner_id: UUID of the owning user.

        Returns:
            Number of alerts updated.
        """
        ...

    @abstractmethod
    async def delete(self, alert_id: uuid.UUID) -> bool:
        """Hard-delete a single alert.

        Args:
            alert_id: UUID of the alert to remove.

        Returns:
            True if deleted, False if not found.
        """
        ...
