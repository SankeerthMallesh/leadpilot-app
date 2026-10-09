"""Client intake: form/JSON/YAML parsing and persistence."""
import json
from collections.abc import Mapping

import yaml
from pydantic import ValidationError

from app.models.client import Client
from app.schemas.intake import FIELD_SPECS, LIST_FIELDS, Intake
from sqlalchemy.orm import Session

from app.services.audit import audit


class IntakeError(Exception):
    """Intake could not be parsed or validated."""

    def __init__(self, messages: list[str]) -> None:
        super().__init__("; ".join(messages))
        self.messages = messages


def _format_errors(exc: ValidationError) -> list[str]:
    return [f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()]


def parse_form(form: Mapping, getlist) -> Intake:  # noqa: ANN001
    """Build an Intake from submitted form data."""
    data: dict = {}
    for field, _label, kind, _help in FIELD_SPECS:
        if kind == "regions":
            data[field] = getlist(field)
        elif kind == "int":
            raw = str(form.get(field, "")).strip()
            if raw:
                data[field] = raw
        else:
            value = str(form.get(field, ""))
            data[field] = value if field in LIST_FIELDS else value.strip()
    try:
        return Intake.model_validate(data)
    except ValidationError as exc:
        raise IntakeError(_format_errors(exc)) from exc


def parse_import(raw: bytes, filename: str) -> list[Intake]:
    """Parse a JSON or YAML upload (one client or a list). Reports every bad item."""
    try:
        text = raw.decode("utf-8")
        loaded = yaml.safe_load(text) if filename.lower().endswith((".yml", ".yaml")) else json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError, yaml.YAMLError) as exc:
        raise IntakeError([f"Could not read file: {exc}"]) from exc
    items = loaded if isinstance(loaded, list) else [loaded]
    parsed: list[Intake] = []
    errors: list[str] = []
    for i, item in enumerate(items, start=1):
        try:
            parsed.append(Intake.model_validate(item))
        except ValidationError as exc:
            errors += [f"item {i}: {m}" for m in _format_errors(exc)]
    if errors:
        raise IntakeError(errors)
    return parsed


def apply_intake(client: Client, intake: Intake) -> None:
    """Copy intake values onto the client row (raw intake is kept as JSON)."""
    client.name = intake.name
    client.intake_json = intake.model_dump()
    client.sender_name = intake.sender_name
    client.sender_title = intake.sender_title
    client.postal_address = intake.postal_address
    client.tone = intake.tone
    client.cta_type = intake.cta_type
    client.cta_value = intake.cta_value
    client.allowed_regions_json = list(intake.allowed_regions)
    client.daily_send_cap = intake.daily_send_cap


def create_client(db: Session, intake: Intake, actor: str) -> Client:
    """Create a client workspace from intake."""
    client = Client(intake_json={}, sender_name="", sender_title="", postal_address="", tone="")
    apply_intake(client, intake)
    db.add(client)
    db.flush()
    audit(db, actor=actor, action="client_created", entity_type="client", entity_id=client.id,
          client_id=client.id, reason="intake submitted")
    db.commit()
    return client


def update_client(db: Session, client: Client, intake: Intake, actor: str) -> Client:
    """Update a client from edited intake."""
    apply_intake(client, intake)
    audit(db, actor=actor, action="client_updated", entity_type="client", entity_id=client.id,
          client_id=client.id, reason="intake edited")
    db.commit()
    return client
