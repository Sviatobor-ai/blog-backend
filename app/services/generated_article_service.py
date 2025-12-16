"""Service layer for orchestrating article generation flows."""

from __future__ import annotations

import json
import logging
import time
from typing import Callable

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.orm import Session

from ..config import get_primary_generation_settings
from ..enhancer.deep_search import DeepSearchError, ParallelDeepSearchClient
from ..services.author_context import build_author_context_from_transcript
from ..enhancer.providers import get_parallel_deep_search_client
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

    def __init__(self) -> None:
        self._primary_settings = get_primary_generation_settings()

    def generate_and_publish(
        self,
        *,
        payload: ArticleCreateRequest,
        db: Session,
        generator: OpenAIAssistantArticleGenerator,
        transcript_generator,
        supadata_provider: Callable[[], SupaDataClient],
        research_client_provider: Callable[[], ParallelDeepSearchClient] | None = None,
        now=None,
    ) -> ArticlePublishResponse:
        from .article_publication import document_from_post

        mode = "video" if payload.video_url else "topic"
        logger.info(
            "article-generation-start mode=%s topic=%s video_url=%s research_enabled=%s",
            mode,
            payload.topic,
            payload.video_url,
            self._primary_settings.research_enabled,
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

            research_summary: str | None = None
            research_sources = []
            transcript_excerpt = transcript[:800]
            author_context = build_author_context_from_transcript(transcript)
            rubric_name = _resolve_rubric_name(payload, db)
            if self._primary_settings.research_enabled:
                research_summary, research_sources = self._run_research(
                    payload=payload,
                    mode=mode,
                    transcript_excerpt=transcript_excerpt,
                    rubric_name=rubric_name,
                    client_provider=research_client_provider,
                )

            try:
                post = generate_article_from_raw(
                    db,
                    raw_text=transcript,
                    source_url=str(payload.video_url),
                    generator=transcript_generator,
                    research_content=research_summary,
                    research_sources=research_sources,
                    author_context=author_context,
                )
            except ArticleGenerationError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc
            document = document_from_post(post)
            logger.info("article-generation-done mode=video slug=%s id=%s", post.slug, post.id)
            return ArticlePublishResponse(slug=post.slug, id=post.id, post=document)

        if not generator.is_configured:
            raise HTTPException(status_code=503, detail="OpenAI API key is not configured")
        rubric_name = _resolve_rubric_name(payload, db)
        research_summary: str | None = None
        research_sources = []
        if self._primary_settings.research_enabled:
            research_summary, research_sources = self._run_research(
                payload=payload,
                mode=mode,
                transcript_excerpt=None,
                rubric_name=rubric_name,
                client_provider=research_client_provider,
            )
        try:
            raw_document = generator.generate_article(
                topic=payload.topic,
                rubric=rubric_name,
                keywords=payload.keywords,
                guidance=payload.guidance,
                research_content=research_summary,
                research_sources=research_sources,
                author_context=None,
                user_guidance=payload.guidance,
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
        research_client_provider: Callable[[], ParallelDeepSearchClient] | None = None,
        now=None,
    ) -> ArticlePublishResponse:
        return self.generate_and_publish(
            payload=payload,
            db=db,
            generator=generator,
            transcript_generator=transcript_generator,
            supadata_provider=supadata_provider,
            research_client_provider=research_client_provider,
            now=now,
        )

    def _run_research(
        self,
        *,
        payload: ArticleCreateRequest,
        mode: str,
        transcript_excerpt: str | None,
        rubric_name: str | None,
        client_provider: Callable[[], ParallelDeepSearchClient] | None,
    ) -> tuple[str | None, list]:
        prompt = build_research_prompt(
            payload,
            mode=mode,
            transcript_excerpt=transcript_excerpt,
            rubric_name=rubric_name,
        )
        topic = _derive_topic(payload, transcript_excerpt)
        provider = _select_client_provider(client_provider)
        started_at = time.monotonic()
        try:
            result = provider().search(title=topic, lead=prompt)
        except DeepSearchError as exc:
            _log_research_failure(exc)
            return None, []
        except Exception as exc:  # pragma: no cover - defensive guard
            _log_research_failure(exc)
            return None, []
        summary, sources = _normalize_research_result(result)
        _log_research_success(started_at, len(sources))
        return summary, sources


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


def build_research_prompt(
    payload: ArticleCreateRequest,
    *,
    mode: str,
    transcript_excerpt: str | None,
    rubric_name: str | None = None,
) -> str:
    """Compose a concise prompt describing the article for Deep Research."""

    topic = _derive_topic(payload, transcript_excerpt)
    keyword_text = ", ".join(k for k in (payload.keywords or []) if k)
    lines = [
        "Przygotuj syntetyczne badanie dla artykułu joga.yoga.",
        f"Tryb generacji: {mode}.",
        f"Temat przewodni: {topic}.",
    ]
    if rubric_name:
        lines.append(f"Rubryka/sekcja: {rubric_name}.")
    if keyword_text:
        lines.append(f"Słowa kluczowe: {keyword_text}.")
    if payload.guidance:
        lines.append(f"Wytyczne redakcyjne: {payload.guidance}.")
    if transcript_excerpt:
        excerpt = transcript_excerpt.strip()
        if len(excerpt) > 400:
            excerpt = f"{excerpt[:400]}…"
        lines.append("Krótki kontekst z transkrypcji:")
        lines.append(excerpt)
    return "\n".join(lines)


def _derive_topic(payload: ArticleCreateRequest, transcript_excerpt: str | None) -> str:
    topic = (payload.topic or "").strip()
    if topic:
        return topic
    if transcript_excerpt:
        words = transcript_excerpt.strip().split()
        return " ".join(words[:12]) if words else "Artykuł joga.yoga"
    return "Artykuł joga.yoga"


def _resolve_rubric_name(payload: ArticleCreateRequest, db: Session) -> str:
    rubric_name = "Zdrowie i joga"
    if payload.rubric_code:
        rubric = db.query(Rubric).filter(Rubric.code == payload.rubric_code).one_or_none()
        if rubric:
            rubric_name = rubric.name_pl
    return rubric_name


def _select_client_provider(
    client_provider: Callable[[], ParallelDeepSearchClient] | None,
) -> Callable[[], ParallelDeepSearchClient]:
    return client_provider or get_parallel_deep_search_client


def _normalize_research_result(result) -> tuple[str | None, list]:
    if not result:
        return None, []
    summary = result.summary if getattr(result, "summary", None) else None
    sources = result.sources if getattr(result, "sources", None) else []
    return summary, sources


def _log_research_failure(exc: Exception) -> None:
    logger.warning("research-step failed reason=%s", exc)


def _log_research_success(started_at: float, sources_count: int) -> None:
    elapsed = time.monotonic() - started_at
    logger.info("research-step done sources=%s duration_s=%.2f", sources_count, elapsed)

