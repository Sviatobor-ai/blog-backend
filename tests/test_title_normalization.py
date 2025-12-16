import os
import sys
from pathlib import Path

os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_title_normalization.db")
os.environ.setdefault("NEXT_PUBLIC_SITE_URL", "https://wiedza.joga.yoga")
os.environ.setdefault("SUPADATA_KEY", "test-key")

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.models import Post  # noqa: E402
from app.schemas import (  # noqa: E402
    ArticleAEO,
    ArticleContent,
    ArticleDocument,
    ArticleFAQ,
    ArticleSEO,
    ArticleSection,
    ArticleTaxonomy,
)
from app.services.article_publication import (  # noqa: E402
    normalize_title_fields,
    prepare_document_for_publication,
)


LONG_TITLE = (
    "Świadome oddychanie w podróży jak zbudować codzienny rytuał oddechu dla stabilności"
)


def _build_valid_document() -> ArticleDocument:
    body = (
        "Praktyka oddechowa wspiera układ nerwowy i poczucie zakorzenienia podczas podróży. "
        "Regularne ćwiczenia pomagają utrzymać spokój i uważność."
    )
    section_body = body + " " + ("Rozwinięcie treści. " * 30)
    taxonomy = ArticleTaxonomy.model_validate(
        {
            "section": "Wellness",
            "categories": ["Wellness"],
            "tags": ["oddech", "mindfulness"],
        }
    )
    seo = ArticleSEO.model_construct(
        title=LONG_TITLE,
        description="Opis meta" + " bardzo" * 20,
        slug="swiadomy-oddech-w-podrozy",
        canonical="https://wiedza.joga.yoga/artykuly/swiadomy-oddech-w-podrozy",
        robots="index,follow",
    )
    sections = [
        ArticleSection.model_validate({"title": f"Sekcja {index}", "body": section_body})
        for index in range(1, 5)
    ]
    article = ArticleContent.model_construct(
        headline=LONG_TITLE,
        lead=body + " " + ("Dodatkowe informacje. " * 20),
        sections=sections,
        citations=["https://przyklad.pl/zrodlo"],
    )
    aeo = ArticleAEO.model_validate(
        {
            "geo_focus": ["Polska"],
            "faq": [
                ArticleFAQ.model_validate(
                    {"question": "Jak ćwiczyć?", "answer": "Regularnie i świadomie."}
                ),
                ArticleFAQ.model_validate(
                    {"question": "Kiedy praktykować?", "answer": "O dowolnej porze dnia."}
                ),
            ],
        }
    )

    return ArticleDocument.model_construct(
        topic="Świadomy oddech w podróży",
        slug="swiadomy-oddech-w-podrozy",
        locale="pl-PL",
        taxonomy=taxonomy,
        seo=seo,
        article=article,
        aeo=aeo,
    )


def test_normalize_title_fields_trims_overflowing_titles():
    document = _build_valid_document()

    normalized = normalize_title_fields(document)

    assert len(normalized.seo.title) <= 60
    assert len(normalized.article.headline) <= 60
    assert normalized.seo.title == normalized.article.headline


def test_prepare_document_for_publication_keeps_slug_and_canonical():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    document = _build_valid_document()

    with SessionLocal() as session:
        prepared = prepare_document_for_publication(
            session,
            document,
            fallback_topic="Zapasy oddechu",
            rubric_name="Wellness",
        )

    assert prepared.slug
    assert str(prepared.seo.canonical).endswith(prepared.slug)
    assert len(prepared.seo.title) <= 60
    assert len(prepared.article.headline) <= 60
