import os
import sys
from copy import deepcopy

os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_article_publication.db")
os.environ.setdefault("NEXT_PUBLIC_SITE_URL", "https://wiedza.joga.yoga")

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app.services.article_publication import apply_sources_presentation, sanitize_faq
from app.services.source_links import extract_urls, normalize_url


def test_sanitize_faq_removes_empty_and_dedupes():
    faq_items = [
        {"question": " Jak oddychać? ", "answer": "  Powoli i świadomie.  "},
        {"question": "jak oddychać?", "answer": "Druga odpowiedź"},
        {"question": "Pozycja góry", "answer": "  Stabilna postawa\n"},
        {"question": " ", "answer": "Brak"},
    ]

    sanitized = sanitize_faq(deepcopy(faq_items))

    assert sanitized == [
        {"question": "Jak oddychać?", "answer": "Powoli i świadomie."},
        {"question": "Pozycja góry", "answer": "Stabilna postawa"},
    ]


def test_apply_sources_presentation_dedupes_links_and_clears_citations():
    document_data = {
        "article": {
            "sections": [
                {
                    "title": "Sekcja 1",
                    "body": (
                        "Pierwszy link [Pierwotny](https://example.com/path#frag) oraz "
                        "[Powtórzony](https://example.com/path/) i dodatkowo https://docs.example.com/guide "
                        "z opisem tematu."
                    ),
                },
                {
                    "title": "Sekcja 2",
                    "body": "Dodany [Kontekst](https://docs.example.com/guide) w dalszej części artykułu.",
                },
            ],
            "citations": [
                "https://example.com/path",
                "https://docs.example.com/guide",
                "https://third.example.com/extra/",
            ],
        }
    }

    updated, final_citations = apply_sources_presentation(deepcopy(document_data))

    sections = updated["article"]["sections"]
    body_urls = []
    for section in sections:
        body_urls.extend(extract_urls(section["body"]))

    normalized_body_urls = [normalize_url(url) for url in body_urls]
    assert normalized_body_urls.count("https://example.com/path") == 1
    assert normalized_body_urls.count("https://docs.example.com/guide") == 1

    assert updated["article"]["citations"] == []
    assert final_citations == [
        "https://example.com/path",
        "https://docs.example.com/guide",
        "https://third.example.com/extra",
    ]
