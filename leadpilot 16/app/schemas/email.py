"""Schemas for grounded email generation and self-checking."""
from pydantic import BaseModel, Field


class ProspectFact(BaseModel):
    """One verifiable fact about a prospect. Emails may only rely on these."""

    id: str
    claim: str
    source_url: str = ""
    snippet: str = ""


class EmailOut(BaseModel):
    """One generated email (body only; greeting, signature and footer are added by code)."""

    subject_variants: list[str] = Field(min_length=3, max_length=3, description="Exactly 3 distinct subject lines")
    body: str = Field(min_length=20, description="Plain-text body, 45-110 words, no greeting or sign-off")
    fact_ids: list[str] = Field(description="IDs of the facts this email relies on")


class SequenceOut(BaseModel):
    """The full sequence, one email per schedule entry, in order."""

    emails: list[EmailOut] = Field(min_length=1)


class CheckItem(BaseModel):
    """Self-check scores for one email (1 = bad, 5 = excellent)."""

    step: int = Field(description="1-based position in the sequence")
    factual_accuracy: int = Field(ge=1, le=5)
    tone_match: int = Field(ge=1, le=5)
    spam_safety: int = Field(ge=1, le=5, description="5 = very unlikely to trigger spam filters")
    compliance: int = Field(ge=1, le=5, description="Truthful, non-deceptive, no implied relationship")
    issues: list[str] = Field(default=[], description="Specific, actionable problems; empty if none")


class SelfCheckOut(BaseModel):
    """Scores for every email."""

    checks: list[CheckItem]
