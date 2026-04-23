"""
External HTTP Client: WeatherClient
=====================================
Fetches weather forecasts from the Open-Meteo API (free, no API key required).
The mocked ``_mock_response`` method mirrors the exact structure of a real
Open-Meteo hourly/daily response so it can be swapped transparently.

Design:
    - ``AsyncClient`` is instantiated per call (not shared) to keep the client
      stateless and safe for Celery worker processes.
    - Retry logic: 3 attempts with exponential back-off (200ms, 400ms, 800ms).
    - All API errors are wrapped in ``WeatherAPIError`` (domain exception).

Open-Meteo Variables Used (real call is commented out):
    - temperature_2m_max, temperature_2m_min
    - precipitation_sum
    - windspeed_10m_max
    - relativehumidity_2m_max
    - uv_index_max
    - weathercode
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import List

import httpx

from app.core.config import settings
from app.core.exceptions import WeatherAPIError

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.open-meteo.com/v1/forecast"
_TIMEOUT = 10.0    # seconds
_MAX_RETRIES = 3


@dataclass(frozen=True)
class WeatherDataPoint:
    """One day of weather data returned by the client."""

    forecast_date: date
    temp_max_c: float
    temp_min_c: float
    humidity_pct: float
    precipitation_mm: float
    wind_speed_kmh: float
    uv_index: float | None
    weather_code: int | None
    source: str = "open-meteo"
    fetched_at: datetime = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        object.__setattr__(self, "fetched_at", datetime.now(tz=timezone.utc))


class WeatherClient:
    """HTTP client for fetching weather forecasts from Open-Meteo.

    Usage::

        client = WeatherClient()
        forecasts = await client.fetch_forecast(lat=44.4, lon=26.1, days=7)
    """

    async def fetch_forecast(
        self,
        lat: float,
        lon: float,
        *,
        days: int = 7,
    ) -> List[WeatherDataPoint]:
        """Fetch a multi-day weather forecast for a geographic point.

        Args:
            lat:  Latitude in decimal degrees (WGS84).
            lon:  Longitude in decimal degrees (WGS84).
            days: Number of forecast days (1–16).

        Returns:
            List of ``WeatherDataPoint`` objects, one per day.

        Raises:
            WeatherAPIError: If the API call fails after all retries.
        """
        logger.info("Fetching %d-day weather forecast for lat=%.4f lon=%.4f", days, lat, lon)

        # --- Real API call (uncomment when Open-Meteo quota is configured) ---
        # params = {
        #     "latitude": lat, "longitude": lon,
        #     "daily": [
        #         "temperature_2m_max", "temperature_2m_min",
        #         "precipitation_sum", "windspeed_10m_max",
        #         "relativehumidity_2m_max", "uv_index_max", "weathercode",
        #     ],
        #     "timezone": "UTC",
        #     "forecast_days": days,
        # }
        # async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        #     for attempt in range(1, _MAX_RETRIES + 1):
        #         try:
        #             resp = await client.get(_BASE_URL, params=params)
        #             resp.raise_for_status()
        #             return self._parse_response(resp.json(), days)
        #         except httpx.HTTPError as exc:
        #             if attempt == _MAX_RETRIES:
        #                 raise WeatherAPIError(f"Open-Meteo request failed: {exc}") from exc
        #             await asyncio.sleep(0.2 * (2 ** attempt))

        return self._mock_response(lat, lon, days)

    # ------------------------------------------------------------------
    # Parser (matches real Open-Meteo daily JSON structure)
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_response(data: dict, days: int) -> List[WeatherDataPoint]:
        """Parse an Open-Meteo JSON response into ``WeatherDataPoint`` list."""
        daily = data.get("daily", {})
        points = []
        for i in range(min(days, len(daily.get("time", [])))):
            points.append(WeatherDataPoint(
                forecast_date=date.fromisoformat(daily["time"][i]),
                temp_max_c=daily["temperature_2m_max"][i],
                temp_min_c=daily["temperature_2m_min"][i],
                humidity_pct=daily["relativehumidity_2m_max"][i],
                precipitation_mm=daily["precipitation_sum"][i] or 0.0,
                wind_speed_kmh=daily["windspeed_10m_max"][i] or 0.0,
                uv_index=daily.get("uv_index_max", [None])[i],
                weather_code=daily.get("weathercode", [None])[i],
            ))
        return points

    # ------------------------------------------------------------------
    # Mock Response — realistic agronomic data for Romanian climate
    # ------------------------------------------------------------------

    @staticmethod
    def _mock_response(lat: float, lon: float, days: int) -> List[WeatherDataPoint]:
        """Generate realistic mock weather data for development/testing.

        Values are seeded on (lat, lon) so repeated calls return consistent
        results for the same parcel location.
        """
        rng = random.Random(hash((round(lat, 2), round(lon, 2))))
        today = date.today()
        results = []

        for i in range(days):
            fc_date = today + timedelta(days=i)
            # Seasonal temperature approximation (Romania: ~45°N)
            month = fc_date.month
            base_temp = 15 + 12 * abs(6 - month) / 6 * -1 + 5  # crude seasonal curve
            temp_max = round(base_temp + rng.uniform(2, 6), 1)
            temp_min = round(base_temp - rng.uniform(4, 8), 1)

            results.append(WeatherDataPoint(
                forecast_date=fc_date,
                temp_max_c=temp_max,
                temp_min_c=temp_min,
                humidity_pct=round(rng.uniform(45, 85), 1),
                precipitation_mm=round(rng.uniform(0, 15) if rng.random() > 0.6 else 0.0, 1),
                wind_speed_kmh=round(rng.uniform(5, 35), 1),
                uv_index=round(rng.uniform(1, 9), 1),
                weather_code=rng.choice([0, 1, 2, 3, 45, 51, 61, 63, 71, 80]),
                source="open-meteo-mock",
            ))

        logger.debug("Mock weather response: %d days for lat=%.4f lon=%.4f", days, lat, lon)
        return results
