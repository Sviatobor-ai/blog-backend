"""Schema for synchronous generate-now endpoint."""

from __future__ import annotations

from pydantic import AnyHttpUrl, BaseModel, ConfigDict


class GenerateNowRequest(BaseModel):
    url: AnyHttpUrl

    model_config = ConfigDict(extra="forbid")


class GenerateNowResponse(BaseModel):
    accepted: bool
    article_id: int | None = None
    reason: str | None = None
