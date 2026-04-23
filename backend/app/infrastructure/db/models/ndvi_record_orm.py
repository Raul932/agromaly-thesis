"""
SQLAlchemy ORM Model: NDVIRecordORM
=====================================
Time-series table for satellite-derived NDVI observations.

Partitioning Note:
    At scale (millions of records), this table would benefit from
    PostgreSQL range partitioning on ``date_captured`` (by year/quarter).
    For now, composite indexes are sufficient for typical parcel counts.

Unique Constraint:
    (parcel_id, date_captured, source) — ensures re-ingestion of the same
    satellite pass is idempotent (INSERT … ON CONFLICT DO NOTHING).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.db.base import Base
from app.domain.entities.ndvi_record import NDVIRecord

if TYPE_CHECKING:
    from app.infrastructure.db.models.parcel_orm import ParcelORM


class NDVIRecordORM(Base):
    """ORM representation of the ``ndvi_records`` time-series table."""

    __tablename__ = "ndvi_records"

    __table_args__ = (
        # Natural key: one record per satellite pass per parcel per source
        UniqueConstraint(
            "parcel_id", "date_captured", "source",
            name="uq_ndvi_parcel_date_source",
        ),
        # Composite index optimised for the most common query pattern
        Index("ix_ndvi_parcel_date", "parcel_id", "date_captured"),
        Index("ix_ndvi_parcel_id", "parcel_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    parcel_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("parcels.id", ondelete="CASCADE"),
        nullable=False,
        comment="Links to the parent parcel. Cascaded on parcel deletion.",
    )
    date_captured: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        comment="Calendar date of the satellite pass (UTC).",
    )
    mean_ndvi: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        comment="Mean NDVI over the parcel area. Range: [-1.0, 1.0].",
    )
    cloud_coverage: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
        server_default="0.0",
        comment="Percentage of parcel obscured by cloud cover [0–100].",
    )
    pixel_count: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="Number of satellite pixels averaged.",
    )
    is_interpolated: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment="True if this NDVI was gap-filled (high cloud coverage).",
    )
    source: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="unknown",
        server_default="unknown",
        comment="Satellite source identifier (e.g. sentinel-2, landsat-8).",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # ------------------------------------------------------------------
    # Relationships
    # ------------------------------------------------------------------
    parcel: Mapped["ParcelORM"] = relationship(
        "ParcelORM",
        back_populates="ndvi_records",
        lazy="noload",
    )

    # ------------------------------------------------------------------
    # Mapping
    # ------------------------------------------------------------------

    def to_domain(self) -> NDVIRecord:
        return NDVIRecord(
            id=self.id,
            parcel_id=self.parcel_id,
            date_captured=self.date_captured,
            mean_ndvi=self.mean_ndvi,
            cloud_coverage=self.cloud_coverage,
            pixel_count=self.pixel_count,
            is_interpolated=self.is_interpolated,
            source=self.source,
            created_at=self.created_at,
        )

    @classmethod
    def from_domain(cls, record: NDVIRecord) -> "NDVIRecordORM":
        return cls(
            id=record.id,
            parcel_id=record.parcel_id,
            date_captured=record.date_captured,
            mean_ndvi=record.mean_ndvi,
            cloud_coverage=record.cloud_coverage,
            pixel_count=record.pixel_count,
            is_interpolated=record.is_interpolated,
            source=record.source,
            created_at=record.created_at,
        )

    def __repr__(self) -> str:
        return (
            f"<NDVIRecordORM parcel={self.parcel_id!s} "
            f"date={self.date_captured!s} ndvi={self.mean_ndvi:.4f}>"
        )
