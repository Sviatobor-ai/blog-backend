import os
import sys
from pathlib import Path

os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_posts.db")
os.environ.setdefault("SUPADATA_KEY", "test-key")

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.dependencies import get_supadata_client  # noqa: E402
from app.integrations.supadata import SDVideo  # noqa: E402
from app.models import GenJob, User  # noqa: E402
from app.services.runner import get_runner  # noqa: E402

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
    assert "Admin Access" in response.text


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


def test_admin_search_forwards_filters_and_maps_results() -> None:
    _ensure_admin_tokens()

    class StubSupaData:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def search_youtube(
            self,
            *,
            query: str,
            limit: int,
            type_: str,
            duration: str,
            features: list[str],
        ) -> list[SDVideo]:
            self.calls.append(
                {
                    "query": query,
                    "limit": limit,
                    "type_": type_,
                    "duration": duration,
                    "features": features,
                }
            )
            return [
                SDVideo(
                    video_id="valid",
                    url="https://www.youtube.com/watch?v=valid",
                    title="Valid",
                    channel="Channel",
                    duration_seconds=900,
                    published_at="2024-01-01T00:00:00Z",
                    description_snippet="desc",
                ),
                SDVideo(
                    video_id="secondary",
                    url="https://www.youtube.com/watch?v=secondary",
                    title="Secondary",
                    channel="Other",
                    duration_seconds=None,
                    published_at=None,
                    description_snippet=None,
                ),
            ]

    stub = StubSupaData()
    app.dependency_overrides[get_supadata_client] = lambda: stub

    response = client.post(
        "/admin/search",
        headers={"X-Admin-Token": TOKENS[0]},
        json={
            "query": "test",
            "limit": 7,
            "type": "playlist",
            "duration": "long",
            "features": ["subtitles", "location", "subtitles"],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["items"]) == 2
    assert payload["items"][0]["video_id"] == "valid"
    assert payload["items"][1]["video_id"] == "secondary"

    assert len(stub.calls) == 1
    call = stub.calls[0]
    assert call == {
        "query": "test",
        "limit": 7,
        "type_": "playlist",
        "duration": "long",
        "features": ["subtitles", "location"],
    }

    app.dependency_overrides.pop(get_supadata_client, None)


def test_admin_search_rejects_unsupported_filters() -> None:
    _ensure_admin_tokens()

    response = client.post(
        "/admin/search",
        headers={"X-Admin-Token": TOKENS[0]},
        json={
            "query": "test",
            "region": "PL",
            "language": "any",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Unsupported filters: language, region"


def test_admin_search_rejects_unsupported_features() -> None:
    _ensure_admin_tokens()

    response = client.post(
        "/admin/search",
        headers={"X-Admin-Token": TOKENS[0]},
        json={
            "query": "test",
            "features": ["hdr"],
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Unsupported features: hdr. Allowed: subtitles, location."


def test_admin_search_returns_502_when_supadata_fails() -> None:
    _ensure_admin_tokens()

    class ErrorClient:
        def search_youtube(self, **_: object) -> list[SDVideo]:  # pragma: no cover - stub helper
            raise HTTPException(status_code=502, detail="supadata search failed")

    app.dependency_overrides[get_supadata_client] = lambda: ErrorClient()

    response = client.post(
        "/admin/search",
        headers={"X-Admin-Token": TOKENS[0]},
        json={
            "query": "test",
            "limit": 10,
        },
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "supadata search failed"

    app.dependency_overrides.pop(get_supadata_client, None)


def test_queue_plan_creates_generation_jobs() -> None:
    _ensure_admin_tokens()
    app.dependency_overrides.pop(get_supadata_client, None)
    with SessionLocal() as session:
        session.query(GenJob).delete()
        session.commit()

    payload_urls = [
        "https://www.youtube.com/watch?v=abc",
        "http://www.youtube.com/watch?v=def",
    ]
    response = client.post(
        "/admin/queue/plan",
        headers={"X-Admin-Token": TOKENS[0]},
        json={"urls": payload_urls},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["planned"] == 2
    assert sorted(body["urls"]) == sorted(
        {"https://www.youtube.com/watch?v=abc", "https://www.youtube.com/watch?v=def"}
    )

    with SessionLocal() as session:
        jobs = session.query(GenJob).order_by(GenJob.id).all()
        assert len(jobs) == 2
        assert all(job.status == "pending" for job in jobs)
        assert {job.url for job in jobs} == {
            "https://www.youtube.com/watch?v=abc",
            "https://www.youtube.com/watch?v=def",
        }

    response_dup = client.post(
        "/admin/queue/plan",
        headers={"X-Admin-Token": TOKENS[0]},
        json={"urls": payload_urls},
    )
    assert response_dup.status_code == 201
    assert response_dup.json()["planned"] == 0


def test_admin_status_counts_jobs() -> None:
    _ensure_admin_tokens()
    with SessionLocal() as session:
        session.query(GenJob).delete()
        session.add_all(
            [
                GenJob(url="https://youtube.com/watch?v=pending", status="pending"),
                GenJob(url="https://youtube.com/watch?v=running", status="running"),
                GenJob(url="https://youtube.com/watch?v=done1", status="done", article_id=1),
                GenJob(url="https://youtube.com/watch?v=done2", status="ready", article_id=2),
                GenJob(url="https://youtube.com/watch?v=skip", status="skipped_no_raw"),
                GenJob(url="https://youtube.com/watch?v=failed", status="failed"),
            ]
        )
        session.commit()

    runner = get_runner(lambda: SessionLocal(), get_supadata_client)
    runner.stop()

    response = client.get(
        "/admin/status",
        headers={"X-Admin-Token": TOKENS[0]},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["pending"] == 1
    assert payload["running"] == 1
    assert payload["done"] == 2  # done + ready
    assert payload["skipped"] == 1
    assert payload["failed"] == 1
    assert payload["runner_on"] is False


def teardown_module(module):
    app.dependency_overrides.clear()
    get_runner(lambda: SessionLocal(), get_supadata_client).stop()
    engine.dispose()
