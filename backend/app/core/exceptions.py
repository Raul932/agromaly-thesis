"""
Unified Domain Exceptions
==========================
Application-layer exceptions that the routers catch and convert to HTTP
responses. Using a typed exception hierarchy ensures:
    - No raw SQLAlchemy / DB errors ever reach the HTTP response body.
    - Exception handlers in ``main.py`` produce consistent JSON error shapes.
    - Domain and application logic stays decoupled from HTTP status codes.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

class AgromalyError(Exception):
    """Base class for all Agromaly application exceptions."""
    message: str = "An unexpected error occurred."

    def __init__(self, message: str | None = None) -> None:
        self.message = message or self.__class__.message
        super().__init__(self.message)


# ---------------------------------------------------------------------------
# Entity Not Found
# ---------------------------------------------------------------------------

class NotFoundError(AgromalyError):
    """Raised when a requested resource does not exist."""
    message = "Resource not found."


class UserNotFoundError(NotFoundError):
    message = "User not found."


class ParcelNotFoundError(NotFoundError):
    message = "Parcel not found."


class NDVIRecordNotFoundError(NotFoundError):
    message = "NDVI record not found."


class AlertNotFoundError(NotFoundError):
    message = "Alert not found."


# ---------------------------------------------------------------------------
# Conflict / Already Exists
# ---------------------------------------------------------------------------

class ConflictError(AgromalyError):
    """Raised when a uniqueness constraint would be violated."""
    message = "A resource with the given identifier already exists."


class EmailAlreadyRegisteredError(ConflictError):
    message = "A user with this email address is already registered."


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------

class PermissionDeniedError(AgromalyError):
    """Raised when a user attempts to access a resource they don't own."""
    message = "You do not have permission to access this resource."


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class ValidationError(AgromalyError):
    """Raised when business-level validation fails (distinct from Pydantic)."""
    message = "The provided data failed validation."


class InvalidGeometryError(ValidationError):
    """Raised when parcel geometry cannot be parsed or is topologically invalid."""
    message = "Invalid geometry: the provided GeoJSON or WKT could not be parsed."


# ---------------------------------------------------------------------------
# External Service Errors
# ---------------------------------------------------------------------------

class ExternalServiceError(AgromalyError):
    """Raised when a call to an external API (weather, satellite) fails."""
    message = "An external service request failed."


class WeatherAPIError(ExternalServiceError):
    message = "Weather API request failed."


class SatelliteAPIError(ExternalServiceError):
    message = "Satellite data fetch failed."
