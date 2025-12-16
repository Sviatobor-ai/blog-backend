"""JSON admin endpoints for SupaData-assisted workflows."""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..auth import require_token
from ..config import get_openai_settings
from ..db import SessionLocal
from ..dependencies import get_db, get_supadata_client
from ..integrations.supadata import SDVideo, SupaDataClient
from ..models import GenJob
from ..schemas import ArticleCreateRequest, ArticlePublishResponse
from ..schemas.generate_now import GenerateNowRequest, GenerateNowResponse
from ..schemas.queue import PlanQueueRequest, PlanQueueResponse, QueueItem, QueueSnapshotResponse
from ..schemas_admin import AdminSearchRequest, AdminSearchResponse, AdminSearchVideo
from ..services import OpenAIAssistantArticleGenerator, get_transcript_generator
from ..services.generated_article_service import GeneratedArticleService
from ..services.runner import get_runner, process_url_once

logger = logging.getLogger(__name__)

admin_api_router = APIRouter(prefix="/admin", tags=["admin-api"])


def _session_factory() -> Session:
    return SessionLocal()


_generated_article_service = GeneratedArticleService()
_transcript_generator = get_transcript_generator()


@lru_cache
def _get_assistant_generator() -> OpenAIAssistantArticleGenerator:
    settings = get_openai_settings()
    return OpenAIAssistantArticleGenerator(
        api_key=settings.api_key,
        assistant_id=settings.assistant_id,
        request_timeout_s=settings.request_timeout_s,
    )


def _queue_job_generator(db: Session, payload: dict) -> ArticlePublishResponse:
    url = payload.get("url") or payload.get("video_url")
    request_payload = ArticleCreateRequest(
        topic=str(payload.get("topic") or "Auto article from queue"),
        rubric_code=payload.get("rubric_code"),
        keywords=list(payload.get("keywords") or []),
        guidance=payload.get("guidance"),
        video_url=url,
    )
    return _generated_article_service.create_article(
        payload=request_payload,
        db=db,
        generator=_get_assistant_generator(),
        transcript_generator=_transcript_generator,
        supadata_provider=get_supadata_client,
    )


def _video_to_dict(video: SDVideo) -> AdminSearchVideo:
    return AdminSearchVideo(
        video_id=video.video_id,
        url=video.url,
        title=video.title,
        channel=video.channel,
        duration_seconds=video.duration_seconds,
        published_at=video.published_at,
        description_snippet=video.description_snippet,
    )


@admin_api_router.post("/search", response_model=AdminSearchResponse)
def search_videos(
    payload: AdminSearchRequest,
    _: object = Depends(require_token),
    supadata: SupaDataClient = Depends(get_supadata_client),
) -> AdminSearchResponse:
    """Proxy SupaData YouTube search and return filtered results."""

    videos = supadata.search_youtube(
        query=payload.query,
        limit=payload.limit,
        type_=payload.type,
        duration=payload.duration,
        features=payload.features or [],
    )
    items = [_video_to_dict(video) for video in videos]
    return AdminSearchResponse(items=items)


@admin_api_router.post(
    "/queue/plan",
    response_model=PlanQueueResponse,
    status_code=status.HTTP_201_CREATED,
)
def plan_queue(
    payload: PlanQueueRequest,
    token_user=Depends(require_token),
    db: Session = Depends(get_db),
) -> PlanQueueResponse:
    """Insert pending jobs for provided URLs, skipping existing ones."""

    urls = [str(url) for url in payload.urls]
    if not urls:
        raise HTTPException(status_code=400, detail="urls must not be empty")

    existing_rows = (
        db.query(GenJob.url)
        .filter(GenJob.status.in_(["pending", "running"]))
        .filter(GenJob.url.in_(urls))
        .all()
    )
    existing = {row[0] for row in existing_rows if row[0]}

    planned: List[str] = []
    user_id = getattr(token_user, "id", None)
    for url in urls:
        if url in existing:
            continue
        job = GenJob(url=url, status="pending", user_id=user_id)
        job.source_url = url  # legacy compatibility
        db.add(job)
        db.flush()
        planned.append(url)
        logger.info("queue-plan created job id=%s url=%s", job.id, url)
    db.commit()
    return PlanQueueResponse(planned=len(planned), urls=planned)


@admin_api_router.post("/run/start", include_in_schema=False)
def run_start(_: object = Depends(require_token)) -> dict:
    runner = get_runner(_session_factory, _queue_job_generator)
    runner.start()
    return {"runner_on": runner.is_on()}


@admin_api_router.post("/run/stop", include_in_schema=False)
def run_stop(_: object = Depends(require_token)) -> dict:
    runner = get_runner(_session_factory, _queue_job_generator)
    runner.stop()
    return {"runner_on": runner.is_on()}


@admin_api_router.get("/status", include_in_schema=False)
def admin_status(
    _: object = Depends(require_token),
    db: Session = Depends(get_db),
) -> dict:
    """Return counts of jobs grouped by status."""

    status_counts = {"pending": 0, "running": 0, "done": 0, "skipped": 0, "failed": 0}
    rows = (
        db.query(GenJob.status, func.count(GenJob.id))
        .group_by(GenJob.status)
        .all()
    )
    for status_value, count in rows:
        if status_value in status_counts:
            status_counts[status_value] += int(count)
        elif status_value == "skipped_no_raw":
            status_counts["skipped"] += int(count)
        elif status_value == "ready":
            status_counts["done"] += int(count)
    runner = get_runner(_session_factory, _queue_job_generator)
    status_counts["runner_on"] = runner.is_on()
    return status_counts


@admin_api_router.get(
    "/queue",
    response_model=QueueSnapshotResponse,
    include_in_schema=False,
)
def admin_queue(
    _: object = Depends(require_token),
    db: Session = Depends(get_db),
) -> QueueSnapshotResponse:
    """Return a snapshot of the most recent jobs."""

    jobs = (
        db.query(GenJob)
        .order_by(GenJob.created_at.desc())
        .limit(50)
        .all()
    )
    items = [
        QueueItem(
            id=job.id,
            url=job.url or job.source_url or "",
            status=job.status,
            error=job.error or job.last_error,
            article_id=job.article_id,
        )
        for job in jobs
    ]
    return QueueSnapshotResponse(items=items)


@admin_api_router.post(
    "/generate_now",
    response_model=GenerateNowResponse,
    include_in_schema=False,
)
def generate_now(
    payload: GenerateNowRequest,
    _: object = Depends(require_token),
    db: Session = Depends(get_db),
    supadata: SupaDataClient = Depends(get_supadata_client),
) -> GenerateNowResponse:
    """Execute the full pipeline synchronously for debugging purposes."""

    success, article_id, reason = process_url_once(
        db,
        supadata=supadata,
        url=str(payload.url),
    )
    if success:
        return GenerateNowResponse(accepted=True, article_id=article_id)
    db.rollback()
    return GenerateNowResponse(accepted=False, reason=reason)
