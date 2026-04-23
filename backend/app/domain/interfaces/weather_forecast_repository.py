"""
Abstract Repository Interface: IWeatherForecastRepository
==========================================================
Defines the persistence Port for WeatherForecast daily data.

Key Query Patterns:
    - Upsert by (parcel_id, forecast_date) — idempotent re-fetching from API.
    - Retrieve upcoming N days for risk assessment.
    - Delete stale forecasts older than a retention window.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from datetime import date
from typing import Optional, Sequence

from app.domain.entities.weather_forecast import WeatherForecast


class IWeatherForecastRepository(ABC):
    """Persistence contract for WeatherForecast records."""

    @abstractmethod
    async def save(self, forecast: WeatherForecast) -> WeatherForecast:
        """Persist a single forecast. Upsert by (parcel_id, forecast_date).

        If a forecast for the same parcel + date already exists, it is
        overwritten with the freshly fetched data.

        Args:
            forecast: Domain entity to persist.

        Returns:
            Saved entity.
        """
        ...

    @abstractmethod
    async def save_batch(self, forecasts: Sequence[WeatherForecast]) -> Sequence[WeatherForecast]:
        """Bulk upsert a list of forecasts (typically 7-day from API batch).

        Args:
            forecasts: List of domain entities.

        Returns:
            Sequence of persisted entities.
        """
        ...

    @abstractmethod
    async def get_by_id(self, forecast_id: uuid.UUID) -> Optional[WeatherForecast]:
        """Retrieve a forecast by its primary key."""
        ...

    @abstractmethod
    async def get_by_parcel_and_date(
        self,
        parcel_id: uuid.UUID,
        forecast_date: date,
    ) -> Optional[WeatherForecast]:
        """Retrieve the forecast for a specific parcel on a specific date.

        Args:
            parcel_id:     UUID of the parent parcel.
            forecast_date: The calendar date of the forecast.

        Returns:
            WeatherForecast or None.
        """
        ...

    @abstractmethod
    async def list_upcoming(
        self,
        parcel_id: uuid.UUID,
        *,
        from_date: date,
        days: int = 7,
    ) -> Sequence[WeatherForecast]:
        """Retrieve forecasts for the next N days starting from a given date.

        Args:
            parcel_id:  UUID of the parcel.
            from_date:  Start date (inclusive).
            days:       Number of forecast days to retrieve (default: 7).

        Returns:
            Forecasts ordered by forecast_date ascending.
        """
        ...

    @abstractmethod
    async def delete_stale(self, older_than: date) -> int:
        """Purge forecast records older than the given date (data retention).

        Args:
            older_than: Records with forecast_date < this value are deleted.

        Returns:
            Number of deleted records.
        """
        ...
