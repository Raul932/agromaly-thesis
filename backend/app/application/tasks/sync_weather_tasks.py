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
    default_retry_delay=60,
    autoretry_for=(WeatherAPIError,),
    retry_backoff=True,
    retry_backoff_max=300,
    acks_late=True,
)
def sync_weather_for_parcel(self, parcel_id_str: str) -> dict:
    """Celery task: fetch 7-day weather forecast and persist to DB."""
    print(f"--- CELERY WEATHER TASK RECEIVED --- parcel_id={parcel_id_str}")
    logger.info("sync_weather_for_parcel started: parcel_id=%s", parcel_id_str)
    try:
        result = asyncio.run(_async_sync_weather(parcel_id_str))
        print(
            f"--- CELERY WEATHER TASK SUCCESS --- parcel_id={parcel_id_str} "
            f"days_saved={result['days_saved']}"
        )
        logger.info(
            "sync_weather_for_parcel done: parcel_id=%s days_saved=%d",
            parcel_id_str, result["days_saved"],
        )
        return result
    except Exception as exc:
        print(f"--- CELERY WEATHER TASK FAILED --- parcel_id={parcel_id_str} error={exc}")
        logger.error("sync_weather_for_parcel failed: %s", exc, exc_info=True)
        raise


# ---------------------------------------------------------------------------
# Async Implementation
# ---------------------------------------------------------------------------

async def _async_sync_weather(parcel_id_str: str) -> dict:
    """Async implementation of the weather sync use case."""
    import app.infrastructure.db.models  # noqa: F401 — trigger mapper registration
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
                print(f"--- WEATHER: Parcel {parcel_id} NOT FOUND — skipping ---")
                return {"parcel_id": parcel_id_str, "days_saved": 0}

            # 2. Compute centroid from parcel WKT
            lat, lon = _centroid_from_wkt(parcel.geometry_wkt)
            print(f"--- WEATHER: Centroid lat={lat:.4f} lon={lon:.4f} ---")

            # 3. Fetch 7-day forecast
            weather_points = await client.fetch_forecast(lat, lon, days=7)
            print(f"--- WEATHER: Got {len(weather_points)} forecast days ---")

            if not weather_points:
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

            print(f"--- WEATHER: Persisted {len(saved)} forecasts to DB ---")
            return {"parcel_id": parcel_id_str, "days_saved": len(saved)}

        except Exception as exc:
            await session.rollback()
            print(f"--- WEATHER DB ERROR: {exc} ---")
            raise


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _centroid_from_wkt(geometry_wkt: str) -> tuple[float, float]:
    """Extract (latitude, longitude) centroid from a WKT geometry string."""
    import shapely.wkt
    geom = shapely.wkt.loads(geometry_wkt)
    centroid = geom.centroid
    return centroid.y, centroid.x  # (lat, lon)
