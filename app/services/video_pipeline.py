"""Pipeline helpers turning raw transcripts into published articles."""

from __future__ import annotations

import json
import logging

from pydantic import ValidationError
from sqlalchemy.orm import Session

from ..models import Post
from ..schemas import ArticleDocument
from ..services import (
    ArticleGenerationError,
    get_transcript_generator,
)
from .article_publication import (
    persist_article_document,
    prepare_document_for_publication,
)


logger = logging.getLogger(__name__)


def generate_article_from_raw(
    db: Session,
    *,
    raw_text: str,
    source_url: str,
    source_key: str | None = None,
    generator=None,
    research_content: str | None = None,
    research_sources=None,
    author_context=None,
) -> Post:
    """Generate and publish an article from raw transcript text."""

    transcript_generator = generator or get_transcript_generator()
    payload = transcript_generator.generate_from_transcript(
        raw_text=raw_text,
        source_url=source_url,
        research_content=research_content,
        research_sources=research_sources,
        author_context=author_context,
    )
    try:
        document = ArticleDocument.model_validate(payload)
    except (ValueError, ValidationError) as exc:  # pragma: no cover - defensive guard
        try:
            serialized = json.dumps(payload, ensure_ascii=False)
        except TypeError:
            serialized = str(payload)
        preview = serialized if len(serialized) <= 800 else f"{serialized[:800]}…"
        logger.warning("assistant-draft invalid transcript reason=%s payload=%s", exc, preview)
        raise ArticleGenerationError(f"Invalid article payload: {exc}") from exc

    citations = {str(url) for url in document.article.citations}
    if source_url not in citations:
        data = document.model_dump(mode="json")
        data.setdefault("article", {}).setdefault("citations", []).append(source_url)
        document = ArticleDocument.model_validate(data)

    rubric_name = document.taxonomy.section or "Automatyczne publikacje"
    fallback_topic = document.topic or document.seo.title or "Artykuł joga.yoga"

    document = prepare_document_for_publication(
        db,
        document,
        fallback_topic=fallback_topic,
        rubric_name=rubric_name,
    )
    _warn_low_voice_match(document, author_context)
    extra_payload = {"meta": {"source_key": source_key}} if source_key else None
    post = persist_article_document(db, document, extra_payload=extra_payload)
    return post


def _warn_low_voice_match(document: ArticleDocument, author_context) -> None:
    if not author_context or not getattr(author_context, "voice_markers", None):
        return

    full_text_parts = [
        document.article.headline,
        document.article.lead,
        " ".join(section.body for section in document.article.sections),
    ]
    full_text = " \n".join(full_text_parts).lower()
    marker_hits = sum(
        1
        for marker in getattr(author_context, "voice_markers", [])
        if isinstance(marker, str) and marker.lower() in full_text
    )
    if marker_hits < 1:
        logger.warning(
            "author_voice_low_match slug=%s markers=%s", document.slug, len(author_context.voice_markers)
        )
