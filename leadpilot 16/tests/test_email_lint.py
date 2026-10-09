from app.services import email_lint as lint

CORPUS = "Opened a second location in Tampa in 2025. Fixed monthly price. 5-day month-end close. $299-$899 per month"
GOOD = ("Saw that you opened a second location in Tampa in 2025, which usually means two sets of books to reconcile each month. "
        "We run fixed-price bookkeeping with a 5-day month-end close for service businesses like yours. "
        "Would it be useful if I sent a one-paragraph outline of how that works? Just reply and I will.")
SUBJECTS = ["second location in tampa", "books after tampa?", "bookkeeping across two sites"]


def run(body=GOOD, subjects=SUBJECTS, ids=("F1",), require=True):
    return lint.lint(body, subjects, CORPUS, list(ids), {"F1"}, require_fact=require)


def test_clean_email_passes():
    assert run() == []


def test_flags_invented_number_and_spam_and_greeting():
    issues = run("Hi there! Act now, we guarantee 47% savings on everything for your business and team today and always.")
    text = " ".join(issues)
    assert "47" in text and "act now" in text and "greeting" in text.lower() and "exclamation" in text.lower()


def test_numbers_from_facts_are_allowed():
    assert not any("Number" in i for i in run())


def test_requires_known_fact_ids():
    assert any("at least one" in i for i in run(ids=()))
    assert any("unknown fact id" in i for i in run(ids=("F9",)))
    assert not any("at least one" in i for i in run(ids=(), require=False))


def test_link_limit_and_placeholders():
    assert any("link" in i for i in run(GOOD + " See https://a.com and https://b.com"))
    assert any("placeholders" in i for i in run(GOOD + " [Name]"))


def test_subject_rules():
    bad = ["RE: HELLO", "RE: HELLO", "x" * 70]
    text = " ".join(run(subjects=bad))
    assert "Deceptive subject prefix" in text and "ALL CAPS" in text and "too long" in text and "Duplicate" in text
    assert any("exactly 3" in i for i in run(subjects=["only one"]))


def test_length_limits():
    assert any("maximum" in i for i in run(" ".join(["word"] * 130)))
    assert any("too thin" in i for i in run("Short note."))
