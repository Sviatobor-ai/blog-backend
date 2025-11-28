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

from app.integrations.supadata import SupaDataClient  # noqa: E402


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
        return httpx.Response(
            200,
            json={
                "data": {
                    "segments": [
                        {"content": "Hello"},
                        {"text": "World"},
                    ]
                }
            },
        )

    client = _make_client(httpx.MockTransport(handler))

    text = client.get_transcript_raw("https://youtube.com/watch?v=abc")
    assert text == "Hello World"


def test_get_transcript_falls_back_to_youtube_endpoint():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        path = request.url.path
        if request.method == "GET" and path.endswith("/youtube/transcript"):
            return httpx.Response(200, json={"content": "Legacy transcript"})
        if request.method == "GET" and path.endswith("/transcript"):
            return httpx.Response(404)
        raise AssertionError("unexpected path")

    client = _make_client(httpx.MockTransport(handler))

    text = client.get_transcript_raw("https://youtube.com/watch?v=fallback")
    assert text == "Legacy transcript"
    assert calls[0].endswith("/transcript")
    assert calls[1].endswith("/youtube/transcript")


def test_get_transcript_returns_none_when_not_found():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    client = _make_client(httpx.MockTransport(handler))

    text = client.get_transcript_raw("https://youtube.com/watch?v=missing")
    assert text is None


def test_asr_transcribe_returns_text_when_synchronous():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path.endswith("/transcript")
        body = request.read()
        assert b"mode" in body
        return httpx.Response(200, json={"text": "Synchronous text"})

    client = _make_client(httpx.MockTransport(handler))

    text = client.asr_transcribe_raw("https://youtube.com/watch?v=sync")
    assert text == "Synchronous text"


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
