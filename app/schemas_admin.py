"""Pydantic models specific to admin API operations."""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    conint,
    constr,
    field_validator,
)

AllowedType = Literal["video", "channel", "playlist", "movie"]
AllowedDuration = Literal["short", "medium", "long"]


class AdminSearchRequest(BaseModel):
    """Incoming payload for SupaData-powered YouTube search."""

    query: constr(strip_whitespace=True, min_length=1)
    limit: conint(ge=1, le=100) = 5
    type: AllowedType = "video"
    duration: AllowedDuration = "medium"
    features: Optional[List[str]] = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("features")
    @classmethod
    def features_whitelist(cls, value: Optional[List[str]]):
        """Ensure only supported feature filters are accepted."""

        if value is None:
            return None
        allowed = {"subtitles", "location"}
        invalid = [feature for feature in value if feature not in allowed]
        if invalid:
            raise ValueError(
                "Unsupported features: {}. Allowed: subtitles, location.".format(
                    ", ".join(invalid)
                )
            )
        seen: set[str] = set()
        deduped: List[str] = []
        for feature in value:
            if feature not in seen:
                deduped.append(feature)
                seen.add(feature)
        return deduped


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
