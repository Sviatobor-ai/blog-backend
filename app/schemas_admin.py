"""Pydantic models specific to admin API operations."""

from __future__ import annotations

from typing import List, Optional

from pydantic import AnyHttpUrl, BaseModel, Field


class AdminSearchRequest(BaseModel):
    """Incoming payload for SupaData-powered YouTube search."""

    query: str = Field(..., min_length=2, max_length=300)
    limit: int = Field(20, ge=1, le=100)
    min_duration_seconds: int = Field(0, ge=0)
    max_duration_seconds: int = Field(36000, ge=1)
    region: Optional[str] = Field(default=None, max_length=5)
    language: Optional[str] = Field(default=None, max_length=20)


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
