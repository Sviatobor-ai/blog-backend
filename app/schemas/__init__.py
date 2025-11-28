"""Pydantic schemas for article generation and publishing."""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, List, Literal

from pydantic import AnyHttpUrl, BaseModel, Field, HttpUrl, constr, field_validator

from ..article_schema import (
    ARTICLE_FAQ_MAX,
    ARTICLE_FAQ_MIN,
    ARTICLE_MIN_CITATIONS,
    ARTICLE_MIN_LEAD,
    ARTICLE_MIN_SECTIONS,
    ARTICLE_MIN_TAGS,
)


class ArticleSection(BaseModel):
    """Represents a single markdown section of the article body."""

    title: str = Field(..., min_length=3)
    body: str = Field(..., min_length=400)


class ArticleFAQ(BaseModel):
    """Small FAQ entry located at the end of the article."""

    question: str = Field(..., min_length=5)
    answer: str = Field(..., min_length=10)


SEO_TITLE_PATTERN = r"^[^:\n]{1,60}$"
ShortTitle = constr(min_length=5, max_length=60, pattern=SEO_TITLE_PATTERN)


def _ensure_contains_letter(value: str, field_name: str) -> str:
    trimmed = value.strip()
    if len(trimmed) < 5:
        raise ValueError(f"{field_name} must contain at least five characters")
    if any(char.isalpha() for char in trimmed):
        return trimmed
    raise ValueError(f"{field_name} must contain at least one letter")


class ArticleContent(BaseModel):
    """Article narrative with structured sections."""

    headline: ShortTitle
    lead: str = Field(..., min_length=ARTICLE_MIN_LEAD)
    sections: List[ArticleSection] = Field(..., min_length=ARTICLE_MIN_SECTIONS)
    citations: List[HttpUrl] = Field(..., min_length=ARTICLE_MIN_CITATIONS)

    @field_validator("headline")
    @classmethod
    def validate_headline(cls, value: str) -> str:
        return _ensure_contains_letter(value, field_name="headline")


class ArticleSEO(BaseModel):
    """SEO metadata used across the platform."""

    title: ShortTitle
    description: str = Field(..., min_length=120, max_length=160)
    slug: str = Field(..., pattern=r"^[a-z0-9-]{3,200}$")
    canonical: HttpUrl
    robots: Literal["index,follow"] = "index,follow"

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        return _ensure_contains_letter(value, field_name="seo.title")


class ArticleTaxonomy(BaseModel):
    """Classification of the article on the site."""

    section: str
    categories: List[str] = Field(..., min_length=1)
    tags: List[str] = Field(..., min_length=ARTICLE_MIN_TAGS)


class ArticleAEO(BaseModel):
    """Answer Engine Optimisation data: geo focus and FAQ."""

    geo_focus: List[str] = Field(..., min_length=1)
    faq: List[ArticleFAQ] = Field(..., min_length=ARTICLE_FAQ_MIN, max_length=ARTICLE_FAQ_MAX)


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
    video_url: AnyHttpUrl | None = None

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

    @field_validator("video_url", mode="before")
    @classmethod
    def ensure_single_video(cls, value):
        if isinstance(value, (list, tuple)):
            raise ValueError("Only one video URL is supported")
        return value


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
    headline: str | None = None
    lead: str | None = None
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


