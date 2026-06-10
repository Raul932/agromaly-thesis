"""
Application Service: ParcelService
=====================================
Orchestrates parcel creation, retrieval, and management use cases.

Depends on:
    - ``IParcelRepository`` (abstract).

Geometry Handling:
    - Input: GeoJSON geometry dict (from ``ParcelCreate`` schema).
    - Conversion: dict → Shapely geometry → WKT string for domain entity.
    - Area: Computed via pyproj equal-area projection when not provided.
    - All GeoJSON parsing errors raise ``InvalidGeometryError`` (400 in HTTP).

Authorization:
    Parcel operations validate that the requesting user owns the resource
    before returning or modifying data.
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional, Tuple

from app.core.exceptions import (
    InvalidGeometryError,
    ParcelNotFoundError,
    PermissionDeniedError,
)
from app.domain.entities.parcel import CropType, Parcel, ParcelStatus
from app.domain.entities.user import User
from app.domain.interfaces.parcel_repository import IParcelRepository
from app.presentation.schemas.parcel import ParcelCreate, ParcelListResponse, ParcelResponse, ParcelUpdate

logger = logging.getLogger(__name__)


class ParcelService:
    """Use cases related to agricultural parcel management.

    Args:
        parcel_repo: Injected abstract repository.
    """

    def __init__(self, parcel_repo: IParcelRepository) -> None:
        self._parcel_repo = parcel_repo

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    async def create_parcel(self, payload: ParcelCreate, owner: User) -> Parcel:
        """Create a new parcel associated with the authenticated user.

        Flow:
            1. Parse GeoJSON geometry → Shapely → WKT.
            2. Auto-compute area_ha if not supplied (projection-aware).
            3. Validate the geometry is topologically valid.
            4. Build ``Parcel`` domain entity; status defaults to PENDING.
            5. Persist and return.

        Args:
            payload: Validated ``ParcelCreate`` schema.
            owner:   Authenticated ``User`` entity (from JWT dependency).

        Returns:
            Created ``Parcel`` domain entity.

        Raises:
            InvalidGeometryError: If GeoJSON cannot be parsed or is invalid.
        """
        print("\n!!! DOCKER RULEAZA CODUL CORECT - METODA CREATE_PARCEL A PORNIT !!!\n", flush=True)
        logger.info(
            "Creating parcel name=%r for owner id=%s", payload.name, owner.id
        )

        geometry_wkt, area_ha = _geojson_to_wkt_and_area(
            payload.geometry.model_dump(), payload.area_ha
        )

        new_parcel = Parcel(
            owner_id=owner.id,
            name=payload.name,
            description=payload.description,
            geometry_wkt=geometry_wkt,
            area_ha=area_ha,
            crop_type=payload.crop_type,
            status=ParcelStatus.ACTIVE,  # AUTO-ACTIVATE on creation for simple UX
        )

        saved = await self._parcel_repo.save(new_parcel)
        logger.info("Parcel created: id=%s name=%r area=%.2f ha", saved.id, saved.name, saved.area_ha)

        # -- Fire-and-forget background tasks (Celery) --------------------
        # Imported here to avoid module-level circular imports and to ensure
        # the Celery app is only loaded when actually needed (not in tests).
        # Task dispatch failures are caught: they MUST NOT abort the HTTP response.
        self._trigger_initial_sync(str(saved.id))

        return saved

    @staticmethod
    def _trigger_initial_sync(parcel_id_str: str) -> None:
        """Enqueue NDVI and weather sync tasks for a newly created parcel.

        Both tasks run asynchronously in the Celery worker. If no broker is
        reachable (e.g., in unit tests), the error is logged but not raised.

        Args:
            parcel_id_str: UUID string of the parcel to sync.
        """
        print(f"\n!!! INCERCAM SA TRIMITEM TASK-UL CELERY PENTRU: {parcel_id_str} !!!\n", flush=True)
        try:
            from app.application.tasks.sync_ndvi_tasks import sync_ndvi_for_parcel
            from app.application.tasks.sync_weather_tasks import sync_weather_for_parcel

            ndvi_result = sync_ndvi_for_parcel.delay(parcel_id_str)
            weather_result = sync_weather_for_parcel.delay(parcel_id_str)

            logger.info(
                "Background tasks enqueued for parcel %s — ndvi_task=%s weather_task=%s",
                parcel_id_str, ndvi_result.id, weather_result.id,
            )
            print("\n!!! AM TRIMIS CU SUCCES IN REDIS !!!\n", flush=True)
        except Exception as exc:
            # Graceful degradation: parcel is saved; sync is best-effort.
            print(f"\n!!! EROARE LA TRIMITEREA IN REDIS: {exc} !!!\n", flush=True)
            logger.error(
                "Failed to enqueue background sync tasks for parcel %s: %s",
                parcel_id_str, exc,
            )

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def list_owner_parcels(
        self,
        owner: User,
        *,
        status: Optional[ParcelStatus] = None,
        crop_type: Optional[CropType] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> ParcelListResponse:
        """List all parcels belonging to the authenticated user.

        Args:
            owner:     Authenticated user entity.
            status:    Optional status filter.
            crop_type: Optional crop filter.
            limit:     Pagination page size.
            offset:    Pagination offset.

        Returns:
            ``ParcelListResponse`` with items and total count.
        """
        parcels = await self._parcel_repo.list_by_owner(
            owner.id,
            status=status,
            crop_type=crop_type,
            limit=limit,
            offset=offset,
        )
        total = await self._parcel_repo.count_by_owner(owner.id, status=status)

        items = [ParcelResponse.model_validate(p, from_attributes=True) for p in parcels]
        return ParcelListResponse(items=items, total=total, limit=limit, offset=offset)

    async def get_parcel(self, parcel_id: uuid.UUID, owner: User) -> Parcel:
        """Retrieve a single parcel, enforcing ownership.

        Args:
            parcel_id: UUID of the requested parcel.
            owner:     Authenticated user (must own the parcel).

        Returns:
            The matching ``Parcel`` domain entity.

        Raises:
            ParcelNotFoundError:    If parcel does not exist.
            PermissionDeniedError:  If the user does not own this parcel.
        """
        parcel = await self._parcel_repo.get_by_id(parcel_id)
        if parcel is None:
            raise ParcelNotFoundError(f"Parcel id={parcel_id} not found.")
        if parcel.owner_id != owner.id and not owner.is_superuser:
            raise PermissionDeniedError(
                "You do not have permission to access this parcel."
            )
        return parcel

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    async def update_parcel(
        self,
        parcel_id: uuid.UUID,
        payload: ParcelUpdate,
        owner: User,
    ) -> Parcel:
        """Apply a partial update to a parcel (name, description, crop_type).

        Only the fields explicitly provided in the payload are changed.

        Args:
            parcel_id: UUID of the parcel to update.
            payload:   ``ParcelUpdate`` schema with optional fields.
            owner:     Authenticated user (must own the parcel).

        Returns:
            Updated ``Parcel`` domain entity.
        """
        parcel = await self.get_parcel(parcel_id, owner)

        update_kwargs: dict = {}
        if payload.name is not None:
            update_kwargs["name"] = payload.name
        if payload.description is not None:
            update_kwargs["description"] = payload.description
        if payload.crop_type is not None:
            update_kwargs["crop_type"] = payload.crop_type

        if not update_kwargs:
            return parcel  # No-op

        from datetime import datetime, timezone
        update_kwargs["updated_at"] = datetime.now(tz=timezone.utc)
        updated = parcel._copy_with(**update_kwargs)
        saved = await self._parcel_repo.save(updated)
        logger.info("Parcel updated: id=%s fields=%s", parcel_id, list(update_kwargs.keys()))
        return saved

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    async def delete_parcel(self, parcel_id: uuid.UUID, owner: User) -> None:
        """Hard-delete a parcel (and cascade to its NDVI/weather/alerts).

        Args:
            parcel_id: UUID of the parcel to remove.
            owner:     Authenticated user (must own the parcel).
        """
        parcel = await self.get_parcel(parcel_id, owner)
        deleted = await self._parcel_repo.delete(parcel.id)
        if not deleted:
            raise ParcelNotFoundError(f"Parcel id={parcel_id} could not be deleted.")
        logger.info("Parcel deleted: id=%s by owner=%s", parcel_id, owner.id)


# ---------------------------------------------------------------------------
# Geometry Helpers (private to this module)
# ---------------------------------------------------------------------------

def _geojson_to_wkt_and_area(
    geojson_dict: dict,
    provided_area_ha: Optional[float],
) -> Tuple[str, float]:
    """Parse a GeoJSON geometry dict and return (WKT string, area_ha).

    Uses Shapely for geometry parsing and pyproj for accurate area calculation
    via an Equal-Area projection (EPSG:6933 — WGS 84 / NSIDC EASE-Grid 2.0).

    Args:
        geojson_dict:    GeoJSON geometry as a plain Python dict.
        provided_area_ha: Pre-supplied area (skips calculation if given).

    Returns:
        Tuple of (WKT string, area in hectares).

    Raises:
        InvalidGeometryError: If the geometry cannot be parsed or is invalid.
    """
    try:
        from shapely.geometry import shape, MultiPolygon
        from shapely.validation import make_valid
        import pyproj
        from shapely.ops import transform as shapely_transform

        shapely_geom = shape(geojson_dict)

        # Auto-repair minor topology issues (self-intersections, etc.)
        if not shapely_geom.is_valid:
            shapely_geom = make_valid(shapely_geom)
            logger.debug("Geometry auto-repaired with make_valid().")

        if shapely_geom.is_empty:
            raise InvalidGeometryError("Geometry is empty.")

        # Promote Polygon → MultiPolygon for consistent storage
        if shapely_geom.geom_type == "Polygon":
            shapely_geom = MultiPolygon([shapely_geom])

        wkt: str = shapely_geom.wkt

    except InvalidGeometryError:
        raise
    except Exception as exc:
        logger.error("GeoJSON parse error: %s", exc)
        raise InvalidGeometryError(
            f"Could not parse GeoJSON geometry: {exc}"
        ) from exc

    # Area calculation
    if provided_area_ha is not None:
        return wkt, provided_area_ha

    try:
        # Project to an equal-area CRS for accurate surface area measurement
        wgs84 = pyproj.CRS("EPSG:4326")
        equal_area = pyproj.CRS("EPSG:6933")  # WGS 84 / NSIDC EASE-Grid 2.0 Global
        project = pyproj.Transformer.from_crs(wgs84, equal_area, always_xy=True).transform
        projected = shapely_transform(project, shapely_geom)
        area_m2 = projected.area
        area_ha = area_m2 / 10_000.0
    except Exception as exc:
        logger.error("Area calculation error: %s", exc)
        raise InvalidGeometryError(
            f"Could not calculate parcel area from geometry: {exc}"
        ) from exc

    if area_ha <= 0:
        raise InvalidGeometryError(
            f"Computed area is zero or negative ({area_ha:.4f} ha). "
            "Check that coordinates are in WGS84 (lon, lat) order."
        )

    logger.debug("Auto-calculated area: %.4f ha", area_ha)
    return wkt, area_ha
