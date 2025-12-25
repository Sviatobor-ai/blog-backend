"""Helpers for finalising and storing generated articles."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Iterable, List, Tuple

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
from .source_links import (
    dedupe_preserve_order,
    enforce_single_hyperlink_per_url,
    extract_urls,
    normalize_url,
)
from .article_utils import compose_body_mdx, extract_sections_from_body
from .internal_links import build_internal_recommendations, format_recommendations_section


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

SOURCE_SECTION_TITLES = {"źródła", "zrodla"}


def sanitize_faq(faq_items: list[dict] | None) -> list[dict]:
    if not faq_items:
        return []

    sanitized: List[dict] = []
    seen_questions = set()

    for item in faq_items:
        if not isinstance(item, dict):
            continue

        question_raw = "" if item is None else str(item.get("question", ""))
        answer_raw = "" if item is None else str(item.get("answer", ""))

        question = " ".join(question_raw.split()).strip()
        answer = " ".join(answer_raw.split()).strip()

        if not question or not answer:
            continue

        normalized_question = question.casefold()
        if normalized_question in seen_questions:
            continue

        seen_questions.add(normalized_question)
        sanitized.append({"question": question, "answer": answer})

    return sanitized


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


def _collect_candidate_citations(article_data: dict, research_sources) -> list[str]:
    urls = [str(url) for url in (article_data.get("citations") or []) if isinstance(url, str)]

    for source in research_sources or []:
        candidate = None
        if isinstance(source, str):
            candidate = source
        elif isinstance(source, dict):
            candidate = source.get("url") or source.get("link")
        else:
            candidate = getattr(source, "url", None) or getattr(source, "link", None)
        if candidate:
            urls.append(str(candidate))

    return dedupe_preserve_order(urls)


def _rewrite_sections_with_single_links(article_data: dict) -> tuple[list[dict], list[str]]:
    seen_urls: set[str] = set()
    sanitized_sections: list[dict] = []
    for section in article_data.get("sections") or []:
        body = str(section.get("body", ""))
        rewritten_body, seen_urls = enforce_single_hyperlink_per_url(body, seen_urls)
        sanitized_sections.append({**section, "body": rewritten_body})

    article_data["sections"] = sanitized_sections
    body_urls = dedupe_preserve_order(
        [
            url
            for section in sanitized_sections
            for url in extract_urls(section.get("body", ""))
        ]
    )
    return sanitized_sections, body_urls


def apply_sources_presentation(document_data: dict, *, research_sources=None) -> tuple[dict, list[str]]:
    """Deduplicate source URLs, enforce single hyperlinks and clear the citations list."""

    article_data = document_data.setdefault("article", {})
    sanitized_sections, body_urls = _rewrite_sections_with_single_links(article_data)
    candidate_urls = _collect_candidate_citations(
        article_data,
        research_sources if research_sources is not None else document_data.get("research_sources"),
    )

    inline_normalized = set(normalize_url(url) for url in body_urls)
    external_only = [url for url in candidate_urls if normalize_url(url) not in inline_normalized]
    final_citations = dedupe_preserve_order(body_urls + external_only)
    document_data.setdefault("debug", {})["citations"] = [
        str(url) for url in final_citations if isinstance(url, str)
    ]
    document_data["article"]["citations"] = []
    document_data["article"]["sections"] = sanitized_sections

    return document_data, final_citations


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


def _dedupe_sources_sections(sections: list[dict]) -> Tuple[list[dict], bool]:
    kept: list[dict] = []
    removed = False
    for section in sections:
        title = str(section.get("title", "")).strip()
        normalized = title.casefold()
        if normalized in SOURCE_SECTION_TITLES:
            if any(str(item.get("title", "")).strip().casefold() in SOURCE_SECTION_TITLES for item in kept):
                removed = True
                continue
        kept.append(section)
    return kept, removed


def _upsert_recommendations_section(sections: list[dict], content: str) -> tuple[list[dict], str]:
    cleaned_sections, removed_duplicate = _dedupe_sources_sections(sections)
    target_index = next(
        (
            index
            for index, section in enumerate(cleaned_sections)
            if str(section.get("title", "")).strip().casefold() in SOURCE_SECTION_TITLES
        ),
        None,
    )

    action = "appended"
    if target_index is not None:
        title = cleaned_sections[target_index].get("title") or "Źródła"
        updated = list(cleaned_sections)
        updated[target_index] = {"title": title, "body": content}
        action = "replaced"
        return updated, action

    updated = list(cleaned_sections) + [{"title": "Źródła", "body": content}]
    if removed_duplicate:
        action = "deduped-appended"
    return updated, action


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


def _apply_sanitized_faq_data(document_data: dict, *, slug: str | None = None) -> dict:
    original_items = document_data.get("aeo", {}).get("faq")
    sanitized = sanitize_faq(original_items)
    removed_count = len(original_items or []) - len(sanitized)

    if removed_count > 0:
        logging.info(
            "event=faq_sanitized removed_count=%s kept_count=%s slug=%s",
            removed_count,
            len(sanitized),
            slug,
        )

    document_data.setdefault("aeo", {})["faq"] = sanitized
    return document_data


def _validate_or_construct_document(document_data: dict, *, slug: str | None = None) -> ArticleDocument:
    try:
        return ArticleDocument.model_validate(document_data)
    except ValidationError as exc:
        logging.warning(
            "faq-sanitization validation fallback slug=%s error=%s", slug or document_data.get("slug"), exc
        )
        constructed = ArticleDocument.model_construct(**document_data)
        if not isinstance(constructed, ArticleDocument):
            raise ArticleGenerationError("Failed to recover ArticleDocument after validation") from exc
        return constructed


def document_from_post(post: Post) -> ArticleDocument:
    if post.payload:
        try:
            sanitized_payload = _apply_sanitized_faq_data(dict(post.payload), slug=post.slug)
            sanitized_payload, _ = apply_sources_presentation(sanitized_payload)
            return ArticleDocument.model_validate(sanitized_payload)
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
    sanitized_fallback = _apply_sanitized_faq_data(fallback_document, slug=post.slug)
    sanitized_fallback, _ = apply_sources_presentation(sanitized_fallback)
    return _validate_or_construct_document(sanitized_fallback, slug=post.slug)


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
    sanitized_data = _apply_sanitized_faq_data(document_data, slug=final_slug)
    sanitized_data, cleared_citations = apply_sources_presentation(sanitized_data)

    recommendations = build_internal_recommendations(
        db,
        current_slug=final_slug,
        current_section=rubric_name,
    )
    recommendation_content = format_recommendations_section(recommendations)
    sections = sanitized_data.get("article", {}).get("sections") or []
    updated_sections, action = _upsert_recommendations_section(sections, recommendation_content)
    sanitized_data.setdefault("article", {})["sections"] = updated_sections

    logging.info(
        "event=prepare_document recommendations=%s action=%s citations_cleared=%s slug=%s",
        len(recommendations),
        action,
        len(cleared_citations),
        final_slug,
    )

    return _validate_or_construct_document(sanitized_data, slug=final_slug)


def persist_article_document(
    db: Session, document: ArticleDocument, *, extra_payload: dict | None = None
) -> Post:
    """Store the provided article document and return the created Post."""

    body_mdx = compose_body_mdx([section.model_dump() for section in document.article.sections])
    if not body_mdx:
        raise ArticleGenerationError("Assistant returned empty article sections")

    payload = document.model_dump(mode="json")
    if extra_payload:
        merged_payload = {**payload}
        for key, value in extra_payload.items():
            if isinstance(value, dict) and isinstance(merged_payload.get(key), dict):
                merged_payload[key] = {**merged_payload.get(key, {}), **value}
            else:
                merged_payload[key] = value
        payload = merged_payload

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
        payload=payload,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(post)
    db.commit()
    db.refresh(post)
    return post
