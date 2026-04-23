"""
Celery Application Factory
============================
Creates and configures the shared Celery application instance used by
all background task modules.

Configuration:
    - Broker:  Redis (CELERY_BROKER_URL from environment)
    - Backend: Redis (CELERY_RESULT_BACKEND from environment)
    - Tasks auto-discovered from ``app.application.tasks`` sub-packages.

Worker Concurrency:
    Workers are spawned as separate processes (default Celery ``prefork``
    pool). Each worker process imports this module at startup, which means
    the SQLAlchemy engine is **not** shared between processes — each gets
    its own connection pool. This is correct and intentional.

Task Serialization:
    JSON is used for arguments and results (never pickle) to prevent
    arbitrary code execution if the Redis broker is compromised (Zero-Trust).

Beat Schedule (future):
    ``beat_schedule`` will contain periodic tasks like:
    - Fetch NDVI for all active parcels every 5 days (Sentinel revisit)
    - Fetch weather every 6 hours
"""

from __future__ import annotations

from celery import Celery

from app.core.config import settings


def create_celery_app() -> Celery:
    """Application factory for the Celery instance.

    Returns:
        Configured ``Celery`` application ready to register tasks.
    """
    app = Celery(
        "agromaly",
        broker=settings.CELERY_BROKER_URL,
        backend=settings.CELERY_RESULT_BACKEND,
        include=[
            "app.application.tasks.sync_weather_tasks",
            "app.application.tasks.sync_ndvi_tasks",
        ],
    )

    app.conf.update(
        # ------------------------------------------------------------------
        # Serialization — JSON only (no pickle for security)
        # ------------------------------------------------------------------
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        # ------------------------------------------------------------------
        # Queues — CRITICAL: default queue must match the -Q flag in docker-compose
        # Without this, .delay() sends tasks to the "celery" queue (Celery built-in
        # default) which the worker does NOT listen to.
        # ------------------------------------------------------------------
        task_default_queue="default",
        # ------------------------------------------------------------------
        # Task behaviour
        # ------------------------------------------------------------------
        task_acks_late=True,          # Acknowledge AFTER task completes (no data loss)
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,  # One task at a time per worker (fair dispatch)
        # Suppress Celery 5→6 deprecation warnings
        broker_connection_retry_on_startup=True,
        worker_cancel_long_running_tasks_on_connection_loss=True,
        # ------------------------------------------------------------------
        # Result TTL
        # ------------------------------------------------------------------
        result_expires=3600,           # Keep results for 1 hour
        # ------------------------------------------------------------------
        # Timezone
        # ------------------------------------------------------------------
        timezone="UTC",
        enable_utc=True,
        # ------------------------------------------------------------------
        # Beat Schedule (periodic tasks — placeholder for future use)
        # ------------------------------------------------------------------
        beat_schedule={
            # Example — uncomment and adjust when ready:
            # "sync-all-ndvi-every-5-days": {
            #     "task": "app.application.tasks.sync_ndvi_tasks.sync_ndvi_for_all_parcels",
            #     "schedule": crontab(hour=3, minute=0),  # 03:00 UTC
            # },
            # "sync-all-weather-every-6-hours": {
            #     "task": "app.application.tasks.sync_weather_tasks.sync_weather_for_all_parcels",
            #     "schedule": crontab(minute=0, hour="*/6"),
            # },
        },
    )

    return app


# Module-level singleton — imported by all task modules
celery_app: Celery = create_celery_app()
