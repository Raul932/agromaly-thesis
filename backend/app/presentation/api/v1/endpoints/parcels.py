"""
Router: Parcels
================
Endpoints:
    POST   /api/v1/parcels           — Create a new parcel
    GET    /api/v1/parcels           — List all parcels for the current user
    GET    /api/v1/parcels/{id}      — Get a single parcel (ownership enforced)
    PATCH  /api/v1/parcels/{id}      — Update parcel metadata
    DELETE /api/v1/parcels/{id}      — Delete a parcel (cascade)

Security:
    ALL endpoints require a valid JWT (``get_current_user`` dependency).
    Ownership is enforced inside ``ParcelService`` — users cannot access
    parcels owned by other users.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status, Response

from app.application.services.parcel_service import ParcelService
from app.core.exceptions import (
    InvalidGeometryError,
    ParcelNotFoundError,
    PermissionDeniedError,
)
from app.core.security import get_current_user
from app.domain.entities.parcel import CropType, ParcelStatus
from app.domain.entities.user import User
from app.presentation.api.v1.dependencies import get_parcel_service
from app.presentation.schemas.parcel import (
    ParcelCreate,
    ParcelListResponse,
    ParcelResponse,
    ParcelUpdate,
)

router = APIRouter(prefix="/parcels", tags=["Parcels"])


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post(
    "",
    response_model=ParcelResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new agricultural parcel",
    responses={
        400: {"description": "Invalid GeoJSON geometry"},
        401: {"description": "Not authenticated"},
        422: {"description": "Validation error"},
    },
)
async def create_parcel(
    payload: ParcelCreate,
    current_user: User = Depends(get_current_user),
    service: ParcelService = Depends(get_parcel_service),
) -> ParcelResponse:
    """Create a new georeferenced agricultural parcel.

    - Accepts a GeoJSON Polygon or MultiPolygon in WGS84 (EPSG:4326).
    - Area is auto-computed from geometry if not provided.
    - The parcel is immediately set to ACTIVE status.
    """
    try:
        parcel = await service.create_parcel(payload, owner=current_user)
        return ParcelResponse.model_validate(parcel, from_attributes=True)
    except InvalidGeometryError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=exc.message,
        )


@router.get(
    "",
    response_model=ParcelListResponse,
    summary="List all parcels for the current user",
    responses={401: {"description": "Not authenticated"}},
)
async def list_parcels(
    current_user: User = Depends(get_current_user),
    service: ParcelService = Depends(get_parcel_service),
    status_filter: ParcelStatus | None = Query(
        default=None,
        alias="status",
        description="Filter by parcel lifecycle status.",
    ),
    crop_type: CropType | None = Query(
        default=None,
        description="Filter by crop type.",
    ),
    limit: int = Query(default=50, ge=1, le=200, description="Page size."),
    offset: int = Query(default=0, ge=0, description="Pagination offset."),
) -> ParcelListResponse:
    """Return a paginated list of all parcels owned by the current user.

    Supports optional filtering by ``status`` and ``crop_type``.
    Response includes ``total`` count for pagination controls.
    """
    return await service.list_owner_parcels(
        owner=current_user,
        status=status_filter,
        crop_type=crop_type,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{parcel_id}",
    response_model=ParcelResponse,
    summary="Get a single parcel by ID",
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Access denied (not your parcel)"},
        404: {"description": "Parcel not found"},
    },
)
async def get_parcel(
    parcel_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    service: ParcelService = Depends(get_parcel_service),
) -> ParcelResponse:
    """Retrieve a specific parcel. Returns 403 if not owned by the current user."""
    try:
        parcel = await service.get_parcel(parcel_id, owner=current_user)
        return ParcelResponse.model_validate(parcel, from_attributes=True)
    except ParcelNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.message)
    except PermissionDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=exc.message)


@router.patch(
    "/{parcel_id}",
    response_model=ParcelResponse,
    summary="Update parcel metadata (name, description, crop_type)",
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Access denied"},
        404: {"description": "Parcel not found"},
    },
)
async def update_parcel(
    parcel_id: uuid.UUID,
    payload: ParcelUpdate,
    current_user: User = Depends(get_current_user),
    service: ParcelService = Depends(get_parcel_service),
) -> ParcelResponse:
    """Partially update a parcel. Only provided fields are changed."""
    try:
        parcel = await service.update_parcel(parcel_id, payload, owner=current_user)
        return ParcelResponse.model_validate(parcel, from_attributes=True)
    except ParcelNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.message)
    except PermissionDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=exc.message)


@router.delete(
    "/{parcel_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,          # Explicitly suppress body — required for HTTP 204
    response_class=Response,
    summary="Delete a parcel and all its associated data",
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Access denied"},
        404: {"description": "Parcel not found"},
    },
)
async def delete_parcel(
    parcel_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    service: ParcelService = Depends(get_parcel_service),
) -> Response:
    """Hard-delete a parcel. Cascades to NDVI records, forecasts, and alerts."""
    try:
        await service.delete_parcel(parcel_id, owner=current_user)
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except ParcelNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.message)
    except PermissionDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=exc.message)
