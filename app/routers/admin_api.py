"""JSON admin endpoints for SupaData-assisted workflows."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..auth import require_token
from ..dependencies import get_db, get_supadata_client
from ..generation_jobs import GenerationJobStatus
from ..integrations.supadata import SDVideo, SupaDataClient
from ..models import GenerationJob
from ..schemas_admin import (
    AdminSearchRequest,
    AdminSearchResponse,
    AdminSearchVideo,
    QueuePlanRequest,
    QueuePlanResponse,
)

admin_api_router = APIRouter(prefix="/admin", tags=["admin-api"])


@admin_api_router.get("/status", include_in_schema=False)
def admin_status(_: str = Depends(require_token)) -> dict:
    """Return a minimal runner status payload for the admin UI."""

    return {
        "pending": 0,
        "running": 0,
        "done": 0,
        "skipped": 0,
        "failed": 0,
        "runner_on": False,
    }


@admin_api_router.get("/queue", include_in_schema=False)
def admin_queue(_: str = Depends(require_token)) -> dict:
    """Return a minimal queue payload for the admin UI."""

    return {"items": []}


def _video_to_dict(video: SDVideo) -> AdminSearchVideo:
    return AdminSearchVideo(
        video_id=video.video_id,
        url=video.url,
        title=video.title,
        channel=video.channel,
        duration_seconds=video.duration_seconds,
        published_at=video.published_at,
        description_snippet=video.description_snippet,
        has_transcript=video.has_transcript,
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
        min_duration_seconds=payload.min_duration_seconds,
        max_duration_seconds=payload.max_duration_seconds,
        region=payload.region,
        language=payload.language,
    )
    filtered_videos = [
        video
        for video in videos
        if video.duration_seconds is None
        or (
            video.duration_seconds >= payload.min_duration_seconds
            and video.duration_seconds <= payload.max_duration_seconds
        )
    ]
    items = [_video_to_dict(video) for video in filtered_videos]
    return AdminSearchResponse(items=items)


@admin_api_router.post(
    "/queue/plan",
    response_model=QueuePlanResponse,
    status_code=status.HTTP_201_CREATED,
)
def plan_generation_jobs(
    payload: QueuePlanRequest,
    _: object = Depends(require_token),
    db: Session = Depends(get_db),
) -> QueuePlanResponse:
    """Store pending jobs for selected YouTube URLs."""

    if not payload.video_urls:
        raise HTTPException(status_code=400, detail="video_urls must not be empty")
    created_ids: List[int] = []
    for url in payload.video_urls:
        job = GenerationJob(
            source_url=str(url),
            status=GenerationJobStatus.PENDING.value,
        )
        db.add(job)
        db.flush()
        created_ids.append(job.id)
    db.commit()
    return QueuePlanResponse(queued=len(created_ids), job_ids=created_ids)
