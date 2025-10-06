import os
import sys
from pathlib import Path

os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_posts.db")

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import func  # noqa: E402
from sqlalchemy.types import JSON  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Post  # noqa: E402


if engine.dialect.name == "sqlite":
    # Downgrade Postgres-specific column types to JSON for SQLite-based tests.
    Post.__table__.c.categories.type = JSON()
    Post.__table__.c.tags.type = JSON()
    Post.__table__.c.geo_focus.type = JSON()
    Post.__table__.c.faq.type = JSON()
    Post.__table__.c.citations.type = JSON()


def _reset_database():
    # Ensure a clean database state for each test run.
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _create_post(**overrides):
    defaults = {
        "slug": "sample-post",
        "locale": "pl-PL",
        "section": "Wyjazdy",
        "categories": ["Wyjazdy"],
        "tags": ["joga"],
        "title": "Sample Post",
        "description": "Opis",
        "canonical": "https://example.com/sample-post",
        "robots": "index,follow",
        "headline": "Sample Headline",
        "lead": "Sample lead",
        "body_mdx": "# Body",
        "geo_focus": ["Polska"],
        "faq": [],
        "citations": [],
    }
    defaults.update(overrides)
    with SessionLocal() as session:
        if "id" not in defaults:
            next_id = session.query(func.coalesce(func.max(Post.id), 0) + 1).scalar()
            defaults["id"] = next_id or 1
        post = Post(**defaults)
        session.add(post)
        session.commit()
        session.refresh(post)
        return post


def setup_module(module):  # noqa: D401
    """Create tables before module tests run."""
    # Remove leftover sqlite db to avoid stale schema
    db_path = Path("test_posts.db")
    if db_path.exists():
        db_path.unlink()
    _reset_database()


def teardown_module(module):  # noqa: D401
    """Clean up sqlite file after tests."""
    Base.metadata.drop_all(bind=engine)
    db_path = Path("test_posts.db")
    if db_path.exists():
        db_path.unlink()


client = TestClient(app)


def test_list_posts_returns_posts():
    _reset_database()
    created = _create_post(slug="pierwszy-post")

    response = client.get("/posts")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["posts"][0]["slug"] == created.slug


def test_get_post_not_found_returns_404():
    _reset_database()

    response = client.get("/posts/does-not-exist")
    assert response.status_code == 404


def test_articles_aliases_behave_like_posts():
    _reset_database()
    created = _create_post(slug="alias-post")

    list_response = client.get("/articles")
    assert list_response.status_code == 200
    assert list_response.json()["posts"][0]["slug"] == created.slug

    detail_response = client.get(f"/articles/{created.slug}")
    assert detail_response.status_code == 200
    assert detail_response.json()["slug"] == created.slug
