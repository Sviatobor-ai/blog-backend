"""Helpers for finalising and storing generated articles."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy.orm import Session

from ..models import Post
from ..schemas import ArticleDocument
from ..services import (
    ArticleGenerationError,
    build_canonical_for_slug,
    ensure_unique_slug,
    slugify_pl,
)
from .article_utils import compose_body_mdx


def _trim_title_value(value: str, max_len: int) -> str:
    if len(value) <= max_len:
        return value
    trimmed = value[:max_len].rstrip()
    last_space = trimmed.rfind(" ")
    if last_space > 0:
        candidate = trimmed[:last_space].rstrip()
        if candidate:
            return candidate
    return trimmed


def normalize_title_fields(document: ArticleDocument, max_len: int = 60) -> ArticleDocument:
    """Ensure title-like fields respect the provided length limit."""

    seo_title = _trim_title_value(document.seo.title, max_len)
    headline = _trim_title_value(document.article.headline, max_len)

    if seo_title == document.seo.title and headline == document.article.headline:
        return document

    payload = document.model_dump(mode="json")
    payload["seo"]["title"] = seo_title
    payload["article"]["headline"] = headline
    return ArticleDocument.model_validate(payload)


def prepare_document_for_publication(
    db: Session,
    document: ArticleDocument,
    *,
    fallback_topic: str,
    rubric_name: str,
    canonical_override: str | None = None,
) -> ArticleDocument:
    """Normalise slug, canonical URL and taxonomy before persistence."""

    normalized_document = normalize_title_fields(document)

    desired_slug_source = (
        normalized_document.slug
        or normalized_document.seo.slug
        or normalized_document.seo.title
        or fallback_topic
    )
    desired_slug = slugify_pl(desired_slug_source)
    if not desired_slug:
        desired_slug = slugify_pl(fallback_topic) or "artykul"

    existing_slugs: Iterable[str] = [slug for (slug,) in db.query(Post.slug).all()]
    final_slug = ensure_unique_slug(existing_slugs, desired_slug)

    canonical = canonical_override or build_canonical_for_slug(final_slug)

    document_data = normalized_document.model_dump(mode="json")
    document_data["slug"] = final_slug
    document_data.setdefault("taxonomy", {})["section"] = rubric_name
    document_data.setdefault("seo", {})["slug"] = final_slug
    document_data["seo"]["canonical"] = canonical
    return ArticleDocument.model_validate(document_data)


def persist_article_document(db: Session, document: ArticleDocument) -> Post:
    """Store the provided article document and return the created Post."""

    body_mdx = compose_body_mdx([section.model_dump() for section in document.article.sections])
    if not body_mdx:
        raise ArticleGenerationError("Assistant returned empty article sections")

    post = Post(
        slug=document.slug,
        locale=document.locale,
        section=document.taxonomy.section,
        categories=document.taxonomy.categories,
        tags=document.taxonomy.tags,
        title=document.seo.title,
        description=document.seo.description,
        canonical=str(document.seo.canonical),
        robots=document.seo.robots,
        headline=document.article.headline,
        lead=document.article.lead,
        body_mdx=body_mdx,
        geo_focus=document.aeo.geo_focus,
        faq=[faq.model_dump() for faq in document.aeo.faq],
        citations=[str(url) for url in document.article.citations],
        payload=document.model_dump(mode="json"),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(post)
    db.commit()
    db.refresh(post)
    return post
