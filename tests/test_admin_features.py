import httpx
import respx

from app.models.audit import AuditLog
from app.models.client import ClientICPVersion
from app.schemas.intake import Intake
from app.services import clients as client_svc
from app.services import intake as intake_svc
from app.services import reporting
from app.services.costs import log_cost
from tests.conftest import VALID_INTAKE, page_token


def _client(db, **over):
    return intake_svc.create_client(db, Intake.model_validate({**VALID_INTAKE, **over}), "admin")


def test_pages_render(logged_in):
    for path, text in [("/", "Dashboard"), ("/clients", "Clients"), ("/costs", "By client"),
                       ("/system", "Prompt files"), ("/clients/new", "Sending identity")]:
        r = logged_in.get(path)
        assert r.status_code == 200 and text in r.text, path


def test_system_page_never_shows_api_key(logged_in):
    assert "test-key" not in logged_in.get("/system").text


def test_pause_requires_reason_then_resume(logged_in, db):
    client = _client(db)
    token = page_token(logged_in)
    r = logged_in.post(f"/clients/{client.id}/status", data={"status": "paused", "reason": "", "csrf_token": token})
    assert r.status_code == 303
    assert "reason" in logged_in.get(f"/clients/{client.id}").text.lower()
    db.refresh(client)
    assert client.status == "active"

    logged_in.post(f"/clients/{client.id}/status",
                   data={"status": "paused", "reason": "bounce spike", "csrf_token": token})
    db.refresh(client)
    assert (client.status, client.pause_reason) == ("paused", "bounce spike")
    assert "bounce spike" in logged_in.get(f"/clients/{client.id}").text

    logged_in.post(f"/clients/{client.id}/status", data={"status": "active", "reason": "", "csrf_token": token})
    db.refresh(client)
    assert client.status == "active" and client.pause_reason is None
    actions = {a.action for a in db.query(AuditLog).filter_by(client_id=client.id)}
    assert {"client_paused", "client_active"} <= actions


def test_invalid_status_rejected(db):
    import pytest
    client = _client(db)
    with pytest.raises(client_svc.ClientStatusError):
        client_svc.set_status(db, client, "deleted", "", "admin")


def test_search_filters_and_escapes_wildcards(db):
    _client(db, name="Acme Roofing")
    _client(db, name="Beta Plumbing")
    assert [c.name for c in client_svc.search(db, "acme")] == ["Acme Roofing"]
    assert client_svc.search(db, "%") == []
    assert len(client_svc.search(db, "")) == 2


def test_unknown_page_shows_html_404_and_json_for_api(logged_in):
    html = logged_in.get("/clients/9999", headers={"accept": "text/html"})
    assert html.status_code == 404 and "Page not found" in html.text
    js = logged_in.get("/clients/9999", headers={"accept": "application/json"})
    assert js.status_code == 404 and js.json()["detail"]


def test_health_endpoints_and_headers(http):
    assert http.get("/healthz").json() == {"status": "ok"}
    r = http.get("/readyz")
    assert r.status_code == 200 and r.json() == {"status": "ready"}
    assert r.headers["x-request-id"] and r.headers["x-frame-options"] == "DENY"


def test_dashboard_counts_and_costs(db):
    a = _client(db, name="A client")
    b = _client(db, name="B client")
    db.add(ClientICPVersion(client_id=a.id, version=1, icp_json={}, status="approved"))
    client_svc.set_status(db, b, "paused", "testing", "admin")
    log_cost(db, client_id=a.id, provider="anthropic", operation="icp_generate", units=1500,
             unit="tokens", cost_usd=0.5)
    log_cost(db, client_id=None, provider="anthropic", operation="assistant_chat", units=100,
             unit="tokens", cost_usd=0.1)
    db.commit()
    d = reporting.dashboard(db)
    assert (d["active"], d["paused"], d["awaiting_icp"]) == (1, 1, 1)
    assert round(d["spend"], 2) == 0.6
    c = reporting.costs_overview(db)
    assert round(c["total"], 2) == 0.6 and round(c["general"], 2) == 0.1
    assert c["by_operation"][0]["operation"] == "icp_generate"
    assert {r["name"]: round(r["spent"], 2) for r in c["per_client"]} == {"A client": 0.5, "B client": 0.0}


@respx.mock
def test_chat_rate_limit_returns_friendly_bubble(logged_in):
    respx.post("https://api.anthropic.com/v1/messages").mock(return_value=httpx.Response(
        200, json={"content": [{"type": "text", "text": "ok"}], "usage": {"input_tokens": 1, "output_tokens": 1}}))
    token = page_token(logged_in)
    last = None
    for _ in range(21):
        last = logged_in.post("/assistant/chat", data={"message": "hi", "client_id": "", "page_path": "/"},
                              headers={"X-CSRF-Token": token})
    assert last.status_code == 200 and "sending messages quickly" in last.text


@respx.mock
def test_assistant_reply_renders_markdown_safely(logged_in):
    respx.post("https://api.anthropic.com/v1/messages").mock(return_value=httpx.Response(
        200, json={"content": [{"type": "text", "text": "**Do this**\n\n- one\n- <script>x</script>"}],
                   "usage": {"input_tokens": 1, "output_tokens": 1}}))
    token = page_token(logged_in)
    r = logged_in.post("/assistant/chat", data={"message": "tips", "client_id": "", "page_path": "/"},
                       headers={"X-CSRF-Token": token})
    assert "<strong>Do this</strong>" in r.text and "<script>" not in r.text
