import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_runner.db")

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.integrations.supadata import SupadataTranscriptTooShortError  # noqa: E402
from app.models import GenJob  # noqa: E402
from app.services.runner import GenRunner  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_database() -> None:
    engine.dispose()
    db_path = Path("test_runner.db")
    if db_path.exists():
        db_path.unlink()
    Base.metadata.create_all(bind=engine)
    yield
    engine.dispose()
    if db_path.exists():
        db_path.unlink()


def _create_running_job() -> int:
    with SessionLocal() as session:
        job = GenJob(url="https://example.com/video", status="running")
        job.started_at = datetime.now(timezone.utc)
        session.add(job)
        session.commit()
        session.refresh(job)
        return job.id


def test_runner_marks_failed_when_generator_raises():
    job_id = _create_running_job()

    def generator(db, payload):  # pragma: no cover - interface stub
        raise RuntimeError("missing supadata key")

    runner = GenRunner(session_factory=SessionLocal, job_generator=generator)

    with SessionLocal() as session:
        job = session.get(GenJob, job_id)
        assert job is not None
        runner._process_job(session, job)
        session.refresh(job)
        assert job.status == "failed"
        assert job.error == "missing supadata key"
        assert job.finished_at is not None
        assert job.article_id is None


def test_runner_marks_skipped_when_no_text_available():
    job_id = _create_running_job()

    def generator(db, payload):  # pragma: no cover - interface stub
        raise SupadataTranscriptTooShortError(
            video_url=str(payload.get("url")), content_chars=0, threshold=10
        )

    runner = GenRunner(session_factory=SessionLocal, job_generator=generator)

    with SessionLocal() as session:
        job = session.get(GenJob, job_id)
        assert job is not None
        runner._process_job(session, job)
        session.refresh(job)
        assert job.status == "skipped"
        assert job.error == "no transcript text"
        assert job.finished_at is not None
        assert job.article_id is None
