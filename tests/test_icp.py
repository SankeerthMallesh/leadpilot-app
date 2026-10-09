import json

import httpx
import pytest
import respx

from app.models.audit import ApiCost
from app.providers import llm
from app.schemas.icp import ICP
from app.schemas.intake import Intake
from app.services import icp as svc
from app.services import intake as intake_svc
from app.services.costs import BudgetExceeded, ensure_budget
from tests.conftest import VALID_INTAKE

GOOD_ICP = {
    "summary": "Owner-run real estate firms needing roofing partners.",
    "offer_summary": "Roof replacement packages",
    "industries": ["Real estate"],
    "company_size": {"min_employees": 5, "max_employees": 50},
    "job_titles": ["Owner"],
    "geography": {"countries": ["United States"], "states": ["Florida"], "cities": []},
}


def _reply(text: str) -> httpx.Response:
    return httpx.Response(200, json={
        "content": [{"type": "text", "text": text}],
        "usage": {"input_tokens": 1000, "output_tokens": 500},
    })


@pytest.fixture
def client(db):
    return intake_svc.create_client(db, Intake.model_validate(VALID_INTAKE), "admin")


def test_extract_json_handles_fences():
    assert llm.extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    with pytest.raises(llm.LLMError):
        llm.extract_json("no json here")


def test_icp_requires_industry_and_ordered_size():
    with pytest.raises(ValueError):
        ICP.model_validate({**GOOD_ICP, "industries": []})
    with pytest.raises(ValueError):
        ICP.model_validate({**GOOD_ICP, "company_size": {"min_employees": 50, "max_employees": 5}})


@respx.mock
def test_generate_icp_stores_draft_and_logs_cost(db, client):
    respx.post("https://api.anthropic.com/v1/messages").mock(return_value=_reply(json.dumps(GOOD_ICP)))
    row = svc.generate_icp(db, client, "admin")
    assert (row.version, row.status, row.prompt_version) == (1, "draft", "icp_v2")
    assert db.query(ApiCost).filter_by(client_id=client.id, operation="icp_generate").count() == 1


@respx.mock
def test_generate_icp_repairs_invalid_output_once(db, client):
    route = respx.post("https://api.anthropic.com/v1/messages")
    route.side_effect = [_reply('{"summary": "short"}'), _reply(json.dumps(GOOD_ICP))]
    assert svc.generate_icp(db, client, "admin").version == 1
    assert route.call_count == 2


@respx.mock
def test_generate_icp_gives_up_after_two_bad_outputs(db, client):
    respx.post("https://api.anthropic.com/v1/messages").mock(return_value=_reply("not json"))
    with pytest.raises(svc.ICPError):
        svc.generate_icp(db, client, "admin")
    assert svc.list_versions(db, client.id) == []


def test_approve_supersedes_previous_and_blocks_edits(db, client):
    from app.models.client import ClientICPVersion

    v1 = ClientICPVersion(client_id=client.id, version=1, icp_json=GOOD_ICP, status="draft")
    v2 = ClientICPVersion(client_id=client.id, version=2, icp_json=GOOD_ICP, status="draft")
    db.add_all([v1, v2])
    db.commit()
    svc.approve(db, v1, "admin")
    svc.approve(db, v2, "admin")
    db.refresh(v1)
    assert (v1.status, v2.status) == ("superseded", "approved")
    assert svc.get_approved(db, client.id).version == 2
    with pytest.raises(svc.ICPError):
        svc.update_draft(db, v2, json.dumps(GOOD_ICP), "admin")
    forked = svc.fork(db, v2, "admin")
    assert forked.version == 3 and forked.status == "draft"


def test_update_draft_validates(db, client):
    from app.models.client import ClientICPVersion

    row = ClientICPVersion(client_id=client.id, version=1, icp_json=GOOD_ICP, status="draft")
    db.add(row)
    db.commit()
    with pytest.raises(svc.ICPError):
        svc.update_draft(db, row, "{bad json", "admin")
    with pytest.raises(svc.ICPError):
        svc.update_draft(db, row, json.dumps({**GOOD_ICP, "industries": []}), "admin")
    svc.update_draft(db, row, json.dumps({**GOOD_ICP, "industries": ["Roofing"]}), "admin")
    assert row.icp_json["industries"] == ["Roofing"]


def test_version_lookup_is_scoped_by_client(db, client):
    from app.models.client import ClientICPVersion

    other = intake_svc.create_client(db, Intake.model_validate(VALID_INTAKE), "admin")
    db.add(ClientICPVersion(client_id=client.id, version=1, icp_json=GOOD_ICP, status="draft"))
    db.commit()
    assert svc.get_version(db, other.id, 1) is None


def test_budget_cap_blocks(db, client):
    from app.services.costs import log_cost

    log_cost(db, client_id=client.id, provider="anthropic", operation="x", units=1, unit="tokens",
             cost_usd=client.monthly_cost_cap_usd)
    db.commit()
    with pytest.raises(BudgetExceeded):
        ensure_budget(db, client)


@respx.mock
def test_generate_icp_uses_forced_tool_output(db, client):
    route = respx.post("https://api.anthropic.com/v1/messages").mock(return_value=httpx.Response(200, json={
        "content": [{"type": "tool_use", "id": "t1", "name": "submit_icp", "input": GOOD_ICP}],
        "usage": {"input_tokens": 100, "output_tokens": 50}}))
    row = svc.generate_icp(db, client, "admin")
    assert row.icp_json["industries"] == ["Real estate"]
    body = json.loads(route.calls.last.request.content)
    assert body["tool_choice"] == {"type": "tool", "name": "submit_icp"}
