"""JSON schema definition for generated Polish wellness articles."""

from __future__ import annotations

from typing import Any, Dict

ARTICLE_MIN_LEAD = 180
ARTICLE_MIN_SECTIONS = 4
ARTICLE_MIN_CITATIONS = 2
ARTICLE_FAQ_MIN = 2
ARTICLE_FAQ_MAX = 4
ARTICLE_MIN_TAGS = 2


ARTICLE_DOCUMENT_SCHEMA: Dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://joga.yoga/schemas/polish-article.json",
    "title": "PolishRetreatArticle",
    "type": "object",
    "additionalProperties": False,
    "required": ["topic", "slug", "locale", "taxonomy", "seo", "article", "aeo"],
    "properties": {
        "topic": {
            "type": "string",
            "minLength": 5,
            "description": "Główny temat artykułu w języku polskim.",
        },
        "slug": {
            "type": "string",
            "pattern": "^[a-z0-9-]{3,200}$",
            "description": "Slug artykułu wygenerowany z tytułu.",
        },
        "locale": {
            "type": "string",
            "const": "pl-PL",
            "description": "Kod językowy artykułu.",
        },
        "taxonomy": {
            "type": "object",
            "additionalProperties": False,
            "required": ["section", "categories", "tags"],
            "properties": {
                "section": {
                    "type": "string",
                    "description": "Nazwa rubryki dopasowana do tematu.",
                },
                "categories": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"type": "string"},
                },
                "tags": {
                    "type": "array",
                    "minItems": ARTICLE_MIN_TAGS,
                    "items": {"type": "string"},
                },
            },
        },
        "seo": {
            "type": "object",
            "additionalProperties": False,
            "required": ["title", "description", "slug", "canonical", "robots"],
            "properties": {
                "title": {
                    "type": "string",
                    "maxLength": 60,
                    "pattern": "^[^:\n]{1,60}$",
                    "description": (
                        "Jednowierszowy tytuł SEO (55-60 znaków) bez dwukropków, zawierający kluczowe słowo w języku polskim."
                    ),
                },
                "description": {
                    "type": "string",
                    "minLength": 120,
                    "maxLength": 170,
                    "description": "Meta description zoptymalizowany pod SEO.",
                },
                "slug": {
                    "type": "string",
                    "pattern": "^[a-z0-9-]{3,200}$",
                },
                "canonical": {
                    "type": "string",
                    "description": "Pełny adres kanoniczny (http/https).",
                    "format": "uri",
                },
                "robots": {
                    "type": "string",
                    "enum": ["index,follow"],
                },
            },
        },
        "article": {
            "type": "object",
            "additionalProperties": False,
            "required": ["headline", "lead", "sections", "citations"],
            "properties": {
                "headline": {
                    "type": "string",
                    "maxLength": 60,
                    "pattern": "^[^:\n]{1,60}$",
                    "description": (
                        "Jednowierszowy nagłówek artykułu (55-60 znaków) bez dwukropków, zawierający kluczowe słowo w języku polskim."
                    ),
                },
                "lead": {
                    "type": "string",
                    "minLength": ARTICLE_MIN_LEAD,
                    "description": "Lead wprowadzający o kilku akapitach.",
                },
                "sections": {
                    "type": "array",
                    "minItems": ARTICLE_MIN_SECTIONS,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["title", "body"],
                        "properties": {
                            "title": {"type": "string"},
                            "body": {
                                "type": "string",
                                "minLength": 400,
                                "description": "Sekcja artykułu z akapitami i wypunktowaniem, jeśli potrzebne.",
                            },
                        },
                    },
                },
                "citations": {
                    "type": "array",
                    "minItems": ARTICLE_MIN_CITATIONS,
                    "items": {
                        "type": "string",
                        "format": "uri",
                        "description": "Źródło w postaci pełnego URL (http/https).",
                    },
                },
            },
        },
        "aeo": {
            "type": "object",
            "additionalProperties": False,
            "required": ["geo_focus", "faq"],
            "properties": {
                "geo_focus": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"type": "string"},
                },
                "faq": {
                    "type": "array",
                    "minItems": ARTICLE_FAQ_MIN,
                    "maxItems": ARTICLE_FAQ_MAX,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["question", "answer"],
                        "properties": {
                            "question": {"type": "string"},
                            "answer": {
                                "type": "string",
                                "description": "Zwięzła odpowiedź na pytanie wynikające z treści artykułu.",
                            },
                        },
                    },
                },
            },
        },
    },
}

__all__ = [
    "ARTICLE_DOCUMENT_SCHEMA",
    "ARTICLE_MIN_LEAD",
    "ARTICLE_MIN_SECTIONS",
    "ARTICLE_MIN_CITATIONS",
    "ARTICLE_FAQ_MIN",
    "ARTICLE_FAQ_MAX",
    "ARTICLE_MIN_TAGS",
]
