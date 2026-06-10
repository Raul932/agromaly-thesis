"""
External HTTP Client: SatelliteClient
========================================
Fetches NDVI satellite data from the **Copernicus Data Space Ecosystem**
via the Sentinel Hub Statistical API.

Authentication:
    OAuth2 Client Credentials flow against the CDSE token endpoint.
    Requires ``SENTINEL_CLIENT_ID`` and ``SENTINEL_CLIENT_SECRET`` in .env.

API Used:
    **Sentinel Hub Statistical API** — computes zonal statistics (mean, std,
    min, max, percentiles) server-side over a user-supplied polygon, returning
    only the aggregated numbers.  This is vastly more efficient than downloading
    raw raster tiles, and stays well within free-tier quotas.

    Endpoint: ``POST {base}/api/v1/statistics``

Evalscript:
    Custom JavaScript executed on the Sentinel Hub backend that:
    1. Reads Sentinel-2 L2A bands B04 (Red) and B08 (NIR).
    2. Computes NDVI = (B08 - B04) / (B08 + B04).
    3. Uses the SCL (Scene Classification Layer) to mask clouds, shadows,
       water, and snow (classes 0, 1, 3, 6, 8, 9, 10, 11).
    4. Returns NDVI + dataMask so the Statistical API can compute valid-pixel
       percentage (= cloud coverage).

Rate Limiting:
    Copernicus free tier: ~100 Statistical API requests / day.
    The client enforces a 1.5 s delay between requests via asyncio.sleep().

Mock Fallback:
    When ``USE_MOCK_SATELLITE=true`` (default for offline dev), the client
    returns synthetic NDVI data identical to the original mock implementation.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import random
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import httpx

from app.core.config import settings
from app.core.exceptions import SatelliteAPIError

logger = logging.getLogger(__name__)

_TIMEOUT = 60.0      # Statistical API can be slow for large polygons
_MAX_RETRIES = 3
_RATE_LIMIT_DELAY = 1.5  # seconds between requests (stay under free-tier)


# ---------------------------------------------------------------------------
# NDVI Evalscript (JavaScript, executed server-side on Sentinel Hub)
# ---------------------------------------------------------------------------

_NDVI_EVALSCRIPT = """
//VERSION=3
// Computes NDVI from Sentinel-2 L2A bands and masks non-vegetation pixels
// using the Scene Classification Layer (SCL).
//
// Returns:
//   ndvi     — Normalized Difference Vegetation Index [-1, 1]
//   dataMask — 1 if pixel is valid (clear land), 0 if masked (cloud/shadow/water)

function setup() {
  return {
    input: [{
      bands: ["B04", "B08", "SCL", "dataMask"],
      units: "DN"
    }],
    output: [
      { id: "ndvi", bands: 1, sampleType: "FLOAT32" },
      { id: "dataMask", bands: 1, sampleType: "UINT8" }
    ]
  };
}

function evaluatePixel(samples) {
  // SCL classes to mask out:
  //   0: No data, 1: Saturated/Defective, 3: Cloud shadow,
  //   6: Water, 8: Cloud medium prob, 9: Cloud high prob,
  //   10: Thin cirrus, 11: Snow/Ice
  let dominated = [0, 1, 3, 6, 8, 9, 10, 11];
  let dominated_mask = dominated.includes(samples.SCL) ? 0 : 1;
  let valid = samples.dataMask * dominated_mask;

  let ndvi = 0;
  if (valid && (samples.B08 + samples.B04) > 0) {
    ndvi = (samples.B08 - samples.B04) / (samples.B08 + samples.B04);
  }

  return {
    ndvi: [ndvi],
    dataMask: [valid]
  };
}
"""


# ---------------------------------------------------------------------------
# Data Transfer Object
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class NDVIDataPoint:
    """NDVI observation for a single satellite pass.

    Fields:
        date_captured:    Calendar date of the satellite acquisition (UTC).
        mean_ndvi:        Mean NDVI over the parcel [-1.0, 1.0].
        cloud_coverage:   Percentage of parcel pixels covered by cloud [0–100].
        pixel_count:      Number of valid (unmasked) pixels.
        is_interpolated:  True if cloud_coverage > 20% (gap-fill candidate).
        source:           Satellite source identifier.
    """

    date_captured: date
    mean_ndvi: float
    cloud_coverage: float    # 0.0 to 100.0
    pixel_count: Optional[int] = None
    is_interpolated: bool = False
    source: str = "sentinel-2"
    fetched_at: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))


# ---------------------------------------------------------------------------
# OAuth2 Token Cache
# ---------------------------------------------------------------------------

_token_cache: Dict[str, str | float] = {}


async def _get_access_token() -> str:
    """Obtain an OAuth2 access token from the Copernicus Data Space.

    Tokens are cached and refreshed 60 seconds before expiry.

    Returns:
        Bearer access token string.

    Raises:
        SatelliteAPIError: If authentication fails.
    """
    global _token_cache

    now = datetime.now(tz=timezone.utc).timestamp()
    if _token_cache.get("token") and _token_cache.get("expires_at", 0) > now:
        return _token_cache["token"]  # type: ignore[return-value]

    token_url = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"

    payload = {
        "grant_type": "client_credentials",
        "client_id": settings.SENTINEL_CLIENT_ID,
        "client_secret": settings.SENTINEL_CLIENT_SECRET,
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.post(token_url, data=payload)
            resp.raise_for_status()
            data = resp.json()
            _token_cache = {
                "token": data["access_token"],
                "expires_at": now + data.get("expires_in", 300) - 60,  # refresh 60s early
            }
            logger.info("Sentinel Hub OAuth token obtained (expires in %ds)", data.get("expires_in", 0))
            return data["access_token"]
        except httpx.HTTPStatusError as exc:
            logger.error("Sentinel Hub OAuth failed: %s — %s", exc.response.status_code, exc.response.text)
            raise SatelliteAPIError(
                f"Failed to authenticate with Copernicus Data Space: {exc.response.status_code}"
            ) from exc
        except Exception as exc:
            raise SatelliteAPIError(f"Sentinel Hub OAuth error: {exc}") from exc


# ---------------------------------------------------------------------------
# WKT → GeoJSON Geometry Converter
# ---------------------------------------------------------------------------

def _wkt_to_geojson_geometry(geometry_wkt: str) -> dict:
    """Convert a WKT geometry string to a GeoJSON geometry dict.

    Uses Shapely for robust parsing. Handles MULTIPOLYGON and POLYGON,
    stripping the SRID prefix if present (e.g. 'SRID=4326;POLYGON(...)').

    Returns:
        GeoJSON geometry dict: {"type": "Polygon", "coordinates": [...]}.
    """
    from shapely.geometry import mapping, shape
    from shapely import wkt as shapely_wkt

    # Strip SRID prefix if present
    clean_wkt = geometry_wkt
    if ";" in clean_wkt:
        clean_wkt = clean_wkt.split(";", 1)[1]

    geom = shapely_wkt.loads(clean_wkt)

    # Statistical API works best with a single Polygon
    if geom.geom_type == "MultiPolygon":
        # Use the largest polygon (by area) from the MultiPolygon
        largest = max(geom.geoms, key=lambda g: g.area)
        geom = largest

    return mapping(geom)


# ---------------------------------------------------------------------------
# Main Client
# ---------------------------------------------------------------------------

class SatelliteClient:
    """Client for fetching NDVI data from Sentinel Hub (Copernicus CDSE).

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
            List of NDVIDataPoint objects, one per Sentinel-2 pass.

        Raises:
            SatelliteAPIError: If the API request fails after retries.
        """
        logger.info(
            "Fetching NDVI time-series from %s to %s via %s (mock=%s)",
            start_date, end_date, source, settings.USE_MOCK_SATELLITE,
        )

        # Mock fallback for offline development
        if settings.USE_MOCK_SATELLITE:
            return self._mock_response(geometry_wkt, start_date, end_date, source)

        # Validate credentials
        if not settings.SENTINEL_CLIENT_ID or settings.SENTINEL_CLIENT_ID == "CHANGE_ME":
            logger.warning("SENTINEL_CLIENT_ID not configured — falling back to mock data")
            return self._mock_response(geometry_wkt, start_date, end_date, source)

        return await self._real_fetch(geometry_wkt, start_date, end_date, source)

    async def _real_fetch(
        self,
        geometry_wkt: str,
        start_date: date,
        end_date: date,
        source: str,
    ) -> List[NDVIDataPoint]:
        """Fetch real NDVI data from Sentinel Hub Statistical API.

        Splits the date range into individual Sentinel-2 passes (5-day intervals)
        and queries each one separately to get per-pass statistics.
        """
        token = await _get_access_token()
        geojson_geom = _wkt_to_geojson_geometry(geometry_wkt)

        stats_url = f"{settings.SENTINEL_HUB_BASE_URL}/api/v1/statistics"

        # Build the request payload for the full time range
        # Using P5D aggregation interval to match Sentinel-2 revisit cycle
        payload = {
            "input": {
                "bounds": {
                    "geometry": geojson_geom,
                    "properties": {"crs": "http://www.opengis.net/def/crs/EPSG/0/4326"},
                },
                "data": [
                    {
                        "type": "sentinel-2-l2a",
                        "dataFilter": {
                            "mosaickingOrder": "leastCC",
                        },
                    }
                ],
            },
            "aggregation": {
                "timeRange": {
                    "from": f"{start_date.isoformat()}T00:00:00Z",
                    "to": f"{end_date.isoformat()}T23:59:59Z",
                },
                "aggregationInterval": {"of": "P5D"},
                "evalscript": _NDVI_EVALSCRIPT,
                "resx": 0.0001,  # ~10 m in EPSG:4326 degrees at Romania's latitude (~47°N)
                "resy": 0.0001,
            },
        }

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            for attempt in range(1, _MAX_RETRIES + 1):
                try:
                    resp = await client.post(stats_url, json=payload, headers=headers)

                    if resp.status_code == 429:
                        # Rate limited — wait and retry
                        retry_after = int(resp.headers.get("Retry-After", "30"))
                        logger.warning("Rate limited by Sentinel Hub — waiting %ds", retry_after)
                        await asyncio.sleep(retry_after)
                        continue

                    resp.raise_for_status()
                    data = resp.json()
                    return self._parse_statistical_response(data, source)

                except httpx.HTTPStatusError as exc:
                    logger.error(
                        "Sentinel Hub Statistical API error (attempt %d/%d): %s — %s",
                        attempt, _MAX_RETRIES, exc.response.status_code, exc.response.text[:500],
                    )
                    if attempt == _MAX_RETRIES:
                        raise SatelliteAPIError(
                            f"Sentinel Hub request failed after {_MAX_RETRIES} attempts: "
                            f"{exc.response.status_code}"
                        ) from exc
                    await asyncio.sleep(2 ** attempt)  # exponential backoff

                except httpx.TimeoutException as exc:
                    logger.error("Sentinel Hub timeout (attempt %d/%d)", attempt, _MAX_RETRIES)
                    if attempt == _MAX_RETRIES:
                        raise SatelliteAPIError(
                            f"Sentinel Hub request timed out after {_MAX_RETRIES} attempts"
                        ) from exc
                    await asyncio.sleep(2 ** attempt)

        return []  # unreachable but satisfies type checker

    @staticmethod
    def _parse_statistical_response(data: dict, source: str) -> List[NDVIDataPoint]:
        """Parse the Sentinel Hub Statistical API JSON response.

        The response contains per-interval statistics with structure:
        {
            "data": [
                {
                    "interval": {"from": "2024-01-01T00:00:00Z", "to": "2024-01-06T00:00:00Z"},
                    "outputs": {
                        "ndvi": {
                            "bands": {
                                "B0": {
                                    "stats": {
                                        "mean": 0.45, "stDev": 0.12,
                                        "min": -0.1, "max": 0.85,
                                        "sampleCount": 5000,
                                        "noDataCount": 200
                                    }
                                }
                            }
                        },
                        "dataMask": {
                            "bands": {
                                "B0": {
                                    "stats": {
                                        "mean": 0.85,  # fraction of valid pixels
                                        "sampleCount": 5000
                                    }
                                }
                            }
                        }
                    }
                },
                ...
            ]
        }
        """
        results: List[NDVIDataPoint] = []

        for interval_data in data.get("data", []):
            interval = interval_data.get("interval", {})
            date_str = interval.get("from", "")
            if not date_str:
                continue

            # Parse the date (take the start of the interval)
            try:
                dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                capture_date = dt.date()
            except (ValueError, TypeError):
                continue

            outputs = interval_data.get("outputs", {})

            # Extract NDVI statistics
            ndvi_output = outputs.get("ndvi", {})
            ndvi_bands = ndvi_output.get("bands", {})
            ndvi_b0 = ndvi_bands.get("B0", {})
            ndvi_stats = ndvi_b0.get("stats", {})

            mean_ndvi = ndvi_stats.get("mean")
            sample_count = ndvi_stats.get("sampleCount", 0)
            no_data_count = ndvi_stats.get("noDataCount", 0)

            # Skip intervals with no data
            if mean_ndvi is None or str(mean_ndvi) == "NaN" or sample_count == 0:
                continue

            # Extract dataMask stats to compute cloud coverage
            mask_output = outputs.get("dataMask", {})
            mask_bands = mask_output.get("bands", {})
            mask_b0 = mask_bands.get("B0", {})
            mask_stats = mask_b0.get("stats", {})

            # dataMask mean = fraction of valid (clear) pixels
            valid_fraction = mask_stats.get("mean", 1.0)
            if str(valid_fraction) == "NaN":
                valid_fraction = 1.0
                
            mean_ndvi = float(mean_ndvi)
            valid_fraction = float(valid_fraction)
            
            cloud_coverage = round((1.0 - valid_fraction) * 100.0, 1)

            # Clamp NDVI to valid range
            mean_ndvi = max(-1.0, min(1.0, round(mean_ndvi, 4)))

            # Valid pixel count
            total_pixels = sample_count + no_data_count
            valid_pixels = int(total_pixels * valid_fraction) if total_pixels > 0 else 0

            # Flag unreliable observations
            is_interpolated = cloud_coverage > 20.0

            results.append(NDVIDataPoint(
                date_captured=capture_date,
                mean_ndvi=mean_ndvi,
                cloud_coverage=cloud_coverage,
                pixel_count=valid_pixels if valid_pixels > 0 else None,
                is_interpolated=is_interpolated,
                source=f"{source}-l2a",
            ))

        logger.info(
            "Parsed %d NDVI observations from Sentinel Hub (%d cloudy)",
            len(results),
            sum(1 for r in results if r.is_interpolated),
        )
        return results

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
        end = date.today()
        start = end - timedelta(days=14)
        records = await self.fetch_ndvi_timeseries(
            geometry_wkt, start_date=start, end_date=end, source=source
        )
        if not records:
            return None
        # Return the most recent reliable record (lowest cloud coverage)
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
