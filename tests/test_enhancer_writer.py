import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("OPENAI_API_KEY", "test-openai")

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.enhancer import writer as writer_module  # noqa: E402
from app.enhancer.writer import EnhancementRequest, EnhancementWriter  # noqa: E402


@pytest.fixture(autouse=True)
def fake_openai(monkeypatch):
    class FakeResponses:
        def __init__(self, payload: str):
            self._payload = payload

        def create(self, **kwargs):  # pragma: no cover - indirect assertions below
            messages = kwargs.get("input") or []
            serialized = "\n".join(item.get("content", "") for item in messages if isinstance(item, dict))
            assert "bez frazy 'Dopelniono'" in serialized
            return SimpleNamespace(output_text=self._payload)

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self._payload = json.dumps(
                {
                    "added_sections": [
                        {"title": "Nowe spojrzenie na oddech", "body": "A" * 450},
                        {"title": "Rutyny przyjazne nerwom", "body": "B" * 450},
                    ],
                    "added_faq": {"question": "Czy praktykować rano?", "answer": "Tak"},
                }
            )
            self.responses = FakeResponses(self._payload)

    monkeypatch.setattr(writer_module, "OpenAI", FakeClient)
    yield


def test_enhancement_writer_generates_multiple_sections():
    request = EnhancementRequest(
        headline="Tytuł",
        lead="L" * 200,
        sections=[{"title": "Sekcja", "body": "B" * 420}],
        faq=[{"question": "Q", "answer": "A"}],
        insights="Nowe dane",
        citations=[{"url": "https://example.com", "label": "Example"}],
    )

    writer = EnhancementWriter(api_key="dummy", model="gpt-test", timeout_s=1)
    response = writer.generate(request)

    assert len(response.added_sections) == 2
    assert all(not section["title"].lower().startswith("dopelniono") for section in response.added_sections)
    assert response.added_faq["question"] == "Czy praktykować rano?"
