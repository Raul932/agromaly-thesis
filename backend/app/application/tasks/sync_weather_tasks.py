"""
Celery Task: Weather Sync
==========================
Fetches weather forecasts for a given parcel and persists them to the DB.

Async Bridge:
    Celery uses a synchronous prefork worker by default. We bridge into
    async code using ``asyncio.run()``, which creates a fresh event loop
    per task execution. This is safe because each worker process is single-
    threaded by design.

Session Isolation:
    Each task creates its own ``AsyncSession`` via the shared
    ``AsyncSessionLocal`` factory. Sessions are NEVER shared between tasks.
    This prevents cross-task transaction contamination.

Retry Policy:
    - 3 automatic retries on ``WeatherAPIError``.
    - Exponential back-off: 60s, 120s, 240s.
    - After all retries exhausted the task enters FAILURE state in Redis.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import date, datetime, timezone

from celery import shared_task
from celery.utils.log import get_task_logger

from app.core.exceptions import WeatherAPIError

logger = get_task_logger(__name__)


# ---------------------------------------------------------------------------
# Public Celery Task
# ---------------------------------------------------------------------------

@shared_task(
    bind=True,
    name="app.application.tasks.sync_weather_tasks.sync_weather_for_parcel",
    max_retries=3,
    default_retry_delay=60,          # seconds (base; doubled each retry)
    autoretry_for=(WeatherAPIError,),
    retry_backoff=True,
    retry_backoff_max=300,           # cap at 5 minutes
    acks_late=True,
)
def sync_weather_for_parcel(self, parcel_id_str: str) -> dict:
    """Celery task: fetch 7-day weather forecast and persist to DB.

    Args:
        parcel_id_str: UUID of the parcel as a string (JSON-serializable).

    Returns:
        Dict with ``{"parcel_id": ..., "days_saved": N}`` for the result backend.
    """
    logger.info("sync_weather_for_parcel started: parcel_id=%s", parcel_id_str)
    try:
        result = asyncio.run(_async_sync_weather(parcel_id_str))
        logger.info(
            "sync_weather_for_parcel done: parcel_id=%s days_saved=%d",
            parcel_id_str, result["days_saved"],
        )
        return result
    except Exception as exc:
        logger.error("sync_weather_for_parcel failed: %s", exc, exc_info=True)
        raise


# ---------------------------------------------------------------------------
# Async Implementation
# ---------------------------------------------------------------------------

async def _async_sync_weather(parcel_id_str: str) -> dict:
    """Async implementation of the weather sync use case.

    Separated from the synchronous task wrapper to allow direct
    ``await`` calls in tests without running a real Celery broker.
    """
    from app.infrastructure.db.models import ParcelORM  # trigger mapper registration
    from app.infrastructure.db.session import AsyncSessionLocal
    from app.infrastructure.external.weather_client import WeatherClient
    from app.infrastructure.repositories.parcel_repository_impl import ParcelRepositoryImpl
    from app.infrastructure.repositories.weather_forecast_repository_impl import WeatherForecastRepositoryImpl
    from app.domain.entities.weather_forecast import WeatherForecast

    parcel_id = uuid.UUID(parcel_id_str)
    client = WeatherClient()

    async with AsyncSessionLocal() as session:
        try:
            # 1. Fetch the parcel to get its geometry centroid
            parcel_repo = ParcelRepositoryImpl(session)
            parcel = await parcel_repo.get_by_id(parcel_id)
            if parcel is None:
                logger.warning("Parcel %s not found — skipping weather sync.", parcel_id)
                return {"parcel_id": parcel_id_str, "days_saved": 0}

            # 2. Compute centroid from parcel WKT
            lat, lon = _centroid_from_wkt(parcel.geometry_wkt)
            logger.debug("Centroid for parcel %s: lat=%.4f lon=%.4f", parcel_id, lat, lon)

            # 3. Fetch 7-day forecast
            weather_points = await client.fetch_forecast(lat, lon, days=7)

            if not weather_points:
                logger.warning("No weather data returned for parcel %s.", parcel_id)
                return {"parcel_id": parcel_id_str, "days_saved": 0}

            # 4. Map to domain entities
            forecasts = [
                WeatherForecast(
                    parcel_id=parcel_id,
                    forecast_date=wp.forecast_date,
                    temp_max_c=wp.temp_max_c,
                    temp_min_c=wp.temp_min_c,
                    humidity_pct=wp.humidity_pct,
                    precipitation_mm=wp.precipitation_mm,
                    wind_speed_kmh=wp.wind_speed_kmh,
                    uv_index=wp.uv_index,
                    weather_code=wp.weather_code,
                    source=wp.source,
                    fetched_at=wp.fetched_at,
                )
                for wp in weather_points
            ]

            # 5. Upsert (ON CONFLICT DO UPDATE) — idempotent
            forecast_repo = WeatherForecastRepositoryImpl(session)
            saved = await forecast_repo.save_batch(forecasts)
            await session.commit()

            return {"parcel_id": parcel_id_str, "days_saved": len(saved)}

        except Exception:
            await session.rollback()
            raise


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _centroid_from_wkt(geometry_wkt: str) -> tuple[float, float]:
    """Extract (latitude, longitude) centroid from a WKT geometry string.

    Args:
        geometry_wkt: WKT geometry string (MULTIPOLYGON or POLYGON).

    Returns:
        Tuple of (latitude, longitude) in decimal degrees.
    """
    import shapely.wkt
    geom = shapely.wkt.loads(geometry_wkt)
    centroid = geom.centroid
    return centroid.y, centroid.x  # (lat, lon)
