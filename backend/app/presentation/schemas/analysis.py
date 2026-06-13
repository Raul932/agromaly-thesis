"""
Pydantic Schemas: Anomaly Analysis
=====================================
Request/Response models for the analysis endpoints.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class NdviBoundsSchema(BaseModel):
    north: float
    south: float
    east: float
    west: float


class NdviImageResponse(BaseModel):
    """Response for GET /parcels/{parcel_id}/ndvi-image."""
    image_base64: str = Field(..., description="PNG image encoded as base64 string.")
    bounds: NdviBoundsSchema = Field(
        ..., description="Geographic bounding box of the image."
    )


class AnalysisResponse(BaseModel):
    """JSON response for the anomaly detection analysis endpoint.

    This schema is designed for direct consumption by the mobile app,
    with fields optimized for card-based UI display.
    """

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "parcel_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                "parcel_name": "North Field - Wheat",
                "status": "ANOMALY_DETECTED",
                "anomaly_score": 0.72,
                "mse_score": 0.0234,
                "z_score": -2.14,
                "ndvi_current": 0.32,
                "ndvi_mean": 0.58,
                "ndvi_std": 0.12,
                "ndvi_trend": -0.0145,
                "records_analyzed": 18,
                "cloud_gap_ratio": 0.22,
                "recommendation": (
                    "🟠 SIGNIFICANT ANOMALY DETECTED. Current NDVI (0.320) is "
                    "44.8% below the historical average (0.580)."
                ),
            }
        },
    )

    parcel_id: uuid.UUID = Field(
        ..., description="UUID of the analyzed parcel."
    )
    parcel_name: str = Field(
        ..., description="Human-readable parcel name."
    )
    status: str = Field(
        ...,
        description="Detection result: ANOMALY_DETECTED | HEALTHY | INSUFFICIENT_DATA",
        pattern=r"^(ANOMALY_DETECTED|HEALTHY|INSUFFICIENT_DATA)$",
    )
    anomaly_score: float = Field(
        ...,
        ge=0.0, le=1.0,
        description="Composite anomaly metric [0.0–1.0]. Above 0.55 = anomaly.",
    )
    mse_score: float = Field(
        ...,
        ge=0.0,
        description="Mean Squared Error: (current_ndvi - historical_mean)².",
    )
    z_score: float = Field(
        ...,
        description="Modified Z-Score of the latest NDVI value. Negative = below median.",
    )
    ndvi_current: Optional[float] = Field(
        None,
        description="Most recent cloud-free NDVI observation [-1.0, 1.0].",
    )
    ndvi_mean: float = Field(
        ...,
        description="Historical mean NDVI across all reliable observations.",
    )
    ndvi_std: float = Field(
        ...,
        description="Standard deviation of historical NDVI.",
    )
    ndvi_trend: float = Field(
        ...,
        description="Linear slope of the last 5 NDVI observations. Negative = declining.",
    )
    records_analyzed: int = Field(
        ..., ge=0,
        description="Number of cloud-free satellite observations used.",
    )
    cloud_gap_ratio: float = Field(
        ...,
        ge=0.0, le=1.0,
        description="Fraction of total observations that were cloud-obscured.",
    )
    recommendation: str = Field(
        ...,
        description="Farmer-friendly recommendation in Romanian.",
    )
    weather_context: Optional[Dict[str, Any]] = Field(
        default=None,
        description="14-day weather diagnostic summary (cause_hint, precip, dry_spell_days, etc.).",
    )


class ForecastDay(BaseModel):
    """One day in a parcel's weather forecast."""

    date: str = Field(..., description="ISO date (YYYY-MM-DD).")
    weekday: str = Field(..., description="Romanian weekday abbreviation (Lun, Mar, ...).")
    temp_max_c: float
    temp_min_c: float
    precipitation_mm: float
    wind_speed_kmh: float
    weather_code: Optional[int] = Field(
        None, description="WMO weather interpretation code."
    )


class ForecastResponse(BaseModel):
    """7-day forecast for a parcel, with plain-language Romanian warnings."""

    days: List[ForecastDay] = Field(default_factory=list)
    warnings: List[str] = Field(
        default_factory=list,
        description="Romanian alerts (frost, heavy rain, heat, strong wind).",
    )
