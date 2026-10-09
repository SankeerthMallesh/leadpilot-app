"""Clients and versioned ICPs."""
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

DEFAULT_SEQUENCE = {"steps": [{"offset_days": 0}, {"offset_days": 3}, {"offset_days": 7}]}


class Client(Base, TimestampMixin):
    """An isolated client workspace."""

    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    pause_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    intake_json: Mapped[dict] = mapped_column(JSON)
    sender_name: Mapped[str] = mapped_column(String(120))
    sender_title: Mapped[str] = mapped_column(String(120))
    postal_address: Mapped[str] = mapped_column(Text)
    tone: Mapped[str] = mapped_column(String(255))
    cta_type: Mapped[str] = mapped_column(String(20), default="reply")
    cta_value: Mapped[str] = mapped_column(String(500), default="")
    allowed_regions_json: Mapped[list] = mapped_column(JSON, default=lambda: ["US"])
    daily_send_cap: Mapped[int] = mapped_column(Integer, default=30)
    monthly_cost_cap_usd: Mapped[float] = mapped_column(Float, default=40.0)
    sequence_config_json: Mapped[dict] = mapped_column(JSON, default=lambda: DEFAULT_SEQUENCE)
    allow_role_accounts: Mapped[bool] = mapped_column(Boolean, default=False)
    allow_risky: Mapped[bool] = mapped_column(Boolean, default=False)
    risky_daily_cap: Mapped[int] = mapped_column(Integer, default=10)
    client_can_approve_emails: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_send_after_n: Mapped[int | None] = mapped_column(Integer, nullable=True)


class ClientICPVersion(Base, TimestampMixin):
    """A versioned ideal-customer-profile. Later steps read the approved version only."""

    __tablename__ = "client_icp_versions"
    __table_args__ = (UniqueConstraint("client_id", "version", name="uq_icp_client_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    icp_json: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    model: Mapped[str | None] = mapped_column(String(80), nullable=True)
