"""
Concrete Repository: WeatherForecastRepositoryImpl
====================================================
SQLAlchemy 2.0 async implementation of IWeatherForecastRepository.

Upsert Strategy:
    Uses PostgreSQL ``INSERT … ON CONFLICT DO UPDATE`` on the natural key
    (parcel_id, forecast_date, source) to overwrite stale forecast data
    when the Celery cron re-fetches from the weather API.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Optional, Sequence

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.weather_forecast import WeatherForecast
from app.domain.interfaces.weather_forecast_repository import IWeatherForecastRepository
from app.infrastructure.db.models.weather_forecast_orm import WeatherForecastORM

logger = logging.getLogger(__name__)


class WeatherForecastRepositoryImpl(IWeatherForecastRepository):
    """Concrete async SQLAlchemy implementation of IWeatherForecastRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, forecast: WeatherForecast) -> WeatherForecast:
        """Upsert a single forecast (insert or overwrite by natural key)."""
        try:
            row = _forecast_to_dict(forecast)
            stmt = pg_insert(WeatherForecastORM).values([row])
            stmt = stmt.on_conflict_do_update(
                index_elements=["parcel_id", "forecast_date", "source"],
                set_={
                    "temp_max_c": stmt.excluded.temp_max_c,
                    "temp_min_c": stmt.excluded.temp_min_c,
                    "humidity_pct": stmt.excluded.humidity_pct,
                    "precipitation_mm": stmt.excluded.precipitation_mm,
                    "wind_speed_kmh": stmt.excluded.wind_speed_kmh,
                    "uv_index": stmt.excluded.uv_index,
                    "weather_code": stmt.excluded.weather_code,
                    "fetched_at": stmt.excluded.fetched_at,
                },
            )
            await self._session.execute(stmt)
            await self._session.flush()
            # Fetch back to return the full record
            return await self.get_by_parcel_and_date(
                forecast.parcel_id, forecast.forecast_date
            ) or forecast
        except SQLAlchemyError as exc:
            logger.error("DB error saving WeatherForecast: %s", exc)
            raise WeatherForecastPersistenceError("DB error saving weather forecast.") from exc

    async def save_batch(self, forecasts: Sequence[WeatherForecast]) -> Sequence[WeatherForecast]:
        """Bulk upsert a list of forecasts (e.g. 7-day API batch)."""
        if not forecasts:
            return []
        try:
            rows = [_forecast_to_dict(f) for f in forecasts]
            stmt = pg_insert(WeatherForecastORM).values(rows)
            stmt = stmt.on_conflict_do_update(
                index_elements=["parcel_id", "forecast_date", "source"],
                set_={
                    "temp_max_c": stmt.excluded.temp_max_c,
                    "temp_min_c": stmt.excluded.temp_min_c,
                    "humidity_pct": stmt.excluded.humidity_pct,
                    "precipitation_mm": stmt.excluded.precipitation_mm,
                    "wind_speed_kmh": stmt.excluded.wind_speed_kmh,
                    "uv_index": stmt.excluded.uv_index,
                    "weather_code": stmt.excluded.weather_code,
                    "fetched_at": stmt.excluded.fetched_at,
                },
            )
            await self._session.execute(stmt)
            await self._session.flush()
            logger.info("Batch-upserted %d weather forecasts.", len(rows))
            # Re-fetch after upsert
            parcel_id = forecasts[0].parcel_id
            fetch_dates = [f.forecast_date for f in forecasts]
            fetch_stmt = select(WeatherForecastORM).where(
                WeatherForecastORM.parcel_id == parcel_id,
                WeatherForecastORM.forecast_date.in_(fetch_dates),
            )
            result = await self._session.execute(fetch_stmt)
            return [row.to_domain() for row in result.scalars().all()]
        except SQLAlchemyError as exc:
            raise WeatherForecastPersistenceError("DB error during forecast batch upsert.") from exc

    async def get_by_id(self, forecast_id: uuid.UUID) -> Optional[WeatherForecast]:
        try:
            orm_obj = await self._session.get(WeatherForecastORM, forecast_id)
            return orm_obj.to_domain() if orm_obj else None
        except SQLAlchemyError as exc:
            raise WeatherForecastPersistenceError(
                f"DB error fetching forecast id={forecast_id}."
            ) from exc

    async def get_by_parcel_and_date(
        self,
        parcel_id: uuid.UUID,
        forecast_date: date,
    ) -> Optional[WeatherForecast]:
        try:
            stmt = select(WeatherForecastORM).where(
                WeatherForecastORM.parcel_id == parcel_id,
                WeatherForecastORM.forecast_date == forecast_date,
            )
            result = await self._session.execute(stmt)
            orm_obj = result.scalar_one_or_none()
            return orm_obj.to_domain() if orm_obj else None
        except SQLAlchemyError as exc:
            raise WeatherForecastPersistenceError(
                f"DB error fetching forecast for parcel {parcel_id} date {forecast_date}."
            ) from exc

    async def list_upcoming(
        self,
        parcel_id: uuid.UUID,
        *,
        from_date: date,
        days: int = 7,
    ) -> Sequence[WeatherForecast]:
        """Retrieve forecasts for the next N days."""
        end_date = from_date + timedelta(days=days - 1)
        try:
            stmt = (
                select(WeatherForecastORM)
                .where(
                    WeatherForecastORM.parcel_id == parcel_id,
                    WeatherForecastORM.forecast_date >= from_date,
                    WeatherForecastORM.forecast_date <= end_date,
                )
                .order_by(WeatherForecastORM.forecast_date.asc())
            )
            result = await self._session.execute(stmt)
            return [row.to_domain() for row in result.scalars().all()]
        except SQLAlchemyError as exc:
            raise WeatherForecastPersistenceError(
                f"DB error listing upcoming forecasts for parcel {parcel_id}."
            ) from exc

    async def delete_stale(self, older_than: date) -> int:
        """Purge forecasts older than the given date (data retention)."""
        try:
            stmt = delete(WeatherForecastORM).where(
                WeatherForecastORM.forecast_date < older_than
            )
            result = await self._session.execute(stmt)
            await self._session.flush()
            count = result.rowcount
            logger.info("Purged %d stale weather forecasts (older than %s).", count, older_than)
            return count
        except SQLAlchemyError as exc:
            raise WeatherForecastPersistenceError("DB error purging stale forecasts.") from exc


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _forecast_to_dict(f: WeatherForecast) -> dict:
    """Serialize a WeatherForecast domain entity to a plain dict for bulk inserts."""
    return {
        "id": f.id,
        "parcel_id": f.parcel_id,
        "forecast_date": f.forecast_date,
        "temp_max_c": f.temp_max_c,
        "temp_min_c": f.temp_min_c,
        "humidity_pct": f.humidity_pct,
        "precipitation_mm": f.precipitation_mm,
        "wind_speed_kmh": f.wind_speed_kmh,
        "uv_index": f.uv_index,
        "weather_code": f.weather_code,
        "source": f.source,
        "fetched_at": f.fetched_at,
    }


class WeatherForecastPersistenceError(Exception):
    """Raised when a database operation on WeatherForecast fails."""
