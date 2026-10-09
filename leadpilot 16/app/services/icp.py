"""ICP generation, editing, versioning, and approval."""
import json
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.client import Client, ClientICPVersion
from app.providers import llm
from app.schemas.icp import ICP
from app.services.audit import audit
from app.services.costs import ensure_budget, log_cost

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"
ICP_PROMPT = "icp_v2"
ICP_TOOL = llm.tool_for("submit_icp", "Submit the structured ideal customer profile.", ICP)


class ICPError(Exception):
    """Invalid ICP operation or content."""


def load_prompt(name: str) -> str:
    """Read an editable prompt file from /prompts."""
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")


def _next_version(db: Session, client_id: int) -> int:
    current = db.scalar(
        select(func.max(ClientICPVersion.version)).where(ClientICPVersion.client_id == client_id)
    )
    return (current or 0) + 1


def list_versions(db: Session, client_id: int) -> list[ClientICPVersion]:
    """All ICP versions for a client, newest first."""
    return list(
        db.scalars(
            select(ClientICPVersion)
            .where(ClientICPVersion.client_id == client_id)
            .order_by(ClientICPVersion.version.desc())
        )
    )


def get_version(db: Session, client_id: int, version: int) -> ClientICPVersion | None:
    """Fetch one version, always scoped by client_id."""
    return db.scalar(
        select(ClientICPVersion).where(
            ClientICPVersion.client_id == client_id, ClientICPVersion.version == version
        )
    )


def get_approved(db: Session, client_id: int) -> ClientICPVersion | None:
    """The approved ICP that every later step must read."""
    return db.scalar(
        select(ClientICPVersion).where(
            ClientICPVersion.client_id == client_id, ClientICPVersion.status == "approved"
        )
    )


def generate_icp(db: Session, client: Client, actor: str) -> ClientICPVersion:
    """Ask Claude to build an ICP from the intake; store it as a new draft version."""
    ensure_budget(db, client)
    system = load_prompt(ICP_PROMPT)
    user_msg = "Client intake JSON:\n" + json.dumps(client.intake_json, indent=2)
    messages = [{"role": "user", "content": user_msg}]
    icp: ICP | None = None
    result: llm.LLMResult | None = None
    error = ""
    for _attempt in range(2):
        result = llm.complete(system=system, messages=messages, max_tokens=2500, tool=ICP_TOOL)
        log_cost(
            db, client_id=client.id, provider=llm.active_provider(), operation="icp_generate",
            units=result.input_tokens + result.output_tokens, unit="tokens",
            cost_usd=result.cost_usd, entity_type="client", entity_id=client.id,
        )
        try:
            data = result.tool_input if result.tool_input is not None else llm.extract_json(result.text)
            icp = ICP.model_validate(data)
            break
        except (llm.LLMError, ValidationError) as exc:
            error = str(exc)[:500]
            messages = messages + [
                {"role": "assistant", "content": result.text},
                {"role": "user", "content": f"That output was invalid: {error}\nReturn corrected JSON only."},
            ]
    if icp is None or result is None:
        db.commit()  # keep the cost rows
        raise ICPError(f"Could not produce a valid ICP: {error}")
    row = ClientICPVersion(
        client_id=client.id, version=_next_version(db, client.id), icp_json=icp.model_dump(),
        status="draft", prompt_version=ICP_PROMPT, model=result.model,
    )
    db.add(row)
    db.flush()
    audit(db, actor=actor, action="icp_generated", entity_type="icp", entity_id=row.id,
          client_id=client.id, reason=f"draft v{row.version} from {ICP_PROMPT}")
    db.commit()
    return row


def update_draft(db: Session, row: ClientICPVersion, raw_json: str, actor: str) -> ClientICPVersion:
    """Validate and save edits to a draft ICP."""
    if row.status != "draft":
        raise ICPError("Only draft versions can be edited. Create an editable copy first.")
    try:
        icp = ICP.model_validate(json.loads(raw_json))
    except json.JSONDecodeError as exc:
        raise ICPError(f"Not valid JSON: {exc}") from exc
    except ValidationError as exc:
        first = exc.errors()[0]
        raise ICPError(f"Invalid ICP at {'.'.join(map(str, first['loc']))}: {first['msg']}") from exc
    row.icp_json = icp.model_dump()
    audit(db, actor=actor, action="icp_edited", entity_type="icp", entity_id=row.id,
          client_id=row.client_id, reason=f"draft v{row.version} edited")
    db.commit()
    return row


def approve(db: Session, row: ClientICPVersion, actor: str) -> ClientICPVersion:
    """Approve a draft and supersede the previously approved version."""
    if row.status != "draft":
        raise ICPError("Only draft versions can be approved.")
    previous = get_approved(db, row.client_id)
    if previous:
        previous.status = "superseded"
    row.status = "approved"
    row.approved_at = datetime.now(UTC)
    row.approved_by = actor
    audit(db, actor=actor, action="icp_approved", entity_type="icp", entity_id=row.id,
          client_id=row.client_id, reason=f"v{row.version} approved")
    db.commit()
    return row


def fork(db: Session, row: ClientICPVersion, actor: str) -> ClientICPVersion:
    """Copy any version into a new editable draft."""
    new = ClientICPVersion(
        client_id=row.client_id, version=_next_version(db, row.client_id),
        icp_json=dict(row.icp_json), status="draft", prompt_version=row.prompt_version, model=row.model,
    )
    db.add(new)
    db.flush()
    audit(db, actor=actor, action="icp_forked", entity_type="icp", entity_id=new.id,
          client_id=row.client_id, reason=f"draft v{new.version} copied from v{row.version}")
    db.commit()
    return new
