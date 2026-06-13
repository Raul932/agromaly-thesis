"""fix broken uix_users_email_lower functional index

The original init migration created the index via
``sa.text("lower(email)")`` which Alembic rendered as a quoted string
literal — ``lower('email')`` — instead of a reference to the ``email``
column. That produces a constant index key for every row, so the second
user ever inserted violates the unique constraint regardless of their
actual email ("email already registered" on any signup).

This migration drops the broken index and recreates it with raw DDL that
references the column correctly.

Revision ID: fix_users_email_lower_index
Revises: add_last_anomaly_status
Create Date: 2026-06-11

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "fix_users_email_lower_index"
down_revision: Union[str, None] = "add_last_anomaly_status"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uix_users_email_lower")
    op.execute(
        "CREATE UNIQUE INDEX uix_users_email_lower ON users (lower(email))"
    )


def downgrade() -> None:
    # Recreate the (broken) original form to keep the chain reversible.
    op.execute("DROP INDEX IF EXISTS uix_users_email_lower")
    op.execute(
        "CREATE UNIQUE INDEX uix_users_email_lower ON users (lower('email'))"
    )
