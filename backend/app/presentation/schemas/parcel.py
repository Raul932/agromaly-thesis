"""
Pydantic V2 Schemas: Parcel
============================
Request/Response models for parcel-related API endpoints.

GeoJSON Input:
    ``ParcelCreate`` accepts a GeoJSON geometry object (as per RFC 7946)
    rather than raw WKT. This is the standard for web/mobile mapping clients
    (Leaflet, Mapbox, Google Maps). The application service converts it to WKT.

Area Auto-Calculation:
    If ``area_ha`` is omitted in ``ParcelCreate``, the service computes it
    from the geometry using a projection-aware Shapely/pyproj calculation.

Response:
    ``ParcelResponse`` includes the geometry as a GeoJSON dict (converted
    back from WKT) so clients receive a consistent format.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.entities.parcel import CropType, ParcelStatus


# ---------------------------------------------------------------------------
# GeoJSON Geometry sub-schema
# ---------------------------------------------------------------------------

class GeoJSONGeometry(BaseModel):
    """A minimal GeoJSON geometry object (RFC 7946).

    Only Polygon and MultiPolygon are accepted for parcels
    (points and lines are not valid agricultural field boundaries).
    """

    model_config = ConfigDict(extra="allow")   # Forward-compatible with GeoJSON extensions

    type: str = Field(
        ...,
        description="GeoJSON geometry type. Must be 'Polygon' or 'MultiPolygon'.",
        examples=["Polygon"],
    )
    coordinates: List[Any] = Field(
        ...,
        description="GeoJSON coordinate array. Coordinates must be in WGS84 (lon, lat).",
    )

    @field_validator("type")
    @classmethod
    def validate_geometry_type(cls, v: str) -> str:
        allowed = {"Polygon", "MultiPolygon"}
        if v not in allowed:
            raise ValueError(
                f"Unsupported geometry type '{v}'. "
                f"Only {sorted(allowed)} are valid for agricultural parcels."
            )
        return v


# ---------------------------------------------------------------------------
# Request Schemas
# ---------------------------------------------------------------------------

class ParcelCreate(BaseModel):
    """Payload for ``POST /api/v1/parcels``.

    The geometry is provided as standard GeoJSON (WGS84 / SRID 4326).
    The application service converts it to WKT and calculates area.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Human-readable name for the parcel.",
        examples=["Câmpul de Nord"],
    )
    description: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="Optional notes about this parcel.",
    )
    geometry: GeoJSONGeometry = Field(
        ...,
        description="Parcel boundary as a GeoJSON Polygon or MultiPolygon (WGS84).",
    )
    crop_type: CropType = Field(
        default=CropType.UNKNOWN,
        description="Crop currently planted on this parcel.",
    )
    area_ha: Optional[float] = Field(
        default=None,
        gt=0,
        description=(
            "Parcel area in hectares. If omitted, computed automatically "
            "from the geometry using an equal-area projection."
        ),
    )


class ParcelUpdate(BaseModel):
    """Payload for ``PATCH /api/v1/parcels/{id}`` (partial update).

    All fields are optional — only provided fields are updated.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=2000)
    crop_type: Optional[CropType] = Field(default=None)


# ---------------------------------------------------------------------------
# Response Schemas
# ---------------------------------------------------------------------------

class ParcelResponse(BaseModel):
    """Complete parcel representation returned from API endpoints.

    ``geometry`` is returned as a GeoJSON dict for consistency with input format.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    owner_id: uuid.UUID
    name: str
    description: Optional[str]
    geometry_wkt: str = Field(
        ...,
        description="Parcel geometry in Well-Known Text format.",
    )
    area_ha: float
    crop_type: CropType
    status: ParcelStatus
    last_ndvi: Optional[float] = Field(
        default=None,
        description="Most recent NDVI value (-1.0 to 1.0). None if no satellite data yet.",
    )
    last_ndvi_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class ParcelListResponse(BaseModel):
    """Paginated list response for parcel queries."""

    items: List[ParcelResponse]
    total: int = Field(..., description="Total number of matching parcels.")
    limit: int
    offset: int
