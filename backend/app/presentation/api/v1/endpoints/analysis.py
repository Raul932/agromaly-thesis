"""
Router: Parcel Analysis (AI Anomaly Detection)
=================================================
Endpoints:
    GET  /api/v1/parcels/{parcel_id}/analysis          — LSTM anomaly detection
    GET  /api/v1/parcels/{parcel_id}/alerts            — list anomaly alerts for parcel
    POST /api/v1/parcels/{parcel_id}/ai-recommendation — on-demand RAG recommendation

Security:
    JWT authentication required on all endpoints.
    Only the parcel owner can access their parcels.
"""

from __future__ import annotations

import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.analysis_service import (
    AnalysisService,
    _compute_anomaly_score,
    fetch_weather_forecast,
    fetch_weather_summary,
)
from app.application.services.rag_service import get_rag_service
from app.core.exceptions import ParcelNotFoundError, PermissionDeniedError, SatelliteAPIError
from app.core.security import get_current_user
from app.domain.entities.user import User
from app.infrastructure.db.session import get_async_session
from app.infrastructure.repositories.alert_repository_impl import AlertRepositoryImpl
from app.infrastructure.repositories.ndvi_record_repository_impl import NDVIRecordRepositoryImpl
from app.infrastructure.repositories.parcel_repository_impl import ParcelRepositoryImpl
from app.presentation.api.v1.dependencies import get_analysis_service
from app.presentation.schemas.alert import AlertResponse
from app.presentation.schemas.analysis import (
    AnalysisResponse,
    ForecastResponse,
    NdviImageResponse,
)
from app.presentation.schemas.chat import ChatResponse

router = APIRouter(prefix="/parcels", tags=["Analysis"])


# ---------------------------------------------------------------------------
# Dependency helpers (request-scoped repos not wired through the main DI file)
# ---------------------------------------------------------------------------

def _alert_repo(session: AsyncSession = Depends(get_async_session)) -> AlertRepositoryImpl:
    return AlertRepositoryImpl(session)


def _parcel_repo(session: AsyncSession = Depends(get_async_session)) -> ParcelRepositoryImpl:
    return ParcelRepositoryImpl(session)


def _ndvi_repo(session: AsyncSession = Depends(get_async_session)) -> NDVIRecordRepositoryImpl:
    return NDVIRecordRepositoryImpl(session)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/{parcel_id}/analysis",
    response_model=AnalysisResponse,
    summary="Run AI anomaly detection on a parcel's NDVI time-series",
    responses={
        200: {"description": "Analysis completed successfully"},
        401: {"description": "Not authenticated"},
        403: {"description": "Not authorized to access this parcel"},
        404: {"description": "Parcel not found"},
    },
)
async def analyze_parcel(
    parcel_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    service: AnalysisService = Depends(get_analysis_service),
) -> AnalysisResponse:
    try:
        result = await service.analyze_parcel(parcel_id, current_user)
        return AnalysisResponse.model_validate(result, from_attributes=True)
    except ParcelNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.message)
    except PermissionDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=exc.message)


@router.get(
    "/{parcel_id}/alerts",
    response_model=List[AlertResponse],
    summary="List anomaly alerts for a specific parcel (newest first)",
    responses={
        200: {"description": "Alert list (may be empty)"},
        401: {"description": "Not authenticated"},
        403: {"description": "Not authorized"},
        404: {"description": "Parcel not found"},
    },
)
async def list_parcel_alerts(
    parcel_id: uuid.UUID,
    limit: int = Query(10, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    alert_repo: AlertRepositoryImpl = Depends(_alert_repo),
    parcel_repo: ParcelRepositoryImpl = Depends(_parcel_repo),
) -> List[AlertResponse]:
    parcel = await parcel_repo.get_by_id(parcel_id)
    if parcel is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Parcel not found.")
    if parcel.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")

    alerts = await alert_repo.list_for_parcel(parcel_id, limit=limit)
    return [
        AlertResponse(
            id=alert.id,
            parcel_id=alert.parcel_id,
            parcel_name=parcel.name,
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
        for alert in alerts
    ]


@router.get(
    "/{parcel_id}/ndvi-image",
    response_model=NdviImageResponse,
    summary="Get a colored NDVI spatial heatmap image for a parcel",
    description=(
        "Returns a base64-encoded PNG that color-codes every pixel of the parcel "
        "by NDVI value: red (bare/dead), orange (stressed), yellow (moderate), "
        "green (healthy). In mock mode the image is synthetically generated from "
        "the parcel's latest mean NDVI with Gaussian spatial variation."
    ),
    responses={
        200: {"description": "PNG image + bounding box"},
        401: {"description": "Not authenticated"},
        403: {"description": "Not authorized"},
        404: {"description": "Parcel not found"},
    },
)
async def get_ndvi_image(
    parcel_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    service: AnalysisService = Depends(get_analysis_service),
) -> NdviImageResponse:
    try:
        result = await service.get_ndvi_image(parcel_id, current_user.id)
        return NdviImageResponse(
            image_base64=result["image_base64"],
            bounds=result["bounds"],
        )
    except ParcelNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.message)
    except PermissionDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=exc.message)
    except SatelliteAPIError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        )


@router.post(
    "/{parcel_id}/ai-recommendation",
    response_model=ChatResponse,
    summary="Generate an on-demand RAG recommendation for a parcel",
    description=(
        "Calls the RAG pipeline with the parcel's current NDVI metrics and 30-day "
        "weather history to produce a 3-paragraph agronomic recommendation. "
        "The result is NOT persisted — use the alerts endpoint to retrieve "
        "previously saved recommendations from the Celery anomaly task."
    ),
    responses={
        200: {"description": "Recommendation generated"},
        401: {"description": "Not authenticated"},
        403: {"description": "Not authorized"},
        404: {"description": "Parcel not found"},
        503: {"description": "RAG service not available"},
    },
)
async def generate_ai_recommendation(
    parcel_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    parcel_repo: ParcelRepositoryImpl = Depends(_parcel_repo),
    ndvi_repo: NDVIRecordRepositoryImpl = Depends(_ndvi_repo),
) -> ChatResponse:
    parcel = await parcel_repo.get_by_id(parcel_id)
    if parcel is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Parcel not found.")
    if parcel.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")

    rag = get_rag_service()
    if rag is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI service is not available. OPENAI_API_KEY is not configured.",
        )

    # Build NDVI context
    all_records = await ndvi_repo.list_by_parcel(parcel_id, limit=100)
    reliable = [r for r in all_records if r.is_reliable]
    total = len(all_records)
    cloud_gap = (total - len(reliable)) / total if total > 0 else 0.0

    crop = parcel.crop_type
    crop_str = crop.value if hasattr(crop, "value") else str(crop)

    weather_summary = await fetch_weather_summary(parcel)

    if len(reliable) >= 3:
        result = _compute_anomaly_score(reliable, cloud_gap, weather_summary)
        parcel_context = {
            "name": parcel.name,
            "crop_type": crop_str,
            "area_ha": round(getattr(parcel, "area_ha", 0) or 0, 2),
            "ndvi_current": result.get("ndvi_current"),
            "ndvi_mean": result.get("ndvi_mean"),
            "ndvi_std": result.get("ndvi_std"),
            "ndvi_trend": result.get("ndvi_trend"),
            "anomaly_score": result.get("anomaly_score"),
            "anomaly_status": result.get("status"),
        }
    else:
        parcel_context = {
            "name": parcel.name,
            "crop_type": crop_str,
            "area_ha": round(getattr(parcel, "area_ha", 0) or 0, 2),
            "ndvi_current": "N/A",
            "ndvi_mean": "N/A",
            "ndvi_std": "N/A",
            "ndvi_trend": "N/A",
            "anomaly_score": "N/A",
            "anomaly_status": "INSUFFICIENT_DATA",
        }

    try:
        recommendation = await rag.generate_anomaly_recommendation(parcel_context, weather_summary)
    except Exception as exc:
        name = type(exc).__name__
        msg = str(exc)
        if "insufficient_quota" in msg or "RateLimitError" in name:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="OpenAI quota exceeded. Please add credits at platform.openai.com/settings/billing.",
            )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"AI service error: {name}",
        )

    return ChatResponse(answer=recommendation)


@router.get(
    "/{parcel_id}/forecast",
    response_model=ForecastResponse,
    summary="Get the 7-day weather forecast for a parcel",
    description=(
        "Returns the next 7 days of weather for the parcel centroid (Open-Meteo) "
        "with plain-language Romanian warnings for frost, heavy rain, heat and wind."
    ),
    responses={
        200: {"description": "Forecast (may be empty if the weather API fails)"},
        401: {"description": "Not authenticated"},
        403: {"description": "Not authorized"},
        404: {"description": "Parcel not found"},
    },
)
async def get_parcel_forecast(
    parcel_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    parcel_repo: ParcelRepositoryImpl = Depends(_parcel_repo),
) -> ForecastResponse:
    parcel = await parcel_repo.get_by_id(parcel_id)
    if parcel is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Parcela nu a fost găsită.")
    if parcel.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acces interzis.")

    data = await fetch_weather_forecast(parcel)
    return ForecastResponse(days=data["days"], warnings=data["warnings"])


@router.post(
    "/{parcel_id}/weekly-advice",
    response_model=ChatResponse,
    summary="Generate AI field-operations advice for the coming week",
    description=(
        "Combines the parcel's current state with the 7-day forecast and asks the "
        "RAG agronomist for a concrete weekly work plan (spraying windows, irrigation, "
        "frost protection, harvesting) in Romanian."
    ),
    responses={
        200: {"description": "Weekly advice generated"},
        401: {"description": "Not authenticated"},
        403: {"description": "Not authorized"},
        404: {"description": "Parcel not found"},
        503: {"description": "RAG service not available"},
    },
)
async def generate_weekly_advice(
    parcel_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    parcel_repo: ParcelRepositoryImpl = Depends(_parcel_repo),
    ndvi_repo: NDVIRecordRepositoryImpl = Depends(_ndvi_repo),
) -> ChatResponse:
    parcel = await parcel_repo.get_by_id(parcel_id)
    if parcel is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Parcela nu a fost găsită.")
    if parcel.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acces interzis.")

    rag = get_rag_service()
    if rag is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Serviciul AI nu este disponibil. OPENAI_API_KEY nu este configurat.",
        )

    crop = parcel.crop_type
    crop_str = crop.value if hasattr(crop, "value") else str(crop)

    # Build current field state from NDVI (best-effort)
    all_records = await ndvi_repo.list_by_parcel(parcel_id, limit=100)
    reliable = [r for r in all_records if r.is_reliable]
    total = len(all_records)
    cloud_gap = (total - len(reliable)) / total if total > 0 else 0.0

    if len(reliable) >= 3:
        result = _compute_anomaly_score(reliable, cloud_gap, weather={})
        parcel_context = {
            "name": parcel.name,
            "crop_type": crop_str,
            "area_ha": round(getattr(parcel, "area_ha", 0) or 0, 2),
            "ndvi_current": result.get("ndvi_current"),
            "ndvi_mean": result.get("ndvi_mean"),
            "ndvi_std": result.get("ndvi_std"),
            "ndvi_trend": result.get("ndvi_trend"),
            "anomaly_score": result.get("anomaly_score"),
            "anomaly_status": result.get("status"),
        }
    else:
        parcel_context = {
            "name": parcel.name,
            "crop_type": crop_str,
            "area_ha": round(getattr(parcel, "area_ha", 0) or 0, 2),
            "anomaly_status": "INSUFFICIENT_DATA",
        }

    # Build the forecast summary text
    forecast = await fetch_weather_forecast(parcel)
    if forecast["days"]:
        lines = [
            f"{d['weekday']}: max {d['temp_max_c']}°C, min {d['temp_min_c']}°C, "
            f"ploaie {d['precipitation_mm']}mm, vânt {d['wind_speed_kmh']}km/h"
            for d in forecast["days"]
        ]
        forecast_summary = "\n".join(lines)
        if forecast["warnings"]:
            forecast_summary += "\nAvertizări: " + "; ".join(forecast["warnings"])
    else:
        forecast_summary = "Prognoză indisponibilă."

    try:
        advice = await rag.generate_weekly_advice(parcel_context, forecast_summary)
    except Exception as exc:
        name = type(exc).__name__
        msg = str(exc)
        if "insufficient_quota" in msg or "RateLimitError" in name:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Cota OpenAI a fost depășită. Adaugă credite la platform.openai.com/settings/billing.",
            )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Eroare la serviciul AI: {name}",
        )

    return ChatResponse(answer=advice)
