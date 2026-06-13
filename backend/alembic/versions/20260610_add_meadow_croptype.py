"""add meadow to croptype enum

Revision ID: add_meadow_croptype
Revises: cc0c9a545dc5
Create Date: 2026-06-10

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "add_meadow_croptype"
down_revision: Union[str, None] = "cc0c9a545dc5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE must run outside a transaction on some
    # PostgreSQL/driver combinations. autocommit_block() handles this correctly
    # for both psycopg2 and asyncpg.
    with op.get_context().autocommit_block():
        op.execute(sa.text("ALTER TYPE croptype ADD VALUE IF NOT EXISTS 'MEADOW'"))


def downgrade() -> None:
    # PostgreSQL cannot remove enum values without recreating the type.
    pass
