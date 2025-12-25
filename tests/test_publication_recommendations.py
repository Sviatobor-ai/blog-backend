import os
import sys
from datetime import datetime
from pathlib import Path

os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_publication_recommendations.db")
os.environ.setdefault("NEXT_PUBLIC_SITE_URL", "https://wiedza.joga.yoga")

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy.types import JSON  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.models import Post  # noqa: E402
from app.schemas import ArticleDocument  # noqa: E402
from app.services.article_publication import prepare_document_for_publication  # noqa: E402


if engine.dialect.name == "sqlite":
    Post.__table__.c.categories.type = JSON()
    Post.__table__.c.tags.type = JSON()
    Post.__table__.c.geo_focus.type = JSON()
    Post.__table__.c.faq.type = JSON()
    Post.__table__.c.citations.type = JSON()
    Post.__table__.c.payload.type = JSON()


def setup_module(module):
    db_path = Path("test_publication_recommendations.db")
    if db_path.exists():
        db_path.unlink()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    seed_posts = [
        Post(
            slug="rec-1",
            locale="pl-PL",
            section="Zdrowie",
            categories=["Zdrowie"],
            tags=["joga"],
            title="Polecany artykuł",
            description="Opis",
            canonical="https://wiedza.joga.yoga/rec-1",
            robots="index,follow",
            headline="Polecany",
            lead="Lead rekomendacji",
            body_mdx="## Sekcja\n\nTreść",
            geo_focus=["Polska"],
            faq=[],
            citations=[],
            payload={},
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        ),
        Post(
            slug="rec-2",
            locale="pl-PL",
            section="Ajurweda",
            categories=["Ajurweda"],
            tags=["ajurweda"],
            title="Inny artykuł",
            description="Opis",
            canonical="https://wiedza.joga.yoga/rec-2",
            robots="index,follow",
            headline="Inny",
            lead="Lead drugi",
            body_mdx="## Sekcja\n\nTreść",
            geo_focus=["Polska"],
            faq=[],
            citations=[],
            payload={},
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        ),
    ]
    with SessionLocal() as session:
        session.add_all(seed_posts)
        session.commit()


def teardown_module(module):
    Base.metadata.drop_all(bind=engine)


def test_prepare_document_rewrites_sources_section():
    payload = {
        "topic": "Trening oddechu",
        "slug": "trening-oddechu",
        "locale": "pl-PL",
        "taxonomy": {"section": "Zdrowie", "categories": ["Zdrowie"], "tags": ["oddech", "joga"]},
        "seo": {
            "title": "Trening oddechu",
            "description": "Opis artykułu o treningu oddechu " * 4,
            "slug": "trening-oddechu",
            "canonical": "https://wiedza.joga.yoga/trening-oddechu",
            "robots": "index,follow",
        },
        "article": {
            "headline": "Trening oddechu",
            "lead": "Lead rozwinięty o praktykę oddechową " * 10,
            "sections": [
                {"title": "Źródła", "body": "Stare źródła i dodatkowy tekst " * 20},
                {"title": "Inna", "body": "Treść rozwinięta " * 25},
                {"title": "Dodatkowa", "body": "Rozszerzona treść sekcji " * 25},
            ],
            "citations": ["https://example.com/a"],
        },
        "aeo": {
            "geo_focus": ["Polska"],
            "faq": [
                {
                    "question": "Jak zacząć?",
                    "answer": "Odpowiedź o długości wystarczającej do walidacji FAQ w artykule.",
                },
                {
                    "question": "Jak często ćwiczyć?",
                    "answer": "Druga odpowiedź zapewniająca zgodność z wymaganiami testu.",
                },
            ],
        },
    }
    document = ArticleDocument.model_validate(payload)

    with SessionLocal() as session:
        prepared = prepare_document_for_publication(
            session,
            document,
            fallback_topic="Trening oddechu",
            rubric_name="Zdrowie",
        )

    sources_sections = [s for s in prepared.article.sections if s.title.casefold() in {"źródła", "zrodla"}]
    assert len(sources_sections) == 1
    assert "Przeczytaj również" in sources_sections[0].body
    assert "/artykuly/rec" in sources_sections[0].body
    assert prepared.article.citations == []
