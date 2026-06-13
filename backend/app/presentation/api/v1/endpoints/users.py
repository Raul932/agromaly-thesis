"""
Router: Users
==============
Endpoints:
    POST /api/v1/users/signup    — Create a new account (mobile-friendly alias)
    POST /api/v1/users/register  — Create a new account (API / Swagger alias)
    POST /api/v1/users/login     — Authenticate and receive JWT tokens
    GET  /api/v1/users/me        — Fetch the current user's profile (protected)

Security:
    - ``/signup``, ``/register``, and ``/login`` are public (no auth required).
    - ``/me`` requires a valid JWT via ``get_current_user`` dependency.
    - Passwords are NEVER echoed in any response.
    - Domain exceptions are mapped to structured HTTP responses in ``main.py``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from app.application.services.user_service import UserService
from app.core.exceptions import (
    EmailAlreadyRegisteredError,
    PermissionDeniedError,
    UserNotFoundError,
)
from app.core.security import decode_refresh_token, get_current_user
from app.domain.entities.user import User
from app.presentation.api.v1.dependencies import get_user_service
from app.presentation.schemas.user import RefreshTokenRequest, Token, UserCreate, UserLogin, UserResponse

router = APIRouter(prefix="/users", tags=["Users"])


# ---------------------------------------------------------------------------
# Public Endpoints
# ---------------------------------------------------------------------------

async def _register_user(
    payload: UserCreate,
    service: UserService,
) -> UserResponse:
    """Shared handler for both /signup and /register."""
    try:
        user = await service.register(payload)
        return UserResponse.model_validate(user, from_attributes=True)
    except EmailAlreadyRegisteredError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=exc.message,
        )


@router.post(
    "/signup",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Sign up — create a new user account (mobile-friendly)",
    responses={
        400: {"description": "Email already registered"},
        422: {"description": "Validation error"},
    },
)
async def signup(
    payload: UserCreate,
    service: UserService = Depends(get_user_service),
) -> UserResponse:
    """Mobile-friendly sign-up endpoint.

    Identical to ``/register`` but returns HTTP 400 (instead of 409) so that
    Flutter HTTP clients can handle the duplicate-email case consistently.

    - Validates email format and password strength (min 8 chars, 1 digit, 1 letter).
    - Hashes password with Argon2 before storage.
    - Returns the created user (without ``hashed_password``).
    """
    return await _register_user(payload, service)


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user account",
    responses={
        409: {"description": "Email already registered"},
        422: {"description": "Validation error"},
    },
)
async def register(
    payload: UserCreate,
    service: UserService = Depends(get_user_service),
) -> UserResponse:
    """Create a new farmer/agronomist account.

    - Validates email format and password strength.
    - Hashes password with Argon2 before storage.
    - Returns the created user (without `hashed_password`).
    """
    try:
        user = await service.register(payload)
        return UserResponse.model_validate(user, from_attributes=True)
    except EmailAlreadyRegisteredError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=exc.message,
        )


@router.post(
    "/login",
    response_model=Token,
    summary="Authenticate and receive JWT tokens",
    description=(
        "Accepts **form data** (`application/x-www-form-urlencoded`). "
        "Use the `username` field for the email address. "
        "This is compatible with the Swagger UI **Authorize** button."
    ),
    responses={
        401: {"description": "Invalid email or password"},
        403: {"description": "Account is deactivated"},
    },
)
async def login(
    form: OAuth2PasswordRequestForm = Depends(),
    service: UserService = Depends(get_user_service),
) -> Token:
    """Authenticate with email + password (form data) and receive JWT tokens.

    - ``username``: the user's email address
    - ``password``: the user's password

    Returns ``access_token`` and ``refresh_token``.
    Include the access token in subsequent requests as:
        ``Authorization: Bearer <access_token>``
    """
    try:
        payload = UserLogin(email=form.username, password=form.password)
        return await service.authenticate(payload)
    except PermissionDeniedError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=exc.message,
            headers={"WWW-Authenticate": "Bearer"},
        )


@router.post(
    "/refresh",
    response_model=Token,
    summary="Refresh JWT access token",
    responses={
        401: {"description": "Invalid or expired refresh token"},
    },
)
async def refresh_token(
    body: RefreshTokenRequest,
    service: UserService = Depends(get_user_service),
) -> Token:
    """Exchange a valid refresh token for a new access + refresh token pair."""
    payload = decode_refresh_token(body.refresh_token)
    try:
        return await service.refresh(payload["sub"])
    except (UserNotFoundError, PermissionDeniedError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=exc.message,
            headers={"WWW-Authenticate": "Bearer"},
        )


# ---------------------------------------------------------------------------
# Protected Endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get the current user's profile",
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Account deactivated"},
    },
)
async def get_me(
    current_user: User = Depends(get_current_user),
) -> UserResponse:
    """Return the authenticated user's profile.

    Requires a valid ``Authorization: Bearer <token>`` header.
    """
    return UserResponse.model_validate(current_user, from_attributes=True)
