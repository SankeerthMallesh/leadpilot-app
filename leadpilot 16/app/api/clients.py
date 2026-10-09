"""Client intake, status, ICP generation, editing, and approval."""
import json

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.client import Client
from app.models.user import User
from app.providers import llm
from app.schemas.intake import form_sections
from app.security import require_admin, verify_csrf
from app.services import clients as client_service
from app.services import icp as icp_service
from app.services import intake as intake_service
from app.services.audit import recent
from app.services.costs import BudgetExceeded, month_spend
from app.web import flash, render

router = APIRouter(dependencies=[Depends(require_admin)])

MAX_UPLOAD_BYTES = 1_000_000


def _client_or_404(db: Session, client_id: int) -> Client:
    client = db.get(Client, client_id)
    if client is None:
        raise HTTPException(404, "Client not found")
    return client


def _icp_or_404(db: Session, client_id: int, version: int):  # noqa: ANN202
    row = icp_service.get_version(db, client_id, version)
    if row is None:
        raise HTTPException(404, "ICP version not found")
    return row


@router.get("/clients")
def client_list(request: Request, q: str = "", status: str = "", db: Session = Depends(get_db)):  # noqa: ANN201
    """List clients with search and status filter."""
    clients = client_service.search(db, q, status)
    approved = {c.id: icp_service.get_approved(db, c.id) is not None for c in clients}
    return render(request, "clients/list.html", clients=clients, approved=approved, q=q, status=status,
                  statuses=client_service.VALID_STATUSES)


@router.get("/clients/new")
def client_new(request: Request):  # noqa: ANN201
    """Blank intake form."""
    return render(request, "clients/form.html", sections=form_sections(), values={}, errors=[], target=None)


@router.post("/clients", dependencies=[Depends(verify_csrf)])
async def client_create(request: Request, db: Session = Depends(get_db),
                        user: User = Depends(require_admin)):  # noqa: ANN201
    """Create a client from the intake form."""
    form = await request.form()
    try:
        intake = intake_service.parse_form(form, form.getlist)
    except intake_service.IntakeError as exc:
        return render(request, "clients/form.html", status_code=422, sections=form_sections(),
                      values=dict(form), errors=exc.messages, target=None)
    client = intake_service.create_client(db, intake, user.email)
    flash(request, "Client created. Generate the ICP next.")
    return RedirectResponse(f"/clients/{client.id}", status_code=303)


@router.post("/clients/import", dependencies=[Depends(verify_csrf)])
async def client_import(request: Request, db: Session = Depends(get_db),
                        user: User = Depends(require_admin)):  # noqa: ANN201
    """Import one or many clients from a JSON or YAML file."""
    form = await request.form()
    upload = form.get("file")
    if not isinstance(upload, UploadFile) or not upload.filename:
        flash(request, "Choose a .json or .yaml file.", "err")
        return RedirectResponse("/clients", status_code=303)
    raw = await upload.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        flash(request, "File too large (1 MB max).", "err")
        return RedirectResponse("/clients", status_code=303)
    try:
        items = intake_service.parse_import(raw, upload.filename)
    except intake_service.IntakeError as exc:
        flash(request, "Import failed, nothing was created: " + " | ".join(exc.messages[:6]), "err")
        return RedirectResponse("/clients", status_code=303)
    for item in items:
        intake_service.create_client(db, item, user.email)
    flash(request, f"Imported {len(items)} client(s).")
    return RedirectResponse("/clients", status_code=303)


@router.get("/clients/{client_id}")
def client_detail(request: Request, client_id: int, db: Session = Depends(get_db)):  # noqa: ANN201
    """Client overview: progress, ICP versions, activity."""
    client = _client_or_404(db, client_id)
    versions = icp_service.list_versions(db, client.id)
    return render(
        request, "clients/detail.html", client=client, versions=versions,
        has_draft=bool(versions), has_approved=any(v.status == "approved" for v in versions),
        spend=month_spend(db, client.id), activity=recent(db, client_id=client.id, limit=10),
    )


@router.post("/clients/{client_id}/status", dependencies=[Depends(verify_csrf)])
async def client_status(request: Request, client_id: int, db: Session = Depends(get_db),
                        user: User = Depends(require_admin)):  # noqa: ANN201
    """Pause, resume, or archive a client."""
    client = _client_or_404(db, client_id)
    form = await request.form()
    try:
        client_service.set_status(db, client, str(form.get("status", "")), str(form.get("reason", "")), user.email)
    except client_service.ClientStatusError as exc:
        flash(request, str(exc), "err")
    else:
        flash(request, f"Client is now {client.status}.")
    return RedirectResponse(f"/clients/{client.id}", status_code=303)


@router.get("/clients/{client_id}/edit")
def client_edit(request: Request, client_id: int, db: Session = Depends(get_db)):  # noqa: ANN201
    """Edit intake."""
    client = _client_or_404(db, client_id)
    values = dict(client.intake_json)
    for key, val in list(values.items()):
        if isinstance(val, list) and key != "allowed_regions":
            values[key] = "\n".join(val)
    return render(request, "clients/form.html", client=client, sections=form_sections(),
                  values=values, errors=[], target=client)


@router.post("/clients/{client_id}/edit", dependencies=[Depends(verify_csrf)])
async def client_update(request: Request, client_id: int, db: Session = Depends(get_db),
                        user: User = Depends(require_admin)):  # noqa: ANN201
    """Save edited intake."""
    client = _client_or_404(db, client_id)
    form = await request.form()
    try:
        intake = intake_service.parse_form(form, form.getlist)
    except intake_service.IntakeError as exc:
        return render(request, "clients/form.html", status_code=422, client=client,
                      sections=form_sections(), values=dict(form), errors=exc.messages, target=client)
    intake_service.update_client(db, client, intake, user.email)
    flash(request, "Intake saved. Regenerate the ICP if the targeting changed.")
    return RedirectResponse(f"/clients/{client.id}", status_code=303)


@router.post("/clients/{client_id}/icp/generate", dependencies=[Depends(verify_csrf)])
def icp_generate(request: Request, client_id: int, db: Session = Depends(get_db),
                 user: User = Depends(require_admin)):  # noqa: ANN201
    """Generate a new draft ICP with Claude."""
    client = _client_or_404(db, client_id)
    try:
        row = icp_service.generate_icp(db, client, user.email)
    except llm.LLMNotConfigured:
        flash(request, "Set ANTHROPIC_API_KEY in .env to generate ICPs.", "err")
        return RedirectResponse(f"/clients/{client.id}", status_code=303)
    except (llm.LLMError, icp_service.ICPError, BudgetExceeded) as exc:
        flash(request, str(exc), "err")
        return RedirectResponse(f"/clients/{client.id}", status_code=303)
    flash(request, f"Draft ICP v{row.version} created. Review it, edit if needed, then approve.")
    return RedirectResponse(f"/clients/{client.id}/icp/{row.version}", status_code=303)


@router.get("/clients/{client_id}/icp/{version}")
def icp_view(request: Request, client_id: int, version: int, db: Session = Depends(get_db)):  # noqa: ANN201
    """View or edit one ICP version."""
    client = _client_or_404(db, client_id)
    row = _icp_or_404(db, client_id, version)
    return render(request, "clients/icp.html", client=client, icp=row, d=row.icp_json,
                  icp_text=json.dumps(row.icp_json, indent=2), error=None)


@router.post("/clients/{client_id}/icp/{version}/save", dependencies=[Depends(verify_csrf)])
async def icp_save(request: Request, client_id: int, version: int, db: Session = Depends(get_db),
                   user: User = Depends(require_admin)):  # noqa: ANN201
    """Save edits to a draft."""
    client = _client_or_404(db, client_id)
    row = _icp_or_404(db, client_id, version)
    form = await request.form()
    text = str(form.get("icp_json", ""))
    try:
        icp_service.update_draft(db, row, text, user.email)
    except icp_service.ICPError as exc:
        return render(request, "clients/icp.html", status_code=422, client=client, icp=row,
                      d=row.icp_json, icp_text=text, error=str(exc), open_editor=True)
    flash(request, "Draft saved.")
    return RedirectResponse(f"/clients/{client_id}/icp/{version}", status_code=303)


@router.post("/clients/{client_id}/icp/{version}/approve", dependencies=[Depends(verify_csrf)])
def icp_approve(request: Request, client_id: int, version: int, db: Session = Depends(get_db),
                user: User = Depends(require_admin)):  # noqa: ANN201
    """Approve a draft so later steps can use it."""
    _client_or_404(db, client_id)
    row = _icp_or_404(db, client_id, version)
    try:
        icp_service.approve(db, row, user.email)
    except icp_service.ICPError as exc:
        flash(request, str(exc), "err")
    else:
        flash(request, f"ICP v{version} approved. It is now the version every later step uses.")
    return RedirectResponse(f"/clients/{client_id}", status_code=303)


@router.post("/clients/{client_id}/icp/{version}/fork", dependencies=[Depends(verify_csrf)])
def icp_fork(request: Request, client_id: int, version: int, db: Session = Depends(get_db),
             user: User = Depends(require_admin)):  # noqa: ANN201
    """Copy a version into a new editable draft."""
    _client_or_404(db, client_id)
    row = _icp_or_404(db, client_id, version)
    new = icp_service.fork(db, row, user.email)
    flash(request, f"Created editable draft v{new.version}.")
    return RedirectResponse(f"/clients/{client_id}/icp/{new.version}", status_code=303)
