"""
Domain Entity: NDVIRecord
==========================
Represents a single satellite-derived NDVI observation for a parcel.

Background:
    NDVI (Normalized Difference Vegetation Index) is computed from
    multispectral satellite imagery (Sentinel-2, Landsat, etc.).
    Values range from -1.0 (water/bare soil) to 1.0 (dense healthy vegetation).
    Healthy crops typically read 0.4–0.9 depending on growth stage.

    ``is_interpolated`` flags records where cloud coverage was too high to
    compute a real NDVI; a synthetic value was gap-filled from nearby dates
    (e.g. linear interpolation). The LSTM Autoencoder uses this flag to
    weight anomaly scores appropriately.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Optional


@dataclass(frozen=True)
class NDVIRecord:
    """A single NDVI measurement associated with an agricultural parcel.

    Attributes:
        id:              Unique record identifier (UUID v4).
        parcel_id:       UUID of the parent Parcel aggregate.
        date_captured:   Calendar date of the satellite pass (UTC).
        mean_ndvi:       Mean NDVI value over the parcel area (-1.0 to 1.0).
        cloud_coverage:  Percentage of the parcel obscured by clouds (0.0–100.0).
        pixel_count:     Number of satellite pixels averaged to produce mean_ndvi.
        is_interpolated: True if this value was gap-filled due to cloud coverage.
        source:          Satellite source identifier (e.g. "sentinel-2", "landsat-8").
        created_at:      UTC timestamp when this record entered the system.
    """

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    parcel_id: uuid.UUID = field(default=...)
    date_captured: date = field(default=...)
    mean_ndvi: float = field(default=...)
    cloud_coverage: float = field(default=0.0)
    pixel_count: Optional[int] = field(default=None)
    is_interpolated: bool = field(default=False)
    source: str = field(default="unknown")
    created_at: datetime = field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )

    def __post_init__(self) -> None:
        self._validate_ndvi()
        self._validate_cloud_coverage()
        self._validate_pixel_count()

    def _validate_ndvi(self) -> None:
        if not isinstance(self.mean_ndvi, (int, float)):
            raise ValueError("'mean_ndvi' must be a numeric value.")
        if not (-1.0 <= self.mean_ndvi <= 1.0):
            raise ValueError(
                f"'mean_ndvi' must be in [-1.0, 1.0], got {self.mean_ndvi}."
            )

    def _validate_cloud_coverage(self) -> None:
        if not isinstance(self.cloud_coverage, (int, float)):
            raise ValueError("'cloud_coverage' must be a numeric value.")
        if not (0.0 <= self.cloud_coverage <= 100.0):
            raise ValueError(
                f"'cloud_coverage' must be in [0.0, 100.0], got {self.cloud_coverage}."
            )

    def _validate_pixel_count(self) -> None:
        if self.pixel_count is not None and self.pixel_count < 0:
            raise ValueError(
                f"'pixel_count' must be non-negative, got {self.pixel_count}."
            )

    # ------------------------------------------------------------------
    # Computed Properties
    # ------------------------------------------------------------------

    @property
    def is_reliable(self) -> bool:
        """Return True if cloud coverage is below 20% and value is not interpolated."""
        return self.cloud_coverage < 20.0 and not self.is_interpolated

    @property
    def vegetation_class(self) -> str:
        """Classify NDVI into agronomic health bands."""
        if self.mean_ndvi < 0.1:
            return "bare_soil_or_water"
        elif self.mean_ndvi < 0.25:
            return "sparse_vegetation"
        elif self.mean_ndvi < 0.45:
            return "moderate_vegetation"
        elif self.mean_ndvi < 0.70:
            return "healthy_vegetation"
        else:
            return "dense_healthy_vegetation"

    def __repr__(self) -> str:
        return (
            f"NDVIRecord(id={self.id!s}, parcel_id={self.parcel_id!s}, "
            f"date={self.date_captured!s}, ndvi={self.mean_ndvi:.4f}, "
            f"cloud={self.cloud_coverage:.1f}%, interpolated={self.is_interpolated})"
        )
