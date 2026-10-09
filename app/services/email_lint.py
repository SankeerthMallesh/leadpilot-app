"""Deterministic email checks (instant, free, and stricter than any prompt).

Runs before the LLM self-check so obvious violations never cost a model call.
"""
import re

SPAM_PHRASES = (
    "act now", "limited time", "risk-free", "risk free", "100% free", "guarantee", "no obligation",
    "click here", "buy now", "make money", "earn $", "winner", "urgent", "once in a lifetime",
    "best price", "cash bonus", "double your", "special promotion", "order now", "free gift",
)
GENERIC_PHRASES = (
    "hope this email finds you well", "just checking in", "circling back", "touching base",
    "bumping this", "following up on my last", "following up on my previous", "i wanted to reach out",
    "synergy", "game-changer", "game changer", "revolutionary",
)
GREETINGS = ("hi ", "hi,", "hello", "dear ", "hey ")
LINK_RE = re.compile(r"(https?://|www\.)\S+", re.I)
NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
WORD_RE = re.compile(r"[\w'’-]+")

MAX_WORDS = 120
MAX_SUBJECT_CHARS = 60


def word_count(text: str) -> int:
    """Number of words in text."""
    return len(WORD_RE.findall(text))


def _norm_number(token: str) -> str:
    return token.replace(",", "").rstrip(".")


def lint(
    body: str,
    subjects: list[str],
    corpus: str,
    fact_ids: list[str],
    valid_fact_ids: set[str],
    *,
    require_fact: bool,
) -> list[str]:
    """Return a list of problems (empty means the email passes)."""
    issues: list[str] = []
    low = body.lower().strip()

    words = word_count(body)
    if words > MAX_WORDS:
        issues.append(f"Body is {words} words; maximum is {MAX_WORDS}.")
    if words < 25:
        issues.append(f"Body is only {words} words; too thin to be useful.")
    if len(LINK_RE.findall(body)) > 1:
        issues.append("More than one link; use at most one.")
    if body.count("!") > 0:
        issues.append("Remove exclamation marks.")
    if low.startswith(GREETINGS):
        issues.append("Remove the greeting; it is added automatically.")
    if re.search(r"\[[^\]]+\]|\{\{[^}]+\}\}", body):
        issues.append("Remove placeholders such as [Name] or {{...}}.")
    for phrase in SPAM_PHRASES:
        if phrase in low:
            issues.append(f'Spam-trigger phrase: "{phrase}".')
    for phrase in GENERIC_PHRASES:
        if phrase in low:
            issues.append(f'Generic or filler phrase: "{phrase}".')

    allowed = {_norm_number(n) for n in NUM_RE.findall(corpus)}
    for token in NUM_RE.findall(body):
        if _norm_number(token) not in allowed:
            issues.append(f'Number "{token}" is not supported by the facts, proof, price or CTA.')

    if require_fact and not fact_ids:
        issues.append("This email must cite at least one provided fact.")
    for fid in fact_ids:
        if fid not in valid_fact_ids:
            issues.append(f'Cites unknown fact id "{fid}".')

    if len(subjects) != 3:
        issues.append("Provide exactly 3 subject variants.")
    seen: set[str] = set()
    for s in subjects:
        sl = s.lower().strip()
        if sl in seen:
            issues.append(f'Duplicate subject variant: "{s}".')
        seen.add(sl)
        if len(s) > MAX_SUBJECT_CHARS:
            issues.append(f'Subject too long ({len(s)} chars): "{s}".')
        if sl.startswith(("re:", "fwd:", "fw:")):
            issues.append(f'Deceptive subject prefix: "{s}".')
        letters = [c for c in s if c.isalpha()]
        if len(letters) > 3 and s.upper() == s:
            issues.append(f'Subject is ALL CAPS: "{s}".')
        if "!" in s:
            issues.append(f'Remove "!" from subject: "{s}".')
        for phrase in SPAM_PHRASES:
            if phrase in sl:
                issues.append(f'Spam-trigger phrase in subject: "{phrase}".')
    return issues
