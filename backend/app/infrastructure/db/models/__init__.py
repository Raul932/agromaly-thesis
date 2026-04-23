"""
ORM Model Registry
====================
Importing all SQLAlchemy ORM models here guarantees they are registered
with ``Base.metadata`` and SQLAlchemy's mapper registry before any mapper
configuration or relationship string-resolution occurs at runtime.

WHY THIS FILE EXISTS:
    SQLAlchemy uses string names in ``relationship("NDVIRecordORM", ...)``
    to defer resolution until mapper configuration time. If a model class
    has never been imported, the string lookup fails with:
        "expression 'NDVIRecordORM' failed to locate a name"

    ``session.py`` imports this package at startup, ensuring every class is
    registered before the first ORM operation executes.

ADDING NEW MODELS:
    Add the import here. This is the single source of truth for model loading.
"""

from app.infrastructure.db.models.user_orm import UserORM  # noqa: F401
from app.infrastructure.db.models.parcel_orm import ParcelORM  # noqa: F401
from app.infrastructure.db.models.ndvi_record_orm import NDVIRecordORM  # noqa: F401
from app.infrastructure.db.models.weather_forecast_orm import WeatherForecastORM  # noqa: F401
from app.infrastructure.db.models.alert_orm import AlertORM  # noqa: F401

__all__ = [
    "UserORM",
    "ParcelORM",
    "NDVIRecordORM",
    "WeatherForecastORM",
    "AlertORM",
]
