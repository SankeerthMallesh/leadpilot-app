import os
import re

os.environ["SECRET_KEY"] = "t" * 48
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["ANTHROPIC_API_KEY"] = "test-key"
os.environ["LLM_MAX_RETRIES"] = "1"
os.environ["LLM_RATE_PER_MINUTE"] = "600"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import ratelimit  # noqa: E402
from app.db import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base, User  # noqa: E402
from app.security import hash_password  # noqa: E402

PASSWORD = "correct-horse-battery"


@pytest.fixture(autouse=True)
def _schema():
    ratelimit.reset_all()
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture
def db():
    with SessionLocal() as session:
        yield session


@pytest.fixture
def admin(db):
    user = User(email="admin@example.com", password_hash=hash_password(PASSWORD))
    db.add(user)
    db.commit()
    return user


@pytest.fixture
def http():
    with TestClient(app, follow_redirects=False) as c:
        yield c


@pytest.fixture
def logged_in(http, admin):
    page = http.get("/login")
    token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
    r = http.post("/login", data={"email": admin.email, "password": PASSWORD, "csrf_token": token})
    assert r.status_code == 303
    return http


def page_token(http, path="/clients") -> str:
    html = http.get(path).text
    return re.search(r'name="csrf-token" content="([^"]+)"', html).group(1)


VALID_INTAKE = {
    "name": "Acme Roofing",
    "business_description": "Residential roofing repair and replacement.",
    "offer": "Roof replacement packages",
    "target_industries": ["Real estate"],
    "target_job_titles": ["Owner"],
    "sender_name": "Sam Rivera",
    "sender_title": "Owner",
    "postal_address": "1 Test Road, Jacksonville, FL 32202",
}
