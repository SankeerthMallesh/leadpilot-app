"""Grounded email-sequence generation: one generation call, deterministic lint, LLM self-check,
and at most one rewrite. Greeting, signature and compliance footer are added by code, so they
can never be forgotten or hallucinated."""
import json
import re
from dataclasses import dataclass, field

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.client import Client, ClientICPVersion
from app.providers import llm
from app.schemas.email import CheckItem, ProspectFact, SelfCheckOut, SequenceOut
from app.services import email_lint
from app.services.audit import audit
from app.services.costs import ensure_budget, log_cost
from app.services.icp import load_prompt

UNSUBSCRIBE_TOKEN = "{{unsubscribe_url}}"
MAX_FACTS = 15
MAX_FACT_CHARS = 400
GENERATE_PROMPT = "draft_sequence_v1"
CHECK_PROMPT = "selfcheck_v1"

SEQUENCE_TOOL = llm.tool_for("submit_sequence", "Submit the email sequence.", SequenceOut)
CHECK_TOOL = llm.tool_for("submit_checks", "Submit the review scores.", SelfCheckOut)


class DraftError(Exception):
    """Generation could not produce a usable sequence."""


@dataclass
class Prospect:
    """Who the sequence is for."""

    company: str
    contact_first_name: str = ""
    contact_title: str = ""
    website: str = ""


@dataclass
class EmailResult:
    """One finished email with its quality verdict."""

    step: int
    offset_days: int
    subjects: list[str]
    body: str
    full_text: str
    fact_ids: list[str]
    words: int
    lint_issues: list[str]
    check: CheckItem | None
    status: str  # "ready" or "needs_human"


@dataclass
class SequenceResult:
    """The whole sequence plus how it was produced."""

    emails: list[EmailResult]
    status: str
    llm_calls: int
    cost_usd: float
    rewritten: bool
    notes: list[str] = field(default_factory=list)


def parse_facts(text: str) -> list[ProspectFact]:
    """Parse lines of 'fact text | optional source url' into numbered facts (F1, F2, ...)."""
    facts: list[ProspectFact] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        claim, _, url = line.partition("|")
        claim, url = claim.strip()[:MAX_FACT_CHARS], url.strip()
        if claim:
            facts.append(ProspectFact(id=f"F{len(facts) + 1}", claim=claim, source_url=url, snippet=claim))
    if len(facts) > MAX_FACTS:
        raise DraftError(f"Use at most {MAX_FACTS} facts.")
    return facts


def _offsets(client: Client) -> list[int]:
    steps = (client.sequence_config_json or {}).get("steps") or [{"offset_days": 0}]
    return [int(s.get("offset_days", 0)) for s in steps]


def _corpus(client: Client, prospect: Prospect, facts: list[ProspectFact]) -> str:
    intake = client.intake_json
    parts = [intake.get("offer", ""), intake.get("price_range", ""), intake.get("business_description", ""),
             client.cta_value, prospect.company, prospect.contact_title]
    parts += intake.get("proof", []) + intake.get("unique_selling_points", [])
    parts += [f.claim + " " + f.snippet for f in facts]
    return " ".join(parts)


def _brief(client: Client, icp: dict, prospect: Prospect, facts: list[ProspectFact], offsets: list[int]) -> dict:
    intake = client.intake_json
    return {
        "client": {
            "company": client.name, "offer": intake.get("offer"), "description": intake.get("business_description"),
            "price_range": intake.get("price_range"), "unique_selling_points": intake.get("unique_selling_points"),
            "proof": intake.get("proof"), "tone": client.tone,
            "cta": {"type": client.cta_type, "value": client.cta_value}, "sender_name": client.sender_name,
        },
        "icp": {k: icp.get(k) for k in ("summary", "value_propositions", "job_titles")},
        "prospect": {"company": prospect.company, "contact_title": prospect.contact_title,
                     "website": prospect.website},
        "facts": [f.model_dump() for f in facts],
        "schedule": [{"email": i + 1, "send_on_day": d} for i, d in enumerate(offsets)],
    }


def assemble_full_text(client: Client, first_name: str, body: str) -> str:
    """Greeting + body + signature + compliance footer (identifies the message as promotional)."""
    greeting = f"Hi {first_name.strip()}," if first_name.strip() else "Hello,"
    return (
        f"{greeting}\n\n{body.strip()}\n\n{client.sender_name}\n{client.sender_title}, {client.name}\n\n"
        f"--\n{client.name} | {client.postal_address.strip()}\n"
        f"This is a promotional message. Unsubscribe: {UNSUBSCRIBE_TOKEN}"
    )


def _tool_call(db: Session, client: Client, operation: str, system: str, payload: dict, tool: dict,
               model: str | None = None, max_tokens: int = 3000) -> tuple[dict, llm.LLMResult]:
    result = llm.complete(system=system, messages=[{"role": "user", "content": json.dumps(payload)}],
                          model=model, max_tokens=max_tokens, tool=tool)
    log_cost(db, client_id=client.id, provider=llm.active_provider(), operation=operation,
             units=result.input_tokens + result.output_tokens + result.cache_read_tokens,
             unit="tokens", cost_usd=result.cost_usd, entity_type="client", entity_id=client.id)
    data = result.tool_input if result.tool_input is not None else llm.extract_json(result.text)
    return data, result


def _generate(db: Session, client: Client, operation: str, payload: dict, expected: int) -> tuple[SequenceOut, float]:
    system = load_prompt(GENERATE_PROMPT)
    cost = 0.0
    error = ""
    for _attempt in range(2):
        data, result = _tool_call(db, client, operation, system, payload, SEQUENCE_TOOL)
        cost += result.cost_usd
        try:
            seq = SequenceOut.model_validate(data)
        except ValidationError as exc:
            error = str(exc)[:300]
            payload = {**payload, "validation_error": error}
            continue
        if len(seq.emails) == expected:
            return seq, cost
        error = f"Expected {expected} emails, got {len(seq.emails)}."
        payload = {**payload, "validation_error": error}
    db.commit()
    raise DraftError(f"The model returned an unusable sequence: {error}")


def _check_ok(item: CheckItem | None) -> bool:
    return bool(item and item.factual_accuracy >= 4 and item.compliance >= 4
                and item.spam_safety >= 4 and item.tone_match >= 3)


def _self_check(db: Session, client: Client, seq: SequenceOut, facts: list[ProspectFact]) -> tuple[dict[int, CheckItem], float]:
    s = get_settings()
    payload = {
        "client_rules": {"tone": client.tone, "cta": {"type": client.cta_type, "value": client.cta_value},
                         "offer": client.intake_json.get("offer"), "proof": client.intake_json.get("proof"),
                         "price_range": client.intake_json.get("price_range")},
        "facts": [f.model_dump() for f in facts],
        "emails": [{"step": i + 1, "subjects": e.subject_variants, "body": e.body, "fact_ids": e.fact_ids}
                   for i, e in enumerate(seq.emails)],
    }
    data, result = _tool_call(db, client, "email_selfcheck", load_prompt(CHECK_PROMPT), payload, CHECK_TOOL,
                              model=s.selfcheck_model or None, max_tokens=1500)
    try:
        checks = SelfCheckOut.model_validate(data).checks
    except ValidationError as exc:
        raise DraftError(f"The self-check returned unusable output: {str(exc)[:200]}") from exc
    return {c.step: c for c in checks}, result.cost_usd


def _lint_all(seq: SequenceOut, corpus: str, facts: list[ProspectFact]) -> list[list[str]]:
    valid = {f.id for f in facts}
    return [email_lint.lint(e.body, e.subject_variants, corpus, e.fact_ids, valid, require_fact=(i == 0))
            for i, e in enumerate(seq.emails)]


def generate_sequence(db: Session, client: Client, icp_row: ClientICPVersion, prospect: Prospect,
                      facts: list[ProspectFact], actor: str) -> SequenceResult:
    """Produce a lint-clean, self-checked sequence for one prospect (2 model calls typical, 4 worst case)."""
    if icp_row.status != "approved":
        raise DraftError("The ICP must be approved before generating emails.")
    if not facts:
        raise DraftError("Add at least one verified fact about the prospect.")
    ensure_budget(db, client)
    offsets = _offsets(client)
    corpus = _corpus(client, prospect, facts)
    brief = _brief(client, icp_row.icp_json, prospect, facts, offsets)

    seq, cost = _generate(db, client, "email_generate", {"brief": brief}, len(offsets))
    calls = 1
    lint = _lint_all(seq, corpus, facts)
    checks: dict[int, CheckItem] = {}
    if not any(lint):
        checks, c = _self_check(db, client, seq, facts)
        cost += c
        calls += 1

    problems = [
        {"email": i + 1, "problems": lint[i] + (checks[i + 1].issues if (i + 1) in checks and not _check_ok(checks[i + 1]) else [])}
        for i in range(len(seq.emails))
        if lint[i] or ((i + 1) in checks and not _check_ok(checks[i + 1]))
    ]
    rewritten = False
    if problems:
        rewritten = True
        payload = {"brief": brief, "previous_output": seq.model_dump(), "problems_to_fix": problems,
                   "instruction": "Rewrite only what is needed to fix every listed problem. Keep what already works."}
        seq, c = _generate(db, client, "email_rewrite", payload, len(offsets))
        cost += c
        calls += 1
        lint = _lint_all(seq, corpus, facts)
        checks = {}
        if not any(lint):
            checks, c = _self_check(db, client, seq, facts)
            cost += c
            calls += 1

    results: list[EmailResult] = []
    for i, email in enumerate(seq.emails):
        item = checks.get(i + 1)
        ready = not lint[i] and _check_ok(item)
        results.append(EmailResult(
            step=i + 1, offset_days=offsets[i], subjects=email.subject_variants, body=email.body.strip(),
            full_text=assemble_full_text(client, prospect.contact_first_name, email.body),
            fact_ids=email.fact_ids, words=email_lint.word_count(email.body), lint_issues=lint[i],
            check=item, status="ready" if ready else "needs_human",
        ))
    status = "ready" if all(r.status == "ready" for r in results) else "needs_human"
    audit(db, actor=actor, action="studio_generated", entity_type="client", entity_id=client.id,
          client_id=client.id, reason=f"{prospect.company}: {status}, {calls} calls, rewritten={rewritten}",
          detail={"prompt": GENERATE_PROMPT, "check_prompt": CHECK_PROMPT, "fact_count": len(facts)})
    db.commit()
    notes = ["Rewritten once to fix problems."] if rewritten else []
    return SequenceResult(results, status, calls, round(cost, 4), rewritten, notes)


FIRST_NAME_RE = re.compile(r"[^\w' -]")


def clean_name(value: str) -> str:
    """Keep a first name safe to place in a greeting."""
    return FIRST_NAME_RE.sub("", value).strip()[:40]
