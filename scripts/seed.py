"""Load the demo client with an approved ICP (no API key needed)."""
from sqlalchemy import select

from app.db import SessionLocal
from app.models.client import Client, ClientICPVersion
from app.schemas.icp import ICP
from app.schemas.intake import Intake
from app.services import icp as icp_service
from app.services import intake as intake_service

DEMO_INTAKE = Intake(
    name="Northwind Bookkeeping (DEMO)",
    business_description="Monthly bookkeeping and tax-ready books for small service businesses in Florida.",
    offer="Fixed-price monthly bookkeeping with a 5-day month-end close.",
    price_range="$299-$899 per month",
    unique_selling_points=["Fixed monthly price", "5-day month-end close"],
    proof=["PLACEHOLDER: replace with a real, verifiable result"],
    target_industries=["Home services", "Landscaping", "Cleaning companies"],
    target_company_size="5-50 employees",
    target_job_titles=["Owner", "Founder", "Operations Manager"],
    target_geography=["Florida, United States"],
    tone="friendly and direct, no jargon",
    sender_name="Alex Demo",
    sender_title="Founder",
    cta_type="reply",
    postal_address="PLACEHOLDER: 123 Example St, Jacksonville, FL 32202, USA",
    allowed_regions=["US"],
    daily_send_cap=20,
)

DEMO_ICP = ICP(
    summary="Owner-operated Florida home-service businesses with 5-50 staff that need reliable monthly books.",
    offer_summary="Fixed-price monthly bookkeeping with a 5-day close.",
    industries=["Home services", "Landscaping", "Cleaning companies"],
    company_size={"min_employees": 5, "max_employees": 50},
    job_titles=["Owner", "Founder", "Operations Manager"],
    geography={"countries": ["United States"], "states": ["Florida"], "cities": []},
    search_keywords=["landscaping company Florida", "cleaning services Jacksonville", "home services contractor Florida"],
    disqualifiers=["no website", "national franchise head office"],
)


def main() -> None:
    with SessionLocal() as db:
        if db.scalar(select(Client).where(Client.name == DEMO_INTAKE.name)):
            print("Demo client already exists.")
            return
        client = intake_service.create_client(db, DEMO_INTAKE, "seed")
        row = ClientICPVersion(client_id=client.id, version=1, icp_json=DEMO_ICP.model_dump(),
                               status="draft", prompt_version="seed")
        db.add(row)
        db.commit()
        icp_service.approve(db, row, "seed")
        print(f"Seeded client #{client.id} with approved ICP v1.")


if __name__ == "__main__":
    main()
