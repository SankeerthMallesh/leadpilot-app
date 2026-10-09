"""API cost logging and per-client monthly budget enforcement."""
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.audit import ApiCost
from app.models.client import Client


class BudgetExceeded(Exception):
    """The client's monthly cost cap has been reached."""


def log_cost(
    db: Session,
    *,
    client_id: int | None,
    provider: str,
    operation: str,
    units: float,
    unit: str,
    cost_usd: float,
    entity_type: str | None = None,
    entity_id: int | None = None,
) -> None:
    """Record one paid API call (caller commits)."""
    db.add(
        ApiCost(
            client_id=client_id, provider=provider, operation=operation, units=units,
            unit=unit, cost_usd=cost_usd, entity_type=entity_type, entity_id=entity_id,
        )
    )


def month_spend(db: Session, client_id: int) -> float:
    """USD spent by a client in the current UTC month."""
    now = datetime.now(UTC)
    start = datetime(now.year, now.month, 1, tzinfo=UTC)
    total = db.scalar(
        select(func.coalesce(func.sum(ApiCost.cost_usd), 0.0)).where(
            ApiCost.client_id == client_id, ApiCost.occurred_at >= start
        )
    )
    return float(total or 0.0)


def ensure_budget(db: Session, client: Client) -> None:
    """Raise BudgetExceeded when the monthly cap is reached."""
    spent = month_spend(db, client.id)
    if spent >= client.monthly_cost_cap_usd:
        raise BudgetExceeded(
            f"Monthly cost cap reached (${spent:.2f} of ${client.monthly_cost_cap_usd:.2f})"
        )
