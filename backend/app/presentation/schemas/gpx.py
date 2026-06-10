"""
Pydantic V2 Schemas: GPX Upload Sessions
==========================================
Schemas for the cross-device GPX file upload portal.

Flow:
    1. Mobile app calls POST /upload/session  → receives UploadSessionResponse.
    2. Session URL is encoded as a QR code displayed on the phone.
    3. PC browser opens the URL, drags .gpx files into the portal.
    4. Backend parses files and stores previews in Redis under the session token.
    5. Mobile polls GET /upload/{token}/status until status == "uploaded".
    6. User reviews GpxParcelPreview list on the phone and confirms.
    7. POST /upload/{token}/confirm creates the Parcel records in PostgreSQL.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Session creation response (returned to mobile after POST /upload/session)
# ---------------------------------------------------------------------------

class UploadSessionResponse(BaseModel):
    """Returned immediately after creating an upload session."""

    token: str = Field(
        ...,
        description="One-time upload token (UUID4). Encoded into the QR code.",
    )
    upload_url: str = Field(
        ...,
        description=(
            "Full URL the farmer opens on their PC browser. "
            "Encodes both the portal HTML and the token."
        ),
    )
    expires_at: datetime = Field(
        ...,
        description="UTC timestamp when this session expires (15 minutes from creation).",
    )


# ---------------------------------------------------------------------------
# Per-file GPX parcel preview (not yet saved to DB)
# ---------------------------------------------------------------------------

class GpxParcelPreview(BaseModel):
    """Preview data extracted from a single GPX file.

    Sent to the mobile app so the farmer can review before confirming.
    No Parcel record exists in PostgreSQL yet at this stage.
    """

    filename: str = Field(..., description="Original filename from the PC upload.")
    name: str = Field(
        ...,
        description=(
            "Parcel name extracted from GPX <name> tag "
            "(e.g. 'RO009055925 - 4a')."
        ),
    )
    detected_crop: Optional[str] = Field(
        default=None,
        description="Crop hint from GPX <desc> tag (e.g. 'PORUMB').",
    )
    area_ha: Optional[float] = Field(
        default=None,
        description="Declared area from GPX <cmt> tag, in hectares.",
    )
    year: Optional[str] = Field(
        default=None,
        description="Campaign year from GPX <src> tag.",
    )
    coordinate_count: int = Field(
        ...,
        description="Number of track points (boundary vertices).",
    )
    centre_lat: float = Field(..., description="Bounding-box centre latitude.")
    centre_lon: float = Field(..., description="Bounding-box centre longitude.")

    # Raw geometry — stored in Redis, used at confirm time to build the Parcel
    geometry_geojson: dict = Field(
        ...,
        description=(
            "GeoJSON Polygon built from the GPX track points. "
            "Passed to ParcelService.create_parcel() at confirm time."
        ),
    )


# ---------------------------------------------------------------------------
# Session status (polled by mobile)
# ---------------------------------------------------------------------------

# Literal union used for type-safe status checks in the Flutter client
UploadStatus = Literal["pending", "uploaded", "confirmed", "expired"]


class UploadStatusResponse(BaseModel):
    """Current state of an upload session.

    The ``parcels`` list is only populated when status == "uploaded".
    """

    token: str
    status: UploadStatus
    parcels: List[GpxParcelPreview] = Field(
        default_factory=list,
        description="Parsed parcel previews. Empty until files have been uploaded.",
    )
    file_count: int = Field(
        default=0,
        description="Number of GPX files successfully parsed in this session.",
    )
    expires_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Confirm request (mobile → backend after user approves the preview)
# ---------------------------------------------------------------------------

class ConfirmUploadResponse(BaseModel):
    """Returned after a successful confirm, listing the IDs of created parcels."""

    created_parcel_ids: List[UUID] = Field(
        ...,
        description="UUIDs of the Parcel records created in PostgreSQL.",
    )
    message: str = Field(
        default="Parcels imported successfully.",
        description="Human-readable confirmation message.",
    )
