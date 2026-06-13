"""
Security Utilities
===================
Centralizes all cryptographic operations:
    1. Password hashing & verification (Argon2 via passlib)
    2. JWT access token creation & decoding
    3. FastAPI dependency: ``get_current_user``

Zero-Trust Principles Applied:
    - Passwords are NEVER stored or logged in plain text.
    - JWTs have a short ``exp`` claim enforced on decode.
    - Decoding errors always raise 401 (never 500) — no internal details leaked.
    - ``get_current_user`` fetches the user from DB on every request to catch
      deactivated accounts even before the token expires.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import get_settings, Settings
from app.domain.entities.user import User

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Password Hashing — Argon2
# ---------------------------------------------------------------------------

# Argon2 is the winner of the Password Hashing Competition (PHC) and is
# strongly preferred over bcrypt for new systems.
# ``bcrypt`` is kept as a deprecated fallback to handle any legacy hashes.
_pwd_context = CryptContext(
    schemes=["argon2", "bcrypt"],
    deprecated="auto",
    argon2__memory_cost=65536,   # 64 MB RAM per hash (OWASP recommended)
    argon2__time_cost=3,         # 3 iterations
    argon2__parallelism=4,       # 4 parallel threads
)


def hash_password(plain_password: str) -> str:
    """Hash a plain-text password with Argon2.

    Args:
        plain_password: The raw password from the registration form.

    Returns:
        Argon2-hashed password string (safe to store in DB).
    """
    return _pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain-text password against its stored Argon2 hash.

    Args:
        plain_password:  Raw password from the login form.
        hashed_password: Stored hash from the database User record.

    Returns:
        True if the password matches, False otherwise.
    """
    return _pwd_context.verify(plain_password, hashed_password)


def needs_rehash(hashed_password: str) -> bool:
    """Check if a stored hash uses outdated parameters and needs upgrading.

    Returns True if the hash was created with old bcrypt or outdated Argon2
    parameters — the application layer should re-hash on successful login.
    """
    return _pwd_context.needs_update(hashed_password)


# ---------------------------------------------------------------------------
# JWT Tokens
# ---------------------------------------------------------------------------

# Token type constants
_TOKEN_TYPE_ACCESS = "access"
_TOKEN_TYPE_REFRESH = "refresh"

# OAuth2 bearer scheme — ``tokenUrl`` is the login endpoint path
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/users/login")


def create_access_token(
    subject: str | UUID,
    *,
    settings: Optional[Settings] = None,
    extra_claims: Optional[dict] = None,
) -> str:
    """Create a signed JWT access token.

    Args:
        subject:      The token subject — typically the user's UUID as a string.
        settings:     Settings instance (defaults to cached singleton).
        extra_claims: Optional additional claims merged into the payload.

    Returns:
        Signed JWT string.
    """
    cfg = settings or get_settings()
    now = datetime.now(tz=timezone.utc)
    expire = now + timedelta(minutes=cfg.ACCESS_TOKEN_EXPIRE_MINUTES)

    payload: dict = {
        "sub": str(subject),
        "type": _TOKEN_TYPE_ACCESS,
        "iat": now,
        "exp": expire,
    }
    if extra_claims:
        payload.update(extra_claims)

    return jwt.encode(payload, cfg.SECRET_KEY, algorithm=cfg.ALGORITHM)


def create_refresh_token(
    subject: str | UUID,
    *,
    settings: Optional[Settings] = None,
) -> str:
    """Create a signed JWT refresh token (longer-lived than access tokens).

    Args:
        subject:  User UUID as string.
        settings: Optional Settings override.

    Returns:
        Signed JWT refresh token string.
    """
    cfg = settings or get_settings()
    now = datetime.now(tz=timezone.utc)
    expire = now + timedelta(days=cfg.REFRESH_TOKEN_EXPIRE_DAYS)

    payload = {
        "sub": str(subject),
        "type": _TOKEN_TYPE_REFRESH,
        "iat": now,
        "exp": expire,
    }
    return jwt.encode(payload, cfg.SECRET_KEY, algorithm=cfg.ALGORITHM)


def decode_refresh_token(token: str, *, settings: Optional[Settings] = None) -> dict:
    """Decode and validate a JWT refresh token.

    Raises:
        HTTPException 401: If the token is expired, malformed, or has wrong type.
    """
    cfg = settings or get_settings()
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid refresh token.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, cfg.SECRET_KEY, algorithms=[cfg.ALGORITHM])
        if payload.get("type") != _TOKEN_TYPE_REFRESH:
            raise credentials_exception
        if "sub" not in payload:
            raise credentials_exception
        return payload
    except JWTError:
        logger.warning("Refresh token validation failed (JWTError).")
        raise credentials_exception


def decode_access_token(token: str, *, settings: Optional[Settings] = None) -> dict:
    """Decode and validate a JWT access token.

    Args:
        token:    Raw JWT string from the Authorization header.
        settings: Optional Settings override.

    Returns:
        Decoded payload dict (contains 'sub', 'exp', 'type', etc.).

    Raises:
        HTTPException 401: If the token is expired, malformed, or has wrong type.
    """
    cfg = settings or get_settings()
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, cfg.SECRET_KEY, algorithms=[cfg.ALGORITHM])
        if payload.get("type") != _TOKEN_TYPE_ACCESS:
            raise credentials_exception
        if "sub" not in payload:
            raise credentials_exception
        return payload
    except JWTError:
        # Never log the raw token — it may be used to impersonate a user
        logger.warning("JWT validation failed (JWTError).")
        raise credentials_exception


# ---------------------------------------------------------------------------
# FastAPI Dependencies
# ---------------------------------------------------------------------------

from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402
from app.infrastructure.db.session import get_async_session  # noqa: E402
from app.infrastructure.repositories.user_repository_impl import UserRepositoryImpl  # noqa: E402


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    session: AsyncSession = Depends(get_async_session),
) -> User:
    """FastAPI dependency: decode JWT and return the authenticated User entity.

    Uses the request-scoped AsyncSession from the shared connection pool
    (no new engine is created per request).

    Raises:
        HTTPException 401: If token is invalid or user not found.
        HTTPException 403: If the account is deactivated.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    payload = decode_access_token(token)
    user_id_str: str = payload.get("sub", "")

    try:
        user_uuid = UUID(user_id_str)
    except ValueError:
        raise credentials_exception

    repo = UserRepositoryImpl(session)
    user = await repo.get_by_id(user_uuid)

    if user is None:
        raise credentials_exception
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated.",
        )
    return user


async def get_current_superuser(
    current_user: User = Depends(get_current_user),
) -> User:
    """FastAPI dependency: require superuser (admin) privileges.

    Raises:
        HTTPException 403: If the user is not a superuser.
    """
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator privileges required.",
        )
    return current_user
