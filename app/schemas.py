"""Pydantic schemas for article generation and publishing."""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, List, Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator


class ArticleSection(BaseModel):
    """Represents a single markdown section of the article body."""

    title: str = Field(..., min_length=3)
    body: str = Field(..., min_length=400)


class ArticleFAQ(BaseModel):
    """Small FAQ entry located at the end of the article."""

    question: str = Field(..., min_length=5)
    answer: str = Field(..., min_length=10)


class ArticleContent(BaseModel):
    """Article narrative with structured sections."""

    headline: str
    lead: str = Field(..., min_length=250)
    sections: List[ArticleSection] = Field(..., min_length=4)
    citations: List[HttpUrl] = Field(..., min_length=2)


class ArticleSEO(BaseModel):
    """SEO metadata used across the platform."""

    title: str = Field(..., max_length=70)
    description: str = Field(..., min_length=140, max_length=160)
    slug: str = Field(..., pattern=r"^[a-z0-9-]{3,200}$")
    canonical: HttpUrl
    robots: Literal["index,follow"] = "index,follow"


class ArticleTaxonomy(BaseModel):
    """Classification of the article on the site."""

    section: str
    categories: List[str] = Field(..., min_length=1)
    tags: List[str] = Field(..., min_length=3)


class ArticleAEO(BaseModel):
    """Answer Engine Optimisation data: geo focus and FAQ."""

    geo_focus: List[str] = Field(..., min_length=1)
    faq: List[ArticleFAQ] = Field(..., min_length=2, max_length=3)


class ArticleDocument(BaseModel):
    """Complete structured article returned by the assistant."""

    topic: str = Field(..., min_length=5)
    slug: str = Field(..., pattern=r"^[a-z0-9-]{3,200}$")
    locale: Literal["pl-PL"] = "pl-PL"
    taxonomy: ArticleTaxonomy
    seo: ArticleSEO
    article: ArticleContent
    aeo: ArticleAEO

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, value: str) -> str:
        if len(value) < 3:
            raise ValueError("slug must have at least 3 characters")
        return value

    @field_validator("locale")
    @classmethod
    def validate_locale(cls, value: str) -> str:
        if value != "pl-PL":
            raise ValueError("locale must be pl-PL")
        return value


class ArticleCreateRequest(BaseModel):
    """Incoming payload to request article creation."""

    topic: str = Field(..., min_length=5, max_length=200)
    rubric_code: str | None = Field(default=None, max_length=64)
    keywords: List[str] = Field(default_factory=list)
    guidance: str | None = Field(default=None, max_length=500)

    @field_validator("rubric_code")
    @classmethod
    def validate_rubric_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            return None
        if not all(ch.isalnum() or ch in {"-", "_"} for ch in cleaned):
            raise ValueError("rubric_code contains invalid characters")
        return cleaned

    @field_validator("keywords")
    @classmethod
    def sanitize_keywords(cls, value: Iterable[str]) -> List[str]:
        sanitized: List[str] = []
        for item in value:
            text = " ".join(item.split())
            if text:
                sanitized.append(text[:80])
        return sanitized[:6]


class ArticlePublishResponse(BaseModel):
    """Response returned when an article is generated and stored."""

    status: Literal["published"] = "published"
    slug: str
    id: int
    post: ArticleDocument


class ArticleSummary(BaseModel):
    """Summary entry returned on list endpoints."""

    slug: str
    title: str
    section: str | None
    tags: List[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class PaginationMeta(BaseModel):
    """Pagination envelope returned alongside collection data."""

    page: int
    per_page: int
    total_items: int
    total_pages: int


class ArticleListResponse(BaseModel):
    """Paginated list response."""

    meta: PaginationMeta
    items: List[ArticleSummary]


