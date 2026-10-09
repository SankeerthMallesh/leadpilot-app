"""Email Studio: generate grounded, self-checked outreach for one prospect."""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.client import Client
from app.models.user import User
from app.providers import llm
from app.security import require_admin, verify_csrf
from app.services import drafting
from app.services import icp as icp_service
from app.services.costs import BudgetExceeded
from app.web import render, templates

router = APIRouter(dependencies=[Depends(require_admin)])


def _client_or_404(db: Session, client_id: int) -> Client:
    client = db.get(Client, client_id)
    if client is None:
        raise HTTPException(404, "Client not found")
    return client


@router.get("/clients/{client_id}/studio")
def studio(request: Request, client_id: int, db: Session = Depends(get_db)):  # noqa: ANN201
    """Studio form (needs an approved ICP)."""
    client = _client_or_404(db, client_id)
    return render(request, "studio.html", client=client, approved=icp_service.get_approved(db, client.id))


@router.post("/clients/{client_id}/studio/generate", dependencies=[Depends(verify_csrf)])
async def studio_generate(request: Request, client_id: int, db: Session = Depends(get_db),
                          user: User = Depends(require_admin)):  # noqa: ANN201
    """Generate a sequence and return the result partial (HTMX)."""
    client = _client_or_404(db, client_id)
    form = await request.form()
    company = str(form.get("company", "")).strip()[:120]

    def show(**ctx):  # noqa: ANN202
        return templates.TemplateResponse(request, "partials/studio_result.html", ctx)

    if not company:
        return show(error="Enter the prospect's company name.")
    approved = icp_service.get_approved(db, client.id)
    if approved is None:
        return show(error="Approve an ICP for this client first.")
    try:
        facts = drafting.parse_facts(str(form.get("facts", "")))
        prospect = drafting.Prospect(
            company=company, contact_first_name=drafting.clean_name(str(form.get("first_name", ""))),
            contact_title=str(form.get("title", "")).strip()[:120], website=str(form.get("website", "")).strip()[:200])
        result = drafting.generate_sequence(db, client, approved, prospect, facts, user.email)
    except llm.LLMNotConfigured:
        return show(error="Set ANTHROPIC_API_KEY in .env to generate emails.")
    except (drafting.DraftError, llm.LLMError, BudgetExceeded) as exc:
        return show(error=str(exc))
    return show(res=result, facts=facts)
