import json

import pytest

from app.schemas.intake import Intake
from app.services import intake as svc
from tests.conftest import VALID_INTAKE


def test_form_lines_split_and_domains_normalized():
    form = dict(VALID_INTAKE)
    form["target_industries"] = "Real estate\nProperty management\n"
    form["exclude_domains"] = "WWW.Example.com\n"
    form["daily_send_cap"] = "25"

    class F(dict):
        def getlist(self, key):
            return ["US"] if key == "allowed_regions" else []

    f = F({k: (v if isinstance(v, str) else "\n".join(v)) for k, v in form.items()})
    intake = svc.parse_form(f, f.getlist)
    assert intake.target_industries == ["Real estate", "Property management"]
    assert intake.exclude_domains == ["example.com"]
    assert intake.daily_send_cap == 25
    assert intake.allowed_regions == ["US"]


def test_form_missing_required_reports_errors():
    class F(dict):
        def getlist(self, key):
            return []

    with pytest.raises(svc.IntakeError) as e:
        svc.parse_form(F(name="x"), F().getlist)
    assert any("business_description" in m for m in e.value.messages)


def test_import_json_list_and_yaml():
    items = svc.parse_import(json.dumps([VALID_INTAKE, VALID_INTAKE]).encode(), "c.json")
    assert len(items) == 2
    yaml_text = "name: Acme Roofing\nbusiness_description: Residential roofing repair.\noffer: Roofs\n" \
                "target_industries: [Real estate]\ntarget_job_titles: [Owner]\nsender_name: Sam Rivera\n" \
                "sender_title: Owner\npostal_address: 1 Test Road, Jacksonville, FL\n"
    assert svc.parse_import(yaml_text.encode(), "c.yaml")[0].name == "Acme Roofing"


def test_import_bad_item_creates_nothing_and_lists_errors():
    bad = dict(VALID_INTAKE, sender_name="")
    with pytest.raises(svc.IntakeError) as e:
        svc.parse_import(json.dumps([VALID_INTAKE, bad]).encode(), "c.json")
    assert any(m.startswith("item 2") for m in e.value.messages)


def test_invalid_region_rejected():
    with pytest.raises(ValueError):
        Intake.model_validate(dict(VALID_INTAKE, allowed_regions=["MARS"]))


def test_create_client_copies_fields(db):
    client = svc.create_client(db, Intake.model_validate(VALID_INTAKE), "admin@example.com")
    assert client.sender_name == "Sam Rivera"
    assert client.allowed_regions_json == ["US"]
    assert client.intake_json["offer"] == "Roof replacement packages"
