"""
SQLAlchemy ORM Model: ParcelORM
================================
The concrete database representation of the Parcel aggregate.

Updated in Step 2:
    - ``owner_id`` now has a real ForeignKey → ``users.id`` (CASCADE).
    - Added relationships: ``owner``, ``ndvi_records``, ``weather_forecasts``,
      ``alerts`` (all lazy="noload" for explicit control).
    - Moved ``Base`` import to shared ``app.infrastructure.db.base``.

Mapping Strategy:
    Two explicit conversion methods keep the layers decoupled:
        ``to_domain()``        — ORM → Domain entity
        ``from_domain(parcel)`` — Domain entity → ORM model (class method)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, List, Optional

from geoalchemy2 import Geometry, WKBElement
from geoalchemy2.shape import to_shape
import shapely.wkt
from sqlalchemy import (
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.entities.parcel import CropType, Parcel, ParcelStatus
from app.infrastructure.db.base import Base

if TYPE_CHECKING:
    from app.infrastructure.db.models.user_orm import UserORM
    from app.infrastructure.db.models.ndvi_record_orm import NDVIRecordORM
    from app.infrastructure.db.models.weather_forecast_orm import WeatherForecastORM
    from app.infrastructure.db.models.alert_orm import AlertORM


class ParcelORM(Base):
    """SQLAlchemy ORM representation of the ``parcels`` database table.

    The table stores georeferenced agricultural parcels. The geometry column
    is stored as PostGIS MULTIPOLYGON (WGS84 / SRID 4326) to support both
    simple polygons and complex multi-part parcels (e.g. disjoint fields).

    Columns:
        id          (UUID)        — Primary key, auto-generated.
        owner_id    (UUID, FK)    — FK → users.id (CASCADE DELETE).
        name        (VARCHAR 255) — Human-readable parcel name.
        description (TEXT)        — Optional free-text notes.
        geometry    (GEOMETRY)    — PostGIS MULTIPOLYGON, SRID 4326.
        area_ha     (FLOAT)       — Pre-computed area in hectares.
        srid        (INTEGER)     — Spatial reference ID (default 4326).
        crop_type   (ENUM)        — Planted crop.
        status      (ENUM)        — Lifecycle state.
        created_at  (TIMESTAMPTZ) — Creation timestamp (server default: NOW()).
        updated_at  (TIMESTAMPTZ) — Last modification timestamp.
        last_ndvi   (FLOAT)       — Most recent NDVI reading (denormalised cache).
        last_ndvi_at(TIMESTAMPTZ) — Timestamp of last NDVI reading.

    Relationships:
        owner            — Many-to-One → UserORM
        ndvi_records     — One-to-Many → NDVIRecordORM (cascade delete)
        weather_forecasts— One-to-Many → WeatherForecastORM (cascade delete)
        alerts           — One-to-Many → AlertORM (cascade delete)

    Indexes:
        ix_parcels_owner_id          — B-tree index for owner lookups.
        ix_parcels_geometry          — GiST spatial index (ST_Intersects, etc.).
        ix_parcels_owner_status      — Composite index for common filtered queries.
    """

    __tablename__ = "parcels"

    __table_args__ = (
        # GiST index for PostGIS spatial operations
        Index(
            "ix_parcels_geometry",
            "geometry",
            postgresql_using="gist",
        ),
        # Composite index: most queries filter by owner + status
        Index(
            "ix_parcels_owner_status",
            "owner_id",
            "status",
        ),
        Index("ix_parcels_owner_id", "owner_id"),
    )

    # ------------------------------------------------------------------
    # Primary Key
    # ------------------------------------------------------------------
    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="Globally unique identifier for the parcel.",
    )

    # ------------------------------------------------------------------
    # Ownership — FK to users table
    # ------------------------------------------------------------------
    owner_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        comment="FK → users.id. Cascaded on user deletion.",
    )

    # ------------------------------------------------------------------
    # Descriptive
    # ------------------------------------------------------------------
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Human-readable label for the parcel.",
    )

    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Optional free-text notes from the farmer.",
    )

    # ------------------------------------------------------------------
    # Geospatial
    # ------------------------------------------------------------------
    geometry: Mapped[WKBElement] = mapped_column(
        Geometry(
            geometry_type="MULTIPOLYGON",
            srid=4326,
            spatial_index=False,  # Named GiST index defined above
        ),
        nullable=False,
        comment="PostGIS MULTIPOLYGON geometry (WGS84, SRID 4326).",
    )

    area_ha: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        comment="Pre-computed area in hectares.",
    )

    srid: Mapped[int] = mapped_column(
        nullable=False,
        default=4326,
        server_default="4326",
        comment="Spatial Reference Identifier (4326 = WGS84).",
    )

    # ------------------------------------------------------------------
    # Agronomy
    # ------------------------------------------------------------------
    crop_type: Mapped[CropType] = mapped_column(
        SAEnum(CropType, name="croptype", create_constraint=True, validate_strings=True),
        nullable=False,
        default=CropType.UNKNOWN,
        server_default="UNKNOWN",
        comment="Current crop planted on this parcel.",
    )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    status: Mapped[ParcelStatus] = mapped_column(
        SAEnum(ParcelStatus, name="parcelstatus", create_constraint=True, validate_strings=True),
        nullable=False,
        default=ParcelStatus.PENDING,
        server_default="PENDING",
        comment="Lifecycle status of the parcel.",
    )

    # ------------------------------------------------------------------
    # Temporal
    # ------------------------------------------------------------------
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="UTC timestamp of record creation.",
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        comment="UTC timestamp of last modification.",
    )

    # ------------------------------------------------------------------
    # Analytics Cache (denormalised for fast reads)
    # ------------------------------------------------------------------
    last_ndvi: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
        comment="Most recent NDVI value from satellite imagery (-1.0 to 1.0).",
    )

    last_ndvi_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="UTC timestamp when last_ndvi was measured.",
    )

    last_anomaly_status: Mapped[Optional[str]] = mapped_column(
        String(30),
        nullable=True,
        comment="Most recent anomaly detection result (HEALTHY/ANOMALY_DETECTED/INSUFFICIENT_DATA).",
    )

    # ------------------------------------------------------------------
    # Relationships
    # ------------------------------------------------------------------
    owner: Mapped["UserORM"] = relationship(
        "UserORM",
        back_populates="parcels",
        lazy="noload",
    )

    ndvi_records: Mapped[List["NDVIRecordORM"]] = relationship(
        "NDVIRecordORM",
        back_populates="parcel",
        cascade="all, delete-orphan",
        lazy="noload",
        passive_deletes=True,
    )

    weather_forecasts: Mapped[List["WeatherForecastORM"]] = relationship(
        "WeatherForecastORM",
        back_populates="parcel",
        cascade="all, delete-orphan",
        lazy="noload",
        passive_deletes=True,
    )

    alerts: Mapped[List["AlertORM"]] = relationship(
        "AlertORM",
        back_populates="parcel",
        cascade="all, delete-orphan",
        lazy="noload",
        passive_deletes=True,
    )

    # ------------------------------------------------------------------
    # Mapping: ORM → Domain Entity
    # ------------------------------------------------------------------

    def to_domain(self) -> Parcel:
        """Convert this ORM row to an immutable ``Parcel`` domain entity.

        Geometry is extracted from the PostGIS WKBElement and converted to
        a WKT string so the domain layer remains ignorant of GeoAlchemy2.
        """
        shapely_geom = to_shape(self.geometry)
        geometry_wkt: str = shapely_geom.wkt

        return Parcel(
            id=self.id,
            owner_id=self.owner_id,
            name=self.name,
            description=self.description,
            geometry_wkt=geometry_wkt,
            area_ha=self.area_ha,
            srid=self.srid,
            crop_type=CropType(self.crop_type),
            status=ParcelStatus(self.status),
            created_at=self.created_at,
            updated_at=self.updated_at,
            last_ndvi=self.last_ndvi,
            last_ndvi_at=self.last_ndvi_at,
            last_anomaly_status=self.last_anomaly_status,
        )

    # ------------------------------------------------------------------
    # Mapping: Domain Entity → ORM Model
    # ------------------------------------------------------------------

    @classmethod
    def from_domain(cls, parcel: Parcel) -> "ParcelORM":
        """Construct a ``ParcelORM`` instance from a ``Parcel`` domain entity."""
        from geoalchemy2.elements import WKTElement

        shapely_geom = shapely.wkt.loads(parcel.geometry_wkt)
        if shapely_geom.geom_type == "Polygon":
            from shapely.geometry import MultiPolygon
            shapely_geom = MultiPolygon([shapely_geom])

        wkt_element = WKTElement(shapely_geom.wkt, srid=parcel.srid)

        return cls(
            id=parcel.id,
            owner_id=parcel.owner_id,
            name=parcel.name,
            description=parcel.description,
            geometry=wkt_element,
            area_ha=parcel.area_ha,
            srid=parcel.srid,
            crop_type=parcel.crop_type,
            status=parcel.status,
            created_at=parcel.created_at,
            updated_at=parcel.updated_at,
            last_ndvi=parcel.last_ndvi,
            last_ndvi_at=parcel.last_ndvi_at,
            last_anomaly_status=parcel.last_anomaly_status,
        )

    def __repr__(self) -> str:
        return (
            f"<ParcelORM id={self.id!s} name={self.name!r} "
            f"status={self.status!r} area_ha={self.area_ha:.2f}>"
        )
