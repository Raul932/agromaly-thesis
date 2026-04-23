"""
Domain Entity: Parcel
=====================
A pure Python dataclass representing an agricultural parcel.

Design Principles:
    - Zero framework dependencies (no SQLAlchemy, FastAPI, Pydantic imports).
    - Immutable by default (frozen=True) to enforce value semantics and
      prevent accidental mutation outside of controlled factory methods.
    - All geospatial geometry is expressed as a serialized WKT string so this
      layer remains agnostic of GeoAlchemy2 or Shapely internals.
    - Rich domain logic lives here (validation, computed properties), NOT in
      ORM models or service layers.

Glossary:
    WKT  — Well-Known Text, an ISO standard for representing geometries as
            human-readable strings, e.g. "POLYGON ((lon lat, lon lat, ...))".
    SRID — Spatial Reference Identifier. 4326 = WGS84 (GPS coordinates).
    NDVI — Normalized Difference Vegetation Index, a satellite-derived
           measure of vegetation health (range: -1.0 → 1.0).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Value Objects / Enumerations
# ---------------------------------------------------------------------------

class CropType(str, Enum):
    """Enumeration of supported crop types for agronomy-specific alerts.

    Using ``str`` as a mixin makes JSON serialization trivial and allows
    direct comparison with raw string values when parsing external data.
    """

    WHEAT = "wheat"
    CORN = "corn"
    SUNFLOWER = "sunflower"
    SOYBEAN = "soybean"
    RAPESEED = "rapeseed"
    BARLEY = "barley"
    POTATO = "potato"
    SUGAR_BEET = "sugar_beet"
    VINEYARD = "vineyard"
    ORCHARD = "orchard"
    OTHER = "other"
    UNKNOWN = "unknown"


class ParcelStatus(str, Enum):
    """Lifecycle status of a parcel within the system.

    Transitions:
        ACTIVE  → ARCHIVED  (user deactivates parcel)
        ACTIVE  → PENDING   (re-import / ownership transfer started)
        PENDING → ACTIVE    (import/transfer confirmed)
    """

    PENDING = "pending"    # Imported but not yet validated / activated
    ACTIVE = "active"      # Fully operational; eligible for anomaly detection
    ARCHIVED = "archived"  # Soft-deleted; retained for historical reporting


# ---------------------------------------------------------------------------
# Domain Entity
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Parcel:
    """Represents a georeferenced agricultural parcel owned by a farmer.

    This is the central aggregate root for the geo-analysis pipeline.
    The entity is *frozen* (immutable) — any state changes must go through
    explicit factory/update methods that return a new ``Parcel`` instance,
    preserving audit trails and preventing hidden mutations.

    Attributes:
        id:           Globally unique identifier (UUID v4).
        owner_id:     Foreign-key reference to the User who owns this parcel.
        name:         Human-readable label assigned by the farmer.
        geometry_wkt: Polygon boundary in Well-Known Text, SRID 4326.
        area_ha:      Pre-computed parcel area in hectares. Must be > 0.
        crop_type:    Current crop planted on this parcel.
        status:       Lifecycle status (PENDING | ACTIVE | ARCHIVED).
        created_at:   UTC timestamp of initial record creation.
        updated_at:   UTC timestamp of the most recent state change.
        description:  Optional free-text notes from the farmer.
        srid:         Spatial Reference ID. Default 4326 (WGS84 / GPS).
        last_ndvi:    Most recent NDVI value computed from satellite imagery.
        last_ndvi_at: UTC timestamp when ``last_ndvi`` was last updated.
    """

    # --- Identity ---
    id: uuid.UUID = field(default_factory=uuid.uuid4)

    # --- Ownership ---
    owner_id: uuid.UUID = field(default=...)   # Required; no default

    # --- Descriptive ---
    name: str = field(default=...)
    description: Optional[str] = field(default=None)

    # --- Geospatial ---
    geometry_wkt: str = field(default=...)    # WKT polygon string
    area_ha: float = field(default=...)       # Hectares
    srid: int = field(default=4326)           # WGS84

    # --- Agronomy ---
    crop_type: CropType = field(default=CropType.UNKNOWN)

    # --- Lifecycle ---
    status: ParcelStatus = field(default=ParcelStatus.PENDING)

    # --- Temporal ---
    created_at: datetime = field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )
    updated_at: datetime = field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )

    # --- Analytics Cache (denormalised for fast reads) ---
    last_ndvi: Optional[float] = field(default=None)
    last_ndvi_at: Optional[datetime] = field(default=None)

    # ------------------------------------------------------------------
    # Post-init validation
    # ------------------------------------------------------------------

    def __post_init__(self) -> None:
        """Run domain-level invariant checks immediately after construction.

        Raises:
            ValueError: If any business rule is violated.
        """
        self._validate_name()
        self._validate_area()
        self._validate_geometry_wkt()
        self._validate_ndvi()

    def _validate_name(self) -> None:
        """Parcel name must be a non-empty string, max 255 chars."""
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("Parcel 'name' must be a non-empty string.")
        if len(self.name) > 255:
            raise ValueError(
                f"Parcel 'name' exceeds 255 characters (got {len(self.name)})."
            )

    def _validate_area(self) -> None:
        """Area must be a positive finite number."""
        if not isinstance(self.area_ha, (int, float)) or self.area_ha <= 0:
            raise ValueError(
                f"Parcel 'area_ha' must be a positive number (got {self.area_ha!r})."
            )

    def _validate_geometry_wkt(self) -> None:
        """WKT string must be non-empty and start with a recognised geometry type."""
        if not isinstance(self.geometry_wkt, str) or not self.geometry_wkt.strip():
            raise ValueError("Parcel 'geometry_wkt' must be a non-empty WKT string.")
        upper = self.geometry_wkt.strip().upper()
        valid_prefixes = ("POLYGON", "MULTIPOLYGON", "GEOMETRYCOLLECTION")
        if not any(upper.startswith(prefix) for prefix in valid_prefixes):
            raise ValueError(
                "Parcel 'geometry_wkt' must be a POLYGON or MULTIPOLYGON WKT string. "
                f"Got: '{self.geometry_wkt[:60]}...'"
            )

    def _validate_ndvi(self) -> None:
        """NDVI, if provided, must be in the valid spectral range [-1.0, 1.0]."""
        if self.last_ndvi is not None:
            if not (-1.0 <= self.last_ndvi <= 1.0):
                raise ValueError(
                    f"NDVI value must be in [-1.0, 1.0], got {self.last_ndvi}."
                )

    # ------------------------------------------------------------------
    # Domain Behaviour / Factory-Style Update Methods
    # ------------------------------------------------------------------

    def activate(self) -> "Parcel":
        """Transition a PENDING parcel to ACTIVE status.

        Returns a *new* Parcel instance with the updated status and
        ``updated_at`` timestamp, preserving immutability.

        Raises:
            ValueError: If the parcel is already ARCHIVED.
        """
        if self.status == ParcelStatus.ARCHIVED:
            raise ValueError(
                f"Cannot activate an ARCHIVED parcel (id={self.id})."
            )
        return self._copy_with(
            status=ParcelStatus.ACTIVE,
            updated_at=datetime.now(tz=timezone.utc),
        )

    def archive(self) -> "Parcel":
        """Soft-delete this parcel (ARCHIVED status).

        Returns:
            A new Parcel instance with status=ARCHIVED.
        """
        return self._copy_with(
            status=ParcelStatus.ARCHIVED,
            updated_at=datetime.now(tz=timezone.utc),
        )

    def update_ndvi(self, ndvi_value: float, measured_at: datetime) -> "Parcel":
        """Record a new NDVI observation.

        Args:
            ndvi_value:  Satellite-derived NDVI (-1.0 to 1.0).
            measured_at: UTC timestamp of the satellite pass.

        Returns:
            A new Parcel instance with updated NDVI fields.

        Raises:
            ValueError: If ``ndvi_value`` is out of range.
        """
        if not (-1.0 <= ndvi_value <= 1.0):
            raise ValueError(
                f"NDVI value must be in [-1.0, 1.0], got {ndvi_value}."
            )
        return self._copy_with(
            last_ndvi=ndvi_value,
            last_ndvi_at=measured_at,
            updated_at=datetime.now(tz=timezone.utc),
        )

    # ------------------------------------------------------------------
    # Computed Properties
    # ------------------------------------------------------------------

    @property
    def is_active(self) -> bool:
        """Return True if the parcel is in ACTIVE status."""
        return self.status == ParcelStatus.ACTIVE

    @property
    def has_ndvi_data(self) -> bool:
        """Return True if at least one NDVI observation has been recorded."""
        return self.last_ndvi is not None and self.last_ndvi_at is not None

    # ------------------------------------------------------------------
    # Private Helpers
    # ------------------------------------------------------------------

    def _copy_with(self, **overrides: object) -> "Parcel":
        """Return a shallow copy of this Parcel with specified field overrides.

        Since the dataclass is frozen, we use ``object.__setattr__`` tricks
        are NOT available; instead we call the constructor with updated args.
        This is intentional — it ensures all invariants are re-validated.
        """
        import dataclasses
        current = dataclasses.asdict(self)
        # UUID and datetime survive asdict as-is (they are not serialised)
        # but we must re-hydrate them from the asdict result.
        # Easier: build from fields directly.
        current_fields = {f.name: getattr(self, f.name) for f in dataclasses.fields(self)}
        current_fields.update(overrides)
        return Parcel(**current_fields)

    # ------------------------------------------------------------------
    # Representations
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"Parcel(id={self.id!s}, name={self.name!r}, "
            f"status={self.status.value!r}, area_ha={self.area_ha:.2f}, "
            f"crop_type={self.crop_type.value!r})"
        )
