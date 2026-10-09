"""Audit log writer."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit import AuditLog


def audit(
    db: Session,
    *,
    actor: str,
    action: str,
    entity_type: str,
    entity_id: int | None = None,
    reason: str = "",
    client_id: int | None = None,
    detail: dict | None = None,
) -> None:
    """Add an audit row (caller commits)."""
    db.add(
        AuditLog(
            client_id=client_id, actor=actor, action=action, entity_type=entity_type,
            entity_id=entity_id, reason=reason, detail_json=detail,
        )
    )


def recent(db: Session, client_id: int | None = None, limit: int = 10) -> list[AuditLog]:
    """Most recent audit rows, optionally for one client."""
    stmt = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)
    if client_id is not None:
        stmt = stmt.where(AuditLog.client_id == client_id)
    return list(db.scalars(stmt))
