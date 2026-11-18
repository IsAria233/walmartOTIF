"""Shared model column helpers."""
import uuid

from sqlalchemy import DateTime, Uuid, func
from sqlalchemy.orm import mapped_column


def uuid_pk():
    return mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)


def created_at():
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
