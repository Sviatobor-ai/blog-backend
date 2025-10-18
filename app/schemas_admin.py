"""Pydantic models specific to admin API operations."""

from __future__ import annotations

from typing import List, Optional

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, conint, constr


class AdminSearchRequest(BaseModel):
    """Incoming payload for SupaData-powered YouTube search."""

    query: constr(strip_whitespace=True, min_length=1)
    limit: conint(ge=1, le=100) = 50
    min_duration_seconds: conint(ge=0) = 600
    max_duration_seconds: conint(gt=0) = 10800

    model_config = ConfigDict(extra="forbid")


class AdminSearchVideo(BaseModel):
    """Video item returned to the admin console."""

    video_id: str
    url: str
    title: str
    channel: Optional[str]
    duration_seconds: Optional[int]
    published_at: Optional[str]
    description_snippet: Optional[str]
    has_transcript: Optional[bool]


class AdminSearchResponse(BaseModel):
    """Envelope containing the search results."""

    items: List[AdminSearchVideo]


class QueuePlanRequest(BaseModel):
    """Payload describing which videos should be enqueued."""

    video_urls: List[AnyHttpUrl] = Field(..., min_length=1, max_length=100)


class QueuePlanResponse(BaseModel):
    """Response returned after storing generation jobs."""

    queued: int
    job_ids: List[int]
