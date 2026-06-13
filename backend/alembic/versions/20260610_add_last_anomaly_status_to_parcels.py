"""add last_anomaly_status to parcels

Revision ID: add_last_anomaly_status
Revises: add_meadow_croptype
Create Date: 2026-06-10

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "add_last_anomaly_status"
down_revision: Union[str, None] = "add_meadow_croptype"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "parcels",
        sa.Column(
            "last_anomaly_status",
            sa.String(30),
            nullable=True,
            comment="Most recent anomaly detection result (HEALTHY/ANOMALY_DETECTED/INSUFFICIENT_DATA).",
        ),
    )


def downgrade() -> None:
    op.drop_column("parcels", "last_anomaly_status")
