"""Client list, search, and status changes."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.client import Client
from app.services.audit import audit

VALID_STATUSES = ("active", "paused", "archived")


class ClientStatusError(Exception):
    """Invalid status change."""


def search(db: Session, q: str = "", status: str = "") -> list[Client]:
    """Clients filtered by name substring and/or status."""
    stmt = select(Client).order_by(Client.name)
    q = q.strip()
    if q:
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        stmt = stmt.where(Client.name.ilike(f"%{escaped}%", escape="\\"))
    if status in VALID_STATUSES:
        stmt = stmt.where(Client.status == status)
    return list(db.scalars(stmt))


def set_status(db: Session, client: Client, status: str, reason: str, actor: str) -> Client:
    """Pause, resume, or archive a client, with an audit entry."""
    if status not in VALID_STATUSES:
        raise ClientStatusError(f"Unknown status: {status}")
    reason = reason.strip()[:255]
    if status == "paused" and not reason:
        raise ClientStatusError("Give a reason for pausing.")
    previous = client.status
    client.status = status
    client.pause_reason = reason if status == "paused" else None
    audit(db, actor=actor, action=f"client_{status}", entity_type="client", entity_id=client.id,
          client_id=client.id, reason=reason or f"{previous} -> {status}")
    db.commit()
    return client
