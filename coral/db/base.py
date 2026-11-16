"""Declarative base and isolated metadata for Coral tables."""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

CORAL_NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

coral_metadata = MetaData(naming_convention=CORAL_NAMING_CONVENTION)


class CoralBase(DeclarativeBase):
    """Declarative base for Coral tables with dedicated MetaData."""

    metadata = coral_metadata


__all__ = ["CORAL_NAMING_CONVENTION", "CoralBase", "coral_metadata"]
