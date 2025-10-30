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
    generator=None,
) -> Post:
    """Generate and publish an article from raw transcript text."""

    transcript_generator = generator or get_transcript_generator()
    payload = transcript_generator.generate_from_transcript(
        raw_text=raw_text,
        source_url=source_url,
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
    post = persist_article_document(db, document)
    return post
