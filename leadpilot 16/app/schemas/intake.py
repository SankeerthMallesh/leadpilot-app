"""Client intake schema and form field specs."""
from typing import Literal

from pydantic import BaseModel, Field, field_validator

Region = Literal["US", "CA", "UK", "EU"]

LIST_FIELDS = (
    "unique_selling_points", "proof", "target_industries", "target_job_titles",
    "target_geography", "tech_used", "buying_signals", "exclude_competitors",
    "exclude_industries", "exclude_existing_customers", "exclude_domains",
)


class Intake(BaseModel):
    """Raw client intake (form or JSON/YAML import)."""

    name: str = Field(min_length=2, max_length=120)
    business_description: str = Field(min_length=10)
    offer: str = Field(min_length=3)
    price_range: str = ""
    unique_selling_points: list[str] = []
    proof: list[str] = []
    target_industries: list[str] = Field(min_length=1)
    target_company_size: str = ""
    target_job_titles: list[str] = Field(min_length=1)
    target_geography: list[str] = []
    tech_used: list[str] = []
    buying_signals: list[str] = []
    exclude_competitors: list[str] = []
    exclude_industries: list[str] = []
    exclude_existing_customers: list[str] = []
    exclude_domains: list[str] = []
    tone: str = "friendly and direct, no jargon"
    sender_name: str = Field(min_length=2, max_length=120)
    sender_title: str = Field(min_length=2, max_length=120)
    cta_type: Literal["reply", "link", "other"] = "reply"
    cta_value: str = ""
    postal_address: str = Field(min_length=10)
    allowed_regions: list[Region] = ["US"]
    daily_send_cap: int = Field(default=30, ge=1, le=200)

    @field_validator(*LIST_FIELDS, mode="before")
    @classmethod
    def _split_lines(cls, v: object) -> object:
        if isinstance(v, str):
            return [line.strip() for line in v.splitlines() if line.strip()]
        return v

    @field_validator("exclude_domains")
    @classmethod
    def _norm_domains(cls, v: list[str]) -> list[str]:
        return [d.strip().lower().removeprefix("www.") for d in v if d.strip()]


# (field, label, kind, help)  kinds: text | textarea | lines | int | select | regions
FIELD_SPECS: list[tuple[str, str, str, str]] = [
    ("name", "Client name", "text", ""),
    ("business_description", "Business description", "textarea", "What the business does."),
    ("offer", "Offer", "textarea", "What they sell."),
    ("price_range", "Price range", "text", ""),
    ("unique_selling_points", "Unique selling points", "lines", "One per line."),
    ("proof", "Proof (case studies, testimonials)", "lines", "One per line. Real results only."),
    ("target_industries", "Target industries", "lines", "One per line."),
    ("target_company_size", "Target company size", "text", "e.g. 5-50 employees"),
    ("target_job_titles", "Target job titles", "lines", "One per line."),
    ("target_geography", "Target geography", "lines", "Cities, states, countries. One per line."),
    ("tech_used", "Technology used (optional)", "lines", ""),
    ("buying_signals", "Buying signals (optional)", "lines", ""),
    ("exclude_competitors", "Exclude: competitors", "lines", ""),
    ("exclude_industries", "Exclude: industries", "lines", ""),
    ("exclude_existing_customers", "Exclude: existing customers", "lines", ""),
    ("exclude_domains", "Exclude: domains", "lines", "example.com, one per line."),
    ("tone", "Tone of voice", "text", ""),
    ("sender_name", "Sender name", "text", "Must be the real person sending."),
    ("sender_title", "Sender title", "text", ""),
    ("cta_type", "Call to action type", "select", "reply|link|other"),
    ("cta_value", "Call to action value", "text", "Booking link or wording."),
    ("postal_address", "Physical postal address (email footer)", "textarea", "Required by CAN-SPAM."),
    ("allowed_regions", "Regions allowed to be emailed", "regions", "Not legal advice; see README."),
    ("daily_send_cap", "Daily send cap", "int", ""),
]


SECTIONS: list[tuple[str, str, list[str]]] = [
    ("Business", "What the client does and sells.",
     ["name", "business_description", "offer", "price_range", "unique_selling_points", "proof"]),
    ("Who to target", "Used to build the ICP.",
     ["target_industries", "target_company_size", "target_job_titles", "target_geography",
      "tech_used", "buying_signals"]),
    ("Exclusions", "Never contact these.",
     ["exclude_competitors", "exclude_industries", "exclude_existing_customers", "exclude_domains"]),
    ("Sending identity", "Shown in every email. Must be real.",
     ["sender_name", "sender_title", "tone", "cta_type", "cta_value", "postal_address"]),
    ("Compliance and limits", "Regions are off until you enable them.",
     ["allowed_regions", "daily_send_cap"]),
]


def form_sections() -> list[tuple[str, str, list[tuple[str, str, str, str]]]]:
    """Intake form fields grouped into sections for rendering."""
    by_name = {spec[0]: spec for spec in FIELD_SPECS}
    return [(title, blurb, [by_name[n] for n in names]) for title, blurb, names in SECTIONS]
