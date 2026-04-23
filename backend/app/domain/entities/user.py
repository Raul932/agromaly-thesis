"""
Domain Entity: User
====================
Pure Python representation of a registered farmer/user in the system.

Security Notes:
    - ``hashed_password`` is NEVER the raw password. The application layer
      always hashes before constructing this entity (Argon2 via passlib).
    - The entity deliberately has no ``password`` field — this boundary
      prevents accidental plain-text storage anywhere in the domain.
    - Email is stored lowercase-normalised to prevent duplicate accounts
      with different casing (e.g. "User@example.com" vs "user@example.com").
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass(frozen=True)
class User:
    """Represents a registered user (farmer/agronomist) of the Agromaly platform.

    Attributes:
        id:              Globally unique identifier (UUID v4).
        email:           Unique, lowercase-normalised email address.
        hashed_password: Argon2/Bcrypt hashed password — NEVER plain text.
        full_name:       User's display name.
        is_active:       Whether this account may log in and access the API.
        is_superuser:    Whether this account has administrative privileges.
        created_at:      UTC timestamp of account creation.
        updated_at:      UTC timestamp of the last account modification.
    """

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    email: str = field(default=...)
    hashed_password: str = field(default=...)
    full_name: str = field(default=...)
    is_active: bool = field(default=True)
    is_superuser: bool = field(default=False)
    created_at: datetime = field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )
    updated_at: datetime = field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )

    def __post_init__(self) -> None:
        self._validate_email()
        self._validate_full_name()
        self._validate_hashed_password()

    def _validate_email(self) -> None:
        """Email must be non-empty and contain exactly one '@'."""
        if not isinstance(self.email, str) or not self.email.strip():
            raise ValueError("User 'email' must be a non-empty string.")
        if self.email.count("@") != 1:
            raise ValueError(f"User 'email' is not a valid email address: {self.email!r}")
        # Enforce canonical lowercase normalisation
        if self.email != self.email.lower():
            raise ValueError(
                "User 'email' must be lowercase-normalised before constructing a User entity. "
                f"Got: {self.email!r}"
            )

    def _validate_full_name(self) -> None:
        """Full name must be a non-empty string, max 255 chars."""
        if not isinstance(self.full_name, str) or not self.full_name.strip():
            raise ValueError("User 'full_name' must be a non-empty string.")
        if len(self.full_name) > 255:
            raise ValueError(
                f"User 'full_name' exceeds 255 characters (got {len(self.full_name)})."
            )

    def _validate_hashed_password(self) -> None:
        """Hashed password must be a non-empty string (sanity check only)."""
        if not isinstance(self.hashed_password, str) or not self.hashed_password.strip():
            raise ValueError("User 'hashed_password' must be a non-empty string.")

    # ------------------------------------------------------------------
    # Domain Behaviour
    # ------------------------------------------------------------------

    def deactivate(self) -> "User":
        """Return a new User with ``is_active=False`` (account suspension)."""
        return self._copy_with(
            is_active=False,
            updated_at=datetime.now(tz=timezone.utc),
        )

    def activate(self) -> "User":
        """Return a new User with ``is_active=True`` (account re-activation)."""
        return self._copy_with(
            is_active=True,
            updated_at=datetime.now(tz=timezone.utc),
        )

    def update_password(self, new_hashed_password: str) -> "User":
        """Return a new User with an updated hashed password.

        Args:
            new_hashed_password: Already-hashed password (Argon2/Bcrypt).

        Returns:
            New User entity with updated password and timestamp.
        """
        if not new_hashed_password or not new_hashed_password.strip():
            raise ValueError("New hashed password must not be empty.")
        return self._copy_with(
            hashed_password=new_hashed_password,
            updated_at=datetime.now(tz=timezone.utc),
        )

    # ------------------------------------------------------------------
    # Computed Properties
    # ------------------------------------------------------------------

    @property
    def can_login(self) -> bool:
        """Return True only if the user account is active."""
        return self.is_active

    # ------------------------------------------------------------------
    # Private Helpers
    # ------------------------------------------------------------------

    def _copy_with(self, **overrides: object) -> "User":
        import dataclasses
        current_fields = {f.name: getattr(self, f.name) for f in dataclasses.fields(self)}
        current_fields.update(overrides)
        return User(**current_fields)

    def __repr__(self) -> str:
        return (
            f"User(id={self.id!s}, email={self.email!r}, "
            f"is_active={self.is_active}, is_superuser={self.is_superuser})"
        )
