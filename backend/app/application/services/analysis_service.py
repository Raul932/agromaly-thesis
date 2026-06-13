"""
Application Service: AnalysisService
========================================
Implements the AI anomaly detection use case — the core innovation of Agromaly.

Algorithm (Thesis Chapter 4 — LSTM Autoencoder):
    1. Fetch all reliable NDVI records (cloud_coverage < 20%) for the parcel.
    2. Pass the NDVI time-series through the trained LSTM Autoencoder
       (input_size=1, NDVI-only, window_size=30).
    3. Compute the MSE reconstruction error per window.
    4. Flag as ANOMALY_DETECTED if MSE > threshold (99th percentile of
       normal-window MSE on the training set).

    Feature ablation confirmed that adding weather features degraded AUC by
    ~8.8%; the production model uses Sentinel-2 NDVI exclusively.

Fallback:
    If the LSTM model files are missing (development without training),
    the service falls back to a Modified Z-Score statistical method.
"""

from __future__ import annotations

import logging
import math
import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, List, Optional

from app.core.exceptions import ParcelNotFoundError, PermissionDeniedError
from app.domain.entities.ndvi_record import NDVIRecord
from app.domain.entities.user import User
from app.domain.interfaces.ndvi_record_repository import INDVIRecordRepository
from app.domain.interfaces.parcel_repository import IParcelRepository

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Response DTOs (plain dataclasses — mapped to Pydantic in the schema layer)
# ---------------------------------------------------------------------------

@dataclass
class AnomalyResult:
    """Result of the anomaly detection analysis for a single parcel."""

    parcel_id: uuid.UUID
    parcel_name: str
    status: str                    # "ANOMALY_DETECTED" | "HEALTHY" | "INSUFFICIENT_DATA"
    anomaly_score: float           # Composite anomaly metric [0.0 – 1.0]
    mse_score: float               # Mean Squared Error vs. historical mean
    z_score: float                 # Modified Z-score of latest NDVI
    ndvi_current: Optional[float]  # Most recent reliable NDVI
    ndvi_mean: float               # Historical mean NDVI
    ndvi_std: float                # Historical std deviation
    ndvi_trend: float              # Slope of recent NDVI (negative = declining)
    records_analyzed: int          # Number of reliable records used
    cloud_gap_ratio: float         # Fraction of total records that were cloudy
    recommendation: str            # Agronomic recommendation text (Romanian)
    weather_context: Dict          # 14-day weather diagnostic summary (empty if unavailable)


# ---------------------------------------------------------------------------
# Anomaly Detection Thresholds (documented in thesis Chapter 4)
# ---------------------------------------------------------------------------

_ANOMALY_THRESHOLD = 0.55          # Composite score above this → ANOMALY_DETECTED
_MIN_RECORDS_FOR_ANALYSIS = 3     # Need at least 3 reliable observations
_SEVERE_DECLINE_RATE = -0.015     # NDVI drop per 5-day interval (severe)
_MODERATE_DECLINE_RATE = -0.008   # NDVI drop per 5-day interval (moderate)


class AnalysisService:
    """Orchestrates NDVI anomaly detection for a parcel.

    This service encapsulates the statistical model that will eventually
    be replaced by the trained LSTM Autoencoder.
    """

    def __init__(
        self,
        parcel_repo: IParcelRepository,
        ndvi_repo: INDVIRecordRepository,
    ) -> None:
        self._parcel_repo = parcel_repo
        self._ndvi_repo = ndvi_repo

    async def get_ndvi_image(
        self,
        parcel_id: uuid.UUID,
        owner_id: uuid.UUID,
    ) -> dict:
        """Fetch a colored NDVI spatial PNG image for a parcel.

        Returns a dict with ``image_base64`` and ``bounds`` keys suitable
        for the NdviImageResponse schema.

        Raises:
            ParcelNotFoundError:   Parcel does not exist.
            PermissionDeniedError: Caller does not own the parcel.
        """
        from app.infrastructure.external.satellite_client import SatelliteClient

        parcel = await self._parcel_repo.get_by_id(parcel_id)
        if parcel is None:
            raise ParcelNotFoundError(f"Parcel id={parcel_id} not found.")
        if parcel.owner_id != owner_id:
            raise PermissionDeniedError(
                "You do not have permission to access this parcel."
            )

        # Use the parcel's last known NDVI to seed the mock spatial variation
        mean_ndvi = parcel.last_ndvi if parcel.last_ndvi is not None else 0.5

        client = SatelliteClient()
        return await client.fetch_ndvi_image(
            parcel.geometry_wkt,
            mean_ndvi=mean_ndvi,
        )

    async def analyze_parcel(
        self,
        parcel_id: uuid.UUID,
        owner: User,
    ) -> AnomalyResult:
        """Run anomaly detection on a parcel's NDVI time-series.

        Args:
            parcel_id: UUID of the parcel to analyze.
            owner:     Authenticated user (must own the parcel).

        Returns:
            ``AnomalyResult`` with status, scores, and recommendation.

        Raises:
            ParcelNotFoundError:   If parcel does not exist.
            PermissionDeniedError: If user does not own the parcel.
        """
        # 1. Ownership check
        parcel = await self._parcel_repo.get_by_id(parcel_id)
        if parcel is None:
            raise ParcelNotFoundError(f"Parcel id={parcel_id} not found.")
        if parcel.owner_id != owner.id and not getattr(owner, "is_superuser", False):
            raise PermissionDeniedError("You do not have permission to access this parcel.")

        # 2. Fetch NDVI records (all — we'll separate reliable vs. cloudy)
        all_records = await self._ndvi_repo.list_by_parcel(parcel_id, limit=1000)
        reliable = [r for r in all_records if r.is_reliable]

        total_count = len(all_records)
        reliable_count = len(reliable)
        cloud_gap_ratio = (
            (total_count - reliable_count) / total_count
            if total_count > 0 else 0.0
        )

        # 3. Fetch weather (best-effort — analysis proceeds even if this fails)
        weather: Dict = {}
        try:
            weather = await fetch_weather_summary(parcel)
        except Exception as exc:
            logger.debug("Weather fetch skipped: %s", exc)

        # 4. Insufficient data guard
        if reliable_count < _MIN_RECORDS_FOR_ANALYSIS:
            try:
                await self._parcel_repo.update_anomaly_status(parcel_id, "INSUFFICIENT_DATA")
            except Exception:
                pass
            return AnomalyResult(
                parcel_id=parcel_id,
                parcel_name=parcel.name,
                status="INSUFFICIENT_DATA",
                anomaly_score=0.0,
                mse_score=0.0,
                z_score=0.0,
                ndvi_current=reliable[-1].mean_ndvi if reliable else None,
                ndvi_mean=0.0,
                ndvi_std=0.0,
                ndvi_trend=0.0,
                records_analyzed=reliable_count,
                cloud_gap_ratio=round(cloud_gap_ratio, 4),
                recommendation=(
                    f"Câmpul tău are doar {reliable_count} imagine(i) satelitare clare disponibile. "
                    "Avem nevoie de cel puțin 3 imagini pentru a evalua sănătatea culturilor. "
                    "Sistemul va colecta automat mai multe date în următoarele zile — "
                    "satelitul trece peste câmp la fiecare 5 zile."
                ),
                weather_context=weather,
            )

        # 5. Core analysis
        result = _compute_anomaly_score(reliable, cloud_gap_ratio, weather)

        # Persist the anomaly status back to the parcel for fast list-view coloring.
        try:
            await self._parcel_repo.update_anomaly_status(parcel_id, result["status"])
        except Exception:
            pass  # Non-fatal — analysis result is still returned

        return AnomalyResult(
            parcel_id=parcel_id,
            parcel_name=parcel.name,
            **result,
        )


# ---------------------------------------------------------------------------
# Core Algorithm (documented in thesis Chapter 4)
# ---------------------------------------------------------------------------

def _compute_anomaly_score(
    records: List[NDVIRecord],
    cloud_gap_ratio: float,
    weather: Dict,
) -> dict:
    """Run NDVI anomaly detection via the LSTM Autoencoder (NDVI-only, input_size=1).

    Falls back to Modified Z-Score if the model is not loaded.

    Args:
        records:         Reliable NDVI records sorted by date.
        cloud_gap_ratio: Fraction of total records that were cloud-obscured.

    Returns:
        Dict with all analysis fields for ``AnomalyResult``.
    """
    from app.ml.lstm_autoencoder import get_anomaly_detector

    # Sort by date ascending
    sorted_records = sorted(records, key=lambda r: r.date_captured)
    ndvi_values = [r.mean_ndvi for r in sorted_records]

    n = len(ndvi_values)
    current_ndvi = ndvi_values[-1]

    # --- Historical statistics (for UI/Recommendation context) ---
    mean_ndvi = sum(ndvi_values) / n
    variance = sum((x - mean_ndvi) ** 2 for x in ndvi_values) / n
    std_ndvi = math.sqrt(variance) if variance > 0 else 0.01

    recent_n = min(5, n)
    recent_values = ndvi_values[-recent_n:]
    if recent_n >= 2:
        x_mean = (recent_n - 1) / 2
        y_mean = sum(recent_values) / recent_n
        numerator = sum((i - x_mean) * (y - y_mean) for i, y in enumerate(recent_values))
        denominator = sum((i - x_mean) ** 2 for i in range(recent_n))
        trend = numerator / denominator if denominator > 0 else 0.0
    else:
        trend = 0.0

    # --- LSTM Inference ---
    detector = get_anomaly_detector()

    if detector is not None:
        # Run NDVI-only inference — no weather argument needed.
        score, is_anomaly, _ = detector.predict(ndvi_values=ndvi_values)

        # Normalise MSE into [0, 1] relative to the threshold so the mobile
        # app has a meaningful anomaly_score:
        #   score == threshold → anomaly_score ≈ 0.50
        #   score == 2×threshold → anomaly_score ≈ 0.75  (clearly anomalous)
        #   score → 0            → anomaly_score → 0.00  (perfectly healthy)
        t = detector.threshold if detector.threshold > 0 else 1e-6
        composite = round(min(1.0, float(score) / (2.0 * t)), 4)
        status = "ANOMALY_DETECTED" if is_anomaly else "HEALTHY"
        mse = float(score)
        z_score = 0.0  # not used with LSTM
        
    else:
        # Fallback to Z-Score if model is not trained/available
        sorted_vals = sorted(ndvi_values)
        median_ndvi = sorted_vals[n // 2] if n % 2 == 1 else (sorted_vals[n // 2 - 1] + sorted_vals[n // 2]) / 2
        mad = sorted(abs(x - median_ndvi) for x in ndvi_values)[n // 2]
        mad = max(mad, 0.01)
        z_score = 0.6745 * (current_ndvi - median_ndvi) / mad
        
        deviation_score = 1.0 / (1.0 + math.exp(-abs(z_score) + 2.0))
        trend_magnitude = max(0.0, -trend)
        trend_score = 1.0 / (1.0 + math.exp(-trend_magnitude * 100 + 1.5))
        quality_penalty = min(1.0, cloud_gap_ratio * 1.5)
        
        composite = 0.50 * deviation_score + 0.35 * trend_score + 0.15 * quality_penalty
        composite = round(min(1.0, max(0.0, composite)), 4)
        
        status = "ANOMALY_DETECTED" if composite >= _ANOMALY_THRESHOLD else "HEALTHY"
        mse = (current_ndvi - mean_ndvi) ** 2

    # --- Hard anomaly override ---
    # The LSTM/Z-score can underestimate anomalies when records < window_size
    # (mean-padding dilutes the MSE). Apply rule-based override for cases where
    # the signal is unambiguous: NDVI >25% below historical mean AND severe decline.
    # Score scales with drop severity: 25% drop → ~0.70, 40% drop → ~0.83, 60%+ → 0.95.
    ndvi_drop_pct = (mean_ndvi - current_ndvi) / max(mean_ndvi, 0.01)
    if ndvi_drop_pct > 0.25 and trend < _SEVERE_DECLINE_RATE:
        status = "ANOMALY_DETECTED"
        drop_contribution = ndvi_drop_pct * 0.70
        trend_contribution = min(0.15, abs(trend) * 1.5)
        override_composite = round(min(0.95, 0.50 + drop_contribution + trend_contribution), 4)
        composite = max(composite, override_composite)

    # --- Generate agronomic recommendation ---
    recommendation = _generate_recommendation(
        status=status,
        current_ndvi=current_ndvi,
        mean_ndvi=mean_ndvi,
        trend=trend,
        composite=composite,
        cloud_gap_ratio=cloud_gap_ratio,
        weather=weather,
    )

    return {
        "status": status,
        "anomaly_score": composite,
        "mse_score": round(mse, 6),
        "z_score": round(z_score, 4),
        "ndvi_current": round(current_ndvi, 4),
        "ndvi_mean": round(mean_ndvi, 4),
        "ndvi_std": round(std_ndvi, 4),
        "ndvi_trend": round(trend, 6),
        "records_analyzed": len(records),
        "cloud_gap_ratio": round(cloud_gap_ratio, 4),
        "recommendation": recommendation,
        "weather_context": weather,
    }


async def fetch_weather_summary(parcel) -> dict:
    """Fetch the last 14 days of weather for the parcel centroid.

    Returns a diagnostic dict with cause_hint and plain-language fields
    used by _generate_recommendation(). Returns {} on any failure.
    """
    try:
        from shapely import wkt
        from app.infrastructure.external.weather_client import WeatherClient

        geom = wkt.loads(parcel.geometry_wkt)
        centroid = geom.centroid
        lat, lon = centroid.y, centroid.x

        client = WeatherClient()
        end = date.today() - timedelta(days=2)
        start = end - timedelta(days=20)  # request wide; archive returns what it has
        forecasts = await client.fetch_historical_weather(
            lat, lon, start_date=start, end_date=end
        )

        if not forecasts:
            return {}

        # Aggregate daily fields (WeatherDataPoint uses temp_max_c / precipitation_mm)
        total_precip = round(sum(f.precipitation_mm for f in forecasts), 1)
        temps_max = [f.temp_max_c for f in forecasts]
        temps_min = [f.temp_min_c for f in forecasts]
        avg_temp_max = round(sum(temps_max) / len(temps_max), 1) if temps_max else 0.0
        hot_days = sum(1 for t in temps_max if t > 33)
        frost_days = sum(1 for t in temps_min if t < 2)
        heavy_rain_days = sum(1 for f in forecasts if f.precipitation_mm > 20)

        # Longest consecutive dry streak (< 1mm/day)
        dry_streak = max_dry = 0
        for f in forecasts:
            if f.precipitation_mm < 1.0:
                dry_streak += 1
                max_dry = max(max_dry, dry_streak)
            else:
                dry_streak = 0

        # Determine most likely cause (priority order)
        if frost_days >= 1:
            cause_hint = "frost"
        elif max_dry >= 7 or total_precip < 5:
            cause_hint = "drought"
        elif hot_days >= 5 and total_precip < 15:
            cause_hint = "heat_stress"
        elif heavy_rain_days >= 2:
            cause_hint = "heavy_rain"
        else:
            cause_hint = "normal"

        return {
            "period_days": len(forecasts),
            "total_precip_mm": total_precip,
            "avg_temp_max_c": avg_temp_max,
            "dry_spell_days": max_dry,
            "hot_days": hot_days,
            "frost_days": frost_days,
            "heavy_rain_days": heavy_rain_days,
            "cause_hint": cause_hint,
        }
    except Exception as exc:
        logger.warning("Weather fetch failed: %s", exc, exc_info=True)
        return {}


# Romanian weekday abbreviations (Mon=0 .. Sun=6)
_RO_WEEKDAYS = ["Lun", "Mar", "Mie", "Joi", "Vin", "Sâm", "Dum"]


async def fetch_weather_forecast(parcel, days: int = 7) -> dict:
    """Fetch the next ``days`` of weather forecast for the parcel centroid.

    Returns a dict ``{"days": [...], "warnings": [...]}`` for the UI forecast
    card. Each day holds date, weekday label, temps, precipitation, wind and
    the WMO weather code. Warnings are plain-language Romanian alerts.
    Returns ``{"days": [], "warnings": []}`` on any failure.
    """
    try:
        from shapely import wkt
        from app.infrastructure.external.weather_client import WeatherClient

        geom = wkt.loads(parcel.geometry_wkt)
        centroid = geom.centroid
        lat, lon = centroid.y, centroid.x

        client = WeatherClient()
        points = await client.fetch_forecast(lat, lon, days=days)
        if not points:
            return {"days": [], "warnings": []}

        days_out = []
        frost_days: list[str] = []
        rain_days: list[str] = []
        heat_days: list[str] = []
        wind_days: list[str] = []

        for p in points:
            label = _RO_WEEKDAYS[p.forecast_date.weekday()]
            days_out.append({
                "date": p.forecast_date.isoformat(),
                "weekday": label,
                "temp_max_c": p.temp_max_c,
                "temp_min_c": p.temp_min_c,
                "precipitation_mm": p.precipitation_mm,
                "wind_speed_kmh": p.wind_speed_kmh,
                "weather_code": p.weather_code,
            })
            if p.temp_min_c < 2:
                frost_days.append(label)
            if p.precipitation_mm > 20:
                rain_days.append(label)
            if p.temp_max_c > 33:
                heat_days.append(label)
            if p.wind_speed_kmh > 40:
                wind_days.append(label)

        warnings: list[str] = []
        if frost_days:
            warnings.append(f"Risc de îngheț: {', '.join(frost_days)}")
        if rain_days:
            warnings.append(f"Ploaie abundentă: {', '.join(rain_days)}")
        if heat_days:
            warnings.append(f"Caniculă: {', '.join(heat_days)}")
        if wind_days:
            warnings.append(f"Vânt puternic: {', '.join(wind_days)}")

        return {"days": days_out, "warnings": warnings}
    except Exception as exc:
        logger.warning("Weather forecast fetch failed: %s", exc, exc_info=True)
        return {"days": [], "warnings": []}


def _generate_recommendation(
    *,
    status: str,
    current_ndvi: float,
    mean_ndvi: float,
    trend: float,
    composite: float,
    cloud_gap_ratio: float,
    weather: Dict,
) -> str:
    """Generate a farmer-friendly recommendation in Romanian.

    Uses weather cause_hint to diagnose what happened, then gives 3 concrete actions.
    No NDVI numbers, no technical jargon — plain language for any farmer.
    """
    cause = weather.get("cause_hint", "normal")
    precip = weather.get("total_precip_mm")
    dry_days = weather.get("dry_spell_days")
    hot_days = weather.get("hot_days")
    frost_days = weather.get("frost_days")
    heavy_rain_days = weather.get("heavy_rain_days")
    period = weather.get("period_days", 14)
    has_weather = bool(weather)

    # --- Vegetation level label ---
    if current_ndvi >= 0.65:
        veg_level = "excelentă"
    elif current_ndvi >= 0.5:
        veg_level = "bună"
    elif current_ndvi >= 0.35:
        veg_level = "medie"
    elif current_ndvi >= 0.2:
        veg_level = "slabă"
    else:
        veg_level = "foarte scăzută"

    # ── HEALTHY ──────────────────────────────────────────────────────────────
    if status == "HEALTHY":
        if has_weather and cause == "normal":
            weather_line = (
                f"Vremea din ultimele {period} zile a fost favorabilă"
                + (f" — {precip:.0f}mm de precipitații" if precip is not None else "")
                + " — ceea ce a ajutat culturile să se dezvolte normal."
            )
        elif has_weather and cause == "drought":
            weather_line = (
                f"Deși ultimele {period} zile au fost mai uscate"
                + (f" (doar {precip:.0f}mm de ploaie)" if precip is not None else "")
                + ", culturile se mențin în parametri normali deocamdată."
            )
        elif has_weather and cause == "heavy_rain":
            weather_line = (
                f"Câmpul a primit precipitații abundente recent"
                + (f" ({heavy_rain_days} zile cu ploaie torențială)" if heavy_rain_days else "")
                + ", dar culturile rezistă bine."
            )
        else:
            weather_line = "Condițiile actuale nu indică probleme."

        if trend >= 0.005:
            return (
                f"✅ Câmpul tău este în stare {veg_level} și în creștere. {weather_line} "
                "Continuă practicile agricole curente."
            )
        return (
            f"✅ Câmpul tău este în stare {veg_level}. {weather_line} "
            "Nu este necesară nicio acțiune imediată."
        )

    # ── ANOMALY_DETECTED ─────────────────────────────────────────────────────
    # 1. Severity opener
    if composite >= 0.80:
        severity = "⚠️ Câmpul tău are o problemă gravă de vegetație"
    elif composite >= 0.65:
        severity = "⚠️ Câmpul tău are o problemă semnificativă de vegetație"
    else:
        severity = "⚠️ Câmpul tău prezintă o scădere moderată a vegetației"

    # 2. Trend context
    if trend <= _SEVERE_DECLINE_RATE:
        trend_line = "Scăderea este rapidă și continuă."
    elif trend <= _MODERATE_DECLINE_RATE:
        trend_line = "Scăderea este graduală."
    else:
        trend_line = ""

    # 3. Weather-based cause diagnosis
    if not has_weather:
        cause_line = "Cauza exactă nu a putut fi determinată (date meteo indisponibile)."
        actions = (
            "Ce trebuie să faci:\n"
            "1. Mergi la câmp și verifică starea culturilor — caută frunze galbene, ofilite sau uscate.\n"
            "2. Verifică umiditatea solului la 10cm adâncime — dacă e uscat, pornește irigarea.\n"
            "3. Uită-te după semne de boli sau dăunători pe frunze și tulpini."
        )
    elif cause == "drought":
        dry_str = f"{dry_days} zile consecutive" if dry_days else "mai multe zile"
        precip_str = f"doar {precip:.0f}mm" if precip is not None else "foarte puțină ploaie"
        cause_line = (
            f"Ultimele {period} zile au fost foarte secetoase "
            f"({precip_str} de precipitații, {dry_str} fără ploaie). "
            "Cel mai probabil cauza este stresul hidric — culturile nu au primit suficientă apă."
        )
        actions = (
            "Ce trebuie să faci:\n"
            "1. Verifică umiditatea solului azi — dacă pământul este uscat la 10cm adâncime, pornește irigarea imediat.\n"
            "2. Inspectează frunzele: dacă sunt galbene, ofilite sau se rulează, cultura suferă de secetă.\n"
            "3. Dacă nu ai sistem de irigare, încearcă să protejezi solul cu paie sau mulci pentru a reduce evaporarea."
        )
    elif cause == "heat_stress":
        hot_str = f"{hot_days} zile cu temperaturi peste 33°C" if hot_days else "temperaturi ridicate"
        cause_line = (
            f"Ultimele {period} zile au adus {hot_str} cu precipitații reduse. "
            "Căldura excesivă combinată cu lipsa apei stresează culturile și reduce vegetația."
        )
        actions = (
            "Ce trebuie să faci:\n"
            "1. Irrigă câmpul dimineața devreme sau seara târziu, când evaporarea este minimă.\n"
            "2. Verifică frunzele pentru semne de arsuri solare sau ofilire — acestea apar mai întâi la vârful plantei.\n"
            "3. Dacă este posibil, aplică un strat de mulci pentru a menține răcoarea și umiditatea solului."
        )
    elif cause == "frost":
        frost_str = f"{frost_days} zile" if frost_days else "zile recente"
        cause_line = (
            f"Au fost temperaturi sub 0°C în {frost_str} din ultimele {period} zile. "
            "Înghețul poate deteriora culturile, mai ales în fazele sensibile de creștere."
        )
        actions = (
            "Ce trebuie să faci:\n"
            "1. Mergi la câmp și verifică dacă frunzele sau tulpinile sunt înnegrite sau moi la atingere — semne clare de degerare.\n"
            "2. Dacă culturile sunt parțial afectate, nu le tăia imediat — dă-le 3-5 zile să se refacă singure.\n"
            "3. Protejează suprafețele vulnerabile cu folie agrotextil dacă se mai anunță nopți geroase."
        )
    elif cause == "heavy_rain":
        rain_str = f"{heavy_rain_days} zile cu ploaie torențială" if heavy_rain_days else "ploi abundente"
        cause_line = (
            f"Au fost {rain_str} în ultimele {period} zile. "
            "Excesul de apă poate sufoca rădăcinile și favoriza boli fungice."
        )
        actions = (
            "Ce trebuie să faci:\n"
            "1. Verifică dacă există zone cu apă stagnantă pe câmp — băltirile sufocă rădăcinile în 24-48 de ore.\n"
            "2. Uită-te după pete maronii sau gri pe frunze și tulpini — acestea pot indica ciuperci sau mucegai.\n"
            "3. Dacă solul este foarte îmbibat, evită să intri cu utilajele grele pentru a nu tasa pământul."
        )
    else:
        cause_line = (
            "Condițiile climatice recente au fost normale, deci cauza poate fi "
            "o boală, dăunători sau o problemă localizată."
        )
        actions = (
            "Ce trebuie să faci:\n"
            "1. Mergi la câmp și verifică dacă există zone cu plante galbene, ofilite sau atacate de insecte.\n"
            "2. Verifică dacă sistemul de irigare funcționează corect și dacă solul primește suficientă apă.\n"
            "3. Recoltează câteva frunze afectate și consultă un agronom local pentru diagnostic."
        )

    parts = [severity + "."]
    if trend_line:
        parts.append(trend_line)
    parts.append(cause_line)
    parts.append(actions)
    return " ".join(parts)
