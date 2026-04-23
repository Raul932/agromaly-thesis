"""
Domain Entity: Alert
=====================
Represents a proactive AI-generated notification to a farmer about a detected
anomaly or weather risk on one of their parcels.

Lifecycle:
    1. Celery task (anomaly or weather) detects a risk condition.
    2. RAG pipeline generates an ``ai_recommendation`` action plan.
    3. An Alert entity is constructed and persisted (status: UNREAD).
    4. Farmer views the alert in the mobile app → ``mark_as_read()`` called.
    5. Optionally resolved with a farmer-supplied outcome note.

Design Note:
    Alert is intentionally a value-object-like aggregate — it carries the
    full recommendation text so no extra join is needed when displaying
    the alert list in the mobile UI.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class AlertType(str, Enum):
    """Classification of what triggered this alert.

    ANOMALY: LSTM Autoencoder detected vegetative stress via high MSE.
    WEATHER: Forecast-based threshold breach (frost, fungal, drought, etc.).
    """

    ANOMALY = "anomaly"    # Satellite NDVI anomaly detected
    WEATHER = "weather"    # Weather forecast risk threshold breached


class AlertSeverity(str, Enum):
    """Urgency level of the alert, used for mobile push notification priority."""

    LOW = "low"          # Advisory; no immediate action needed
    MEDIUM = "medium"    # Action recommended within 48 hours
    HIGH = "high"        # Urgent; act within 24 hours
    CRITICAL = "critical"  # Immediate action required (e.g. frost imminent)


# ---------------------------------------------------------------------------
# Domain Entity
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Alert:
    """An AI-generated proactive alert for a farmer's parcel.

    Attributes:
        id:                Unique alert identifier.
        parcel_id:         UUID of the affected parcel.
        alert_type:        What triggered this alert (ANOMALY | WEATHER).
        severity:          Urgency classification.
        title:             Short human-readable headline (max 255 chars).
        description:       Detailed description of the detected condition.
        ai_recommendation: RAG-generated action plan (may be long-form text).
        is_read:           Whether the farmer has acknowledged this alert.
        created_at:        UTC timestamp of alert creation.
        read_at:           UTC timestamp when the farmer read the alert.
        triggered_value:   The numeric value that crossed a threshold
                           (e.g. MSE score, precipitation_mm). Optional.
        threshold_value:   The threshold that was crossed. Optional.
    """

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    parcel_id: uuid.UUID = field(default=...)
    alert_type: AlertType = field(default=...)
    severity: AlertSeverity = field(default=AlertSeverity.MEDIUM)
    title: str = field(default=...)
    description: str = field(default=...)
    ai_recommendation: Optional[str] = field(default=None)
    is_read: bool = field(default=False)
    created_at: datetime = field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )
    read_at: Optional[datetime] = field(default=None)
    triggered_value: Optional[float] = field(default=None)
    threshold_value: Optional[float] = field(default=None)

    def __post_init__(self) -> None:
        self._validate_title()
        self._validate_description()
        self._validate_read_state()

    def _validate_title(self) -> None:
        if not isinstance(self.title, str) or not self.title.strip():
            raise ValueError("Alert 'title' must be a non-empty string.")
        if len(self.title) > 255:
            raise ValueError(
                f"Alert 'title' exceeds 255 characters (got {len(self.title)})."
            )

    def _validate_description(self) -> None:
        if not isinstance(self.description, str) or not self.description.strip():
            raise ValueError("Alert 'description' must be a non-empty string.")

    def _validate_read_state(self) -> None:
        """Enforce invariant: read_at must be set iff is_read is True."""
        if self.is_read and self.read_at is None:
            raise ValueError(
                "Alert 'read_at' must be provided when 'is_read' is True."
            )
        if not self.is_read and self.read_at is not None:
            raise ValueError(
                "Alert 'read_at' must be None when 'is_read' is False."
            )

    # ------------------------------------------------------------------
    # Domain Behaviour
    # ------------------------------------------------------------------

    def mark_as_read(self) -> "Alert":
        """Return a new Alert with is_read=True and read_at set to now.

        Raises:
            ValueError: If the alert is already read (idempotency guard).
        """
        if self.is_read:
            raise ValueError(
                f"Alert id={self.id} is already marked as read."
            )
        now = datetime.now(tz=timezone.utc)
        return self._copy_with(is_read=True, read_at=now)

    def attach_recommendation(self, recommendation: str) -> "Alert":
        """Return a new Alert with the AI-generated action plan attached.

        Args:
            recommendation: The RAG-generated recommendation text.

        Returns:
            New Alert with ``ai_recommendation`` populated.
        """
        if not recommendation or not recommendation.strip():
            raise ValueError("Recommendation text must not be empty.")
        return self._copy_with(ai_recommendation=recommendation)

    # ------------------------------------------------------------------
    # Computed Properties
    # ------------------------------------------------------------------

    @property
    def is_critical(self) -> bool:
        """Return True if this alert requires immediate farmer attention."""
        return self.severity == AlertSeverity.CRITICAL

    @property
    def has_recommendation(self) -> bool:
        """Return True if an AI recommendation has been attached."""
        return bool(self.ai_recommendation)

    # ------------------------------------------------------------------
    # Private Helpers
    # ------------------------------------------------------------------

    def _copy_with(self, **overrides: object) -> "Alert":
        import dataclasses
        current_fields = {f.name: getattr(self, f.name) for f in dataclasses.fields(self)}
        current_fields.update(overrides)
        return Alert(**current_fields)

    def __repr__(self) -> str:
        return (
            f"Alert(id={self.id!s}, parcel={self.parcel_id!s}, "
            f"type={self.alert_type.value!r}, severity={self.severity.value!r}, "
            f"is_read={self.is_read})"
        )
