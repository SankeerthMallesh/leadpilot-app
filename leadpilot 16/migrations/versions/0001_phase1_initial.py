"""Phase 1: users, clients, ICP versions, audit log, API costs, assistant messages.

Revision ID: 0001
Revises:
"""
import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def _ts() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("totp_secret_enc", sa.String(255)),
        sa.Column("is_active", sa.Boolean, nullable=False),
        sa.Column("failed_logins", sa.Integer, nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True)),
        *_ts(),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "clients",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("pause_reason", sa.String(255)),
        sa.Column("intake_json", sa.JSON, nullable=False),
        sa.Column("sender_name", sa.String(120), nullable=False),
        sa.Column("sender_title", sa.String(120), nullable=False),
        sa.Column("postal_address", sa.Text, nullable=False),
        sa.Column("tone", sa.String(255), nullable=False),
        sa.Column("cta_type", sa.String(20), nullable=False),
        sa.Column("cta_value", sa.String(500), nullable=False),
        sa.Column("allowed_regions_json", sa.JSON, nullable=False),
        sa.Column("daily_send_cap", sa.Integer, nullable=False),
        sa.Column("monthly_cost_cap_usd", sa.Float, nullable=False),
        sa.Column("sequence_config_json", sa.JSON, nullable=False),
        sa.Column("allow_role_accounts", sa.Boolean, nullable=False),
        sa.Column("allow_risky", sa.Boolean, nullable=False),
        sa.Column("risky_daily_cap", sa.Integer, nullable=False),
        sa.Column("client_can_approve_emails", sa.Boolean, nullable=False),
        sa.Column("auto_send_after_n", sa.Integer),
        *_ts(),
    )
    op.create_index("ix_clients_status", "clients", ["status"])

    op.create_table(
        "client_icp_versions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("client_id", sa.Integer, sa.ForeignKey("clients.id"), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("icp_json", sa.JSON, nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("approved_by", sa.String(255)),
        sa.Column("prompt_version", sa.String(50)),
        sa.Column("model", sa.String(80)),
        *_ts(),
        sa.UniqueConstraint("client_id", "version", name="uq_icp_client_version"),
    )
    op.create_index("ix_icp_client_id", "client_icp_versions", ["client_id"])
    op.create_index("ix_icp_status", "client_icp_versions", ["status"])

    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("client_id", sa.Integer, sa.ForeignKey("clients.id")),
        sa.Column("actor", sa.String(255), nullable=False),
        sa.Column("action", sa.String(60), nullable=False),
        sa.Column("entity_type", sa.String(60), nullable=False),
        sa.Column("entity_id", sa.Integer),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("detail_json", sa.JSON),
        *_ts(),
    )
    op.create_index("ix_audit_log_client_id", "audit_log", ["client_id"])
    op.create_index("ix_audit_log_action", "audit_log", ["action"])
    op.create_index("ix_audit_entity", "audit_log", ["entity_type", "entity_id"])

    op.create_table(
        "api_costs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("client_id", sa.Integer, sa.ForeignKey("clients.id")),
        sa.Column("provider", sa.String(60), nullable=False),
        sa.Column("operation", sa.String(80), nullable=False),
        sa.Column("units", sa.Float, nullable=False),
        sa.Column("unit", sa.String(30), nullable=False),
        sa.Column("cost_usd", sa.Float, nullable=False),
        sa.Column("entity_type", sa.String(60)),
        sa.Column("entity_id", sa.Integer),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        *_ts(),
    )
    op.create_index("ix_costs_client_time", "api_costs", ["client_id", "occurred_at"])

    op.create_table(
        "assistant_messages",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("client_id", sa.Integer, sa.ForeignKey("clients.id")),
        sa.Column("role", sa.String(12), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("page_path", sa.String(255)),
        *_ts(),
    )
    op.create_index("ix_assistant_scope", "assistant_messages", ["user_id", "client_id"])


def downgrade() -> None:
    for table in ("assistant_messages", "api_costs", "audit_log", "client_icp_versions", "clients", "users"):
        op.drop_table(table)
