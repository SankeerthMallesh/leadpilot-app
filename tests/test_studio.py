import httpx
import respx

from app.models.client import ClientICPVersion
from app.schemas.intake import Intake
from app.services import intake as intake_svc
from tests.conftest import VALID_INTAKE, page_token
from tests.test_drafting import B1, B2, B3, checks, seq, tool_reply

URL = "https://api.anthropic.com/v1/messages"


def _client(db, approved=True):
    c = intake_svc.create_client(db, Intake.model_validate(VALID_INTAKE), "admin")
    if approved:
        db.add(ClientICPVersion(client_id=c.id, version=1, icp_json={"summary": "s"}, status="approved"))
        db.commit()
    return c


def test_studio_page_needs_approved_icp(logged_in, db):
    c = _client(db, approved=False)
    assert "no approved ICP" in logged_in.get(f"/clients/{c.id}/studio").text


@respx.mock
def test_generate_renders_emails(logged_in, db):
    c = _client(db)
    route = respx.post(URL)
    route.side_effect = [tool_reply(seq(B1, B2, B3)), tool_reply(checks())]
    token = page_token(logged_in)
    r = logged_in.post(f"/clients/{c.id}/studio/generate", headers={"X-CSRF-Token": token}, data={
        "company": "Gulf Coast Homes", "first_name": "Sam",
        "facts": "Opened a second location in Tampa in 2025 | https://example.com"})
    assert r.status_code == 200 and "Email 1" in r.text and "all ready" in r.text and "Hi Sam," in r.text


def test_generate_validates_input_and_csrf(logged_in, db):
    c = _client(db)
    token = page_token(logged_in)
    assert logged_in.post(f"/clients/{c.id}/studio/generate", data={"company": "X"}).status_code == 403
    r = logged_in.post(f"/clients/{c.id}/studio/generate", headers={"X-CSRF-Token": token}, data={"company": ""})
    assert "company name" in r.text
    r = logged_in.post(f"/clients/{c.id}/studio/generate", headers={"X-CSRF-Token": token},
                       data={"company": "X", "facts": ""})
    assert "at least one" in r.text
