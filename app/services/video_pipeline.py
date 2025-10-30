"""Pipeline helpers turning raw transcripts into published articles."""

from __future__ import annotations

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
