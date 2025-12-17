import os
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict

os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_generated_article_service.db")
os.environ.setdefault("NEXT_PUBLIC_SITE_URL", "https://wiedza.joga.yoga")
os.environ.setdefault("SUPADATA_KEY", "test-key")

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.db import Base, SessionLocal, engine  # noqa: E402
from sqlalchemy.types import JSON  # noqa: E402

from app import config  # noqa: E402
from app.enhancer.deep_search import DeepSearchError, DeepSearchResult, DeepSearchSource  # noqa: E402
from app.integrations.supadata import TranscriptResult  # noqa: E402
from app.models import Post  # noqa: E402
from app.schemas import ArticleCreateRequest  # noqa: E402
from app.services.generated_article_service import GeneratedArticleService  # noqa: E402

if engine.dialect.name == "sqlite":
    Post.__table__.c.categories.type = JSON()
    Post.__table__.c.tags.type = JSON()
    Post.__table__.c.geo_focus.type = JSON()
    Post.__table__.c.faq.type = JSON()
    Post.__table__.c.citations.type = JSON()
    Post.__table__.c.payload.type = JSON()


_BODY_PADDING = (
    " Ten akapit testowy uzupełnia narrację sekcji i zapewnia wystarczającą długość tekstu "
    "dla walidacji dokumentu i rozbudowuje opis praktyki na potrzeby testów automatycznych."
) * 8

SAMPLE_DOCUMENT: Dict[str, Any] = {
    "topic": "Joga nidra dla początkujących",
    "slug": "joga-nidra-dla-poczatkujacych",
    "locale": "pl-PL",
    "taxonomy": {
        "section": "Zdrowie i joga",
        "categories": ["Zdrowie i joga"],
        "tags": ["joga", "relaks", "mindfulness"],
    },
    "seo": {
        "title": "Joga nidra dla początkujących regeneracja",
        "description": (
            "Dowiedz się, jak zacząć praktykę jogi nidry, by uspokoić układ nerwowy, wprowadzić rytuał relaksu"
            " i zadbać o głęboki sen w domu oraz na wyjazdach wellness."
        ),
        "slug": "joga-nidra-dla-poczatkujacych",
        "canonical": "https://wiedza.joga.yoga/artykuly/joga-nidra-dla-poczatkujacych",
        "robots": "index,follow",
    },
    "article": {
        "headline": "Pierwsze kroki w jodze nidrze",
        "lead": (
            "Joga nidra to prowadzone wejście w stan głębokiego odprężenia, które możesz praktykować podczas "
            "wieczornych sesji regeneracyjnych oraz w czasie wyjazdów wellness. "
            "Regularna praktyka pomaga przywrócić równowagę układu nerwowego, zwiększa poczucie bezpieczeństwa i "
            "wspiera głęboki sen, co ułatwia codzienne funkcjonowanie nawet w intensywnym grafiku zajęć."
        ),
        "sections": [
            {
                "title": "Czym jest joga nidra",
                "body": "Opisujemy historię jogi nidry oraz wpływ na układ nerwowy." + _BODY_PADDING,
            },
            {
                "title": "Jak przygotować przestrzeń",
                "body": "Podpowiadamy, jakie akcesoria i rytuały stworzą atmosferę bezpieczeństwa." + _BODY_PADDING,
            },
            {
                "title": "Przebieg praktyki krok po kroku",
                "body": "Wskazujemy strukturę sesji od ustawienia intencji po wyjście z relaksu." + _BODY_PADDING,
            },
            {
                "title": "Integracja po zakończeniu",
                "body": "Proponujemy krótkie notatki refleksji i delikatny ruch, aby utrwalić efekty." + _BODY_PADDING,
            },
        ],
        "citations": [
            "https://example.com/joga-nidra",
            "https://example.com/regeneracja"
        ],
    },
    "aeo": {
        "geo_focus": ["Polska"],
        "faq": [
            {
                "question": "Jak często praktykować jogę nidrę?",
                "answer": "Dwa lub trzy razy w tygodniu, zachowując spokojne tempo i wygodną pozycję leżącą.",
            },
            {
                "question": "Czy potrzebuję sprzętu do jogi nidry?",
                "answer": "Wystarczy mata, koc i podparcie pod kolana lub głowę, aby ciało w pełni odpoczęło.",
            },
        ],
    },
}


def _reset_database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


class FakeGenerator:
    is_configured = True

    def __init__(self) -> None:
        self.research_content = None
        self.research_sources = None

    def generate_article(
        self,
        *,
        topic: str,
        rubric: str,
        keywords=None,
        guidance=None,
        research_content=None,
        research_sources=None,
        author_context=None,
        user_guidance=None,
    ):
        self.research_content = research_content
        self.research_sources = research_sources
        document = deepcopy(SAMPLE_DOCUMENT)
        document["topic"] = topic
        document["taxonomy"] = dict(document["taxonomy"])
        document["taxonomy"]["section"] = rubric
        document["slug"] = document["seo"]["slug"]
        return document


class FakeTranscriptGenerator:
    is_configured = True

    def __init__(self) -> None:
        self.called_with: Dict[str, str] | None = None

    def generate_from_transcript(
        self,
        *,
        raw_text: str,
        source_url: str,
        research_content=None,
        research_sources=None,
        author_context=None,
    ):
        self.called_with = {"raw_text": raw_text, "source_url": source_url}
        document = deepcopy(SAMPLE_DOCUMENT)
        document["topic"] = "Transkrypcja do artykulu"
        document["slug"] = "transkrypcja-do-artykulu"
        document["article"] = dict(document["article"])
        document["article"]["citations"] = [source_url]
        return document


def test_service_creates_article_without_video():
    _reset_database()
    service = GeneratedArticleService()
    payload = ArticleCreateRequest(topic="Regeneracja z jogą nidrą", rubric_code=None, keywords=["joga"])

    with SessionLocal() as session:
        response = service.create_article(
            payload=payload,
            db=session,
            generator=FakeGenerator(),
            transcript_generator=FakeTranscriptGenerator(),
            supadata_provider=lambda: None,
        )

    assert response.status == "published"
    with SessionLocal() as session:
        stored = session.query(Post).filter(Post.slug == response.slug).one()
        assert stored.payload["topic"] == payload.topic


def test_service_creates_article_from_video_path():
    _reset_database()
    service = GeneratedArticleService()
    transcript_calls = []

    class StubSupadata:
        def get_transcript(self, *, url: str, lang: str | None = None, mode: str = "auto", text: bool = True):
            transcript_calls.append(url)
            payload = "Transkrypcja testowa " * 15
            return TranscriptResult(text=payload, lang=lang, available_langs=["pl"], content_chars=len(payload))

    transcript_generator = FakeTranscriptGenerator()
    payload = ArticleCreateRequest(topic="Temat video test", video_url="https://youtube.com/watch?v=video123")

    with SessionLocal() as session:
        response = service.create_article(
            payload=payload,
            db=session,
            generator=FakeGenerator(),
            transcript_generator=transcript_generator,
            supadata_provider=lambda: StubSupadata(),
        )

    assert response.slug == "transkrypcja-do-artykulu"
    assert transcript_calls == ["https://youtube.com/watch?v=video123"]
    assert transcript_generator.called_with is not None
    assert transcript_generator.called_with["source_url"] == "https://youtube.com/watch?v=video123"


def test_video_path_uses_existing_post_for_same_source_key():
    _reset_database()
    service = GeneratedArticleService()

    class StubSupadata:
        def __init__(self) -> None:
            self.calls = 0

        def get_transcript(self, *, url: str, lang: str | None = None, mode: str = "auto", text: bool = True):
            self.calls += 1
            payload = "Transkrypcja testowa " * 15
            return TranscriptResult(text=payload, lang=lang, available_langs=["pl"], content_chars=len(payload))

    transcript_generator = FakeTranscriptGenerator()
    payload = ArticleCreateRequest(topic="Temat video test", video_url="https://youtu.be/video123")

    with SessionLocal() as session:
        stub = StubSupadata()
        first_response = service.create_article(
            payload=payload,
            db=session,
            generator=FakeGenerator(),
            transcript_generator=transcript_generator,
            supadata_provider=lambda: stub,
        )
        assert stub.calls == 1

    with SessionLocal() as session:
        dedup_stub = StubSupadata()
        second_response = service.create_article(
            payload=payload,
            db=session,
            generator=FakeGenerator(),
            transcript_generator=FakeTranscriptGenerator(),
            supadata_provider=lambda: dedup_stub,
        )
        assert dedup_stub.calls == 0

    assert first_response.slug == second_response.slug
    assert first_response.id == second_response.id


def _set_research_flag(enabled: bool) -> None:
    os.environ["PRIMARY_GENERATION_RESEARCH_ENABLED"] = "true" if enabled else "false"
    config.get_primary_generation_settings.cache_clear()


def test_service_runs_research_when_enabled():
    _reset_database()
    _set_research_flag(True)
    research_calls: list[dict] = []
    service = GeneratedArticleService()

    class StubResearchClient:
        def search(self, *, title: str, lead: str):
            research_calls.append({"title": title, "lead": lead})
            return DeepSearchResult(
                summary="Research summary",
                sources=[DeepSearchSource(url="https://example.com/source", title="Example")],
            )

    generator = FakeGenerator()

    with SessionLocal() as session:
        payload = ArticleCreateRequest(topic="Badanie jogi", rubric_code=None)
        response = service.create_article(
            payload=payload,
            db=session,
            generator=generator,
            transcript_generator=FakeTranscriptGenerator(),
            supadata_provider=lambda: None,
            research_client_provider=lambda: StubResearchClient(),
        )

    _set_research_flag(False)

    assert research_calls, "research client should be invoked when flag is enabled"
    assert generator.research_content == "Research summary"
    assert generator.research_sources and generator.research_sources[0].url == "https://example.com/source"
    assert response.status == "published"


def test_service_falls_back_when_research_fails():
    _reset_database()
    _set_research_flag(True)
    service = GeneratedArticleService()

    class FailingResearchClient:
        def search(self, *, title: str, lead: str):  # noqa: ARG002
            raise DeepSearchError("parallel failure")

    generator = FakeGenerator()

    try:
        with SessionLocal() as session:
            payload = ArticleCreateRequest(topic="Fallback without research", rubric_code=None)
            response = service.create_article(
                payload=payload,
                db=session,
                generator=generator,
                transcript_generator=FakeTranscriptGenerator(),
                supadata_provider=lambda: None,
                research_client_provider=lambda: FailingResearchClient(),
            )
    finally:
        _set_research_flag(False)

    assert response.status == "published"
    assert generator.research_content is None
    assert generator.research_sources == []
