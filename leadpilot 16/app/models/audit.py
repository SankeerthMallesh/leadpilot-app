"""Audit log, API cost log, and assistant chat history."""
from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, utcnow


class AuditLog(Base, TimestampMixin):
    """Why something happened (scored, approved, blocked, ...)."""

    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_entity", "entity_type", "entity_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id"), index=True, nullable=True)
    actor: Mapped[str] = mapped_column(String(255))
    action: Mapped[str] = mapped_column(String(60), index=True)
    entity_type: Mapped[str] = mapped_column(String(60))
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    detail_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class ApiCost(Base, TimestampMixin):
    """One row per paid API call."""

    __tablename__ = "api_costs"
    __table_args__ = (Index("ix_costs_client_time", "client_id", "occurred_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id"), nullable=True)
    provider: Mapped[str] = mapped_column(String(60))
    operation: Mapped[str] = mapped_column(String(80))
    units: Mapped[float] = mapped_column(Float, default=0)
    unit: Mapped[str] = mapped_column(String(30), default="tokens")
    cost_usd: Mapped[float] = mapped_column(Float, default=0)
    entity_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AssistantMessage(Base, TimestampMixin):
    """Chat history for the AI panel, scoped per admin and per client."""

    __tablename__ = "assistant_messages"
    __table_args__ = (Index("ix_assistant_scope", "user_id", "client_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id"), nullable=True)
    role: Mapped[str] = mapped_column(String(12))
    content: Mapped[str] = mapped_column(Text)
    page_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
