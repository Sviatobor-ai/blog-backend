import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import text

os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_enhancer.db")
os.environ.setdefault("PARALLELAI_API_KEY", "test-key")
os.environ.setdefault("OPENAI_API_KEY", "test-openai")

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.enhancer import run_batch  # noqa: E402
from app.models import Post  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_database():
    engine.dispose()
    db_path = Path("test_enhancer.db")
    if db_path.exists():
        db_path.unlink()
    Base.metadata.create_all(bind=engine)
    yield
    engine.dispose()
    if db_path.exists():
        db_path.unlink()


def _create_post(slug: str, created_at: datetime) -> None:
    with SessionLocal() as session:
        post = Post(
            slug=slug,
            title=f"{slug} title",
            lead="Lead",
            body_mdx="Body",
            payload={"foo": "bar"},
            created_at=created_at,
            updated_at=created_at,
        )
        session.add(post)
        session.commit()


def test_run_batch_rolls_back_and_continues(monkeypatch):
    now = datetime.now(timezone.utc)
    old = now - timedelta(days=20)
    _create_post("first", created_at=old)
    _create_post("second", created_at=old)

    class FakeWriter:
        def __init__(self, *args, **kwargs):  # pragma: no cover - test stub
            pass

    class FakeEnhancer:
        calls: list[str] = []

        def __init__(self, *args, **kwargs):
            pass

        def enhance_post(self, db, post, now):  # pragma: no cover - exercised via run_batch
            self.calls.append(post.slug)
            if post.slug == "first":
                db.execute(text("SELECT * FROM missing_table"))
            else:
                db.execute(text("UPDATE posts SET title='updated' WHERE slug=:slug"), {"slug": post.slug})
                db.commit()

    FakeEnhancer.calls = []

    monkeypatch.setattr(run_batch, "EnhancementWriter", FakeWriter)
    monkeypatch.setattr(run_batch, "get_parallel_deep_search_client", lambda: object())
    monkeypatch.setattr(run_batch, "ArticleEnhancer", FakeEnhancer)

    run_batch.run_batch(verbose=False)

    with SessionLocal() as session:
        first = session.query(Post).filter_by(slug="first").one()
        second = session.query(Post).filter_by(slug="second").one()
        assert first.title == "first title"
        assert FakeEnhancer.calls == ["first", "second"]
        assert second.title == "updated"
