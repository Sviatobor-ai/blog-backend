"""JSON schema definition for generated Polish wellness articles."""

from __future__ import annotations

from typing import Any, Dict

ARTICLE_DOCUMENT_SCHEMA: Dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://joga.yoga/schemas/polish-article.json",
    "title": "PolishRetreatArticle",
    "type": "object",
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
                    "minItems": 3,
                    "items": {"type": "string"},
                },
            },
        },
        "seo": {
            "type": "object",
            "required": ["title", "description", "slug", "canonical", "robots"],
            "properties": {
                "title": {
                    "type": "string",
                    "maxLength": 70,
                    "description": "SEO title w języku polskim.",
                },
                "description": {
                    "type": "string",
                    "minLength": 140,
                    "maxLength": 160,
                    "description": "Meta description zoptymalizowany pod SEO.",
                },
                "slug": {
                    "type": "string",
                    "pattern": "^[a-z0-9-]{3,200}$",
                },
                "canonical": {
                    "type": "string",
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
            "required": ["headline", "lead", "sections", "citations"],
            "properties": {
                "headline": {
                    "type": "string",
                    "description": "Nagłówek artykułu w języku polskim.",
                },
                "lead": {
                    "type": "string",
                    "minLength": 250,
                    "description": "Lead o długości 60-80 słów.",
                },
                "sections": {
                    "type": "array",
                    "minItems": 4,
                    "items": {
                        "type": "object",
                        "required": ["title", "body"],
                        "properties": {
                            "title": {"type": "string"},
                            "body": {
                                "type": "string",
                                "minLength": 400,
                                "description": "Sekcja artykułu z akapitami i wypunktowaniem, jeżeli potrzebne.",
                            },
                        },
                    },
                },
                "citations": {
                    "type": "array",
                    "minItems": 2,
                    "items": {
                        "type": "string",
                        "format": "uri",
                    },
                },
            },
        },
        "aeo": {
            "type": "object",
            "required": ["geo_focus", "faq"],
            "properties": {
                "geo_focus": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"type": "string"},
                },
                "faq": {
                    "type": "array",
                    "minItems": 2,
                    "maxItems": 3,
                    "items": {
                        "type": "object",
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

__all__ = ["ARTICLE_DOCUMENT_SCHEMA"]
