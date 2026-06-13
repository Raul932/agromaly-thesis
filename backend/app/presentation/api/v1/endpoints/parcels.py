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

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status, Response

logger = logging.getLogger(__name__)

from app.application.services.parcel_service import ParcelService
from app.core.exceptions import (
    InvalidGeometryError,
    ParcelAlreadyExistsError,
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
        409: {"description": "A parcel with this name already exists"},
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
    except ParcelAlreadyExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=exc.message,
        )
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


@router.post(
    "/sync-all",
    summary="Sync NDVI + weather for all parcels owned by the current user",
    responses={
        200: {"description": "Sync complete summary"},
        401: {"description": "Not authenticated"},
    },
)
async def sync_all_parcels(
    current_user: User = Depends(get_current_user),
    service: ParcelService = Depends(get_parcel_service),
) -> dict:
    """Run NDVI + weather sync for every active parcel owned by the current user.

    Parcels synced within the last 24 hours are skipped (same rate-limit as
    the per-parcel endpoint).  All eligible parcels are synced concurrently.
    """
    import asyncio
    from datetime import datetime, timezone, timedelta
    from app.application.tasks.sync_ndvi_tasks import _async_sync_ndvi
    from app.application.tasks.sync_weather_tasks import _async_sync_weather

    result = await service.list_owner_parcels(owner=current_user, limit=200, offset=0)
    now = datetime.now(tz=timezone.utc)

    eligible = [
        p for p in result.items
        if p.last_ndvi_at is None
        or (now - p.last_ndvi_at) >= timedelta(hours=24)
    ]

    if not eligible:
        return {
            "message": "All parcels were synced recently. No action needed.",
            "synced": 0,
            "skipped": len(result.items),
            "records_saved": 0,
        }

    parcel_id_strs = [str(p.id) for p in eligible]

    ndvi_results = await asyncio.gather(
        *[_async_sync_ndvi(pid) for pid in parcel_id_strs],
        return_exceptions=True,
    )
    await asyncio.gather(
        *[_async_sync_weather(pid) for pid in parcel_id_strs],
        return_exceptions=True,
    )

    total_records = sum(
        r.get("records_saved", 0) if isinstance(r, dict) else 0
        for r in ndvi_results
    )
    failed = sum(1 for r in ndvi_results if isinstance(r, Exception))

    msg = f"Sync complete. {len(eligible)} parcels processed"
    if total_records:
        msg += f", {total_records} NDVI records saved"
    if failed:
        msg += f" ({failed} failed)"
    msg += "."

    return {
        "message": msg,
        "synced": len(eligible),
        "skipped": len(result.items) - len(eligible),
        "records_saved": total_records,
    }


@router.post(
    "/{parcel_id}/sync",
    summary="Queue NDVI + weather sync tasks for a specific parcel",
    responses={
        200: {"description": "Sync tasks queued, or skipped if synced within 24h"},
        401: {"description": "Not authenticated"},
        403: {"description": "Access denied"},
        404: {"description": "Parcel not found"},
    },
)
async def sync_parcel(
    parcel_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    service: ParcelService = Depends(get_parcel_service),
) -> dict:
    """Queue NDVI satellite and weather re-sync for a parcel.

    Returns 202 immediately — the actual sync runs in a Celery worker.
    Pull to refresh the analysis screen after ~30 seconds.
    """
    try:
        parcel = await service.get_parcel(parcel_id, owner=current_user)
    except ParcelNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.message)
    except PermissionDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=exc.message)

    # Rate-limit: do not re-sync if data was fetched within the last 24 hours.
    # Sentinel-2 revisit cycle is ~5 days, so syncing more often than daily
    # would only waste API quota and create no new records.
    from datetime import datetime, timezone, timedelta
    if parcel.last_ndvi_at is not None:
        age = datetime.now(tz=timezone.utc) - parcel.last_ndvi_at
        if age < timedelta(hours=24):
            hours_left = max(1, int((timedelta(hours=24) - age).total_seconds() / 3600))
            return {
                "message": f"Already synced recently. Next sync available in ~{hours_left}h.",
                "recently_synced": True,
                "records_saved": 0,
            }

    # Run NDVI sync directly (synchronous, no Celery worker required).
    # This guarantees data is available immediately when the client refreshes.
    # Celery Beat still handles scheduled periodic syncs for all parcels.
    from app.application.tasks.sync_ndvi_tasks import _async_sync_ndvi
    from app.application.tasks.sync_weather_tasks import _async_sync_weather

    parcel_id_str = str(parcel_id)
    try:
        ndvi_result = await _async_sync_ndvi(parcel_id_str)
        records_saved = ndvi_result.get("records_saved", 0)
    except Exception as exc:
        logger.warning("NDVI sync failed for parcel %s: %s", parcel_id_str, exc)
        records_saved = 0

    # Fire-and-forget weather sync (non-blocking, best-effort)
    try:
        await _async_sync_weather(parcel_id_str)
    except Exception as exc:
        logger.debug("Weather sync failed for parcel %s: %s", parcel_id_str, exc)

    msg = (
        f"Sync complete. {records_saved} NDVI records saved."
        if records_saved > 0
        else "Sync complete. No new satellite records (data already up to date or API unavailable)."
    )
    return {
        "message": msg,
        "recently_synced": False,
        "records_saved": records_saved,
    }


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
