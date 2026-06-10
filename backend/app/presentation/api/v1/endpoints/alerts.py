"""
Router: Alerts
================
Endpoints:
    GET  /api/v1/alerts             — list user's alerts (newest first)
    GET  /api/v1/alerts/unread-count — badge count
    PATCH /api/v1/alerts/{id}/read  — mark single alert as read
    POST /api/v1/alerts/read-all    — mark all as read

All endpoints require JWT authentication.
"""

from __future__ import annotations

import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.domain.entities.user import User
from app.infrastructure.db.session import get_async_session
from app.infrastructure.repositories.alert_repository_impl import AlertRepositoryImpl
from app.infrastructure.repositories.parcel_repository_impl import ParcelRepositoryImpl
from app.presentation.schemas.alert import AlertResponse, UnreadCountResponse

router = APIRouter(prefix="/alerts", tags=["Alerts"])


def _get_alert_repo(session: AsyncSession = Depends(get_async_session)) -> AlertRepositoryImpl:
    return AlertRepositoryImpl(session)


def _get_parcel_repo(session: AsyncSession = Depends(get_async_session)) -> ParcelRepositoryImpl:
    return ParcelRepositoryImpl(session)


async def _to_response(alert, parcel_repo: ParcelRepositoryImpl) -> AlertResponse:
    """Convert domain Alert to AlertResponse, joining parcel name."""
    parcel = await parcel_repo.get_by_id(alert.parcel_id)
    parcel_name = parcel.name if parcel else "Unknown Parcel"
    return AlertResponse(
        id=alert.id,
        parcel_id=alert.parcel_id,
        parcel_name=parcel_name,
        alert_type=alert.alert_type.value,
        severity=alert.severity.value,
        title=alert.title,
        description=alert.description,
        ai_recommendation=alert.ai_recommendation,
        is_read=alert.is_read,
        created_at=alert.created_at,
        read_at=alert.read_at,
        triggered_value=alert.triggered_value,
        threshold_value=alert.threshold_value,
    )


@router.get(
    "",
    response_model=List[AlertResponse],
    summary="List alerts for the authenticated user",
)
async def list_alerts(
    unread_only: bool = Query(False, description="Return only unread alerts"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    alert_repo: AlertRepositoryImpl = Depends(_get_alert_repo),
    parcel_repo: ParcelRepositoryImpl = Depends(_get_parcel_repo),
) -> List[AlertResponse]:
    alerts = await alert_repo.list_for_user(
        current_user.id,
        unread_only=unread_only,
        limit=limit,
        offset=offset,
    )
    result = []
    for alert in alerts:
        result.append(await _to_response(alert, parcel_repo))
    return result


@router.get(
    "/unread-count",
    response_model=UnreadCountResponse,
    summary="Count unread alerts (mobile badge count)",
)
async def unread_count(
    current_user: User = Depends(get_current_user),
    alert_repo: AlertRepositoryImpl = Depends(_get_alert_repo),
) -> UnreadCountResponse:
    count = await alert_repo.count_unread(current_user.id)
    return UnreadCountResponse(count=count)


@router.patch(
    "/{alert_id}/read",
    response_model=AlertResponse,
    summary="Mark a single alert as read",
)
async def mark_as_read(
    alert_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    alert_repo: AlertRepositoryImpl = Depends(_get_alert_repo),
    parcel_repo: ParcelRepositoryImpl = Depends(_get_parcel_repo),
    session: AsyncSession = Depends(get_async_session),
) -> AlertResponse:
    # Ownership check: alert must belong to a parcel owned by the current user
    alert = await alert_repo.get_by_id(alert_id)
    if alert is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found.")

    parcel = await parcel_repo.get_by_id(alert.parcel_id)
    if parcel is None or parcel.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")

    updated = await alert_repo.mark_as_read(alert_id)
    if updated is None:
        # Already read — return as-is
        updated = alert
    await session.commit()
    return await _to_response(updated, parcel_repo)


@router.post(
    "/read-all",
    response_model=UnreadCountResponse,
    summary="Mark all alerts as read",
)
async def mark_all_as_read(
    current_user: User = Depends(get_current_user),
    alert_repo: AlertRepositoryImpl = Depends(_get_alert_repo),
    session: AsyncSession = Depends(get_async_session),
) -> UnreadCountResponse:
    count = await alert_repo.mark_all_as_read(current_user.id)
    await session.commit()
    return UnreadCountResponse(count=count)
