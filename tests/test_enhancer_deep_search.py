import os
import sys
from pathlib import Path

import httpx
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


def test_parallel_deep_search_fetches_results_payload(monkeypatch):
    basis_citations = [
        {
            "citations": [
                {
                    "url": "https://blocked.ru/skip",
                    "title": "Blocked",
                    "excerpts": ["spam"],
                }
            ]
        },
        {
            "citations": [
                {
                    "url": f"https://example.com/{idx}",
                    "title": f"Example {idx}",
                    "excerpts": [f"Snippet {idx}"],
                    "score": idx,
                }
                for idx in range(2, 9)
            ]
        },
    ]
    statuses = [
        {"status": "running", "run_id": "run-123"},
        {"status": "succeeded", "run_id": "run-123"},
    ]

    results_payload = {
        "run_id": "run-123",
        "output": {
            "summary": "Research summary text",
            "sources": [
                {"url": "https://example.com/one", "title": "Example One", "description": "Snippet A"},
                {"url": "https://example.com/2", "title": "Duplicate"},
            ],
            "basis": basis_citations,
        },
    }

    def fake_post(url: str, json: dict, headers: dict, timeout: float):  # type: ignore[override]
        assert url.endswith("/v1/tasks/runs")
        assert headers.get("x-api-key") == "secret"
        assert json.get("processor") == "base"
        assert isinstance(json.get("input"), str)

        class Response:
            status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return {"run_id": "run-123", "status": "queued"}

        return Response()

    def fake_get(url: str, headers: dict, timeout: float):  # type: ignore[override]
        assert headers.get("x-api-key") == "secret"

        class Response:
            status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                if "/v1/tasks/results/" in url or "/result" in url:
                    assert "expand=output,basis" in url
                    return results_payload
                assert statuses, "status polling exhausted"
                assert "/v1/tasks/runs/" in url
                return statuses.pop(0)

        return Response()

    monkeypatch.setattr(deep_search.httpx, "post", fake_post)
    monkeypatch.setattr(deep_search.httpx, "get", fake_get)

    client = ParallelDeepSearchClient(api_key="secret", base_url="https://api.parallel.ai", timeout_s=5)
    result = client.search(title="Yoga benefits", lead="Lead text")

    assert isinstance(result, DeepSearchResult)
    assert result.summary == "Research summary text"
    assert len(result.sources) == 5  # capped at 6 despite more citations
    urls = [source.url for source in result.sources]
    assert "https://example.com/one" in urls
    assert "https://example.com/2" in urls
    assert len(set(urls)) == len(urls)
    assert all(not url.endswith(".ru") for url in urls)


def test_parallel_deep_search_handles_missing_basis(monkeypatch):
    statuses = [
        {"status": "running", "run_id": "run-777"},
        {"status": "completed", "run_id": "run-777"},
    ]

    results_payload = {
        "output": {
            "content": {"summary": "Nested summary"},
            "sources": [
                {"url": "https://example.com/a", "title": "Title A", "excerpts": "Snippet"},
                {"url": "https://example.com/a", "title": "Title A", "excerpts": "Dup"},
            ],
        }
    }

    def fake_post(url: str, json: dict, headers: dict, timeout: float):  # type: ignore[override]
        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                return {"run_id": "run-777"}

        return Response()

    def fake_get(url: str, headers: dict, timeout: float):  # type: ignore[override]
        class Response:
            status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                if "/v1/tasks/results/" in url or "/result" in url:
                    return results_payload
                assert statuses, "status polling exhausted"
                return statuses.pop(0)

        return Response()

    monkeypatch.setattr(deep_search.httpx, "post", fake_post)
    monkeypatch.setattr(deep_search.httpx, "get", fake_get)

    client = ParallelDeepSearchClient(api_key="secret", base_url="https://api.parallel.ai", timeout_s=5)
    result = client.search(title="Yoga benefits", lead="Lead text")

    assert isinstance(result, DeepSearchResult)
    assert result.summary == "Nested summary"
    assert len(result.sources) == 1
    assert result.sources[0].url == "https://example.com/a"


def test_parallel_deep_search_handles_422(monkeypatch):
    def fake_post(url: str, json: dict, headers: dict, timeout: float):  # type: ignore[override]
        response = httpx.Response(422, request=httpx.Request("POST", url), json={"error": "bad"})
        return response

    monkeypatch.setattr(deep_search.httpx, "post", fake_post)

    client = ParallelDeepSearchClient(api_key="secret", base_url="https://api.parallel.ai", timeout_s=5)
    with pytest.raises(deep_search.DeepSearchError) as excinfo:
        client.search(title="Yoga", lead="Lead")
    assert "Parallel.ai request failed" in str(excinfo.value)
