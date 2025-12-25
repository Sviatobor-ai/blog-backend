import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_internal_links.db")
os.environ.setdefault("NEXT_PUBLIC_SITE_URL", "https://wiedza.joga.yoga")

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy.types import JSON  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.models import Post  # noqa: E402
from app.schemas import ArticleDocument  # noqa: E402
from app.services.internal_links import (  # noqa: E402
    build_internal_recommendations,
    format_recommendations_section,
)


if engine.dialect.name == "sqlite":
    Post.__table__.c.categories.type = JSON()
    Post.__table__.c.tags.type = JSON()
    Post.__table__.c.geo_focus.type = JSON()
    Post.__table__.c.faq.type = JSON()
    Post.__table__.c.citations.type = JSON()
    Post.__table__.c.payload.type = JSON()


def setup_module(module):
    db_path = Path("test_internal_links.db")
    if db_path.exists():
        db_path.unlink()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def teardown_module(module):
    Base.metadata.drop_all(bind=engine)


def _create_post(slug: str, section: str, lead: str, offset_days: int = 0):
    long_description = "Opis artykułu testowy " * 7
    long_lead = (lead + " rozbudowany wstęp") * 20
    body_text = (lead + " dodatkowe zdania na potrzeby testu") * 20
    payload = ArticleDocument.model_validate(
        {
            "topic": slug,
            "slug": slug,
            "locale": "pl-PL",
            "taxonomy": {"section": section, "categories": [section], "tags": ["joga", "wellness"]},
            "seo": {
                "title": f"Tytuł {slug}",
                "description": long_description,
                "slug": slug,
                "canonical": f"https://wiedza.joga.yoga/{slug}",
                "robots": "index,follow",
            },
            "article": {
                "headline": f"Nagłówek {slug}",
                "lead": long_lead,
                "sections": [
                    {"title": "Sekcja", "body": body_text},
                    {"title": "Sekcja 2", "body": body_text},
                    {"title": "Sekcja 3", "body": body_text},
                ],
                "citations": [],
            },
            "aeo": {
                "geo_focus": ["Polska"],
                "faq": [
                    {
                        "question": "Jak korzystać z artykułu?",
                        "answer": "To przykładowa odpowiedź wypełniająca wymagania długości testu.",
                    },
                    {
                        "question": "Czy to test?",
                        "answer": "Tak, służy do weryfikacji logiki rekomendacji wewnętrznych.",
                    },
                ],
            },
        }
    )
    with SessionLocal() as session:
        post = Post(
            slug=payload.slug,
            locale=payload.locale,
            section=payload.taxonomy.section,
            categories=payload.taxonomy.categories,
            tags=payload.taxonomy.tags,
            title=payload.seo.title,
            description=payload.seo.description,
            canonical=str(payload.seo.canonical),
            robots=payload.seo.robots,
            headline=payload.article.headline,
            lead=payload.article.lead,
            body_mdx="\n\n".join([f"## {s.title}\n\n{s.body}" for s in payload.article.sections]),
            geo_focus=payload.aeo.geo_focus,
            faq=[],
            citations=[],
            payload=payload.model_dump(mode="json"),
            created_at=datetime.utcnow() - timedelta(days=offset_days),
            updated_at=datetime.utcnow() - timedelta(days=offset_days),
        )
        session.add(post)
        session.commit()
        session.refresh(post)
        session.expunge(post)
        return post.slug


def test_build_internal_recommendations_mix_sections():
    long_lead = "A" * 240
    base_slug = _create_post("base-article", "Zdrowie", "Lead bazowy")
    same_1_slug = _create_post("same-1", "Zdrowie", long_lead)
    _create_post("same-2", "Zdrowie", "Lead 2")
    _create_post("same-3", "Zdrowie", "Lead 3", offset_days=2)
    _create_post("other-1", "Ajurweda", "Inny lead")

    with SessionLocal() as session:
        recs = build_internal_recommendations(
            session,
            current_slug=base_slug,
            current_section="Zdrowie",
        )

    assert all(item["slug"] != base_slug for item in recs)
    assert len({item["slug"] for item in recs}) == len(recs)
    assert any(item["section"] != "Zdrowie" for item in recs)
    assert any(item["section"] == "Zdrowie" for item in recs)
    assert any(item["preview"].endswith("…") for item in recs if item["slug"] == same_1_slug)
    assert 3 <= len(recs) <= 4


def test_format_recommendations_section_includes_titles_and_preview():
    recommendations = [
        {"title": "T1", "url": "/artykuly/a", "preview": "Lead a"},
        {"title": "T2", "url": "/artykuly/b", "preview": "Lead b"},
    ]

    content = format_recommendations_section(recommendations)

    assert "Przeczytaj również" in content
    assert "[T1](/artykuly/a)" in content
    assert "Lead a" in content
