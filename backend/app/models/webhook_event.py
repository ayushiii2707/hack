"""Processed webhook events – for provider-level idempotency.

The provider's own event id is the primary key, so a duplicate delivery is
rejected by the database, not by a check-then-act in Python.
"""
from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class WebhookEvent(Base, TimestampMixin):
    __tablename__ = "webhook_events"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)  # provider event id
    provider: Mapped[str] = mapped_column(String(24), default="razorpay", nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    result: Mapped[str] = mapped_column(String(256), default="", nullable=False)
