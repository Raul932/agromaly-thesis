"""
Concrete Repository: UserRepositoryImpl
========================================
SQLAlchemy 2.0 async implementation of IUserRepository.

Security Notes:
    - ``get_by_email`` uses ``func.lower()`` for case-insensitive lookup,
      consistent with the partial index ``uix_users_email_lower``.
    - ``exists_by_email`` is used during registration to prevent duplicates.
    - No method ever returns the raw ``hashed_password`` in logs.
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import PersistenceError
from app.domain.entities.user import User
from app.domain.interfaces.user_repository import IUserRepository
from app.infrastructure.db.models.user_orm import UserORM

logger = logging.getLogger(__name__)


class UserRepositoryImpl(IUserRepository):
    """Concrete async SQLAlchemy implementation of IUserRepository.

    Args:
        session: Injected AsyncSession (managed by caller/DI container).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, user: User) -> User:
        """Upsert user (insert or update by id)."""
        logger.debug("Saving user id=%s email=%s", user.id, user.email)
        try:
            orm_model = UserORM.from_domain(user)
            merged = await self._session.merge(orm_model)
            await self._session.flush()
            await self._session.refresh(merged)
            logger.info("User saved: id=%s", merged.id)
            return merged.to_domain()
        except IntegrityError as exc:
            logger.error("Integrity error saving user id=%s: %s", user.id, exc)
            # Detect specifically an email uniqueness violation by constraint name
            orig = getattr(exc, "orig", None)
            constraint = getattr(getattr(orig, "diag", None), "constraint_name", "") or ""
            orig_str = str(orig or exc).lower()
            if constraint in ("uix_users_email_lower", "users_email_key") or (
                "email" in orig_str and ("unique" in orig_str or "duplicate" in orig_str)
            ):
                raise UserPersistenceError(
                    "email_already_registered"
                ) from exc
            raise UserPersistenceError(
                f"Database integrity error while saving user id={user.id}."
            ) from exc
        except SQLAlchemyError as exc:
            logger.error("DB error saving user id=%s: %s", user.id, exc)
            raise UserPersistenceError(f"Database error while saving user id={user.id}.") from exc

    async def get_by_id(self, user_id: uuid.UUID) -> Optional[User]:
        """Retrieve user by primary key."""
        try:
            orm_obj = await self._session.get(UserORM, user_id)
            return orm_obj.to_domain() if orm_obj else None
        except SQLAlchemyError as exc:
            raise UserPersistenceError(f"DB error fetching user id={user_id}.") from exc

    async def get_by_email(self, email: str) -> Optional[User]:
        """Retrieve user by email (case-insensitive)."""
        try:
            stmt = select(UserORM).where(func.lower(UserORM.email) == email.lower())
            result = await self._session.execute(stmt)
            orm_obj = result.scalar_one_or_none()
            return orm_obj.to_domain() if orm_obj else None
        except SQLAlchemyError as exc:
            raise UserPersistenceError(f"DB error fetching user by email.") from exc

    async def exists_by_email(self, email: str) -> bool:
        """Check if email is already registered."""
        try:
            stmt = (
                select(func.count())
                .select_from(UserORM)
                .where(func.lower(UserORM.email) == email.lower())
            )
            result = await self._session.execute(stmt)
            return result.scalar_one() > 0
        except SQLAlchemyError as exc:
            raise UserPersistenceError("DB error checking email existence.") from exc

    async def delete(self, user_id: uuid.UUID) -> bool:
        """Hard-delete a user (GDPR erasure)."""
        try:
            orm_obj = await self._session.get(UserORM, user_id)
            if orm_obj is None:
                return False
            await self._session.delete(orm_obj)
            await self._session.flush()
            logger.info("User deleted: id=%s", user_id)
            return True
        except SQLAlchemyError as exc:
            raise UserPersistenceError(f"DB error deleting user id={user_id}.") from exc

    async def list_all(
        self,
        *,
        is_active: Optional[bool] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[User]:
        """Paginated list of all users (admin endpoint)."""
        try:
            stmt = (
                select(UserORM)
                .order_by(UserORM.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            if is_active is not None:
                stmt = stmt.where(UserORM.is_active == is_active)
            result = await self._session.execute(stmt)
            return [row.to_domain() for row in result.scalars().all()]
        except SQLAlchemyError as exc:
            raise UserPersistenceError("DB error listing users.") from exc


class UserPersistenceError(PersistenceError):
    """Raised when a database operation on User fails."""
