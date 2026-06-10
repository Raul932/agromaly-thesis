"""
Application Service: GpxService
=================================
Orchestrates GPX upload sessions using Redis as ephemeral session storage.

Responsibilities:
    1. Create short-lived upload sessions (TTL = 15 min) stored in Redis DB 2.
    2. Parse uploaded GPX files using gpxpy, extract parcel geometry + metadata.
    3. Store parsed parcel previews back into the session (Redis).
    4. On confirm: delegate to ParcelService.create_parcel() for each preview.

Redis key schema:
    ``gpx_upload:{token}``  →  JSON-serialised session dict, TTL 900 s.

GPX Parsing (APIA format):
    APIA GPX files contain exactly one <trk> per parcel, with:
        <name>   — parcel identifier (e.g. "RO009055925 - 4a")
        <cmt>    — declared area in hectares (e.g. "2.57")
        <desc>   — crop type in Romanian (e.g. "PORUMB")
        <src>    — campaign year (e.g. "2026")
        <trkseg> — ordered boundary vertices as <trkpt lat="..." lon="..."/>

    The track points form a closed ring → converted to a GeoJSON Polygon.
    The ring is closed automatically if the first and last points differ.

Clean Architecture:
    This service has NO knowledge of HTTP or FastAPI.
    It receives plain Python objects and returns domain/schema objects.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional

logger = logging.getLogger(__name__)

# Upload session TTL in seconds (15 minutes)
_SESSION_TTL_SECONDS = 900
# Redis DB index for upload sessions (separate from Celery: 0/1)
_REDIS_DB = 2
# Redis key prefix
_KEY_PREFIX = "gpx_upload:"


# ---------------------------------------------------------------------------
# Redis client (lazily created, one per process)
# ---------------------------------------------------------------------------

_redis_client: Optional["redis.asyncio.Redis"] = None  # type: ignore[name-defined]


async def _get_redis() -> "redis.asyncio.Redis":  # type: ignore[name-defined]
    """Return a cached async Redis client for DB 2 (upload sessions)."""
    global _redis_client
    if _redis_client is None:
        import redis.asyncio as aioredis  # type: ignore[import]
        from app.core.config import settings

        _redis_client = aioredis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            password=settings.REDIS_PASSWORD,
            db=_REDIS_DB,
            decode_responses=True,
        )
    return _redis_client


# ---------------------------------------------------------------------------
# Session CRUD (Redis)
# ---------------------------------------------------------------------------

async def create_session(user_id: str, base_url: str) -> dict:
    """Create a new upload session in Redis.

    Args:
        user_id:  UUID string of the authenticated user.
        base_url: The server's base URL, used to construct the portal URL.
                  Example: "http://192.168.0.106:8000"

    Returns:
        Session dict with keys: token, upload_url, expires_at, status.
    """
    redis = await _get_redis()
    token = str(uuid.uuid4())
    expires_at = datetime.now(tz=timezone.utc) + timedelta(seconds=_SESSION_TTL_SECONDS)

    session = {
        "token": token,
        "user_id": user_id,
        "status": "pending",
        "parcels": [],            # Will be populated after GPX upload
        "upload_url": f"{base_url}/upload/{token}",
        "expires_at": expires_at.isoformat(),
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
    }

    await redis.setex(
        f"{_KEY_PREFIX}{token}",
        _SESSION_TTL_SECONDS,
        json.dumps(session),
    )
    logger.info("Upload session created: token=%s user=%s", token, user_id)
    return session


async def get_session(token: str) -> Optional[dict]:
    """Fetch a session from Redis by token.

    Returns None if the token does not exist or has expired.
    """
    redis = await _get_redis()
    raw = await redis.get(f"{_KEY_PREFIX}{token}")
    if raw is None:
        return None
    return json.loads(raw)


async def update_session(token: str, updates: dict, ttl: int = _SESSION_TTL_SECONDS) -> None:
    """Persist updated session data to Redis, refreshing the TTL."""
    redis = await _get_redis()
    raw = await redis.get(f"{_KEY_PREFIX}{token}")
    if raw is None:
        raise KeyError(f"Upload session '{token}' not found or expired.")
    session = json.loads(raw)
    session.update(updates)
    await redis.setex(f"{_KEY_PREFIX}{token}", ttl, json.dumps(session))


async def mark_session_confirmed(token: str) -> None:
    """Set session status to 'confirmed'. Keeps key for 60 s for idempotency."""
    await update_session(token, {"status": "confirmed"}, ttl=60)


# ---------------------------------------------------------------------------
# GPX Parsing
# ---------------------------------------------------------------------------

def parse_gpx_file(file_bytes: bytes, filename: str) -> "GpxParcelPreview":  # type: ignore[name-defined]
    """Parse an APIA-format GPX file and return a GpxParcelPreview.

    Uses the gpxpy library which handles namespace differences between
    GPX 1.0 and 1.1 transparently.

    Args:
        file_bytes: Raw bytes of the uploaded .gpx file.
        filename:   Original filename from the browser upload.

    Returns:
        GpxParcelPreview with extracted metadata and GeoJSON geometry.

    Raises:
        ValueError: If the file has no tracks or track segments.
    """
    import gpxpy  # type: ignore[import]
    from app.presentation.schemas.gpx import GpxParcelPreview

    try:
        gpx = gpxpy.parse(file_bytes.decode("utf-8", errors="replace"))
    except Exception as exc:
        raise ValueError(f"Cannot parse '{filename}' as GPX: {exc}") from exc

    if not gpx.tracks:
        raise ValueError(f"GPX file '{filename}' contains no tracks.")

    track = gpx.tracks[0]

    # --- Metadata extraction ---
    name: str = (track.name or filename.removesuffix(".gpx")).strip()
    detected_crop: Optional[str] = (track.description or "").strip() or None
    year: Optional[str] = (track.source or "").strip() or None

    # <cmt> holds declared area in hectares (APIA convention)
    area_ha: Optional[float] = None
    if track.comment:
        try:
            area_ha = float(track.comment.strip())
        except ValueError:
            pass

    # --- Coordinate extraction ---
    if not track.segments or not track.segments[0].points:
        raise ValueError(f"GPX file '{filename}' has no track points.")

    points = track.segments[0].points
    # Build coordinate ring: [lon, lat] per GeoJSON spec
    coords: List[List[float]] = [[p.longitude, p.latitude] for p in points]

    # Close the ring if necessary
    if coords[0] != coords[-1]:
        coords.append(coords[0])

    if len(coords) < 4:
        raise ValueError(
            f"GPX file '{filename}' has too few points ({len(coords)}) "
            "to form a valid polygon ring (minimum 4)."
        )

    geometry_geojson = {
        "type": "Polygon",
        "coordinates": [coords],
    }

    # --- Bounding box centre ---
    lats = [p.latitude for p in points]
    lons = [p.longitude for p in points]
    centre_lat = (min(lats) + max(lats)) / 2
    centre_lon = (min(lons) + max(lons)) / 2

    logger.debug(
        "Parsed GPX '%s': name=%r points=%d area=%s",
        filename, name, len(points), area_ha,
    )

    return GpxParcelPreview(
        filename=filename,
        name=name,
        detected_crop=detected_crop,
        area_ha=area_ha,
        year=year,
        coordinate_count=len(points),
        centre_lat=round(centre_lat, 6),
        centre_lon=round(centre_lon, 6),
        geometry_geojson=geometry_geojson,
    )
