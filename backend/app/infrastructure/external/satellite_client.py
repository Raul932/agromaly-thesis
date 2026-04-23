"""
External HTTP Client: SatelliteClient
========================================
Fetches NDVI satellite data for a parcel geometry from the Sentinel Hub API.
The mocked response includes ``cloud_coverage`` as a first-class field because:

    1. Real Sentinel-2 imagery is frequently obscured by clouds (especially in
       temperate climates — Romania averages 40–60% cloudy days).
    2. The NDVI anomaly detection pipeline MUST know which observations are
       reliable vs. cloud-contaminated.
    3. Poor-quality records (cloud_coverage > 20%) will be flagged as
       ``is_interpolated=True`` by the ingestion logic, to be gap-filled
       using linear interpolation or a Kalman filter before LSTM inference.

Real Integration Notes (Sentinel Hub):
    - Endpoint: https://services.sentinel-hub.com/api/v1/process
    - Requires OAuth2 client credentials (SENTINEL_HUB_CLIENT_ID / SECRET).
    - Returns GeoTIFF or raw pixel arrays; NDVI is computed as (NIR-Red)/(NIR+Red).
    - Cloud detection uses the Sentinel-2 SCL (Scene Classification Layer).

Mock Design:
    The mock generates NDVI values with:
    - Realistic seasonal vegetation curves (NDVI peaks in summer).
    - Random cloud events with realistic cloud cover percentages.
    - Statistical noise consistent with real Sentinel-2 L2A products.
"""

from __future__ import annotations

import logging
import math
import random
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import List, Optional

import httpx

from app.core.exceptions import SatelliteAPIError

logger = logging.getLogger(__name__)

_SENTINEL_HUB_URL = "https://services.sentinel-hub.com/api/v1/process"
_TIMEOUT = 30.0     # Satellite API calls can be slow (GeoTIFF processing)
_MAX_RETRIES = 3


@dataclass(frozen=True)
class NDVIDataPoint:
    """NDVI observation for a single satellite pass.

    Fields:
        date_captured:    Calendar date of the satellite acquisition (UTC).
        mean_ndvi:        Mean NDVI over the parcel [-1.0, 1.0].
                          Healthy vegetation: 0.2–0.9.
                          Bare soil: -0.1–0.2.
        cloud_coverage:   Percentage of parcel pixels covered by cloud [0–100].
                          Values > 20% indicate a potentially unreliable observation.
        pixel_count:      Number of 10m Sentinel-2 pixels averaged.
        is_interpolated:  True if cloud_coverage > 20% (data gap-filled).
        source:           Satellite identifier.
    """

    date_captured: date
    mean_ndvi: float
    cloud_coverage: float    # CRITICAL field — 0.0 to 100.0
    pixel_count: Optional[int] = None
    is_interpolated: bool = False
    source: str = "sentinel-2"
    fetched_at: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))


class SatelliteClient:
    """HTTP client for fetching NDVI data from Sentinel Hub.

    Usage::

        client = SatelliteClient()
        records = await client.fetch_ndvi_timeseries(
            geometry_wkt="MULTIPOLYGON(...)",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
        )
    """

    async def fetch_ndvi_timeseries(
        self,
        geometry_wkt: str,
        *,
        start_date: date,
        end_date: date,
        source: str = "sentinel-2",
    ) -> List[NDVIDataPoint]:
        """Fetch NDVI time-series data for a parcel geometry.

        Args:
            geometry_wkt: Parcel boundary in WKT format (MULTIPOLYGON, SRID 4326).
            start_date:   Beginning of the acquisition window.
            end_date:     End of the acquisition window.
            source:       Satellite source identifier.

        Returns:
            List of ``NDVIDataPoint`` objects — one per cloud-free (or partially
            cloudy) satellite pass in the date range.

        Raises:
            SatelliteAPIError: If the Sentinel Hub request fails after retries.
        """
        logger.info(
            "Fetching NDVI time-series from %s to %s via %s",
            start_date, end_date, source,
        )

        # --- Real Sentinel Hub call (uncomment and add auth when available) ---
        # payload = {
        #     "input": {
        #         "bounds": {"geometry": shapely_geom_to_geojson(geometry_wkt)},
        #         "data": [{"type": "S2L2A", "dataFilter": {
        #             "timeRange": {"from": start_date.isoformat(), "to": end_date.isoformat()},
        #             "maxCloudCoverage": 100,  # Fetch all; filter client-side
        #         }}],
        #     },
        #     "output": {"responses": [{"identifier": "default", "format": {"type": "application/json"}}]},
        #     "evalscript": _NDVI_EVALSCRIPT,
        # }
        # headers = {"Authorization": f"Bearer {await self._get_token()}"}
        # async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        #     for attempt in range(1, _MAX_RETRIES + 1):
        #         try:
        #             resp = await client.post(_SENTINEL_HUB_URL, json=payload, headers=headers)
        #             resp.raise_for_status()
        #             return self._parse_response(resp.json(), source)
        #         except httpx.HTTPError as exc:
        #             if attempt == _MAX_RETRIES:
        #                 raise SatelliteAPIError(f"Sentinel Hub request failed: {exc}") from exc

        return self._mock_response(geometry_wkt, start_date, end_date, source)

    async def fetch_latest_ndvi(
        self,
        geometry_wkt: str,
        *,
        source: str = "sentinel-2",
    ) -> Optional[NDVIDataPoint]:
        """Fetch only the most recent NDVI observation (last 14 days).

        Used by the parcel-creation trigger to quickly populate ``last_ndvi``.

        Returns:
            The most recent ``NDVIDataPoint``, or None if no passes found.
        """
        from datetime import timedelta
        end = date.today()
        start = end - timedelta(days=14)
        records = await self.fetch_ndvi_timeseries(
            geometry_wkt, start_date=start, end_date=end, source=source
        )
        # Return the most recent reliable record (lowest cloud coverage)
        if not records:
            return None
        return min(records, key=lambda r: r.cloud_coverage)

    # ------------------------------------------------------------------
    # Mock Response — realistic Sentinel-2 NDVI data
    # ------------------------------------------------------------------

    @staticmethod
    def _mock_response(
        geometry_wkt: str,
        start_date: date,
        end_date: date,
        source: str,
    ) -> List[NDVIDataPoint]:
        """Generate realistic mock NDVI data with cloud events.

        Simulates Sentinel-2's 5-day revisit cycle with:
        - Seasonal NDVI vegetation curve (0.2 in winter → 0.7 in summer).
        - Random cloud events (30% probability per pass, 0–100% coverage).
        - Gaussian noise (σ=0.03) to mimic real pixel variance.
        """
        # Seed on WKT hash for consistent results per parcel
        rng = random.Random(hash(geometry_wkt[:50]))

        results: List[NDVIDataPoint] = []
        current = start_date
        sentinel_revisit_days = 5  # Sentinel-2A + 2B combined: ~5 days

        while current <= end_date:
            # Seasonal NDVI: peaks in June-July (month 6-7 in Northern Hemisphere)
            # Using a sinusoidal approximation
            day_of_year = current.timetuple().tm_yday
            seasonal_ndvi = 0.35 + 0.35 * math.sin(
                math.pi * (day_of_year - 80) / 180  # peak ~day 170 (mid-June)
            )
            seasonal_ndvi = max(0.05, min(0.95, seasonal_ndvi))

            # Add realistic Gaussian noise (σ=0.04)
            noisy_ndvi = seasonal_ndvi + rng.gauss(0, 0.04)
            noisy_ndvi = round(max(-0.1, min(1.0, noisy_ndvi)), 4)

            # Cloud event simulation
            # Romanian climate: ~35% of days have cloud cover affecting Sentinel
            has_cloud_event = rng.random() < 0.35
            if has_cloud_event:
                # Cloud coverage follows a bimodal distribution:
                # either thin clouds (5–25%) or thick clouds (60–100%)
                if rng.random() < 0.4:
                    cloud_pct = round(rng.uniform(5.0, 25.0), 1)   # thin: usable
                else:
                    cloud_pct = round(rng.uniform(60.0, 100.0), 1)  # thick: interpolate
            else:
                cloud_pct = round(rng.uniform(0.0, 5.0), 1)  # essentially clear

            # Flag for gap-filling: > 20% cloud cover is considered unreliable
            is_interpolated = cloud_pct > 20.0

            # Pixel count: ~10m Sentinel pixels for a 1–500 ha parcel
            pixel_count = rng.randint(100, 50000)

            results.append(NDVIDataPoint(
                date_captured=current,
                mean_ndvi=noisy_ndvi,
                cloud_coverage=cloud_pct,
                pixel_count=pixel_count,
                is_interpolated=is_interpolated,
                source=f"{source}-mock",
            ))

            current += timedelta(days=sentinel_revisit_days)

        logger.debug(
            "Mock NDVI response: %d passes from %s to %s (%d cloudy)",
            len(results), start_date, end_date,
            sum(1 for r in results if r.is_interpolated),
        )
        return results
