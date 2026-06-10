"""
Router: Parcel Analysis (AI Anomaly Detection)
=================================================
Endpoints:
    GET /api/v1/parcels/{parcel_id}/analysis — Run anomaly detection on NDVI data

Security:
    Requires JWT authentication. Only the parcel owner can analyze their parcels.

This is the **core innovation endpoint** of the Agromaly thesis. It exposes
the statistical anomaly detection model (future: LSTM Autoencoder) via a
clean REST API consumed by the mobile app.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from app.application.services.analysis_service import AnalysisService
from app.core.exceptions import ParcelNotFoundError, PermissionDeniedError
from app.core.security import get_current_user
from app.domain.entities.user import User
from app.presentation.api.v1.dependencies import get_analysis_service
from app.presentation.schemas.analysis import AnalysisResponse

router = APIRouter(prefix="/parcels", tags=["Analysis"])


@router.get(
    "/{parcel_id}/analysis",
    response_model=AnalysisResponse,
    summary="Run AI anomaly detection on a parcel's NDVI time-series",
    description=(
        "Analyzes the historical NDVI satellite data for the specified parcel "
        "using a statistical anomaly detection model (Modified Z-Score + MSE + "
        "trend analysis). Returns a composite anomaly score [0.0–1.0] and an "
        "agronomic recommendation.\n\n"
        "**Algorithm Overview:**\n"
        "1. Fetch all reliable (cloud_coverage < 20%) NDVI observations.\n"
        "2. Compute historical mean, std, and Modified Z-Score.\n"
        "3. Calculate linear trend over the last 5 observations.\n"
        "4. Weight deviation (50%) + trend (35%) + data quality (15%).\n"
        "5. Classify: composite ≥ 0.55 → ANOMALY_DETECTED.\n\n"
        "In production, this will be replaced by an LSTM Autoencoder."
    ),
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
    """Run anomaly detection on the specified parcel.

    Requires JWT authentication. The authenticated user must own the parcel.
    """
    try:
        result = await service.analyze_parcel(parcel_id, current_user)
        return AnalysisResponse.model_validate(result, from_attributes=True)
    except ParcelNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=exc.message,
        )
    except PermissionDeniedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=exc.message,
        )
