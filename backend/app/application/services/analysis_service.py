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
from typing import List, Optional

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
    recommendation: str            # Agronomic recommendation text


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

        # 3. Insufficient data guard
        if reliable_count < _MIN_RECORDS_FOR_ANALYSIS:
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
                    "Insufficient satellite data for reliable analysis. "
                    f"Only {reliable_count} cloud-free observation(s) available. "
                    "The system requires at least 3 observations to establish "
                    "a baseline. Data will accumulate automatically over the "
                    "next Sentinel-2 revisit cycles (every 5 days)."
                ),
            )

        # 4. Core analysis
        result = _compute_anomaly_score(reliable, cloud_gap_ratio)

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

    # --- Generate agronomic recommendation ---
    recommendation = _generate_recommendation(
        status=status,
        current_ndvi=current_ndvi,
        mean_ndvi=mean_ndvi,
        trend=trend,
        composite=composite,
        cloud_gap_ratio=cloud_gap_ratio,
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
    }


def _generate_recommendation(
    *,
    status: str,
    current_ndvi: float,
    mean_ndvi: float,
    trend: float,
    composite: float,
    cloud_gap_ratio: float,
) -> str:
    """Generate a human-readable agronomic recommendation.

    The text is structured for display in a mobile app card and includes:
    - Risk severity classification
    - Likely cause analysis
    - Actionable field inspection advice
    """
    if status == "HEALTHY":
        if trend >= 0.005:
            return (
                f"✅ Vegetation health is NORMAL. Current NDVI ({current_ndvi:.3f}) "
                f"is consistent with the historical average ({mean_ndvi:.3f}). "
                f"Positive growth trend detected (+{trend:.4f}/interval). "
                "Continue standard agronomic practices."
            )
        return (
            f"✅ Vegetation health is NORMAL. Current NDVI ({current_ndvi:.3f}) "
            f"is within expected bounds (μ={mean_ndvi:.3f}). "
            "No anomalies detected. No immediate action required."
        )

    # --- ANOMALY_DETECTED ---
    parts = []

    # Severity
    if composite >= 0.80:
        parts.append("🔴 CRITICAL ANOMALY DETECTED.")
    elif composite >= 0.65:
        parts.append("🟠 SIGNIFICANT ANOMALY DETECTED.")
    else:
        parts.append("🟡 MODERATE ANOMALY DETECTED.")

    # NDVI deviation analysis
    drop_pct = ((mean_ndvi - current_ndvi) / mean_ndvi * 100) if mean_ndvi > 0 else 0
    parts.append(
        f"Current NDVI ({current_ndvi:.3f}) is {abs(drop_pct):.1f}% "
        f"{'below' if current_ndvi < mean_ndvi else 'above'} "
        f"the historical average ({mean_ndvi:.3f})."
    )

    # Trend analysis
    if trend <= _SEVERE_DECLINE_RATE:
        parts.append(
            f"Rapid vegetation decline detected (slope={trend:.4f}/interval). "
            "This suggests acute stress — possible causes include drought, "
            "pest infestation, or herbicide drift."
        )
    elif trend <= _MODERATE_DECLINE_RATE:
        parts.append(
            f"Gradual vegetation decline observed (slope={trend:.4f}/interval). "
            "This may indicate early-stage nutrient deficiency, water stress, "
            "or progressive disease onset."
        )

    # Possible causes based on NDVI level
    if current_ndvi < 0.2:
        parts.append(
            "Very low NDVI suggests bare soil exposure, crop failure, or "
            "post-harvest residue. Immediate field inspection recommended."
        )
    elif current_ndvi < 0.35:
        parts.append(
            "Low NDVI indicates sparse vegetation cover. Possible causes: "
            "drought stress, poor germination, or early-season planting issues."
        )
    elif current_ndvi < 0.5:
        parts.append(
            "Below-average NDVI. Consider checking for: localized pest damage, "
            "nutrient deficiency (N/P/K), or irrigation system malfunction."
        )

    # Data quality warning
    if cloud_gap_ratio > 0.3:
        parts.append(
            f"⚠️ Data quality notice: {cloud_gap_ratio:.0%} of recent satellite "
            "passes were cloud-obscured. Analysis confidence is reduced."
        )

    # Action
    parts.append(
        "📋 RECOMMENDED ACTIONS: (1) Conduct ground-truth field inspection "
        "in the affected zone. (2) Check irrigation and drainage systems. "
        "(3) Collect soil samples for nutrient analysis. "
        "(4) Compare with neighboring parcels to rule out sensor artifacts."
    )

    return " ".join(parts)
