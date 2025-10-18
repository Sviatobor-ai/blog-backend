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
from app.dependencies import get_supadata_client  # noqa: E402
from app.integrations.supadata import SDVideo  # noqa: E402
from app.models import GenerationJob, User  # noqa: E402

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


def test_admin_search_filters_videos_by_duration() -> None:
    _ensure_admin_tokens()

    class StubSupaData:
        def search_youtube(self, **_: object) -> list[SDVideo]:
            return [
                SDVideo(
                    video_id="valid",
                    url="https://www.youtube.com/watch?v=valid",
                    title="Valid",
                    channel="Channel",
                    duration_seconds=900,
                    published_at="2024-01-01T00:00:00Z",
                    description_snippet="desc",
                    has_transcript=True,
                ),
                SDVideo(
                    video_id="short",
                    url="https://www.youtube.com/watch?v=short",
                    title="Too short",
                    channel="Channel",
                    duration_seconds=30,
                    published_at=None,
                    description_snippet=None,
                    has_transcript=None,
                ),
                SDVideo(
                    video_id="long",
                    url="https://www.youtube.com/watch?v=long",
                    title="Too long",
                    channel="Channel",
                    duration_seconds=20000,
                    published_at=None,
                    description_snippet=None,
                    has_transcript=False,
                ),
            ]

    stub = StubSupaData()
    app.dependency_overrides[get_supadata_client] = lambda: stub

    response = client.post(
        "/admin/search",
        headers={"X-Admin-Token": TOKENS[0]},
        json={
            "query": "test",
            "limit": 10,
            "min_duration_seconds": 60,
            "max_duration_seconds": 1200,
            "region": "PL",
            "language": "any",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["items"]) == 1
    assert payload["items"][0]["video_id"] == "valid"
    assert payload["items"][0]["has_transcript"] is True

    app.dependency_overrides.pop(get_supadata_client, None)


def test_queue_plan_creates_generation_jobs() -> None:
    _ensure_admin_tokens()
    app.dependency_overrides.pop(get_supadata_client, None)
    with SessionLocal() as session:
        session.query(GenerationJob).delete()
        session.commit()

    response = client.post(
        "/admin/queue/plan",
        headers={"X-Admin-Token": TOKENS[0]},
        json={
            "video_urls": [
                "https://www.youtube.com/watch?v=abc",
                "https://www.youtube.com/watch?v=def",
            ]
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["queued"] == 2
    assert len(body["job_ids"]) == 2

    with SessionLocal() as session:
        jobs = session.query(GenerationJob).order_by(GenerationJob.id).all()
        assert len(jobs) == 2
        assert all(job.status == "pending" for job in jobs)


def teardown_module(module):
    app.dependency_overrides.clear()
    engine.dispose()
