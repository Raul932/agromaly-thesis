"""
Domain Entity: WeatherForecast
================================
Represents a localized daily weather forecast for a specific parcel.

Data Source:
    Populated by the Celery ``weather_alerts`` task which calls the
    Open-Meteo API (or OpenWeatherMap) and stores the parsed forecast
    for each active parcel's centroid coordinates.

Risk Assessment:
    Domain methods encode agronomic thresholds taken from standard
    crop-science literature (fungal risk, frost risk, drought stress).
    These rules live in the domain entity — NOT in the Celery task —
    so they can be independently unit-tested without any I/O.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Optional


@dataclass(frozen=True)
class WeatherForecast:
    """Daily weather forecast record linked to a specific parcel.

    Attributes:
        id:               Unique identifier.
        parcel_id:        UUID of the parent Parcel.
        forecast_date:    The calendar date this forecast applies to.
        temp_max_c:       Maximum air temperature in degrees Celsius.
        temp_min_c:       Minimum air temperature in degrees Celsius.
        humidity_pct:     Relative humidity percentage (0–100).
        precipitation_mm: Total expected precipitation in millimetres.
        wind_speed_kmh:   Mean wind speed in km/h.
        uv_index:         UV index (0–11+).
        weather_code:     WMO weather code (e.g. 0=clear, 61=rain, 71=snow).
        source:           API/provider name (e.g. "open-meteo", "openweathermap").
        fetched_at:       UTC timestamp when this forecast was fetched.
    """

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    parcel_id: uuid.UUID = field(default=...)
    forecast_date: date = field(default=...)
    temp_max_c: float = field(default=...)
    temp_min_c: float = field(default=...)
    humidity_pct: float = field(default=...)
    precipitation_mm: float = field(default=0.0)
    wind_speed_kmh: float = field(default=0.0)
    uv_index: Optional[float] = field(default=None)
    weather_code: Optional[int] = field(default=None)
    source: str = field(default="open-meteo")
    fetched_at: datetime = field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )

    def __post_init__(self) -> None:
        self._validate_temperatures()
        self._validate_humidity()
        self._validate_non_negative("precipitation_mm", self.precipitation_mm)
        self._validate_non_negative("wind_speed_kmh", self.wind_speed_kmh)

    def _validate_temperatures(self) -> None:
        """Absolute temperature limits (sanity check, not domain rule)."""
        for name, val in (("temp_max_c", self.temp_max_c), ("temp_min_c", self.temp_min_c)):
            if not isinstance(val, (int, float)):
                raise ValueError(f"'{name}' must be numeric.")
            if not (-90.0 <= val <= 60.0):
                raise ValueError(f"'{name}' is outside physically plausible range: {val}.")
        if self.temp_min_c > self.temp_max_c:
            raise ValueError(
                f"'temp_min_c' ({self.temp_min_c}) must not exceed "
                f"'temp_max_c' ({self.temp_max_c})."
            )

    def _validate_humidity(self) -> None:
        if not (0.0 <= self.humidity_pct <= 100.0):
            raise ValueError(
                f"'humidity_pct' must be in [0, 100], got {self.humidity_pct}."
            )

    def _validate_non_negative(self, field_name: str, value: float) -> None:
        if value < 0:
            raise ValueError(f"'{field_name}' must be non-negative, got {value}.")

    # ------------------------------------------------------------------
    # Agronomic Risk Assessments (Domain Logic)
    # ------------------------------------------------------------------

    @property
    def frost_risk(self) -> bool:
        """Return True if minimum temperature drops below 0°C (crop freeze risk)."""
        return self.temp_min_c < 0.0

    @property
    def fungal_disease_risk(self) -> bool:
        """High humidity + mild temps + rain = ideal conditions for fungal spread.

        Threshold: humidity ≥ 80%, precipitation > 5mm, temp in [10°C, 25°C].
        Based on Botrytis and Fusarium disease onset conditions.
        """
        return (
            self.humidity_pct >= 80.0
            and self.precipitation_mm > 5.0
            and 10.0 <= self.temp_max_c <= 25.0
        )

    @property
    def drought_stress_risk(self) -> bool:
        """Prolonged heat + zero rain = drought stress signal.

        Threshold: max temp ≥ 35°C, precipitation < 1mm.
        """
        return self.temp_max_c >= 35.0 and self.precipitation_mm < 1.0

    @property
    def heavy_rain_risk(self) -> bool:
        """Return True if precipitation exceeds 30mm (waterlogging / erosion risk)."""
        return self.precipitation_mm >= 30.0

    def __repr__(self) -> str:
        return (
            f"WeatherForecast(parcel={self.parcel_id!s}, date={self.forecast_date!s}, "
            f"T=[{self.temp_min_c:.1f}°C, {self.temp_max_c:.1f}°C], "
            f"rain={self.precipitation_mm:.1f}mm, RH={self.humidity_pct:.0f}%)"
        )
