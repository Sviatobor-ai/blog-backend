import os
import sys
from pathlib import Path

import httpx
import pytest
from fastapi import HTTPException

os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_supadata.db")

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.integrations.supadata import (  # noqa: E402
    MIN_TRANSCRIPT_CHARS,
    SupaDataClient,
    SupadataTranscriptError,
    SupadataTranscriptTooShortError,
)


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
        assert params["type"] == "video"
        assert params["duration"] == "medium"
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
        type_="video",
        duration="medium",
        features=[],
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
                type_="video",
                duration="medium",
                features=[],
            )

    assert exc.value.status_code == 502
    assert "supadata-search status=401" in caplog.text


def test_get_transcript_parses_content_variants():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path.endswith("/transcript")
        assert request.url.params["text"] == "true"
        assert request.url.params["mode"] == "auto"
        return httpx.Response(
            200,
            json={
                "content": " Hello " + "!" * MIN_TRANSCRIPT_CHARS,
                "lang": "en",
                "availableLangs": ["en", "pl"],
            },
        )

    client = _make_client(httpx.MockTransport(handler))

    result = client.get_transcript(url="https://youtube.com/watch?v=abc", lang="pl", mode="auto", text=True)
    assert result.text.startswith("Hello")
    assert result.lang == "en"
    assert result.available_langs == ["en", "pl"]


def test_get_transcript_handles_async_polling():
    poll_calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/transcript") and request.method == "GET":
            return httpx.Response(202, json={"jobId": "abc"})
        if request.url.path.endswith("/transcript/abc"):
            poll_calls["count"] += 1
            if poll_calls["count"] < 3:
                return httpx.Response(200, json={"status": "queued"})
            return httpx.Response(
                200,
                json={
                    "status": "completed",
                    "content": [
                        {"text": "Hello"},
                        {"text": "world"},
                        {"text": "!" * MIN_TRANSCRIPT_CHARS},
                    ],
                },
            )
        raise AssertionError("unexpected request")

    client = _make_client(httpx.MockTransport(handler))

    result = client.get_transcript(url="https://youtube.com/watch?v=poll")

    assert poll_calls["count"] == 3
    assert result.text.startswith("Hello")
    assert result.content_chars >= MIN_TRANSCRIPT_CHARS


def test_get_transcript_raises_on_error_response(caplog):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "not found"})

    client = _make_client(httpx.MockTransport(handler))

    with caplog.at_level("WARNING"):
        with pytest.raises(SupadataTranscriptError) as exc:
            client.get_transcript(url="https://youtube.com/watch?v=missing")

    assert exc.value.status_code == 404
    assert "supadata.transcript.error" in caplog.text


def test_get_transcript_raises_on_too_short():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"content": "too short"})

    client = _make_client(httpx.MockTransport(handler))

    with pytest.raises(SupadataTranscriptTooShortError):
        client.get_transcript(url="https://youtube.com/watch?v=short")


def test_get_transcript_times_out_polling():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/transcript"):
            return httpx.Response(202, json={"jobId": "slow"})
        return httpx.Response(200, json={"status": "queued"})

    client = _make_client(httpx.MockTransport(handler))

    with pytest.raises(SupadataTranscriptError) as exc:
        client.get_transcript(
            url="https://youtube.com/watch?v=slow", poll_interval=0.01, poll_timeout=0.05
        )

    assert exc.value.status_code == 504


def test_asr_transcribe_polls_until_ready():
    poll_calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path.endswith("/transcript"):
            return httpx.Response(200, json={"job_id": "job-1", "status": "processing"})
        if request.method == "GET" and request.url.path.endswith("/transcript/job-1"):
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
        path = request.url.path
        if path.endswith("/transcript") or path.endswith("/youtube/asr"):
            return httpx.Response(500, json={"error": "server"})
        raise AssertionError("unexpected path")

    client = _make_client(httpx.MockTransport(handler))

    text = client.asr_transcribe_raw("https://youtube.com/watch?v=err")
    assert text is None


def test_asr_transcribe_falls_back_to_legacy_route():
    sequence: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        sequence.append(f"{request.method}:{path}")
        if request.method == "POST" and path.endswith("/transcript"):
            return httpx.Response(404)
        if request.method == "POST" and path.endswith("/youtube/asr"):
            return httpx.Response(200, json={"job_id": "legacy-job"})
        if request.method == "GET" and path.endswith("/youtube/asr/legacy-job"):
            return httpx.Response(200, json={"text": "Legacy ASR"})
        raise AssertionError("unexpected request")

    client = _make_client(httpx.MockTransport(handler))

    text = client.asr_transcribe_raw("https://youtube.com/watch?v=legacy")
    assert text == "Legacy ASR"
    assert sequence[0].endswith("/transcript")
    assert any(item.startswith("POST:") and item.endswith("/youtube/asr") for item in sequence)
