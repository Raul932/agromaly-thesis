"""
SQLAlchemy ORM Model: UserORM
==============================
Concrete database representation of the User aggregate.

Security Constraints:
    - Email column has a UNIQUE constraint with a partial index (lowercase).
    - No ``password`` column — only ``hashed_password``.
    - Cascade strategy: deleting a User cascades to all their Parcels
      (and transitively to NDVIRecords/Alerts via the Parcel FK cascade).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, List

from sqlalchemy import Boolean, DateTime, Index, String, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.db.base import Base
from app.domain.entities.user import User

if TYPE_CHECKING:
    from app.infrastructure.db.models.parcel_orm import ParcelORM


class UserORM(Base):
    """SQLAlchemy ORM for the ``users`` table.

    Columns:
        id              (UUID)        — Primary key, auto-generated.
        email           (VARCHAR 320) — RFC 5321 max, UNIQUE, lowercase.
        hashed_password (TEXT)        — Argon2/Bcrypt hash.
        full_name       (VARCHAR 255) — Display name.
        is_active       (BOOLEAN)     — Account active flag.
        is_superuser    (BOOLEAN)     — Admin flag.
        created_at      (TIMESTAMPTZ) — Creation timestamp.
        updated_at      (TIMESTAMPTZ) — Last modification timestamp.

    Relationships:
        parcels: One-to-Many → ParcelORM (cascade delete).
    """

    __tablename__ = "users"

    __table_args__ = (
        # Case-insensitive unique index on email for PostgreSQL
        Index(
            "uix_users_email_lower",
            func.lower(email_col := "email"),  # type: ignore[arg-type]
            unique=True,
        ),
    )

    # ------------------------------------------------------------------
    # Columns
    # ------------------------------------------------------------------
    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    email: Mapped[str] = mapped_column(
        String(320),
        nullable=False,
        unique=True,
        index=True,
        comment="Unique lowercase email address.",
    )
    hashed_password: Mapped[str] = mapped_column(
        String(1024),  # Argon2 hashes can be ~100+ chars; generous buffer
        nullable=False,
        comment="Argon2/Bcrypt hashed password. Never store plain text.",
    )
    full_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="User's display name.",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
        comment="False = suspended account that cannot authenticate.",
    )
    is_superuser: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment="True = admin privileges.",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # ------------------------------------------------------------------
    # Relationships
    # ------------------------------------------------------------------
    parcels: Mapped[List["ParcelORM"]] = relationship(
        "ParcelORM",
        back_populates="owner",
        cascade="all, delete-orphan",
        lazy="noload",   # Never eagerly load — always use explicit joinedload
        passive_deletes=True,
    )

    # ------------------------------------------------------------------
    # Mapping
    # ------------------------------------------------------------------

    def to_domain(self) -> User:
        """Convert ORM row to User domain entity."""
        return User(
            id=self.id,
            email=self.email,
            hashed_password=self.hashed_password,
            full_name=self.full_name,
            is_active=self.is_active,
            is_superuser=self.is_superuser,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )

    @classmethod
    def from_domain(cls, user: User) -> "UserORM":
        """Construct ORM model from domain entity."""
        return cls(
            id=user.id,
            email=user.email,
            hashed_password=user.hashed_password,
            full_name=user.full_name,
            is_active=user.is_active,
            is_superuser=user.is_superuser,
            created_at=user.created_at,
            updated_at=user.updated_at,
        )

    def __repr__(self) -> str:
        return f"<UserORM id={self.id!s} email={self.email!r} active={self.is_active}>"
