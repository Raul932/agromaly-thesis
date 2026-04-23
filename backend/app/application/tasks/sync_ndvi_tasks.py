"""
Celery Task: NDVI Satellite Sync
==================================
Fetches NDVI satellite data for a parcel and persists the records to the DB.
Also updates the denormalised ``last_ndvi`` / ``last_ndvi_at`` cache on the
``parcels`` table for fast mobile app reads.

Cloud Coverage Strategy:
    Records with ``cloud_coverage > 20%`` are persisted with
    ``is_interpolated=True``. This flag signals the LSTM pre-processing
    pipeline to run gap-filling (linear interpolation or Kalman filter)
    on cloudy observations before feeding the time-series to the model.

Idempotency:
    Uses ``ON CONFLICT DO NOTHING`` on the natural key
    (parcel_id, date_captured, source) so re-running the task never
    creates duplicate records.

Retry Policy:
    - 3 retries on ``SatelliteAPIError``.
    - Exponential back-off: 120s, 240s, 480s.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import date, datetime, timedelta, timezone

from celery import shared_task
from celery.utils.log import get_task_logger

from app.core.exceptions import SatelliteAPIError

logger = get_task_logger(__name__)


# ---------------------------------------------------------------------------
# Public Celery Task
# ---------------------------------------------------------------------------

@shared_task(
    bind=True,
    name="app.application.tasks.sync_ndvi_tasks.sync_ndvi_for_parcel",
    max_retries=3,
    default_retry_delay=120,
    autoretry_for=(SatelliteAPIError,),
    retry_backoff=True,
    retry_backoff_max=600,
    acks_late=True,
)
def sync_ndvi_for_parcel(self, parcel_id_str: str) -> dict:
    """Celery task: fetch NDVI satellite data and persist to DB.

    Args:
        parcel_id_str: UUID of the parcel as a JSON-serializable string.

    Returns:
        Dict with saved record count, cloudy count, and updated last_ndvi.
    """
    logger.info("sync_ndvi_for_parcel started: parcel_id=%s", parcel_id_str)
    try:
        result = asyncio.run(_async_sync_ndvi(parcel_id_str))
        logger.info(
            "sync_ndvi_for_parcel done: parcel_id=%s records=%d cloudy=%d last_ndvi=%.4f",
            parcel_id_str,
            result["records_saved"],
            result["cloudy_records"],
            result.get("last_ndvi") or 0.0,
        )
        return result
    except Exception as exc:
        logger.error("sync_ndvi_for_parcel failed: %s", exc, exc_info=True)
        raise


# ---------------------------------------------------------------------------
# Async Implementation
# ---------------------------------------------------------------------------

async def _async_sync_ndvi(parcel_id_str: str) -> dict:
    """Async implementation of the NDVI sync use case."""
    import app.infrastructure.db.models  # noqa: F401 — trigger mapper registration
    from app.infrastructure.db.session import AsyncSessionLocal
    from app.infrastructure.external.satellite_client import SatelliteClient
    from app.infrastructure.repositories.parcel_repository_impl import ParcelRepositoryImpl
    from app.infrastructure.repositories.ndvi_record_repository_impl import NDVIRecordRepositoryImpl
    from app.domain.entities.ndvi_record import NDVIRecord
    from sqlalchemy import update
    from app.infrastructure.db.models.parcel_orm import ParcelORM

    parcel_id = uuid.UUID(parcel_id_str)
    client = SatelliteClient()

    async with AsyncSessionLocal() as session:
        try:
            # 1. Fetch the parcel
            parcel_repo = ParcelRepositoryImpl(session)
            parcel = await parcel_repo.get_by_id(parcel_id)
            if parcel is None:
                logger.warning("Parcel %s not found — skipping NDVI sync.", parcel_id)
                return {"parcel_id": parcel_id_str, "records_saved": 0,
                        "cloudy_records": 0, "last_ndvi": None}

            # 2. Determine date window:
            #    - First sync: last 90 days (seed historical data)
            #    - Subsequent syncs: last 14 days (rolling window)
            ndvi_repo = NDVIRecordRepositoryImpl(session)
            existing = await ndvi_repo.get_latest_n(parcel_id, n=1)
            if existing:
                start_date = date.today() - timedelta(days=14)
            else:
                start_date = date.today() - timedelta(days=90)  # First sync: 3 months
            end_date = date.today()

            logger.debug(
                "NDVI sync window for parcel %s: %s → %s",
                parcel_id, start_date, end_date,
            )

            # 3. Fetch from satellite client
            ndvi_points = await client.fetch_ndvi_timeseries(
                parcel.geometry_wkt,
                start_date=start_date,
                end_date=end_date,
            )

            if not ndvi_points:
                logger.warning("No NDVI data for parcel %s in window.", parcel_id)
                return {"parcel_id": parcel_id_str, "records_saved": 0,
                        "cloudy_records": 0, "last_ndvi": None}

            # 4. Map to domain entities
            records = [
                NDVIRecord(
                    parcel_id=parcel_id,
                    date_captured=pt.date_captured,
                    mean_ndvi=pt.mean_ndvi,
                    cloud_coverage=pt.cloud_coverage,
                    pixel_count=pt.pixel_count,
                    is_interpolated=pt.is_interpolated,
                    source=pt.source,
                )
                for pt in ndvi_points
            ]

            # 5. Bulk insert (ON CONFLICT DO NOTHING — idempotent)
            saved = await ndvi_repo.save_batch(records)
            cloudy_count = sum(1 for r in records if r.is_interpolated)

            # 6. Update the denormalised last_ndvi / last_ndvi_at cache.
            #    Only use cloud-reliable records (cloud_coverage < 20%).
            reliable = [r for r in records if not r.is_interpolated]
            if reliable:
                best = max(reliable, key=lambda r: r.date_captured)
                now_utc = datetime.now(tz=timezone.utc)
                stmt = (
                    update(ParcelORM)
                    .where(ParcelORM.id == parcel_id)
                    .values(last_ndvi=best.mean_ndvi, last_ndvi_at=now_utc)
                )
                await session.execute(stmt)
                last_ndvi = best.mean_ndvi
            else:
                last_ndvi = None

            await session.commit()

            return {
                "parcel_id": parcel_id_str,
                "records_saved": len(saved),
                "cloudy_records": cloudy_count,
                "last_ndvi": last_ndvi,
            }

        except Exception:
            await session.rollback()
            raise
