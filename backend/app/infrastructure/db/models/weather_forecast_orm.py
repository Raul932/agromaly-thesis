"""
SQLAlchemy ORM Model: WeatherForecastORM
==========================================
Daily weather forecast records stored per parcel.

Unique Constraint:
    (parcel_id, forecast_date, source) — supports idempotent upserts when
    the Celery cron job re-fetches data for the same date.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.db.base import Base
from app.domain.entities.weather_forecast import WeatherForecast

if TYPE_CHECKING:
    from app.infrastructure.db.models.parcel_orm import ParcelORM


class WeatherForecastORM(Base):
    """ORM representation of the ``weather_forecasts`` table."""

    __tablename__ = "weather_forecasts"

    __table_args__ = (
        UniqueConstraint(
            "parcel_id", "forecast_date", "source",
            name="uq_weather_parcel_date_source",
        ),
        Index("ix_weather_parcel_date", "parcel_id", "forecast_date"),
        Index("ix_weather_parcel_id", "parcel_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    parcel_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("parcels.id", ondelete="CASCADE"),
        nullable=False,
        comment="Parent parcel. Cascaded on deletion.",
    )
    forecast_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        comment="The calendar date this forecast applies to.",
    )
    temp_max_c: Mapped[float] = mapped_column(
        Float, nullable=False, comment="Maximum air temperature (°C)."
    )
    temp_min_c: Mapped[float] = mapped_column(
        Float, nullable=False, comment="Minimum air temperature (°C)."
    )
    humidity_pct: Mapped[float] = mapped_column(
        Float, nullable=False, comment="Relative humidity percentage [0–100]."
    )
    precipitation_mm: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
        server_default="0.0",
        comment="Expected precipitation in millimetres.",
    )
    wind_speed_kmh: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
        server_default="0.0",
        comment="Mean wind speed (km/h).",
    )
    uv_index: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="UV index (0–11+)."
    )
    weather_code: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, comment="WMO weather interpretation code."
    )
    source: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="open-meteo",
        server_default="open-meteo",
        comment="API/provider name (e.g. open-meteo, openweathermap).",
    )
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="UTC timestamp when this forecast was fetched from the API.",
    )

    # ------------------------------------------------------------------
    # Relationships
    # ------------------------------------------------------------------
    parcel: Mapped["ParcelORM"] = relationship(
        "ParcelORM",
        back_populates="weather_forecasts",
        lazy="noload",
    )

    # ------------------------------------------------------------------
    # Mapping
    # ------------------------------------------------------------------

    def to_domain(self) -> WeatherForecast:
        return WeatherForecast(
            id=self.id,
            parcel_id=self.parcel_id,
            forecast_date=self.forecast_date,
            temp_max_c=self.temp_max_c,
            temp_min_c=self.temp_min_c,
            humidity_pct=self.humidity_pct,
            precipitation_mm=self.precipitation_mm,
            wind_speed_kmh=self.wind_speed_kmh,
            uv_index=self.uv_index,
            weather_code=self.weather_code,
            source=self.source,
            fetched_at=self.fetched_at,
        )

    @classmethod
    def from_domain(cls, forecast: WeatherForecast) -> "WeatherForecastORM":
        return cls(
            id=forecast.id,
            parcel_id=forecast.parcel_id,
            forecast_date=forecast.forecast_date,
            temp_max_c=forecast.temp_max_c,
            temp_min_c=forecast.temp_min_c,
            humidity_pct=forecast.humidity_pct,
            precipitation_mm=forecast.precipitation_mm,
            wind_speed_kmh=forecast.wind_speed_kmh,
            uv_index=forecast.uv_index,
            weather_code=forecast.weather_code,
            source=forecast.source,
            fetched_at=forecast.fetched_at,
        )

    def __repr__(self) -> str:
        return (
            f"<WeatherForecastORM parcel={self.parcel_id!s} "
            f"date={self.forecast_date!s} T=[{self.temp_min_c:.1f}, {self.temp_max_c:.1f}]°C>"
        )
