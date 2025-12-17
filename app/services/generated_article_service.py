"""Service layer for orchestrating article generation flows."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass
from typing import Callable
from urllib.parse import parse_qs, urlparse

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.orm import Session

from ..config import get_primary_generation_settings
from sqlalchemy import func
from ..enhancer.deep_search import DeepSearchError, ParallelDeepSearchClient
from ..services.author_context import build_author_context_from_transcript
from ..enhancer.providers import get_parallel_deep_search_client
from ..integrations.supadata import (
    SupaDataClient,
    SupadataTranscriptError,
    SupadataTranscriptTooShortError,
)
from ..models import Post, Rubric
from ..schemas import ArticleCreateRequest, ArticleDocument, ArticlePublishResponse
from . import ArticleGenerationError, OpenAIAssistantArticleGenerator
from .article_publication import persist_article_document, prepare_document_for_publication
from .video_pipeline import generate_article_from_raw

logger = logging.getLogger(__name__)


@dataclass
class GenerationTelemetry:
    generation_mode: str
    research_enabled: bool
    research_attempted: bool = False
    research_ok: bool = False
    research_run_id: str | None = None
    research_sources_count: int = 0
    research_duration_ms: int | None = None
    writer_ok: bool = False
    writer_duration_ms: int | None = None
    slug: str | None = None
    post_id: int | None = None
    error_stage: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


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

        telemetry = GenerationTelemetry(
            generation_mode="transcript" if payload.video_url else "topic",
            research_enabled=self._primary_settings.research_enabled,
        )
        logger.info(
            "article-generation-start mode=%s topic=%s video_url=%s research_enabled=%s",
            telemetry.generation_mode,
            payload.topic,
            payload.video_url,
            telemetry.research_enabled,
        )

        try:
            if payload.video_url:
                if not transcript_generator.is_configured:
                    telemetry.error_stage = "writer"
                    raise HTTPException(
                        status_code=503, detail="Transcript generator is not configured"
                    )

                source_key = _build_source_key(str(payload.video_url))
                existing_post = None
                if source_key:
                    existing_post = _find_post_by_source_key(db, source_key)
                    if existing_post and existing_post.payload:
                        document = document_from_post(existing_post)
                        telemetry.slug = existing_post.slug
                        telemetry.post_id = existing_post.id
                        logger.info(
                            "event=video_dedup_hit source_key=%s slug=%s id=%s",
                            source_key,
                            existing_post.slug,
                            existing_post.id,
                        )
                        _log_generation_success(telemetry)
                        return ArticlePublishResponse(
                            slug=existing_post.slug, id=existing_post.id, post=document
                        )
                    if existing_post:
                        logger.info(
                            "event=video_dedup_miss source_key=%s slug=%s id=%s reason=no_payload",
                            source_key,
                            existing_post.slug,
                            existing_post.id,
                        )
                    else:
                        logger.info("event=video_dedup_miss source_key=%s", source_key)

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
                    telemetry.error_stage = "writer"
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
                    telemetry.error_stage = "writer"
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
                    telemetry.error_stage = "writer"
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
                        mode=telemetry.generation_mode,
                        transcript_excerpt=transcript_excerpt,
                        rubric_name=rubric_name,
                        client_provider=research_client_provider,
                        telemetry=telemetry,
                    )

                writer_started = time.monotonic()
                try:
                    post = generate_article_from_raw(
                        db,
                        raw_text=transcript,
                        source_url=str(payload.video_url),
                        source_key=source_key,
                        generator=transcript_generator,
                        research_content=research_summary,
                        research_sources=research_sources,
                        author_context=author_context,
                    )
                    telemetry.writer_ok = True
                except ArticleGenerationError as exc:
                    telemetry.error_stage = "writer"
                    raise HTTPException(status_code=502, detail=str(exc)) from exc
                finally:
                    telemetry.writer_duration_ms = _duration_ms(writer_started)

                document = document_from_post(post)
                telemetry.slug = post.slug
                telemetry.post_id = post.id
                _log_generation_success(telemetry)
                return ArticlePublishResponse(slug=post.slug, id=post.id, post=document)

            if not generator.is_configured:
                telemetry.error_stage = "writer"
                raise HTTPException(status_code=503, detail="OpenAI API key is not configured")
            rubric_name = _resolve_rubric_name(payload, db)
            research_summary: str | None = None
            research_sources = []
            if self._primary_settings.research_enabled:
                research_summary, research_sources = self._run_research(
                    payload=payload,
                    mode=telemetry.generation_mode,
                    transcript_excerpt=None,
                    rubric_name=rubric_name,
                    client_provider=research_client_provider,
                    telemetry=telemetry,
                )
            writer_started = time.monotonic()
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
                telemetry.writer_ok = True
            except ArticleGenerationError as exc:
                telemetry.error_stage = "writer"
                raise HTTPException(status_code=502, detail=str(exc)) from exc
            finally:
                telemetry.writer_duration_ms = _duration_ms(writer_started)

            try:
                document = ArticleDocument.model_validate(raw_document)
            except (ValueError, ValidationError) as exc:
                telemetry.error_stage = "writer"
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
                telemetry.error_stage = "publish"
                raise HTTPException(status_code=502, detail=str(exc)) from exc

            telemetry.slug = post.slug
            telemetry.post_id = post.id
            _log_generation_success(telemetry)
            return ArticlePublishResponse(slug=post.slug, id=post.id, post=document)
        except Exception as exc:
            _log_generation_failure(telemetry, exc)
            raise

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
        telemetry: GenerationTelemetry,
    ) -> tuple[str | None, list]:
        prompt = build_research_prompt(
            payload,
            mode=mode,
            transcript_excerpt=transcript_excerpt,
            rubric_name=rubric_name,
        )
        topic = _derive_topic(payload, transcript_excerpt)
        provider = _select_client_provider(client_provider)
        try:
            client = provider()
        except DeepSearchError as exc:
            telemetry.research_ok = False
            telemetry.error_stage = telemetry.error_stage or "research"
            logger.warning("event=research_skipped_missing_config reason=%s", exc)
            return None, []
        except Exception as exc:  # pragma: no cover - defensive guard for provider errors
            telemetry.research_ok = False
            telemetry.error_stage = telemetry.error_stage or "research"
            _log_research_failure(exc)
            return None, []
        telemetry.research_attempted = True
        started_at = time.monotonic()
        try:
            result = client.search(title=topic, lead=prompt)
        except DeepSearchError as exc:
            telemetry.research_ok = False
            telemetry.research_duration_ms = _duration_ms(started_at)
            telemetry.error_stage = telemetry.error_stage or "research"
            _log_research_failure(exc)
            return None, []
        except Exception as exc:  # pragma: no cover - defensive guard
            telemetry.research_ok = False
            telemetry.research_duration_ms = _duration_ms(started_at)
            telemetry.error_stage = telemetry.error_stage or "research"
            _log_research_failure(exc)
            return None, []
        telemetry.research_duration_ms = _duration_ms(started_at)
        summary, sources, run_id = _normalize_research_result(result)
        telemetry.research_ok = True
        telemetry.research_sources_count = len(sources)
        telemetry.research_run_id = run_id
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


def _build_source_key(video_url: str | None) -> str | None:
    if not video_url:
        return None

    trimmed = video_url.strip()
    if not trimmed:
        return None

    parsed = urlparse(trimmed)
    hostname = parsed.netloc.lower()
    path = parsed.path

    if "youtube.com" in hostname or "youtu.be" in hostname:
        video_id = None

        if "youtube.com" in hostname:
            query_params = parse_qs(parsed.query)
            video_id = (query_params.get("v") or [None])[0]
            if not video_id and path.startswith("/shorts/"):
                parts = [part for part in path.split("/") if part]
                if len(parts) >= 2:
                    video_id = parts[1]
            if not video_id and path.startswith("/embed/"):
                parts = [part for part in path.split("/") if part]
                if len(parts) >= 2:
                    video_id = parts[1]
        if not video_id and "youtu.be" in hostname:
            video_id = path.lstrip("/") or None

        if video_id:
            return f"youtube:{video_id}"

    return trimmed


def _find_post_by_source_key(db: Session, source_key: str) -> Post | None:
    source_key_field = Post.payload["meta"]["source_key"]
    try:
        source_key_field = source_key_field.astext
    except AttributeError:
        source_key_field = func.json_extract(Post.payload, "$.meta.source_key")

    return (
        db.query(Post)
        .filter(source_key_field == source_key)
        .order_by(Post.updated_at.desc())
        .first()
    )


def _normalize_research_result(result) -> tuple[str | None, list, str | None]:
    if not result:
        return None, [], None
    summary = result.summary if getattr(result, "summary", None) else None
    sources = result.sources if getattr(result, "sources", None) else []
    run_id = result.run_id if getattr(result, "run_id", None) else None
    return summary, sources, run_id


def _log_research_failure(exc: Exception) -> None:
    logger.warning("research-step failed reason=%s", exc)


def _log_research_success(started_at: float, sources_count: int) -> None:
    elapsed = time.monotonic() - started_at
    logger.info("research-step done sources=%s duration_s=%.2f", sources_count, elapsed)


def _log_generation_success(telemetry: GenerationTelemetry) -> None:
    logger.info("event=article_generation_completed telemetry=%s", telemetry.to_dict())


def _log_generation_failure(telemetry: GenerationTelemetry, exc: Exception) -> None:
    logger.exception(
        "event=article_generation_failed telemetry=%s error=%s",
        telemetry.to_dict(),
        exc,
    )


def _duration_ms(started_at: float) -> int:
    return int((time.monotonic() - started_at) * 1000)

