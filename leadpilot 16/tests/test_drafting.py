import json

import httpx
import pytest
import respx

from app.models.audit import ApiCost
from app.models.client import ClientICPVersion
from app.schemas.intake import Intake
from app.services import drafting
from app.services import intake as intake_svc
from tests.conftest import VALID_INTAKE

URL = "https://api.anthropic.com/v1/messages"
SUBJECTS = ["second tampa location", "who handles the roofing?", "roof quotes for two sites"]
B1 = ("Saw that Gulf Coast Homes opened a second location in Tampa in 2025, which usually means more roofs to inspect before storm season. "
      "We handle roof replacement packages for property managers and keep timelines predictable. "
      "Would it help if I shared how we scope a replacement in one short reply?")
B2 = ("Different angle: property managers often lose weeks waiting on roofing quotes. Our packages come with a fixed scope up front, "
      "so you can budget before you commit. Is quote timing something you track at the Tampa site?")
B3 = ("Last note from me. If a roof replacement is on the horizon for either location, I can send a short checklist that makes "
      "quotes easy to compare. Happy to leave it there if the timing is wrong.")
BAD = "Act now! We guarantee savings on every roof you will ever need for your business."


def seq(*bodies):
    return {"emails": [{"subject_variants": SUBJECTS, "body": b, "fact_ids": ["F1"]} for b in bodies]}


def tool_reply(payload):
    return httpx.Response(200, json={"content": [{"type": "tool_use", "id": "t", "name": "x", "input": payload}],
                                     "usage": {"input_tokens": 100, "output_tokens": 100}})


def checks(accuracy=5):
    return {"checks": [{"step": i, "factual_accuracy": accuracy, "tone_match": 5, "spam_safety": 5,
                        "compliance": 5, "issues": [] if accuracy >= 4 else ["Unsupported claim"]} for i in (1, 2, 3)]}


@pytest.fixture
def setup(db):
    client = intake_svc.create_client(db, Intake.model_validate(VALID_INTAKE), "admin")
    icp = ClientICPVersion(client_id=client.id, version=1, icp_json={"summary": "s"}, status="approved")
    db.add(icp)
    db.commit()
    facts = drafting.parse_facts("Opened a second location in Tampa in 2025 | https://example.com/news")
    return client, icp, facts, drafting.Prospect(company="Gulf Coast Homes", contact_first_name="Sam")


def run(db, setup):
    client, icp, facts, prospect = setup
    return drafting.generate_sequence(db, client, icp, prospect, facts, "admin")


def test_parse_facts_numbers_and_sources():
    facts = drafting.parse_facts("one | https://a.com\n\ntwo")
    assert [(f.id, f.source_url) for f in facts] == [("F1", "https://a.com"), ("F2", "")]
    with pytest.raises(drafting.DraftError):
        drafting.parse_facts("\n".join(f"fact {i}" for i in range(20)))


@respx.mock
def test_happy_path_two_calls_and_footer(db, setup):
    route = respx.post(URL)
    route.side_effect = [tool_reply(seq(B1, B2, B3)), tool_reply(checks())]
    res = run(db, setup)
    assert (res.status, res.llm_calls, res.rewritten) == ("ready", 2, False)
    first = res.emails[0]
    assert first.full_text.startswith("Hi Sam,") and "1 Test Road" in first.full_text
    assert "Unsubscribe: {{unsubscribe_url}}" in first.full_text and "promotional" in first.full_text
    assert [e.offset_days for e in res.emails] == [0, 3, 7]
    ops = {c.operation for c in db.query(ApiCost)}
    assert {"email_generate", "email_selfcheck"} <= ops
    assert json.loads(route.calls[0].request.content)["tool_choice"]["name"] == "submit_sequence"


@respx.mock
def test_lint_failure_skips_check_and_rewrites_once(db, setup):
    route = respx.post(URL)
    route.side_effect = [tool_reply(seq(BAD, B2, B3)), tool_reply(seq(B1, B2, B3)), tool_reply(checks())]
    res = run(db, setup)
    assert (res.status, res.llm_calls, res.rewritten) == ("ready", 3, True)
    rewrite_payload = json.loads(route.calls[1].request.content)["messages"][0]["content"]
    assert "problems_to_fix" in rewrite_payload and "act now" in rewrite_payload


@respx.mock
def test_persistent_lint_failure_goes_to_human(db, setup):
    route = respx.post(URL)
    route.side_effect = [tool_reply(seq(BAD, B2, B3)), tool_reply(seq(BAD, B2, B3))]
    res = run(db, setup)
    assert res.status == "needs_human" and res.llm_calls == 2
    assert res.emails[0].status == "needs_human" and res.emails[0].lint_issues
    assert res.emails[1].status == "needs_human"  # no check ran, so nothing is marked ready


@respx.mock
def test_failed_self_check_triggers_rewrite_then_passes(db, setup):
    route = respx.post(URL)
    route.side_effect = [tool_reply(seq(B1, B2, B3)), tool_reply(checks(accuracy=2)),
                         tool_reply(seq(B1, B2, B3)), tool_reply(checks())]
    res = run(db, setup)
    assert (res.status, res.llm_calls, res.rewritten) == ("ready", 4, True)


@respx.mock
def test_wrong_email_count_is_rejected(db, setup):
    respx.post(URL).mock(return_value=tool_reply(seq(B1)))
    with pytest.raises(drafting.DraftError):
        run(db, setup)


def test_requires_approved_icp_and_facts(db, setup):
    client, icp, facts, prospect = setup
    icp.status = "draft"
    with pytest.raises(drafting.DraftError):
        drafting.generate_sequence(db, client, icp, prospect, facts, "admin")
    icp.status = "approved"
    with pytest.raises(drafting.DraftError):
        drafting.generate_sequence(db, client, icp, prospect, [], "admin")
