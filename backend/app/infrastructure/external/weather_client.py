"""
External HTTP Client: WeatherClient
=====================================
Fetches weather data from the Open-Meteo API (free, no API key required).

Two modes of operation:
    1. **Forecast** (``fetch_forecast``): Uses the Forecast API to get the
       next 7 days. Used by the weather alerts Celery task.
    2. **Historical** (``fetch_historical_weather``): Uses the Archive API to
       get past daily weather for a date range. Used by the LSTM training
       notebook and the anomaly detection inference pipeline.

Both modes return ``WeatherDataPoint`` objects for consistent downstream usage.

Open-Meteo API Details:
    - Forecast: ``https://api.open-meteo.com/v1/forecast``
    - Archive:  ``https://archive-api.open-meteo.com/v1/archive``
    - No API key required for non-commercial use.
    - Rate limit: ~10,000 requests/day (very generous).
"""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional

import httpx

from app.core.config import settings
from app.core.exceptions import WeatherAPIError

logger = logging.getLogger(__name__)

_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
_TIMEOUT = 15.0    # seconds
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
    """HTTP client for fetching weather data from Open-Meteo.

    Usage::

        client = WeatherClient()

        # Future forecast (next 7 days)
        forecasts = await client.fetch_forecast(lat=44.4, lon=26.1, days=7)

        # Historical archive (past data for LSTM training)
        history = await client.fetch_historical_weather(
            lat=46.77, lon=21.32,
            start_date=date(2024, 1, 1),
            end_date=date(2025, 12, 31),
        )
    """

    # ==================================================================
    # Forecast API (future weather — used by weather alerts task)
    # ==================================================================

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

        params = {
            "latitude": lat,
            "longitude": lon,
            "daily": ",".join([
                "temperature_2m_max", "temperature_2m_min",
                "precipitation_sum", "wind_speed_10m_max",
                "relative_humidity_2m_max", "uv_index_max", "weather_code",
            ]),
            "timezone": "UTC",
            "forecast_days": days,
        }

        return await self._fetch_daily(_FORECAST_URL, params, source="open-meteo")

    # ==================================================================
    # Archive API (historical weather — used by LSTM training & inference)
    # ==================================================================

    async def fetch_historical_weather(
        self,
        lat: float,
        lon: float,
        *,
        start_date: date,
        end_date: date,
    ) -> List[WeatherDataPoint]:
        """Fetch historical daily weather data from the Open-Meteo Archive API.

        This is the primary data source for LSTM Autoencoder training.
        Returns one ``WeatherDataPoint`` per calendar day in the range.

        The Archive API supports dates from 1940 to ~5 days ago
        (there's a ~5-day lag for archive ingestion).

        Args:
            lat:        Latitude in decimal degrees (WGS84).
            lon:        Longitude in decimal degrees (WGS84).
            start_date: First day of the range (inclusive).
            end_date:   Last day of the range (inclusive).

        Returns:
            List of ``WeatherDataPoint`` objects, one per day, sorted chronologically.

        Raises:
            WeatherAPIError: If the API call fails.
        """
        # Clamp end_date to ~5 days ago (archive lag)
        max_date = date.today() - timedelta(days=5)
        if end_date > max_date:
            end_date = max_date
            logger.info("Clamped end_date to %s (archive lag)", end_date)

        if start_date >= end_date:
            logger.warning("start_date >= end_date after clamping — returning empty")
            return []

        logger.info(
            "Fetching historical weather from %s to %s for lat=%.4f lon=%.4f",
            start_date, end_date, lat, lon,
        )

        params = {
            "latitude": lat,
            "longitude": lon,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "daily": ",".join([
                "temperature_2m_max", "temperature_2m_min",
                "precipitation_sum", "wind_speed_10m_max",
                "relative_humidity_2m_mean", "weather_code",
            ]),
            "timezone": "UTC",
        }

        return await self._fetch_daily(
            _ARCHIVE_URL, params, source="open-meteo-archive"
        )

    # ==================================================================
    # Shared HTTP + parsing logic
    # ==================================================================

    async def _fetch_daily(
        self,
        url: str,
        params: dict,
        *,
        source: str,
    ) -> List[WeatherDataPoint]:
        """Execute a daily weather API call with retries.

        Works for both the Forecast and Archive endpoints since they
        share the same response structure.
        """
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            for attempt in range(1, _MAX_RETRIES + 1):
                try:
                    resp = await client.get(url, params=params)
                    resp.raise_for_status()
                    return self._parse_daily_response(resp.json(), source=source)
                except httpx.HTTPStatusError as exc:
                    logger.error(
                        "Open-Meteo API error (attempt %d/%d): %s — %s",
                        attempt, _MAX_RETRIES,
                        exc.response.status_code,
                        exc.response.text[:300],
                    )
                    if attempt == _MAX_RETRIES:
                        raise WeatherAPIError(
                            f"Open-Meteo request failed after {_MAX_RETRIES} attempts: "
                            f"{exc.response.status_code}"
                        ) from exc
                    await asyncio.sleep(0.5 * (2 ** attempt))
                except httpx.TimeoutException as exc:
                    logger.error(
                        "Open-Meteo timeout (attempt %d/%d)", attempt, _MAX_RETRIES,
                    )
                    if attempt == _MAX_RETRIES:
                        raise WeatherAPIError(
                            f"Open-Meteo request timed out after {_MAX_RETRIES} attempts"
                        ) from exc
                    await asyncio.sleep(0.5 * (2 ** attempt))
                except Exception as exc:
                    raise WeatherAPIError(f"Open-Meteo unexpected error: {exc}") from exc

        return []  # unreachable

    @staticmethod
    def _parse_daily_response(data: dict, *, source: str) -> List[WeatherDataPoint]:
        """Parse an Open-Meteo daily JSON response into WeatherDataPoint list.

        Handles both Forecast and Archive response formats (same structure).
        Gracefully handles missing fields with sensible defaults.
        """
        daily = data.get("daily", {})
        times = daily.get("time", [])

        if not times:
            logger.warning("Open-Meteo response has no daily time series")
            return []

        # Extract arrays with fallbacks for missing fields
        temp_max = daily.get("temperature_2m_max", [])
        temp_min = daily.get("temperature_2m_min", [])
        precip = daily.get("precipitation_sum", [])
        wind = daily.get("wind_speed_10m_max", [])
        # Accept both field name variants (forecast vs archive may differ)
        humidity = (
            daily.get("relative_humidity_2m_max", [])
            or daily.get("relative_humidity_2m_mean", [])
        )
        uv = daily.get("uv_index_max", [])
        weather_codes = daily.get("weather_code", [])

        points: List[WeatherDataPoint] = []

        for i, time_str in enumerate(times):
            try:
                fc_date = date.fromisoformat(time_str)
            except (ValueError, TypeError):
                continue

            # Safe index access with defaults
            t_max = temp_max[i] if i < len(temp_max) and temp_max[i] is not None else 20.0
            t_min = temp_min[i] if i < len(temp_min) and temp_min[i] is not None else 10.0
            hum = humidity[i] if i < len(humidity) and humidity[i] is not None else 50.0
            prec = precip[i] if i < len(precip) and precip[i] is not None else 0.0
            wnd = wind[i] if i < len(wind) and wind[i] is not None else 0.0
            uv_val = uv[i] if i < len(uv) else None
            wc = weather_codes[i] if i < len(weather_codes) else None

            points.append(WeatherDataPoint(
                forecast_date=fc_date,
                temp_max_c=round(t_max, 1),
                temp_min_c=round(t_min, 1),
                humidity_pct=round(hum, 1),
                precipitation_mm=round(prec, 1),
                wind_speed_kmh=round(wnd, 1),
                uv_index=round(uv_val, 1) if uv_val is not None else None,
                weather_code=int(wc) if wc is not None else None,
                source=source,
            ))

        logger.info(
            "Parsed %d daily weather records from Open-Meteo (%s)",
            len(points), source,
        )
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
