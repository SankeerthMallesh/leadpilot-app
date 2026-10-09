"""Validated ICP JSON schema."""
from pydantic import BaseModel, Field, model_validator


class CompanySize(BaseModel):
    """Employee range."""

    min_employees: int | None = Field(default=None, ge=0)
    max_employees: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _ordered(self) -> "CompanySize":
        lo, hi = self.min_employees, self.max_employees
        if lo is not None and hi is not None and lo > hi:
            raise ValueError("min_employees must be <= max_employees")
        return self


class Geography(BaseModel):
    """Where targets are located."""

    countries: list[str] = []
    states: list[str] = []
    cities: list[str] = []


class Exclusions(BaseModel):
    """Things to never target."""

    competitors: list[str] = []
    industries: list[str] = []
    domains: list[str] = []
    existing_customers: list[str] = []


class ICP(BaseModel):
    """Ideal customer profile used by every later pipeline step."""

    summary: str = Field(min_length=10)
    offer_summary: str = Field(min_length=3)
    industries: list[str] = Field(min_length=1)
    company_size: CompanySize = CompanySize()
    job_titles: list[str] = Field(min_length=1)
    geography: Geography = Geography()
    tech_used: list[str] = []
    buying_signals: list[str] = []
    exclusions: Exclusions = Exclusions()
    value_propositions: list[str] = []
    proof_points: list[str] = []
    search_keywords: list[str] = []
    disqualifiers: list[str] = []
