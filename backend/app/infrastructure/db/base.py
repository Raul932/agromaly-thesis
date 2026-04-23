"""
Shared SQLAlchemy Declarative Base & Model Registry
=====================================================
This module is the single point of truth for:
    1. The shared ``Base`` (DeclarativeBase) that all ORM models inherit from.
    2. Importing every ORM model so Alembic's ``target_metadata`` sees them.

CRITICAL for Alembic:
    ``alembic/env.py`` imports ``Base`` and ``metadata`` from THIS module.
    If you add a new ORM model, you MUST add its import here, otherwise
    Alembic will NOT detect it during ``alembic revision --autogenerate``.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Master declarative base — all ORM models inherit from this class.

    SQLAlchemy uses this to:
        - Register all mapped tables in ``Base.metadata``.
        - Generate CREATE TABLE / ALTER TABLE SQL via ``metadata.create_all()``.
        - Provide migration metadata to Alembic ``env.py``.
    """
    pass


