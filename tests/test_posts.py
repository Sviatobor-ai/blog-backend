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


_BODY_PADDING = (
    " Ten akapit testowy uzupełnia narrację sekcji, rozwija przykłady pracy z oddechem,"
    " sygnalizuje wpływ praktyki na układ nerwowy i dodaje wskazówki wdrożenia w realnych"
    " scenariuszach wyjazdowych. Podkreśla znaczenie konsekwencji, mikro-rytuałów oraz"
    " pielęgnowania dobrostanu po powrocie do domu, aby spełnić wymagania długości treści"
    " i zachować spójność merytoryczną testowego artykułu."
)


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
        "description": (
            "Dowiedz się, jak zacząć praktykę jogi nidry, by uspokoić układ nerwowy, poprawić regenerację i zbudować"
            " wieczorny rytuał relaksu podczas wyjazdów wellness."
        ),
        "slug": "joga-nidra-dla-poczatkujacych",
        "canonical": "https://joga.yoga/artykuly/joga-nidra-dla-poczatkujacych",
        "robots": "index,follow",
    },
    "article": {
        "headline": "Joga nidra dla początkujących: pierwszy krok do głębokiego relaksu",
        "lead": (
            "Joga nidra to prowadzone wejście w stan głębokiego odprężenia, które możesz praktykować w domu oraz na wyjazdach"
            " regeneracyjnych, aby ukoić układ nerwowy i świadomie zadbać o higienę snu nawet w intensywnym grafiku dnia. "
            "Dzięki konsekwencji w praktyce uczysz się zauważać subtelne sygnały ciała, wydłużasz fazę odpoczynku i tworzysz"
            " rytuał, który wspiera codzienną równowagę."
        ),
        "sections": [
            {
                "title": "Czym jest joga nidra",
                "body": (
                    "Opisujemy historię jogi nidry, jej korzenie w tradycji tantrycznej oraz współczesne badania wskazujące na"
                    " korzystny wpływ na układ nerwowy. Szczegółowo omawiamy, jak naprzemienne fale mózgowe wspierają regenerację,"
                    " dlaczego praktyka uznawana jest za jogiczny sen oraz w jaki sposób prowadzone wizualizacje scalają"
                    " doświadczane emocje i ułatwiają odzyskanie równowagi. Dodajemy przykłady z zajęć warsztatowych i relacji"
                    " uczestników, którzy dzięki konsekwencji w praktyce odzyskali spokojny sen oraz poczucie zakorzenienia"
                    " w ciele."
                )
                + _BODY_PADDING,
            },
            {
                "title": "Jak przygotować przestrzeń",
                "body": (
                    "Podpowiadamy, jakie akcesoria i rytuały stworzą atmosferę bezpieczeństwa. Od zasłonięcia okien i dobrania"
                    " naturalnego oświetlenia, po wybór wspierających zapachów i kojącej muzyki. Prezentujemy sposoby na ułożenie"
                    " ciała z pomocą koców, bolstera i podparć pod kolana, by kręgosłup i barki pozostały zrelaksowane przez całą"
                    " sesję. Wskazujemy, jak zadbać o termikę ciała i komunikację z grupą, aby każdy czuł się komfortowo, oraz"
                    " jak przygotować notatnik do zapisania wrażeń po praktyce, co pogłębia integrację doświadczeń."
                )
                + _BODY_PADDING,
            },
            {
                "title": "Przebieg praktyki krok po kroku",
                "body": (
                    "Wskazujemy strukturę sesji od ustawienia intencji po wyjście z relaksu. Wyjaśniamy znaczenie sankalpy,"
                    " prowadzonego skanowania ciała, wizualizacji zmysłowej i wyciszenia oddechu. Dodajemy sugestie dla"
                    " nauczyciela, jak modulować głos oraz tempo, a także jak reagować na pojawiające się emocje. Przypominamy"
                    " o łagodnym przywracaniu ruchu w dłoniach i stopach oraz o czasie na integrację wrażeń, co pozwala utrzymać"
                    " poczucie bezpieczeństwa i zakotwiczenia przez resztę dnia."
                )
                + _BODY_PADDING,
            },
            {
                "title": "Integracja po zakończeniu",
                "body": (
                    "Proponujemy krótkie notatki refleksji i delikatny ruch, aby utrwalić efekty. Sugestie obejmują prowadzone"
                    " rozciąganie dłoni i stóp, miękkie przeciąganie kręgosłupa oraz zapisanie odczuć w dzienniku wdzięczności."
                    " Zachęcamy do krótkiej wymiany wrażeń w grupie oraz zaplanowania domowej praktyki, by oddech i poczucie"
                    " lekkości towarzyszyły uczestnikom na co dzień. Pokazujemy także, jak wykorzystać aromaterapię lub krótką"
                    " medytację po zajęciach, aby pogłębić efekt regeneracji i utrzymać dobre nawyki jeszcze długo po powrocie"
                    " do domu."
                )
                + _BODY_PADDING,
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
        "canonical": str(payload.seo.canonical),
        "robots": payload.seo.robots,
        "headline": payload.article.headline,
        "lead": payload.article.lead,
        "body_mdx": "\n\n".join(
            [f"## {section.title}\n\n{section.body}" for section in payload.article.sections]
        ),
        "geo_focus": payload.aeo.geo_focus,
        "faq": [faq.model_dump() for faq in payload.aeo.faq],
        "citations": [str(url) for url in payload.article.citations],
        "payload": payload.model_dump(mode="json"),
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
        "/artykuly",
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

    response = client.get("/artykuly")
    assert response.status_code == 200
    data = response.json()
    assert data["meta"]["total_items"] == 2
    assert data["meta"]["total_pages"] == 1
    assert data["meta"]["page"] == 1
    assert data["meta"]["per_page"] == 10
    assert len(data["items"]) == 2
    summaries = {item["slug"]: item for item in data["items"]}
    assert set(summaries) == {first.slug, second.slug}
    assert summaries[first.slug]["lead"] == first.lead
    assert summaries[first.slug]["headline"] == first.headline
    assert summaries[second.slug]["lead"] == second.lead
    assert summaries[second.slug]["headline"] == second.headline


def test_list_articles_supports_search_by_tags():
    _reset_database()
    _create_post(
        tags=["joga", "regeneracja"],
        title="Regeneracja z jogą",
        slug="regeneracja-z-joga",
    )
    _create_post(
        tags=["mindfulness"],
        title="Mindfulness na wyjazdach",
        slug="mindfulness-na-wyjazdach",
    )

    response = client.get("/artykuly", params={"q": "regener"})
    assert response.status_code == 200
    data = response.json()
    assert data["meta"]["total_items"] == 1
    assert data["items"][0]["slug"] == "regeneracja-z-joga"


def test_list_articles_paginates_and_counts_filtered_results():
    _reset_database()
    for index in range(7):
        _create_post(
            slug=f"artykul-{index}",
            title=f"Artykuł {index}",
            section="Wellness" if index % 2 == 0 else "Inne",
        )

    response = client.get(
        "/artykuly",
        params={"per_page": 2, "page": 2, "section": "Wellness"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["meta"]["total_items"] == 4
    assert data["meta"]["total_pages"] == 2
    assert data["meta"]["page"] == 2
    assert len(data["items"]) <= 2


def test_get_article_returns_document_payload():
    _reset_database()
    created = _create_post()

    response = client.get(f"/artykuly/{created.slug}")
    assert response.status_code == 200
    document = response.json()
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

    response = client.get(f"/artykuly/{created.slug}")
    assert response.status_code == 200
    document = response.json()
    assert document["slug"] == created.slug
    assert document["article"]["sections"]


def test_openapi_includes_article_routes():
    schema = client.get("/openapi.json").json()

    assert "/artykuly" in schema["paths"]
    assert "/artykuly/{slug}" in schema["paths"]


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
        "/artykuly",
        json={
            "topic": "Niepoprawny artykuł",
            "rubric_code": None,
            "keywords": [],
        },
    )

    app.dependency_overrides.clear()

    assert response.status_code == 502
    assert "Invalid article payload" in response.json()["detail"]
