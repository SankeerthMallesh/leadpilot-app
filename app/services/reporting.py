"""Dashboard and cost reporting queries."""
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.audit import ApiCost
from app.models.client import Client, ClientICPVersion
from app.services.audit import recent


def month_start() -> datetime:
    now = datetime.now(UTC)
    return datetime(now.year, now.month, 1, tzinfo=UTC)


def dashboard(db: Session) -> dict:
    """Headline numbers for the home page."""
    start = month_start()
    approved_exists = (
        select(ClientICPVersion.id)
        .where(ClientICPVersion.client_id == Client.id, ClientICPVersion.status == "approved")
        .exists()
    )
    count = lambda *conds: int(db.scalar(select(func.count()).select_from(Client).where(*conds)) or 0)  # noqa: E731
    spend = float(db.scalar(select(func.coalesce(func.sum(ApiCost.cost_usd), 0.0))
                            .where(ApiCost.occurred_at >= start)) or 0.0)
    budget = get_settings().monthly_budget_usd
    return {
        "active": count(Client.status == "active"),
        "paused": count(Client.status == "paused"),
        "awaiting_icp": count(Client.status != "archived", ~approved_exists),
        "spend": spend,
        "budget": budget,
        "spend_pct": min(100.0, spend / budget * 100) if budget else 0.0,
        "activity": recent(db, limit=8),
    }


def costs_overview(db: Session) -> dict:
    """This month's spend per client and per operation."""
    start = month_start()
    spent = {
        cid: float(total or 0.0)
        for cid, total in db.execute(
            select(ApiCost.client_id, func.sum(ApiCost.cost_usd))
            .where(ApiCost.occurred_at >= start).group_by(ApiCost.client_id)
        )
    }
    per_client = []
    for client in db.scalars(select(Client).order_by(Client.name)):
        amount = spent.pop(client.id, 0.0)
        cap = client.monthly_cost_cap_usd
        per_client.append({"name": client.name, "id": client.id, "spent": amount, "cap": cap,
                           "pct": min(100.0, amount / cap * 100) if cap else 0.0})
    general = spent.pop(None, 0.0)
    by_operation = [
        {"provider": prov, "operation": op, "calls": calls, "units": float(units or 0), "cost": float(cost or 0)}
        for prov, op, calls, units, cost in db.execute(
            select(ApiCost.provider, ApiCost.operation, func.count(), func.sum(ApiCost.units),
                   func.sum(ApiCost.cost_usd))
            .where(ApiCost.occurred_at >= start)
            .group_by(ApiCost.provider, ApiCost.operation)
            .order_by(func.sum(ApiCost.cost_usd).desc())
        )
    ]
    total = sum(r["spent"] for r in per_client) + general
    budget = get_settings().monthly_budget_usd
    return {"per_client": per_client, "general": general, "by_operation": by_operation, "total": total,
            "budget": budget, "pct": min(100.0, total / budget * 100) if budget else 0.0}
