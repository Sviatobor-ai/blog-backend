import os
import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_enhancer.db")

from app.enhancer import deep_search  # noqa: E402
from app.enhancer.deep_search import DeepSearchResult, ParallelDeepSearchClient  # noqa: E402


@pytest.fixture(autouse=True)
def _patch_sleep(monkeypatch):
    monkeypatch.setattr(deep_search.time, "sleep", lambda _s: None)


def test_parallel_deep_search_returns_sources(monkeypatch):
    statuses = [
        {"status": "running", "run_id": "run-123"},
        {
            "status": "completed",
            "run_id": "run-123",
            "output": "Research summary text",
            "basis": [
                {
                    "citations": [
                        {
                            "url": "https://example.com/one",
                            "title": "Example One",
                            "excerpts": ["Snippet A"],
                        },
                        {
                            "url": "https://example.com/two",
                            "title": "Example Two",
                            "excerpts": ["Snippet B"],
                        },
                    ]
                }
            ],
        },
    ]

    def fake_post(url: str, json: dict, headers: dict, timeout: float):  # type: ignore[override]
        assert url.endswith("/v1/tasks/runs")
        assert headers.get("x-api-key") == "secret"

        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                return {"run_id": "run-123", "status": "queued"}

        return Response()

    def fake_get(url: str, headers: dict, timeout: float):  # type: ignore[override]
        assert "run-123" in url

        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                return statuses.pop(0)

        return Response()

    monkeypatch.setattr(deep_search.httpx, "post", fake_post)
    monkeypatch.setattr(deep_search.httpx, "get", fake_get)

    client = ParallelDeepSearchClient(api_key="secret", base_url="https://api.parallel.ai", timeout_s=5)
    result = client.search(title="Yoga benefits", lead="Lead text")

    assert isinstance(result, DeepSearchResult)
    assert result.summary == "Research summary text"
    assert len(result.sources) == 2
    assert {source.url for source in result.sources} == {
        "https://example.com/one",
        "https://example.com/two",
    }
    assert result.sources[0].title == "Example One"
