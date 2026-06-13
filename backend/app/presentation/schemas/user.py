"""
Pydantic V2 Schemas: User
==========================
Request/Response models for user-related API endpoints.

Security:
    - ``UserCreate.password`` has strict strength requirements enforced
      at the schema level — before the service even sees the value.
    - Responses NEVER include ``hashed_password`` or any internal fields.
    - ``UserResponse`` uses ``model_config = ConfigDict(from_attributes=True)``
      so it can be constructed from ORM or domain objects without extra mapping.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

class UserCreate(BaseModel):
    """Payload for ``POST /api/v1/users/register``.

    Validates:
        - Email is a syntactically valid address (via ``EmailStr``).
        - Password meets minimum strength requirements.
        - Password and confirmation match.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    email: EmailStr = Field(
        ...,
        description="User's email address. Must be unique in the system.",
        examples=["farmer@example.com"],
    )
    full_name: str = Field(
        ...,
        min_length=2,
        max_length=255,
        description="User's full display name.",
        examples=["Ion Popescu"],
    )
    password: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="Plain-text password. Min 8 chars, must contain a digit.",
    )
    password_confirm: str = Field(
        ...,
        description="Must match 'password' exactly.",
    )

    @field_validator("email", mode="before")
    @classmethod
    def normalise_email(cls, v: str) -> str:
        """Normalise email to lowercase before any downstream processing."""
        return v.lower().strip()

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        """Enforce basic password strength: at least one digit."""
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit.")
        if not any(c.isalpha() for c in v):
            raise ValueError("Password must contain at least one letter.")
        return v

    @model_validator(mode="after")
    def passwords_match(self) -> "UserCreate":
        if self.password != self.password_confirm:
            raise ValueError("'password' and 'password_confirm' do not match.")
        return self


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

class UserLogin(BaseModel):
    """OAuth2-compatible login payload for ``POST /api/v1/users/login``.

    FastAPI's ``OAuth2PasswordRequestForm`` is also supported by the endpoint,
    but this schema is used for JSON-body login (mobile app flows).
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    email: EmailStr = Field(..., examples=["farmer@example.com"])
    password: str = Field(..., min_length=1)

    @field_validator("email", mode="before")
    @classmethod
    def normalise_email(cls, v: str) -> str:
        return v.lower().strip()


# ---------------------------------------------------------------------------
# Responses (never expose sensitive fields)
# ---------------------------------------------------------------------------

class UserResponse(BaseModel):
    """Public user representation returned from API endpoints.

    Note:
        ``hashed_password`` is intentionally absent.
        ``from_attributes=True`` allows construction from domain ``User`` objects.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str
    is_active: bool
    is_superuser: bool
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# JWT Token Response
# ---------------------------------------------------------------------------

class Token(BaseModel):
    """Response body for successful authentication."""

    access_token: str = Field(..., description="JWT access token.")
    refresh_token: str = Field(..., description="JWT refresh token.")
    token_type: str = Field(default="bearer")
    expires_in: int = Field(..., description="Access token lifetime in seconds.")


class RefreshTokenRequest(BaseModel):
    """Request body for POST /api/v1/users/refresh."""

    refresh_token: str = Field(..., description="JWT refresh token.")


class TokenData(BaseModel):
    """Internal model for decoded JWT payload — used in security dependency."""

    user_id: uuid.UUID
