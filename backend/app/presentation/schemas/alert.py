"""Pydantic schemas for the Alerts endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class AlertResponse(BaseModel):
    """Serialized alert for the mobile app."""

    id: UUID
    parcel_id: UUID
    parcel_name: str
    alert_type: str
    severity: str
    title: str
    description: str
    ai_recommendation: Optional[str] = None
    is_read: bool
    created_at: datetime
    read_at: Optional[datetime] = None
    triggered_value: Optional[float] = None
    threshold_value: Optional[float] = None

    model_config = {"from_attributes": True}


class UnreadCountResponse(BaseModel):
    """Badge count response."""

    count: int
