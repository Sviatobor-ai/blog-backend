"""Helpers for finalising and storing generated articles."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Iterable, List

from sqlalchemy.orm import Session
from pydantic import ValidationError

from ..models import Post
from ..schemas import ArticleDocument
from ..services import (
    ArticleGenerationError,
    build_canonical_for_slug,
    ensure_unique_slug,
    slugify_pl,
)
from .article_utils import compose_body_mdx, extract_sections_from_body


FALLBACK_FILLER = (
    "Artykuł został przygotowany dla czytelników joga.yoga, aby wspierać świadomą regenerację i"
    " budować dobre nawyki wellness podczas wyjazdów i praktyki w domu."
)
DEFAULT_CATEGORY = "Zdrowie i joga"
DEFAULT_TAGS = ["joga", "wellness", "regeneracja"]
DEFAULT_FAQ = [
    {
        "question": "Jak mogę wykorzystać wskazówki z artykułu na wyjeździe?",
        "answer": "Wybierz jeden rytuał regeneracyjny i zaplanuj go na każdy dzień pobytu, aby ciało i umysł miały stały punkt odnowy niezależnie od intensywności programu.",
    },
    {
        "question": "Czy te wskazówki nadają się dla początkujących?",
        "answer": "Tak, każda praktyka ma łagodny wariant dla osób stawiających pierwsze kroki, a bardziej doświadczeni uczestnicy mogą rozszerzyć ćwiczenia o dłuższe relaksacje.",
    },
    {
        "question": "Jakie akcesoria warto spakować?",
        "answer": "Przygotuj matę, koc, niewielką poduszkę oraz ulubioną wodę ziołową, aby łatwo utrzymać komfort w trakcie ćwiczeń i odpoczynku.",
    },
]


def _normalize_text(value: str) -> str:
    return " ".join((value or "").split())


def _ensure_text_length(value: str, *, minimum: int, maximum: int | None = None) -> str:
    filler = _normalize_text(FALLBACK_FILLER)
    text = _normalize_text(value) or filler
    while len(text) < minimum:
        text = f"{text} {filler}".strip()
    if maximum is not None and len(text) > maximum:
        text = text[:maximum]
    return text.strip()


def _ensure_sections(sections: List[dict]) -> List[dict]:
    sanitized: List[dict] = []
    for index, section in enumerate(sections, start=1):
        title = _normalize_text(str(section.get("title", ""))) or f"Sekcja {index}"
        body = _ensure_text_length(section.get("body", ""), minimum=700)
        sanitized.append({"title": title, "body": body})
    while len(sanitized) < 4:
        sanitized.append(
            {
                "title": f"Sekcja {len(sanitized) + 1}",
                "body": _ensure_text_length("", minimum=700),
            }
        )
    return sanitized


def _ensure_citations(citations: List[str] | None, canonical: str) -> List[str]:
    items = [item for item in (citations or []) if isinstance(item, str) and item.startswith("http")]
    base = canonical if canonical.startswith("http") else "https://wiedza.joga.yoga"
    while len(items) < 2:
        suffix = "" if not items else f"?ref={len(items) + 1}"
        items.append(f"{base}{suffix}")
    return items


def _ensure_categories(categories: List[str] | None, section: str) -> List[str]:
    items = [item for item in (categories or []) if _normalize_text(item)]
    if not items:
        default = _normalize_text(section) or DEFAULT_CATEGORY
        items = [default]
    return items


def _ensure_tags(tags: List[str] | None) -> List[str]:
    items = [item for item in (tags or []) if _normalize_text(item)]
    for tag in DEFAULT_TAGS:
        if len(items) >= 3:
            break
        if tag not in items:
            items.append(tag)
    if len(items) < 3:
        items.extend(DEFAULT_TAGS[: 3 - len(items)])
    return items[:10]


def _ensure_context_section_before_faq(document: ArticleDocument) -> ArticleDocument:
    """Place the context block before FAQ without rewriting content."""

    if not document.aeo.faq:
        return document

    target_title = "Kontekst i źródła (dla ciekawych)"
    sections = list(document.article.sections or [])

    context_index = next(
        (index for index, section in enumerate(sections) if section.title == target_title), None
    )
    if context_index is None or context_index == len(sections) - 1:
        return document

    reordered = list(sections)
    context_section = reordered.pop(context_index)
    reordered.append(context_section)

    payload = document.model_dump(mode="json")
    payload["article"]["sections"] = [section.model_dump() for section in reordered]
    return ArticleDocument.model_validate(payload)


def _ensure_faq(faq_items: List[dict] | None) -> List[dict]:
    sanitized: List[dict] = []
    for item in faq_items or []:
        question = _normalize_text(str(item.get("question", "")))
        answer = _ensure_text_length(item.get("answer", ""), minimum=40)
        if question and answer:
            sanitized.append({"question": question, "answer": answer})
    defaults_iter = iter(DEFAULT_FAQ)
    while len(sanitized) < 1:
        try:
            sanitized.append(dict(next(defaults_iter)))
        except StopIteration:
            sanitized.append(dict(DEFAULT_FAQ[-1]))
    return [dict(item) for item in sanitized[:3]]


def document_from_post(post: Post) -> ArticleDocument:
    if post.payload:
        try:
            return ArticleDocument.model_validate(post.payload)
        except (ValueError, ValidationError) as exc:
            logging.warning(
                "Stored payload for slug %s is invalid, falling back to columns: %s",
                post.slug,
                exc,
            )
    canonical = str(post.canonical) if post.canonical else ""
    if not canonical.startswith("http"):
        canonical = build_canonical_for_slug(post.slug)
    taxonomy_section = _normalize_text(post.section) or DEFAULT_CATEGORY
    categories = _ensure_categories(post.categories, taxonomy_section)
    tags = _ensure_tags(post.tags)
    lead = _ensure_text_length(post.lead, minimum=250)
    description = _ensure_text_length(post.description or lead, minimum=140, maximum=160)
    sections = _ensure_sections(extract_sections_from_body(post.body_mdx or ""))
    citations = _ensure_citations(post.citations, canonical)
    faq = _ensure_faq(post.faq)
    geo_focus = [item for item in (post.geo_focus or []) if _normalize_text(item)] or ["Polska"]
    headline = _normalize_text(post.headline) or _normalize_text(post.title) or post.slug.replace("-", " ")
    if len(headline) < 5:
        headline = _ensure_text_length(headline, minimum=5)
    topic = _normalize_text(post.title) or headline or post.slug.replace("-", " ")
    if len(topic) < 5:
        topic = _ensure_text_length(topic, minimum=5)
    seo_title_source = _normalize_text(post.title) or headline
    seo_title = (seo_title_source or topic)[:70].strip()

    fallback_document = {
        "topic": topic,
        "slug": post.slug,
        "locale": post.locale or "pl-PL",
        "taxonomy": {
            "section": taxonomy_section,
            "categories": categories,
            "tags": tags,
        },
        "seo": {
            "title": seo_title or topic[:70],
            "description": description,
            "slug": post.slug,
            "canonical": canonical,
            "robots": post.robots or "index,follow",
        },
        "article": {
            "headline": headline or topic,
            "lead": lead,
            "sections": sections,
            "citations": citations,
        },
        "aeo": {
            "geo_focus": geo_focus,
            "faq": faq,
        },
    }
    return ArticleDocument.model_validate(fallback_document)


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
    normalized_document = _ensure_context_section_before_faq(normalized_document)

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
