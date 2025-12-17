import os
import sys
from pathlib import Path

os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_prompt_builders.db")
os.environ.setdefault("NEXT_PUBLIC_SITE_URL", "https://wiedza.joga.yoga")
os.environ.setdefault("SUPADATA_KEY", "test-key")

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.config import get_site_base_url  # noqa: E402
from app.services.prompt_builders import (  # noqa: E402
    build_generation_brief_topic,
    build_generation_brief_transcript,
    build_generation_system_instructions,
)
from app.services import OpenAIAssistantFromTranscriptGenerator  # noqa: E402


def test_topic_brief_includes_inputs():
    prompt = build_generation_brief_topic(
        topic="Regeneracja po intensywnej praktyce",
        rubric_name="Zdrowie i joga",
        keywords=["odpoczynek", "rozciaganie"],
        guidance="Podaj praktyczne przykłady",
    )

    assert "Rubryka redakcyjna: Zdrowie i joga." in prompt
    assert "Temat przewodni artykułu: Regeneracja po intensywnej praktyce." in prompt
    assert "słowa kluczowe SEO: odpoczynek, rozciaganie." in prompt
    assert "Wytyczne redakcyjne: Podaj praktyczne przykłady." in prompt


def test_transcript_brief_includes_transcript_and_guidance():
    transcript = "Przykładowa transkrypcja rozmowy o jodze."
    prompt = build_generation_brief_transcript(
        transcript_text=transcript,
        rubric_name="Wellness",
        keywords=None,
        guidance="Zachowaj ton ekspercki",
    )

    assert transcript in prompt
    assert "Rubryka redakcyjna: Wellness." in prompt
    assert "Zachowaj ton ekspercki" in prompt


def test_transcript_brief_accepts_optional_keywords():
    prompt = build_generation_brief_transcript(
        transcript_text="Dowolna treść",
        rubric_name=None,
        topic="Techniki oddechowe",
        keywords=["pranayama", "oddech"],
        guidance="Stosuj język prosty",
    )

    assert prompt
    assert "Techniki oddechowe" in prompt


def test_system_instructions_include_canonical_base():
    os.environ["NEXT_PUBLIC_SITE_URL"] = "https://example.com"
    get_site_base_url.cache_clear()
    instructions = build_generation_system_instructions()
    assert "https://example.com." in instructions


def test_transcript_generator_handles_optional_fields(monkeypatch):
    captured: dict[str, str] = {}
    generator = OpenAIAssistantFromTranscriptGenerator(api_key="test", assistant_id="assistant")

    def fake_execute(*, user_message: str, run_instructions: str, timeout_s: float | None = None):
        captured["user_message"] = user_message
        captured["instructions"] = run_instructions
        return {"ok": True}

    generator._execute = fake_execute  # type: ignore[method-assign]

    result = generator.generate_from_transcript(
        raw_text="Transkrypcja video",
        source_url="https://example.com/video",
        research_content=None,
        research_sources=None,
        author_context=None,
    )

    assert result == {"ok": True}
    assert "Transkrypcja video" in captured["user_message"]
