"""
Abstract Repository Interface: IUserRepository
================================================
Defines the persistence Port for User aggregate operations.
The concrete implementation (infrastructure) handles SQLAlchemy details.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from typing import Optional, Sequence

from app.domain.entities.user import User


class IUserRepository(ABC):
    """Persistence contract for User aggregates.

    All methods are async to support non-blocking database drivers.
    Implementations must never leak SQLAlchemy types into return values.
    """

    @abstractmethod
    async def save(self, user: User) -> User:
        """Persist a new User or update an existing one (upsert by id).

        Args:
            user: Domain entity to persist.

        Returns:
            Saved User reflecting any server-computed values.
        """
        ...

    @abstractmethod
    async def get_by_id(self, user_id: uuid.UUID) -> Optional[User]:
        """Retrieve a User by primary key.

        Args:
            user_id: UUID of the target user.

        Returns:
            User entity or None if not found.
        """
        ...

    @abstractmethod
    async def get_by_email(self, email: str) -> Optional[User]:
        """Retrieve a User by their unique email address.

        The email lookup must be case-insensitive at the storage layer,
        even though domain entities store emails in lowercase.

        Args:
            email: Lowercase-normalised email address.

        Returns:
            User entity or None if not found.
        """
        ...

    @abstractmethod
    async def exists_by_email(self, email: str) -> bool:
        """Efficient existence check by email for registration validation.

        Args:
            email: Email address to check.

        Returns:
            True if a user with this email already exists.
        """
        ...

    @abstractmethod
    async def delete(self, user_id: uuid.UUID) -> bool:
        """Hard-delete a User record (GDPR erasure).

        Args:
            user_id: UUID of the user to remove.

        Returns:
            True if deleted, False if not found.
        """
        ...

    @abstractmethod
    async def list_all(
        self,
        *,
        is_active: Optional[bool] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[User]:
        """Paginated list of all users (admin use only).

        Args:
            is_active: Optional filter to list only active/inactive accounts.
            limit:     Page size.
            offset:    Pagination offset.

        Returns:
            Sequence of User entities ordered by created_at descending.
        """
        ...
