"""
Application Service: UserService
==================================
Orchestrates user registration and authentication use cases.

Depends on:
    - ``IUserRepository`` (abstract) — never the concrete SQLAlchemy class.
    - ``hash_password`` / ``verify_password`` from ``app.core.security``.

Clean Architecture Guarantee:
    This service knows nothing about HTTP, FastAPI, or SQLAlchemy.
    It communicates purely through domain entities and domain exceptions.
"""

from __future__ import annotations

import logging

from app.core.exceptions import (
    EmailAlreadyRegisteredError,
    PermissionDeniedError,
    UserNotFoundError,
)
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    needs_rehash,
    verify_password,
)
from app.domain.entities.user import User
from app.domain.interfaces.user_repository import IUserRepository
from app.presentation.schemas.user import Token, UserCreate, UserLogin

logger = logging.getLogger(__name__)


class UserService:
    """Use cases related to user lifecycle and authentication.

    Args:
        user_repo: Injected abstract repository (concrete impl injected by FastAPI DI).
    """

    def __init__(self, user_repo: IUserRepository) -> None:
        self._user_repo = user_repo

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    async def register(self, payload: UserCreate) -> User:
        """Register a new farmer/user account.

        Flow:
            1. Check email uniqueness (raises ``EmailAlreadyRegisteredError`` if taken).
            2. Hash the password with Argon2.
            3. Build a ``User`` domain entity (all invariants validated).
            4. Persist via the repository.

        Args:
            payload: Validated ``UserCreate`` schema from the router.

        Returns:
            Newly created ``User`` domain entity (no password field).

        Raises:
            EmailAlreadyRegisteredError: If the email is already taken.
        """
        logger.info("Registration attempt for email=%s", payload.email)

        if await self._user_repo.exists_by_email(payload.email):
            logger.warning("Registration rejected — email already exists: %s", payload.email)
            raise EmailAlreadyRegisteredError(
                f"Email '{payload.email}' is already registered."
            )

        hashed = hash_password(payload.password)

        new_user = User(
            email=payload.email,
            hashed_password=hashed,
            full_name=payload.full_name,
            is_active=True,
            is_superuser=False,
        )

        saved = await self._user_repo.save(new_user)
        logger.info("User registered successfully: id=%s email=%s", saved.id, saved.email)
        return saved

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    async def authenticate(self, payload: UserLogin) -> Token:
        """Verify credentials and issue JWT tokens.

        Flow:
            1. Fetch user by email (raises 401-equivalent on not found).
            2. Verify Argon2 password hash.
            3. Check account is active.
            4. Optionally re-hash if stored hash uses outdated parameters.
            5. Return access + refresh JWT pair.

        Args:
            payload: Validated ``UserLogin`` schema.

        Returns:
            ``Token`` schema containing access_token, refresh_token, etc.

        Raises:
            PermissionDeniedError: If credentials are wrong or account is inactive.
        """
        _AUTH_FAIL_MSG = "Invalid email or password."

        user = await self._user_repo.get_by_email(payload.email)
        if user is None:
            # Constant-time: still run password verify to prevent timing attacks
            verify_password(payload.password, "$argon2id$v=19$m=65536,t=3,p=4$placeholder")
            logger.warning("Auth failed — unknown email: %s", payload.email)
            raise PermissionDeniedError(_AUTH_FAIL_MSG)

        if not verify_password(payload.password, user.hashed_password):
            logger.warning("Auth failed — bad password for user id=%s", user.id)
            raise PermissionDeniedError(_AUTH_FAIL_MSG)

        if not user.is_active:
            raise PermissionDeniedError("Account is suspended.")

        # Upgrade hash if needed (transparent re-hashing on login)
        if needs_rehash(user.hashed_password):
            logger.info("Re-hashing outdated password for user id=%s", user.id)
            upgraded = user.update_password(hash_password(payload.password))
            await self._user_repo.save(upgraded)

        from app.core.config import settings
        access_token = create_access_token(str(user.id))
        refresh_token = create_refresh_token(str(user.id))

        logger.info("User authenticated: id=%s", user.id)
        return Token(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def get_profile(self, user_id_str: str) -> User:
        """Retrieve user profile by UUID string (from JWT sub claim).

        Args:
            user_id_str: UUID string extracted from a decoded JWT.

        Returns:
            User domain entity.

        Raises:
            UserNotFoundError: If the user no longer exists in the DB.
        """
        import uuid as _uuid
        try:
            user_uuid = _uuid.UUID(user_id_str)
        except ValueError as exc:
            raise UserNotFoundError("Invalid user ID format.") from exc

        user = await self._user_repo.get_by_id(user_uuid)
        if user is None:
            raise UserNotFoundError(f"User id={user_id_str} not found.")
        return user
