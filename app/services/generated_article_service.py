"""Service layer for orchestrating article generation flows."""

from __future__ import annotations

import json
import logging
from typing import Callable

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.orm import Session

from ..integrations.supadata import (
    SupaDataClient,
    SupadataTranscriptError,
    SupadataTranscriptTooShortError,
)
from ..models import Rubric
from ..schemas import ArticleCreateRequest, ArticleDocument, ArticlePublishResponse
from . import ArticleGenerationError, OpenAIAssistantArticleGenerator
from .article_publication import persist_article_document, prepare_document_for_publication
from .video_pipeline import generate_article_from_raw

logger = logging.getLogger(__name__)


class GeneratedArticleService:
    """Application service orchestrating article creation."""

    def generate_and_publish(
        self,
        *,
        payload: ArticleCreateRequest,
        db: Session,
        generator: OpenAIAssistantArticleGenerator,
        transcript_generator,
        supadata_provider: Callable[[], SupaDataClient],
        now=None,
    ) -> ArticlePublishResponse:
        from .article_publication import document_from_post

        logger.info(
            "article-generation-start mode=%s topic=%s video_url=%s",
            "video" if payload.video_url else "topic",
            payload.topic,
            payload.video_url,
        )

        if payload.video_url:
            if not transcript_generator.is_configured:
                raise HTTPException(status_code=503, detail="Transcript generator is not configured")
            try:
                supadata = supadata_provider()
                transcript_result = supadata.get_transcript(
                    url=str(payload.video_url),
                    lang="pl",
                    mode="auto",
                    text=True,
                )
                transcript = (transcript_result.text or "").strip()
            except SupadataTranscriptTooShortError as exc:
                logger.warning(
                    "event=supadata.transcript.too_short video_url=%s content_chars=%s threshold=%s",
                    payload.video_url,
                    exc.content_chars,
                    exc.threshold,
                )
                raise HTTPException(
                    status_code=422,
                    detail="Transcript unavailable or too short to generate a reliable article.",
                ) from exc
            except SupadataTranscriptError as exc:
                logger.warning(
                    "event=supadata.transcript.error video_url=%s status_code=%s err=%s",
                    payload.video_url,
                    exc.status_code,
                    exc.error_body,
                )
                status = exc.status_code or 422
                status_code = 422 if status and 400 <= status < 500 else 503
                raise HTTPException(
                    status_code=status_code,
                    detail="Transcript unavailable for this video. Please choose another video.",
                ) from exc
            except Exception as exc:  # pragma: no cover - defensive guard for provider errors
                logger.warning("transcript-fetch failed url=%s err=%s", payload.video_url, exc)
                raise HTTPException(
                    status_code=503,
                    detail="Transcript unavailable for this video. Please choose another video.",
                ) from exc

            try:
                post = generate_article_from_raw(
                    db,
                    raw_text=transcript,
                    source_url=str(payload.video_url),
                    generator=transcript_generator,
                )
            except ArticleGenerationError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc
            document = document_from_post(post)
            logger.info("article-generation-done mode=video slug=%s id=%s", post.slug, post.id)
            return ArticlePublishResponse(slug=post.slug, id=post.id, post=document)

        if not generator.is_configured:
            raise HTTPException(status_code=503, detail="OpenAI API key is not configured")
        rubric_name = "Zdrowie i joga"
        if payload.rubric_code:
            rubric = db.query(Rubric).filter(Rubric.code == payload.rubric_code).one_or_none()
            if rubric:
                rubric_name = rubric.name_pl
        try:
            raw_document = generator.generate_article(
                topic=payload.topic,
                rubric=rubric_name,
                keywords=payload.keywords,
                guidance=payload.guidance,
            )
        except ArticleGenerationError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        try:
            document = ArticleDocument.model_validate(raw_document)
        except (ValueError, ValidationError) as exc:
            try:
                serialized = json.dumps(raw_document, ensure_ascii=False)
            except TypeError:
                serialized = str(raw_document)
            preview = serialized if len(serialized) <= 800 else f"{serialized[:800]}…"
            logger.warning("assistant-draft invalid manual reason=%s payload=%s", exc, preview)
            raise HTTPException(status_code=502, detail=f"Invalid article payload: {exc}") from exc

        document = prepare_document_for_publication(
            db,
            document,
            fallback_topic=payload.topic,
            rubric_name=rubric_name,
        )

        try:
            post = persist_article_document(db, document)
        except ArticleGenerationError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        logger.info("article-generation-done mode=topic slug=%s id=%s", post.slug, post.id)
        return ArticlePublishResponse(slug=post.slug, id=post.id, post=document)

    def create_article(
        self,
        *,
        payload: ArticleCreateRequest,
        db: Session,
        generator: OpenAIAssistantArticleGenerator,
        transcript_generator,
        supadata_provider: Callable[[], SupaDataClient],
        now=None,
    ) -> ArticlePublishResponse:
        return self.generate_and_publish(
            payload=payload,
            db=db,
            generator=generator,
            transcript_generator=transcript_generator,
            supadata_provider=supadata_provider,
            now=now,
        )


def build_request_from_payload(payload: dict) -> ArticleCreateRequest:
    """Normalize external payloads into the canonical request model."""

    url = payload.get("url") or payload.get("video_url")
    topic = payload.get("topic") or "Auto article from queue"
    keywords = payload.get("keywords") or []
    guidance = payload.get("guidance")
    rubric_code = payload.get("rubric_code")

    return ArticleCreateRequest(
        topic=str(topic),
        rubric_code=rubric_code,
        keywords=list(keywords),
        guidance=guidance,
        video_url=url,
    )
