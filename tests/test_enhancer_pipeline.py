import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_enhancer_pipeline.db")

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.enhancer.deep_search import DeepSearchSource  # noqa: E402
from app.enhancer.pipeline import ArticleEnhancer  # noqa: E402
from app.enhancer.writer import EnhancementResponse  # noqa: E402
from app.schemas import ArticleDocument  # noqa: E402


@pytest.fixture()
def enhancer() -> ArticleEnhancer:
    return ArticleEnhancer(search_client=object(), writer=object())


def _sample_document() -> ArticleDocument:
    section_body = "B" * 450
    base = {
        "topic": "Joga na stres",
        "slug": "joga-na-stres",
        "locale": "pl-PL",
        "taxonomy": {
            "section": "Wellness",
            "categories": ["Wellness"],
            "tags": ["joga", "stress"],
        },
        "seo": {
            "title": "Joga na stres i ukojenie",
            "description": ("Przewodnik" * 12)[:160],
            "slug": "joga-na-stres",
            "canonical": "https://wiedza.joga.yoga/artykuly/joga-na-stres",
            "robots": "index,follow",
        },
        "article": {
            "headline": "Joga na stres",
            "lead": "L" * 200,
            "sections": [
                {"title": "Sekcja 1", "body": section_body},
                {"title": "Sekcja 2", "body": section_body},
                {"title": "Sekcja 3", "body": section_body},
                {"title": "Sekcja 4", "body": section_body},
            ],
            "citations": ["https://example.com/a"],
        },
        "aeo": {
            "geo_focus": ["Polska"],
            "faq": [
                {
                    "question": "Jak zacząć ćwiczyć oddech w pracy?",
                    "answer": "Znajdź dwie minuty na spokojne wdechy nosem i wydłużony wydech ustami.",
                },
                {
                    "question": "Czy joga na stres wymaga akcesoriów?",
                    "answer": "Wystarczy mata i koc, ale przydatne są paski do rozciągania ramion.",
                },
                {
                    "question": "Jak często powtarzać sekwencję uspokajającą?",
                    "answer": "Ćwicz trzy razy w tygodniu, łącząc łagodne skłony i skręty z oddechem.",
                },
                {
                    "question": "Co robić po treningu redukującym napięcie?",
                    "answer": "Połóż się na macie, obserwuj tętno i zapisz wrażenia, by utrwalać progres.",
                },
            ],
        },
    }
    return ArticleDocument.model_validate(base)


def test_select_citations_filters_blocked_domains_and_duplicates(enhancer: ArticleEnhancer):
    sources = [
        DeepSearchSource(url="https://example.com/one", title="One", score=0.9, published_at="2024-06-01"),
        DeepSearchSource(url="https://example.com/one", title="Dup", score=0.1),
        DeepSearchSource(url="https://blocked.ru/bad", title="Blocked"),
        DeepSearchSource(url="https://fresh.com/new", title="Fresh", published_at="2024-06-02"),
        DeepSearchSource(url="https://older.com/old", title="Old", published_at="2023-05-01", score=0.5),
        DeepSearchSource(url="https://another.com/ok", title="Another"),
        DeepSearchSource(url="https://fifth.com/ok", title="Fifth"),
        DeepSearchSource(url="https://sixth.com/ok", title="Sixth"),
        DeepSearchSource(url="https://seventh.com/ok", title="Seventh"),
    ]

    citations = enhancer._select_citations(sources)

    assert len(citations) == 6
    assert all(not item.url.endswith(".ru") for item in citations)
    assert citations[0].url == "https://fresh.com/new"
    assert "https://seventh.com/ok" not in {item.url for item in citations}
    assert len({item.url for item in citations}) == len(citations)


def test_apply_updates_appends_sections_and_updates_faq(enhancer: ArticleEnhancer):
    document = _sample_document()
    response = EnhancementResponse(
        added_sections=[
            {"title": "Nowe rytuały oddechowe", "body": "C" * 500},
            {"title": "Regeneracja przy biurku", "body": "D" * 500},
        ],
        added_faq={"question": "Jak długo ćwiczyć?", "answer": "Pełna i konkretna odpowiedź"},
    )
    citations = ["https://new.example/one", "https://new.example/two"]

    updated = enhancer._apply_updates(document=document, response=response, citations=citations)

    assert len(updated.article.sections) == len(document.article.sections) + 2
    assert updated.article.sections[-2].title == "Nowe rytuały oddechowe"
    assert updated.article.sections[-1].title == "Regeneracja przy biurku"
    assert [str(url) for url in updated.article.citations] == citations
    assert updated.aeo.faq[-1].question == "Jak długo ćwiczyć?"
    # Oldest FAQ entry removed to respect ARTICLE_FAQ_MAX
    assert all(item.question != "Q1" for item in updated.aeo.faq)


def test_merge_single_citation_preserves_existing_order(enhancer: ArticleEnhancer):
    existing = [
        "https://example.com/one",
        "https://example.com/two",
        "https://example.com/three",
    ]
    merged = enhancer._merge_single_citation(existing, "https://fresh.com/new")
    assert merged[0] == "https://fresh.com/new"
    assert merged[1:] == existing


def test_merge_single_citation_limits_total_count(enhancer: ArticleEnhancer):
    existing = [f"https://example.com/{idx}" for idx in range(10)]
    merged = enhancer._merge_single_citation(existing, "https://fresh.com/new")
    assert len(merged) == 6
    assert merged[0] == "https://fresh.com/new"
