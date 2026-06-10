"""
Router: GPX Upload Sessions
============================
Cross-device GPX file import via a QR-code-linked browser portal.

Endpoints:
    POST /api/v1/upload/session          — (auth) Create session, returns token + QR URL
    POST /api/v1/upload/{token}/files    — (token-auth) Upload GPX files from PC browser
    GET  /api/v1/upload/{token}/status   — (auth) Poll session status from the mobile app
    POST /api/v1/upload/{token}/confirm  — (auth) Save previewed parcels to PostgreSQL

Security model:
    - Session creation and status/confirm require a valid JWT (the phone's auth).
    - The file upload endpoint authenticates via the token embedded in the URL.
      This is intentional: the PC browser does NOT have the user's JWT. The
      upload token IS the credential for that one endpoint.
    - Tokens are UUID4 (128 bits of entropy), expire after 15 minutes,
      and are single-use (status becomes 'confirmed' after use).

Clean Architecture:
    - No direct DB access here — all persistence goes through ParcelService.
    - Redis session logic is in gpx_service (application layer).
    - GPX parsing is also in gpx_service (domain-ignorant utility).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import List

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services import gpx_service
from app.application.services.parcel_service import ParcelService
from app.core.security import get_current_user
from app.domain.entities.user import User
from app.infrastructure.db.session import get_async_session
from app.infrastructure.repositories.parcel_repository_impl import ParcelRepositoryImpl
from app.presentation.schemas.gpx import (
    ConfirmUploadResponse,
    GpxParcelPreview,
    UploadSessionResponse,
    UploadStatusResponse,
)
from app.presentation.schemas.parcel import GeoJSONGeometry, ParcelCreate
from app.domain.entities.parcel import CropType

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/upload", tags=["GPX Upload"])


# ---------------------------------------------------------------------------
# Helper: derive the server base URL from the incoming request
# ---------------------------------------------------------------------------

def _base_url(request: Request) -> str:
    """Return scheme://host for use in the upload portal URL.

    The 'X-Forwarded-Proto' / 'X-Forwarded-Host' headers are respected so
    this works correctly behind a reverse proxy or ngrok tunnel —
    making internet-accessible deployments a zero-config change.
    """
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host  = request.headers.get("x-forwarded-host",  request.url.netloc)
    return f"{proto}://{host}"


# ---------------------------------------------------------------------------
# Helper: map APIA crop hint string → CropType enum
# ---------------------------------------------------------------------------

_CROP_MAP: dict[str, CropType] = {
    "porumb":     CropType.CORN,
    "corn":       CropType.CORN,
    "grau":       CropType.WHEAT,
    "wheat":      CropType.WHEAT,
    "floarea":    CropType.SUNFLOWER,
    "sunflower":  CropType.SUNFLOWER,
    "soia":       CropType.SOYBEAN,
    "soybean":    CropType.SOYBEAN,
    "rapita":     CropType.RAPESEED,
    "rapeseed":   CropType.RAPESEED,
    "orz":        CropType.BARLEY,
    "barley":     CropType.BARLEY,
    "cartof":     CropType.POTATO,
    "potato":     CropType.POTATO,
    "sfecla":     CropType.SUGAR_BEET,
    "vie":        CropType.VINEYARD,
    "viticultura": CropType.VINEYARD,
    "livada":     CropType.ORCHARD,
}


def _detect_crop_type(hint: str | None) -> CropType:
    """Map a free-text APIA crop description to a CropType enum value."""
    if not hint:
        return CropType.UNKNOWN
    lower = hint.lower()
    for keyword, crop in _CROP_MAP.items():
        if keyword in lower:
            return crop
    return CropType.UNKNOWN


# ===========================================================================
# Endpoints
# ===========================================================================

@router.post(
    "/session",
    response_model=UploadSessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a GPX upload session (mobile → QR code)",
    description=(
        "Creates a 15-minute upload session keyed by a UUID4 token. "
        "The returned `upload_url` is encoded as a QR code on the mobile app "
        "and opened in the PC browser to start the drag-and-drop upload."
    ),
)
async def create_upload_session(
    request: Request,
    current_user: User = Depends(get_current_user),
) -> UploadSessionResponse:
    """Create a new upload session tied to the authenticated user."""
    base = _base_url(request)
    session = await gpx_service.create_session(
        user_id=str(current_user.id),
        base_url=base,
    )
    logger.info(
        "Upload session created: token=%s user=%s",
        session["token"], current_user.id,
    )
    return UploadSessionResponse(
        token=session["token"],
        upload_url=session["upload_url"],
        expires_at=session["expires_at"],
    )


@router.post(
    "/{token}/files",
    response_model=UploadStatusResponse,
    summary="Upload GPX files from PC browser (token-authenticated)",
    description=(
        "Accepts one or more `.gpx` files via multipart/form-data. "
        "Authenticates via the session token in the URL path (no JWT). "
        "Parses each file and stores the previews in Redis. "
        "The mobile app detects the change via the status polling endpoint."
    ),
    responses={
        400: {"description": "No valid GPX files or parse error"},
        404: {"description": "Session token not found or expired"},
    },
)
async def upload_gpx_files(
    token: str,
    files: List[UploadFile] = File(..., description="One or more .gpx files"),
) -> UploadStatusResponse:
    """Process uploaded GPX files and store previews in the session."""
    session = await gpx_service.get_session(token)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Upload session not found or expired. Please generate a new QR code.",
        )
    if session["status"] in ("confirmed", "expired"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Session is already '{session['status']}' and cannot accept new files.",
        )

    previews: List[GpxParcelPreview] = []
    errors: list[str] = []

    for upload in files:
        if not upload.filename or not upload.filename.lower().endswith(".gpx"):
            errors.append(f"'{upload.filename}' is not a .gpx file — skipped.")
            continue
        try:
            raw = await upload.read()
            preview = gpx_service.parse_gpx_file(raw, upload.filename)
            previews.append(preview)
        except ValueError as exc:
            errors.append(str(exc))
        except Exception as exc:
            logger.error("Unexpected GPX parse error for '%s': %s", upload.filename, exc)
            errors.append(f"Failed to parse '{upload.filename}'.")

    if not previews:
        detail = "No valid GPX files were found."
        if errors:
            detail += " Errors: " + "; ".join(errors)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)

    # Persist previews to Redis (overwrite any previous upload in this session)
    await gpx_service.update_session(
        token,
        {
            "status": "uploaded",
            "parcels": [p.model_dump() for p in previews],
        },
    )

    if errors:
        logger.warning(
            "Session %s: %d files parsed, %d errors: %s",
            token, len(previews), len(errors), errors,
        )

    return UploadStatusResponse(
        token=token,
        status="uploaded",
        parcels=previews,
        file_count=len(previews),
    )


@router.get(
    "/{token}/status",
    response_model=UploadStatusResponse,
    summary="Poll upload session status (mobile polling endpoint)",
    description=(
        "Polled every ~3 seconds by the mobile app to detect when "
        "the PC browser has completed the file upload. "
        "Returns status: pending | uploaded | confirmed | expired."
    ),
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Session belongs to a different user"},
        404: {"description": "Session not found or expired"},
    },
)
async def get_upload_status(
    token: str,
    current_user: User = Depends(get_current_user),
) -> UploadStatusResponse:
    """Return the current state of an upload session."""
    session = await gpx_service.get_session(token)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found or expired.",
        )

    # Ownership check — only the creating user may poll
    if session.get("user_id") != str(current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied.",
        )

    raw_parcels = session.get("parcels", [])
    previews = [GpxParcelPreview(**p) for p in raw_parcels]

    return UploadStatusResponse(
        token=token,
        status=session["status"],
        parcels=previews,
        file_count=len(previews),
        expires_at=(
            datetime.fromisoformat(session["expires_at"])
            if session.get("expires_at")
            else None
        ),
    )


@router.post(
    "/{token}/confirm",
    response_model=ConfirmUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Confirm upload — save parcels to PostgreSQL",
    description=(
        "Called after the user reviews the parcel previews on the mobile app "
        "and taps 'Save'. Creates one Parcel record per GPX file, triggers "
        "NDVI and weather background sync, and marks the session as confirmed."
    ),
    responses={
        400: {"description": "Session not in 'uploaded' state or no parcels to save"},
        401: {"description": "Not authenticated"},
        403: {"description": "Session belongs to a different user"},
        404: {"description": "Session not found or expired"},
    },
)
async def confirm_upload(
    token: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> ConfirmUploadResponse:
    """Save confirmed parcel previews as real Parcel records."""
    upload_session = await gpx_service.get_session(token)
    if upload_session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found or expired.",
        )
    if upload_session.get("user_id") != str(current_user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
    if upload_session["status"] != "uploaded":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Session is '{upload_session['status']}', not 'uploaded'. Nothing to confirm.",
        )

    raw_parcels = upload_session.get("parcels", [])
    if not raw_parcels:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No parcel previews found in this session.",
        )

    # Wire up ParcelService for this request's DB session
    parcel_service = ParcelService(parcel_repo=ParcelRepositoryImpl(session))
    created_ids = []

    for raw in raw_parcels:
        preview = GpxParcelPreview(**raw)
        crop_type = _detect_crop_type(preview.detected_crop)

        payload = ParcelCreate(
            name=preview.name,
            description=(
                f"Imported from APIA GPX — {preview.filename}"
                + (f" — {preview.year}" if preview.year else "")
            ),
            geometry=GeoJSONGeometry(**preview.geometry_geojson),
            crop_type=crop_type,
            area_ha=preview.area_ha,
        )

        try:
            parcel = await parcel_service.create_parcel(payload, owner=current_user)
            created_ids.append(parcel.id)
            logger.info(
                "Parcel created from GPX: id=%s name=%r owner=%s",
                parcel.id, parcel.name, current_user.id,
            )
        except Exception as exc:
            # Log but continue — partial success is better than full failure
            logger.error(
                "Failed to create parcel '%s' from GPX: %s", preview.name, exc
            )

    if not created_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="All parcel creations failed. Check geometry validity.",
        )

    # Mark session as confirmed (short TTL for idempotency window)
    await gpx_service.mark_session_confirmed(token)

    return ConfirmUploadResponse(
        created_parcel_ids=created_ids,
        message=f"{len(created_ids)} parcel(s) imported and monitoring started.",
    )
