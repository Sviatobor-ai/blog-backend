import os
import sys
from pathlib import Path

os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_posts.db")

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import User  # noqa: E402

TOKENS = [
    "c2f1b8d2-8b6f-4c70-8a12-6a6b0d7e9a11",
    "f1a2c3d4-5e6f-7a89-b0c1-d2e3f4a5b6c7",
    "1b3d5f79-2468-4c8f-9e1a-0b2c4d6e8f10",
    "9a8b7c6d-5e4f-3a2b-1c0d-efab12345678",
    "0f9e8d7c-6b5a-4a39-8c27-1d0e2f3a4b5c",
]


client = TestClient(app)


def _ensure_admin_tokens() -> None:
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as session:
        for token in TOKENS:
            exists = session.query(User).filter(User.token == token).first()
            if not exists:
                session.add(User(token=token, profile_json={}, is_active=True))
        session.commit()
    engine.dispose()


def test_admin_login_page_returns_html() -> None:
    _ensure_admin_tokens()
    response = client.get("/admin")
    assert response.status_code == 200
    assert "Wiedza.joga.yoga — Admin Access" in response.text


def test_admin_login_invalid_redirects_back() -> None:
    _ensure_admin_tokens()
    response = client.post("/admin/login", data={"token": "invalid"}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/admin?error=invalid"


def test_admin_login_valid_redirects_to_dashboard() -> None:
    _ensure_admin_tokens()
    token = TOKENS[0]
    response = client.post("/admin/login", data={"token": token}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == f"/admin/dashboard?t={token}"


def test_admin_dashboard_requires_valid_token() -> None:
    _ensure_admin_tokens()
    response = client.get("/admin/dashboard")
    assert response.status_code == 401

    response_invalid = client.get("/admin/dashboard", params={"t": "invalid"})
    assert response_invalid.status_code == 401

    response_valid = client.get("/admin/dashboard", params={"t": TOKENS[1]})
    assert response_valid.status_code == 200
    assert "Welcome to the Auto-Generator Console" in response_valid.text


def teardown_module(module):
    engine.dispose()
