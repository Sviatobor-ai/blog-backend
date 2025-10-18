import os
import sys
from pathlib import Path

import httpx
import pytest
from fastapi import HTTPException
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


def _make_client(handler: httpx.MockTransport) -> SupaDataClient:
    http_client = httpx.Client(transport=handler, base_url="https://api.supadata.ai/v1")
    return SupaDataClient(api_key="test-key", client=http_client, asr_poll_interval=0.0, asr_poll_attempts=3)


def test_supadata_search_maps_supadata_response():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path.endswith("/youtube/search")
        assert request.headers["x-api-key"] == "test-key"
        params = request.url.params
        assert params["query"] == "test"
        assert "q" not in params
        assert "region" not in params
        assert "language" not in params
        return httpx.Response(
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

    client = _make_client(httpx.MockTransport(handler))

    videos = client.search_youtube(
        query="test",
        limit=5,
    )

    assert len(videos) == 3
    assert videos[0].video_id == "keep"
    assert videos[0].duration_seconds == 900
    assert videos[1].video_id == "short"
    assert videos[1].duration_seconds == 20
    assert videos[2].video_id == "long"
    assert videos[2].duration_seconds == 21600


def test_supadata_search_non_success_raises_http_exception(caplog):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path.endswith("/youtube/search")
        return httpx.Response(401, json={"error": "unauthorised"})

    client = _make_client(httpx.MockTransport(handler))

    with caplog.at_level("WARNING"):
        with pytest.raises(HTTPException) as exc:
            client.search_youtube(
                query="unauthorised",
                limit=5,
            )

    assert exc.value.status_code == 502
    assert "supadata-search status=401" in caplog.text


def test_get_transcript_concatenates_segments():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        if request.url.path.endswith("/youtube/transcript"):
            return httpx.Response(
                200,
                json={"segments": [{"text": "Hello"}, {"text": "World"}]},
            )
        raise AssertionError("unexpected path")

    client = _make_client(httpx.MockTransport(handler))

    text = client.get_transcript_raw("https://youtube.com/watch?v=abc")
    assert text == "Hello World"


def test_get_transcript_returns_none_when_not_found():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    client = _make_client(httpx.MockTransport(handler))

    text = client.get_transcript_raw("https://youtube.com/watch?v=missing")
    assert text is None


def test_asr_transcribe_returns_text_when_synchronous():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path.endswith("/youtube/asr")
        return httpx.Response(200, json={"text": "Synchronous text"})

    client = _make_client(httpx.MockTransport(handler))

    text = client.asr_transcribe_raw("https://youtube.com/watch?v=sync")
    assert text == "Synchronous text"


def test_asr_transcribe_polls_until_ready():
    poll_calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path.endswith("/youtube/asr"):
            return httpx.Response(200, json={"job_id": "job-1", "status": "processing"})
        if request.method == "GET" and request.url.path.endswith("/youtube/asr/job-1"):
            poll_calls["count"] += 1
            if poll_calls["count"] < 2:
                return httpx.Response(200, json={"status": "processing"})
            return httpx.Response(200, json={"text": "Final text"})
        raise AssertionError("unexpected request")

    client = _make_client(httpx.MockTransport(handler))

    text = client.asr_transcribe_raw("https://youtube.com/watch?v=poll")
    assert text == "Final text"
    assert poll_calls["count"] == 2


def test_asr_transcribe_returns_none_on_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "server"})

    client = _make_client(httpx.MockTransport(handler))

    text = client.asr_transcribe_raw("https://youtube.com/watch?v=err")
    assert text is None


def test_fetch_raw_text_uses_asr_when_transcript_missing():
    class StubClient:
        def get_transcript_raw(self, url: str) -> str | None:  # pragma: no cover - stub helper
            return None

        def asr_transcribe_raw(self, url: str) -> str | None:  # pragma: no cover - stub helper
            return "Recognised speech"

    text, mode = fetch_raw_text_from_youtube(StubClient(), "https://youtube.com/watch?v=abc")
    assert text == "Recognised speech"
    assert mode == "asr"


def test_run_generation_job_marks_skipped_when_no_text():
    class EmptyClient:
        def get_transcript_raw(self, url: str) -> str | None:  # pragma: no cover - stub helper
            return None

        def asr_transcribe_raw(self, url: str) -> str | None:  # pragma: no cover - stub helper
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
        def get_transcript_raw(self, url: str) -> str | None:  # pragma: no cover - stub helper
            return "Transcript text"

        def asr_transcribe_raw(self, url: str) -> str | None:  # pragma: no cover - stub helper
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
