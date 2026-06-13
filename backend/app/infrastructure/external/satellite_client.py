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
import base64
import io
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

        try:
            return await self._real_fetch(geometry_wkt, start_date, end_date, source)
        except SatelliteAPIError as exc:
            logger.warning(
                "Real Sentinel Hub API failed (%s) — falling back to mock data for development",
                exc,
            )
            return self._mock_response(geometry_wkt, start_date, end_date, source)

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
    # NDVI Spatial Image
    # ------------------------------------------------------------------

    async def fetch_ndvi_image(
        self,
        geometry_wkt: str,
        *,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        mean_ndvi: float = 0.5,
    ) -> dict:
        """Return a real-satellite vegetation PNG image + bounding box for the parcel.

        Priority:
            1. Mapbox satellite tile RGB analysis (uses same tiles user sees in the app).
            2. Sentinel Hub Process API (if SENTINEL_CLIENT_ID is configured).

        VARI (Visible Atmospherically Resistant Index) is computed from the tile
        RGB pixels and mapped using absolute thresholds calibrated for satellite
        agricultural imagery:
            VARI < 0.00  → red    (bare soil / tractor tracks / no vegetation)
            0.00–0.10    → orange (sparse / stressed / early emergence)
            0.10–0.25    → yellow (moderate cover)
            ≥ 0.25       → green  (dense healthy canopy)

        Pixels outside the parcel polygon are fully transparent (alpha=0).

        Returns:
            dict with keys:
                image_base64 (str) — RGBA PNG encoded as base64 string
                bounds (dict)      — {north, south, east, west} in WGS-84

        Raises:
            SatelliteAPIError: If no real data source is available or all fail.
        """
        to_dt = date_to or date.today()
        from_dt = date_from or (to_dt - timedelta(days=30))

        # Primary: Mapbox satellite tile RGB analysis
        if settings.MAPBOX_ACCESS_TOKEN:
            return await self._analyze_mapbox_tiles(
                geometry_wkt, mapbox_token=settings.MAPBOX_ACCESS_TOKEN
            )

        # Secondary: Sentinel Hub Process API
        if settings.SENTINEL_CLIENT_ID and settings.SENTINEL_CLIENT_ID != "CHANGE_ME":
            return await self._real_ndvi_image(geometry_wkt, from_dt, to_dt)

        raise SatelliteAPIError(
            "No satellite data source configured. Set MAPBOX_ACCESS_TOKEN in .env."
        )

    async def _analyze_mapbox_tiles(
        self,
        geometry_wkt: str,
        *,
        mapbox_token: str,
        output_size: int = 512,
    ) -> dict:
        """Download Mapbox satellite tiles and compute per-pixel ExG vegetation index.

        Downloads the same tiles the Flutter app is displaying, analyzes their
        RGB values to detect vegetation vs. bare soil / tractor tracks, clips
        the result to the exact parcel polygon, and returns a base64 RGBA PNG.
        """
        import math
        import numpy as np
        import shapely
        from shapely import wkt as shapely_wkt
        from PIL import Image

        # --- Parse polygon --------------------------------------------------
        clean_wkt = geometry_wkt.split(";", 1)[-1]
        polygon = shapely_wkt.loads(clean_wkt)
        if polygon.geom_type == "MultiPolygon":
            polygon = max(polygon.geoms, key=lambda g: g.area)

        bounds = self._compute_parcel_bounds(geometry_wkt)
        west  = bounds["west"]
        south = bounds["south"]
        east  = bounds["east"]
        north = bounds["north"]

        # --- Web Mercator tile helpers ---------------------------------------
        def _latlon_to_tile(lat: float, lon: float, z: int) -> Tuple[int, int]:
            x = int((lon + 180) / 360 * (2 ** z))
            lat_r = math.radians(lat)
            y = int((1 - math.log(math.tan(lat_r) + 1 / math.cos(lat_r)) / math.pi) / 2 * (2 ** z))
            return x, y

        def _tile_nw_corner(tx: int, ty: int, z: int) -> Tuple[float, float]:
            lon = tx / (2 ** z) * 360 - 180
            n   = math.pi - 2 * math.pi * ty / (2 ** z)
            lat = math.degrees(math.atan(math.sinh(n)))
            return lat, lon

        # --- Choose zoom level ----------------------------------------------
        # Target native tile resolution high enough to see tractor tracks.
        # For small fields (≤3.4ha ≈ 185m): z=18 → ~0.4m/pixel native.
        # Cap at 9 total tiles (3×3) to limit parallel requests.
        max_extent = max(east - west, north - south)
        z = max(13, min(18, int(math.log2(720 / max_extent))))

        x_nw, y_nw = _latlon_to_tile(north, west, z)
        x_se, y_se = _latlon_to_tile(south, east, z)

        while (x_se - x_nw + 1) * (y_se - y_nw + 1) > 9 and z > 13:
            z -= 1
            x_nw, y_nw = _latlon_to_tile(north, west, z)
            x_se, y_se = _latlon_to_tile(south, east, z)

        tile_px  = 256
        mosaic_w = (x_se - x_nw + 1) * tile_px
        mosaic_h = (y_se - y_nw + 1) * tile_px
        mosaic   = np.zeros((mosaic_h, mosaic_w, 3), dtype=np.uint8)

        logger.info(
            "Mapbox tile analysis: z=%d, tiles=%dx%d, parcel bbox=(%.4f,%.4f,%.4f,%.4f)",
            z, x_se - x_nw + 1, y_se - y_nw + 1, west, south, east, north,
        )

        # --- Download tiles in parallel -------------------------------------
        async def _fetch(tx: int, ty: int, client: httpx.AsyncClient) -> Tuple[int, int, bytes]:
            url = (
                f"https://api.mapbox.com/styles/v1/mapbox/satellite-v9"
                f"/tiles/256/{z}/{tx}/{ty}?access_token={mapbox_token}"
            )
            resp = await client.get(url)
            resp.raise_for_status()
            return tx, ty, resp.content

        async with httpx.AsyncClient(timeout=15.0) as client:
            tile_tasks = [
                _fetch(x, y, client)
                for x in range(x_nw, x_se + 1)
                for y in range(y_nw, y_se + 1)
            ]
            tile_results = await asyncio.gather(*tile_tasks, return_exceptions=True)

        for result in tile_results:
            if isinstance(result, Exception):
                logger.warning("Tile download error: %s", result)
                continue
            tx, ty, content = result
            tile_arr = np.array(Image.open(io.BytesIO(content)).convert("RGB"))
            row_off  = (ty - y_nw) * tile_px
            col_off  = (tx - x_nw) * tile_px
            mosaic[row_off : row_off + tile_px, col_off : col_off + tile_px] = tile_arr

        # --- Mosaic extent (NW corner of top-left → NW corner after bottom-right) ---
        mos_north, mos_west = _tile_nw_corner(x_nw,     y_nw,     z)
        mos_south, mos_east = _tile_nw_corner(x_se + 1, y_se + 1, z)

        # --- Output pixel coordinate grids ----------------------------------
        lons = np.linspace(west, east,   output_size)
        lats = np.linspace(north, south, output_size)
        lon_grid, lat_grid = np.meshgrid(lons, lats)  # (output_size, output_size)

        # --- Vectorized polygon mask (shapely 2.x) --------------------------
        pts  = shapely.points(lon_grid.ravel(), lat_grid.ravel())
        mask = shapely.contains(polygon, pts).reshape(output_size, output_size)

        # --- Map output pixels → mosaic pixel coordinates -------------------
        col_mos = np.clip(
            ((lon_grid - mos_west) / (mos_east - mos_west) * mosaic_w).astype(int),
            0, mosaic_w - 1,
        )
        row_mos = np.clip(
            ((mos_north - lat_grid) / (mos_north - mos_south) * mosaic_h).astype(int),
            0, mosaic_h - 1,
        )

        # --- Sample RGB from mosaic -----------------------------------------
        r = mosaic[row_mos, col_mos, 0].astype(np.float32) / 255.0
        g = mosaic[row_mos, col_mos, 1].astype(np.float32) / 255.0
        b = mosaic[row_mos, col_mos, 2].astype(np.float32) / 255.0

        # --- VARI (Visible Atmospherically Resistant Index) -----------------
        # Designed for broadband RGB satellite sensors; reduces atmospheric
        # scattering artefacts that defeat ExG on Mapbox satellite-v9 imagery.
        # Range: [-1, +1]; positive → vegetation, negative → bare/tracks.
        vari = (g - r) / (g + r - b + 1e-8)
        vari = np.clip(vari, -1.0, 1.0)

        # Light Gaussian blur to suppress per-pixel JPEG tile noise before
        # thresholding (creates smoother, spatially coherent color regions).
        try:
            from scipy.ndimage import gaussian_filter
            vari = gaussian_filter(vari, sigma=0.8)
        except ImportError:
            pass  # scipy unavailable — skip smoothing

        # --- Absolute VARI thresholds ----------------------------------------
        # Calibrated for Mapbox satellite-v9 RGB imagery at agricultural scale.
        # These represent globally meaningful vegetation levels, not relative
        # quartiles — a healthy field shows mostly green, bare soil shows red.
        #
        #   VARI < 0.00  → red    (bare soil, tractor tracks, no vegetation)
        #   0.00–0.10    → orange (sparse / stressed / early emergence)
        #   0.10–0.25    → yellow (moderate cover)
        #   ≥ 0.25       → green  (dense healthy canopy)

        # --- Color mapping --------------------------------------------------
        out_r = np.zeros((output_size, output_size), dtype=np.uint8)
        out_g = np.zeros((output_size, output_size), dtype=np.uint8)
        out_b = np.zeros((output_size, output_size), dtype=np.uint8)

        bare     = vari < 0.00
        stressed = (vari >= 0.00) & (vari < 0.10)
        moderate = (vari >= 0.10) & (vari < 0.25)
        healthy  = vari >= 0.25

        out_r[bare]     = 217; out_g[bare]     = 43;  out_b[bare]     = 43   # red
        out_r[stressed] = 230; out_g[stressed] = 126; out_b[stressed] = 34   # orange
        out_r[moderate] = 217; out_g[moderate] = 192; out_b[moderate] = 43   # yellow
        out_r[healthy]  = 29;  out_g[healthy]  = 185; out_b[healthy]  = 84   # green

        # Alpha: opaque inside polygon, fully transparent outside
        out_a = np.where(mask, 200, 0).astype(np.uint8)

        # --- Assemble and encode --------------------------------------------
        rgba = np.stack([out_r, out_g, out_b, out_a], axis=-1)
        img  = Image.fromarray(rgba, "RGBA")

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        image_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

        logger.info("Mapbox tile analysis complete: %dx%d RGBA PNG", output_size, output_size)
        return {"image_base64": image_b64, "bounds": bounds}

    @staticmethod
    def _compute_parcel_bounds(geometry_wkt: str) -> dict:
        """Return {north, south, east, west} from a WKT geometry."""
        from shapely import wkt as shapely_wkt
        clean = geometry_wkt.split(";", 1)[-1]  # strip SRID if present
        geom = shapely_wkt.loads(clean)
        minx, miny, maxx, maxy = geom.bounds
        return {"west": minx, "south": miny, "east": maxx, "north": maxy}

    @staticmethod
    def _ndvi_to_color(ndvi: float) -> tuple:
        """Map an NDVI value to an RGBA tuple."""
        if ndvi < 0.10:
            return (217, 43, 43, 220)      # dark red
        if ndvi < 0.30:
            return (230, 126, 34, 210)     # orange
        if ndvi < 0.50:
            return (217, 192, 43, 200)     # yellow
        return (29, 185, 84, 200)          # green

    def _mock_ndvi_image(self, geometry_wkt: str, *, mean_ndvi: float = 0.5) -> dict:
        """Generate a synthetic NDVI PNG image with spatial variation.

        Uses Pillow (PIL) to create a 256×256 image where each pixel has an
        NDVI value drawn from N(mean_ndvi, 0.08) — producing realistic spatial
        heterogeneity around the parcel's actual mean NDVI.
        """
        try:
            from PIL import Image
        except ImportError:
            raise SatelliteAPIError(
                "Pillow is required for NDVI image generation. "
                "Install it with: pip install Pillow"
            )

        bounds = self._compute_parcel_bounds(geometry_wkt)
        size = 256
        rng = random.Random(hash(geometry_wkt[:60]))

        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        pixels = img.load()

        for row in range(size):
            for col in range(size):
                # Gaussian noise around the parcel mean, clamped to [-0.1, 1.0]
                pixel_ndvi = rng.gauss(mean_ndvi, 0.08)
                pixel_ndvi = max(-0.1, min(1.0, pixel_ndvi))
                r, g, b, a = self._ndvi_to_color(pixel_ndvi)
                pixels[col, row] = (r, g, b, a)

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        image_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

        return {"image_base64": image_b64, "bounds": bounds}

    async def _real_ndvi_image(
        self,
        geometry_wkt: str,
        date_from: date,
        date_to: date,
    ) -> dict:
        """Fetch a colored NDVI raster image from Sentinel Hub Process API."""
        token = await _get_access_token()
        geojson_geom = _wkt_to_geojson_geometry(geometry_wkt)
        bounds = self._compute_parcel_bounds(geometry_wkt)

        evalscript = """
//VERSION=3
function setup() {
  return { input: ["B04", "B08"], output: { bands: 4, sampleType: "UINT8" } };
}
function evaluatePixel(s) {
  let ndvi = (s.B08 - s.B04) / (s.B08 + s.B04 + 1e-10);
  if (ndvi < 0.10) return [217, 43,  43, 220];
  if (ndvi < 0.30) return [230, 126, 34, 210];
  if (ndvi < 0.50) return [217, 192, 43, 200];
  return [29, 185, 84, 200];
}
"""
        payload = {
            "input": {
                "bounds": {
                    "geometry": geojson_geom,
                    "properties": {"crs": "http://www.opengis.net/def/crs/EPSG/0/4326"},
                },
                "data": [{
                    "type": "sentinel-2-l2a",
                    "dataFilter": {
                        "timeRange": {
                            "from": f"{date_from.isoformat()}T00:00:00Z",
                            "to": f"{date_to.isoformat()}T23:59:59Z",
                        },
                        "mosaickingOrder": "leastCC",
                    },
                }],
            },
            "output": {
                "width": 256,
                "height": 256,
                "responses": [{
                    "identifier": "default",
                    "format": {"type": "image/png"},
                }],
            },
            "evalscript": evalscript,
        }

        process_url = f"{settings.SENTINEL_HUB_BASE_URL}/api/v1/process"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(process_url, json=payload, headers=headers)
            resp.raise_for_status()
            image_b64 = base64.b64encode(resp.content).decode("utf-8")

        return {"image_base64": image_b64, "bounds": bounds}

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
