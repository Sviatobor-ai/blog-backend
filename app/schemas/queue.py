"""Pydantic models for queue management endpoints."""

from __future__ import annotations

from typing import List

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator


class PlanQueueRequest(BaseModel):
    """Request payload describing URLs to enqueue."""

    urls: List[AnyHttpUrl] = Field(..., min_length=1, max_length=100)

    model_config = ConfigDict(extra="forbid")

    @field_validator("urls", mode="before")
    @classmethod
    def normalise_urls(cls, values: List[str]) -> List[str]:
        seen: set[str] = set()
        normalised: List[str] = []
        for url in values:
            text = str(url or "").strip()
            if text.startswith("http://"):
                text = "https://" + text[len("http://") :]
            if text not in seen:
                seen.add(text)
                normalised.append(text)
        if not normalised:
            raise ValueError("at least one valid url must be provided")
        return normalised


class PlanQueueResponse(BaseModel):
    """Response returned after enqueueing jobs."""

    planned: int
    urls: List[str]


class QueueItem(BaseModel):
    id: int
    url: str
    status: str
    error: str | None = None
    article_id: int | None = None


class QueueSnapshotResponse(BaseModel):
    items: List[QueueItem]
