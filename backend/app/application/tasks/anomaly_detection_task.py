"""
Celery Task: Anomaly Detection
================================
Runs the LSTM Autoencoder anomaly detection on active parcels.

Triggered via Celery Beat (e.g. daily) or triggered manually via API.

If an anomaly is detected:
    1. The RAG pipeline generates an ai_recommendation from the knowledge base
       + last 30 days of weather.
    2. An Alert is created in the database with the recommendation attached.
"""

from __future__ import annotations

import asyncio
import logging
import uuid

from celery import shared_task
from celery.utils.log import get_task_logger

logger = get_task_logger(__name__)


@shared_task(
    bind=True,
    name="app.application.tasks.anomaly_detection_task.run_anomaly_detection_for_all_parcels",
    max_retries=3,
    default_retry_delay=300,
)
def run_anomaly_detection_for_all_parcels(self) -> dict:
    """Run anomaly detection for all active parcels."""
    logger.info("Starting global anomaly detection task.")
    try:
        result = asyncio.run(_async_run_anomaly_detection_for_all())
        logger.info(
            "Anomaly detection complete. Analyzed %d parcels, found %d anomalies.",
            result["parcels_analyzed"], result["anomalies_detected"]
        )
        return result
    except Exception as exc:
        logger.error("Failed to run anomaly detection: %s", exc, exc_info=True)
        raise


async def _async_run_anomaly_detection_for_all() -> dict:
    """Async implementation of the global anomaly detection."""
    from app.infrastructure.db.session import AsyncSessionLocal
    from app.infrastructure.repositories.parcel_repository_impl import ParcelRepositoryImpl
    from app.infrastructure.repositories.ndvi_record_repository_impl import NDVIRecordRepositoryImpl
    from app.infrastructure.repositories.alert_repository_impl import AlertRepositoryImpl
    from app.infrastructure.repositories.user_repository_impl import UserRepositoryImpl
    from app.application.services.analysis_service import _compute_anomaly_score
    from app.application.services.rag_service import get_rag_service
    from app.domain.entities.alert import Alert, AlertType, AlertSeverity
    from app.domain.entities.parcel import ParcelStatus

    analyzed = 0
    anomalies = 0

    async with AsyncSessionLocal() as session:
        parcel_repo = ParcelRepositoryImpl(session)
        ndvi_repo = NDVIRecordRepositoryImpl(session)
        alert_repo = AlertRepositoryImpl(session)
        user_repo = UserRepositoryImpl(session)

        all_parcels = await parcel_repo.list_all(limit=10000)
        active_parcels = [p for p in all_parcels if p.status == ParcelStatus.ACTIVE]

        for parcel in active_parcels:
            owner = await user_repo.get_by_id(parcel.owner_id)
            if not owner:
                continue

            all_records = await ndvi_repo.list_by_parcel(parcel.id, limit=100)
            reliable = [r for r in all_records if r.is_reliable]

            total_count = len(all_records)
            reliable_count = len(reliable)
            cloud_gap_ratio = (
                (total_count - reliable_count) / total_count
                if total_count > 0 else 0.0
            )

            if reliable_count < 3:
                continue

            analyzed += 1

            result_dict = _compute_anomaly_score(reliable, cloud_gap_ratio)

            if result_dict["status"] == "ANOMALY_DETECTED":
                anomalies += 1

                # Try to generate a RAG recommendation (failure is non-fatal)
                ai_rec = None
                try:
                    rag = get_rag_service()
                    if rag is not None:
                        weather_summary = await _fetch_weather_summary(parcel)
                        crop = parcel.crop_type
                        parcel_context = {
                            "name": parcel.name,
                            "crop_type": crop.value if hasattr(crop, "value") else str(crop),
                            "area_ha": round(getattr(parcel, "area_ha", 0) or 0, 2),
                            "ndvi_current": result_dict.get("ndvi_current"),
                            "ndvi_mean": result_dict.get("ndvi_mean"),
                            "ndvi_std": result_dict.get("ndvi_std"),
                            "ndvi_trend": result_dict.get("ndvi_trend"),
                            "anomaly_score": result_dict.get("anomaly_score"),
                            "anomaly_status": result_dict.get("status"),
                        }
                        ai_rec = await rag.generate_anomaly_recommendation(
                            parcel_context, weather_summary
                        )
                        logger.info("RAG recommendation generated for parcel %s", parcel.id)
                except Exception as rag_exc:
                    logger.warning(
                        "RAG recommendation failed for parcel %s: %s",
                        parcel.id, rag_exc,
                    )

                alert = Alert(
                    parcel_id=parcel.id,
                    alert_type=AlertType.ANOMALY,
                    severity=(
                        AlertSeverity.HIGH
                        if result_dict["anomaly_score"] >= 0.8
                        else AlertSeverity.MEDIUM
                    ),
                    title=f"Anomaly Detected on {parcel.name}",
                    description=result_dict["recommendation"],
                    ai_recommendation=ai_rec,
                    triggered_value=result_dict["mse_score"],
                    threshold_value=0.55,
                )
                await alert_repo.save(alert)

        await session.commit()

    return {
        "parcels_analyzed": analyzed,
        "anomalies_detected": anomalies,
    }


async def _fetch_weather_summary(parcel) -> dict:
    """Fetch 30-day average weather for the parcel centroid.

    Returns an empty dict on any failure so the caller can proceed.
    """
    try:
        from datetime import date, timedelta
        from shapely import wkt
        from app.infrastructure.external.weather_client import WeatherClient

        geom = wkt.loads(parcel.geometry_wkt)
        centroid = geom.centroid
        lat, lon = centroid.y, centroid.x

        client = WeatherClient()
        end = date.today() - timedelta(days=1)
        start = end - timedelta(days=29)
        forecasts = await client.fetch_historical_weather(lat, lon, start, end)

        if not forecasts:
            return {}

        temps = [f.temperature_max for f in forecasts if f.temperature_max is not None]
        precips = [f.precipitation_sum for f in forecasts if f.precipitation_sum is not None]

        return {
            "period": f"{start} to {end}",
            "avg_temp_max_C": round(sum(temps) / len(temps), 1) if temps else "N/A",
            "total_precip_mm": round(sum(precips), 1) if precips else "N/A",
            "days_analyzed": len(forecasts),
        }
    except Exception as exc:
        logger.debug("Weather fetch failed for anomaly task: %s", exc)
        return {}
