import os
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict

os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_posts.db")

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import func  # noqa: E402
from sqlalchemy.types import JSON  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app, get_generator  # noqa: E402
from app.models import Post  # noqa: E402
from app.schemas import ArticleDocument  # noqa: E402


if engine.dialect.name == "sqlite":
    Post.__table__.c.categories.type = JSON()
    Post.__table__.c.tags.type = JSON()
    Post.__table__.c.geo_focus.type = JSON()
    Post.__table__.c.faq.type = JSON()
    Post.__table__.c.citations.type = JSON()
    Post.__table__.c.payload.type = JSON()


SAMPLE_DOCUMENT = {
    "topic": "Joga nidra dla początkujących",
    "slug": "joga-nidra-dla-poczatkujacych",
    "locale": "pl-PL",
    "taxonomy": {
        "section": "Zdrowie i joga",
        "categories": ["Zdrowie i joga"],
        "tags": ["joga", "relaks", "mindfulness"],
    },
    "seo": {
        "title": "Joga nidra dla początkujących – joga.yoga",
        "description": "Poznaj podstawy jogi nidry, aby wzmocnić regenerację, odprężyć układ nerwowy i odnaleźć spokojny rytm dnia.",
        "slug": "joga-nidra-dla-poczatkujacych",
        "canonical": "https://joga.yoga/artykuly/joga-nidra-dla-poczatkujacych",
        "robots": "index,follow",
    },
    "article": {
        "headline": "Joga nidra dla początkujących: pierwszy krok do głębokiego relaksu",
    "lead": (
        "Joga nidra to prowadzone wejście w stan głębokiego odprężenia, które możesz praktykować w domu oraz na wyjazdach "
        "regeneracyjnych, aby ukoić układ nerwowy i świadomie zadbać o higienę snu nawet w intensywnym grafiku dnia."
    ),
        "sections": [
            {
                "title": "Czym jest joga nidra",
                "body": (
                    "Opisujemy historię jogi nidry, jej korzenie w tradycji tantricznej oraz współczesne badania wskazujące na "
                    "korzystny wpływ na układ nerwowy. Szczegółowo omawiamy, jak naprzemienne fale mózgowe wspierają regenerację, "
                    "dlaczego praktyka uznawana jest za jogiczny sen oraz w jaki sposób prowadzone wizualizacje scalają doświadczane "
                    "emocje i ułatwiają odzyskanie równowagi."
                ),
            },
            {
                "title": "Jak przygotować przestrzeń",
                "body": (
                    "Podpowiadamy, jakie akcesoria i rytuały stworzą atmosferę bezpieczeństwa. Od zasłonięcia okien i dobrania "
                    "naturalnego oświetlenia, po wybór wspierających zapachów i kojącej muzyki. Prezentujemy sposoby na ułożenie "
                    "ciała z pomocą koców, bolstera i podparć pod kolana, by kręgosłup i barki pozostały zrelaksowane przez całą "
                    "sesję. Wskazujemy, jak zadbać o termikę ciała i komunikację z grupą, aby każdy czuł się komfortowo."
                ),
            },
            {
                "title": "Przebieg praktyki krok po kroku",
                "body": (
                    "Wskazujemy strukturę sesji od ustawienia intencji po wyjście z relaksu. Wyjaśniamy znaczenie sankalpy, "
                    "prowadzonego skanowania ciała, wizualizacji zmysłowej i wyciszenia oddechu. Dodajemy sugestie dla nauczyciela, "
                    "jak modulować głos oraz tempo, a także jak reagować na pojawiające się emocje. Dzięki temu cała praktyka staje "
                    "się przewidywalna i sprzyja głębokiemu poczuciu bezpieczeństwa."
                ),
            },
            {
                "title": "Integracja po zakończeniu",
                "body": (
                    "Proponujemy krótkie notatki refleksji i delikatny ruch, aby utrwalić efekty. Sugestie obejmują prowadzone "
                    "rozciąganie dłoni i stóp, miękkie przeciąganie kręgosłupa oraz zapisanie odczuć w dzienniku wdzięczności. "
                    "Zachęcamy do krótkiej wymiany wrażeń w grupie oraz zaplanowania domowej praktyki, by oddech i poczucie lekkości "
                    "towarzyszyły uczestnikom na co dzień."
                ),
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


def _create_post(document: Dict[str, Any] | None = None, **overrides):
    document = document or SAMPLE_DOCUMENT
    payload = ArticleDocument.model_validate(document)
    defaults = {
        "slug": payload.slug,
        "locale": payload.locale,
        "section": payload.taxonomy.section,
        "categories": payload.taxonomy.categories,
        "tags": payload.taxonomy.tags,
        "title": payload.seo.title,
        "description": payload.seo.description,
        "canonical": payload.seo.canonical,
        "robots": payload.seo.robots,
        "headline": payload.article.headline,
        "lead": payload.article.lead,
        "body_mdx": "\n\n".join(
            [f"## {section.title}\n\n{section.body}" for section in payload.article.sections]
        ),
        "geo_focus": payload.aeo.geo_focus,
        "faq": [faq.model_dump() for faq in payload.aeo.faq],
        "citations": payload.article.citations,
        "payload": payload.model_dump(),
    }
    defaults.update(overrides)
    with SessionLocal() as session:
        if "id" not in defaults:
            next_id = session.query(func.coalesce(func.max(Post.id), 0) + 1).scalar()
            defaults["id"] = next_id or 1
        post = Post(**defaults)
        session.add(post)
        session.commit()
        session.refresh(post)
        return post


def setup_module(module):
    db_path = Path("test_posts.db")
    if db_path.exists():
        db_path.unlink()
    _reset_database()


def teardown_module(module):
    Base.metadata.drop_all(bind=engine)
    db_path = Path("test_posts.db")
    if db_path.exists():
        db_path.unlink()


client = TestClient(app)


class FakeGenerator:
    is_configured = True

    def generate_article(self, *, topic: str, rubric: str, keywords=None, guidance=None):
        document = deepcopy(SAMPLE_DOCUMENT)
        document["topic"] = topic
        document["taxonomy"] = dict(document["taxonomy"])
        document["taxonomy"]["section"] = rubric
        document["slug"] = document["seo"]["slug"]
        return document


class InvalidGenerator:
    is_configured = True

    def generate_article(self, *, topic: str, rubric: str, keywords=None, guidance=None):
        return {"slug": 123}


def test_create_article_publishes_and_returns_document():
    _reset_database()
    app.dependency_overrides[get_generator] = lambda: FakeGenerator()

    response = client.post(
        "/articles",
        json={
            "topic": "Regeneracja z jogą nidrą",
            "rubric_code": None,
            "keywords": ["joga nidra", "relaks", "sen"],
        },
    )

    app.dependency_overrides.clear()

    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == "published"
    assert payload["post"]["aeo"]["faq"]

    with SessionLocal() as session:
        stored = session.query(Post).filter(Post.slug == payload["slug"]).one()
        assert stored.payload["topic"] == "Regeneracja z jogą nidrą"


def test_list_articles_returns_summaries():
    _reset_database()
    first = _create_post()
    second_document = deepcopy(SAMPLE_DOCUMENT)
    second_document["topic"] = "Zaawansowana joga nidra"
    second_document["slug"] = "zaawansowana-joga-nidra"
    second_document["seo"] = dict(second_document["seo"])
    second_document["seo"]["title"] = "Zaawansowana joga nidra – joga.yoga"
    second_document["seo"]["slug"] = "zaawansowana-joga-nidra"
    second_document["seo"]["canonical"] = (
        "https://joga.yoga/artykuly/zaawansowana-joga-nidra"
    )
    second_document["article"] = dict(second_document["article"])
    second_document["article"]["headline"] = (
        "Zaawansowana joga nidra: prowadzenie praktyki"
    )
    second = _create_post(document=second_document)

    response = client.get("/articles")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert len(data["items"]) == 2
    assert {item["slug"] for item in data["items"]} == {first.slug, second.slug}


def test_get_article_returns_document_payload():
    _reset_database()
    created = _create_post()

    response = client.get(f"/articles/{created.slug}")
    assert response.status_code == 200
    document = response.json()["post"]
    assert document["slug"] == created.slug
    assert len(document["article"]["sections"]) == 4


def test_get_article_falls_back_when_payload_invalid():
    _reset_database()
    created = _create_post()

    with SessionLocal() as session:
        stored = session.query(Post).filter(Post.id == created.id).one()
        stored.payload = {"slug": 123}
        session.add(stored)
        session.commit()

    response = client.get(f"/articles/{created.slug}")
    assert response.status_code == 200
    document = response.json()["post"]
    assert document["slug"] == created.slug
    assert document["article"]["sections"]


def test_openapi_includes_article_routes():
    schema = client.get("/openapi.json").json()

    assert "/articles" in schema["paths"]
    assert "/articles/{slug}" in schema["paths"]


def test_schema_endpoint_returns_expected_shape():
    response = client.get("/schemas/article")

    assert response.status_code == 200
    schema = response.json()
    assert schema["title"] == "PolishRetreatArticle"
    for field in ["topic", "slug", "article", "aeo"]:
        assert field in schema["required"]
        assert field in schema["properties"]


def test_create_article_returns_502_when_generator_returns_invalid_payload():
    _reset_database()
    app.dependency_overrides[get_generator] = lambda: InvalidGenerator()

    response = client.post(
        "/articles",
        json={
            "topic": "Niepoprawny artykuł",
            "rubric_code": None,
            "keywords": [],
        },
    )

    app.dependency_overrides.clear()

    assert response.status_code == 502
    assert "Invalid article payload" in response.json()["detail"]
