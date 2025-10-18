import os
import sys
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_supadata.db")

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.db import Base  # noqa: E402
from app.generation_jobs import (  # noqa: E402
    GenerationJobStatus,
    fetch_raw_text_from_youtube,
    run_generation_job,
)
from app.integrations.supadata import SupaDataClient  # noqa: E402
from app.models import GenerationJob  # noqa: E402

TEST_ENGINE = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
TestSessionLocal = sessionmaker(bind=TEST_ENGINE, autoflush=False, autocommit=False)


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=TEST_ENGINE)
    with TestSessionLocal() as session:
        session.query(GenerationJob).delete()
        session.commit()
    yield
    with TestSessionLocal() as session:
        session.query(GenerationJob).delete()
        session.commit()


def _mock_client(response_map: dict[str, httpx.Response]) -> SupaDataClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return response_map.get(request.url.path, httpx.Response(404))

    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport, base_url="https://api.supadata.ai")
    return SupaDataClient(api_key="test-key", client=http_client)


def test_supadata_search_filters_short_and_long_videos():
    client = _mock_client(
        {
            "/youtube/search": httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "video_id": "keep",
                            "url": "https://www.youtube.com/watch?v=keep",
                            "title": "Keep",
                            "duration_seconds": 900,
                        },
                        {
                            "video_id": "short",
                            "duration_seconds": 20,
                        },
                        {
                            "video_id": "long",
                            "duration": "PT6H0M0S",
                        },
                    ]
                },
            )
        }
    )

    videos = client.search_youtube(
        query="test",
        limit=5,
        min_duration_seconds=60,
        max_duration_seconds=3600,
    )

    assert len(videos) == 1
    assert videos[0].video_id == "keep"
    assert videos[0].duration_seconds == 900


def test_get_transcript_concatenates_segments():
    client = _mock_client(
        {
            "/youtube/get-transcript": httpx.Response(
                200,
                json={"segments": [{"text": "Hello"}, {"text": "World"}]},
            )
        }
    )

    text = client.get_transcript_raw("https://youtube.com/watch?v=abc")
    assert text == "Hello World"


def test_fetch_raw_text_uses_asr_when_transcript_missing():
    class StubClient:
        def get_transcript_raw(self, url: str) -> str | None:
            return None

        def asr_transcribe_raw(self, url: str) -> str | None:
            return "Recognised speech"

    text, mode = fetch_raw_text_from_youtube(StubClient(), "https://youtube.com/watch?v=abc")
    assert text == "Recognised speech"
    assert mode == "asr"


def test_run_generation_job_marks_skipped_when_no_text():
    class EmptyClient:
        def get_transcript_raw(self, url: str) -> str | None:
            return None

        def asr_transcribe_raw(self, url: str) -> str | None:
            return None

    with TestSessionLocal() as session:
        job = GenerationJob(source_url="https://youtube.com/watch?v=none", status="pending")
        session.add(job)
        session.commit()
        session.refresh(job)

        result = run_generation_job(session, job, EmptyClient())
        assert result is None

        session.refresh(job)
        assert job.status == GenerationJobStatus.SKIPPED_NO_RAW.value
        assert job.mode is None
        assert job.text_length is None


def test_run_generation_job_records_mode_and_length():
    class TranscriptClient:
        def get_transcript_raw(self, url: str) -> str | None:
            return "Transcript text"

        def asr_transcribe_raw(self, url: str) -> str | None:
            return None

    collected: list[str] = []

    def capture(job: GenerationJob, text: str) -> None:
        collected.append(f"{job.id}:{len(text)}")

    with TestSessionLocal() as session:
        job = GenerationJob(source_url="https://youtube.com/watch?v=data", status="pending")
        session.add(job)
        session.commit()
        session.refresh(job)

        result = run_generation_job(session, job, TranscriptClient(), process_raw_text=capture)
        assert result == "Transcript text"

        session.refresh(job)
        assert job.status == GenerationJobStatus.READY.value
        assert job.mode == "transcript"
        assert job.text_length == len("Transcript text")
        assert collected == [f"{job.id}:{len('Transcript text')}"]
