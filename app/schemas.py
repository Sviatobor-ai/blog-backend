"""Pydantic schemas for writer publishing endpoints."""
from typing import Literal
import re

from pydantic import BaseModel, Field, field_validator


class WriterPublishIn(BaseModel):
    """Payload accepted from the writer tool when requesting publication."""

    topic: str
    rubric_code: str | None = None
    seed_queries: list[str] = Field(default_factory=list)
    seed_urls: list[str] = Field(default_factory=list)
    extra_prompts: str | None = None

    @field_validator("topic")
    @classmethod
    def validate_topic(cls, value: str) -> str:
        """Ensure the topic is present and within the allowed length."""
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("topic must not be empty")
        if len(cleaned) > 200:
            raise ValueError("topic must be 200 characters or fewer")
        return cleaned

    @field_validator("rubric_code")
    @classmethod
    def validate_rubric_code(cls, value: str | None) -> str | None:
        """Allow only rubric codes with safe characters."""
        if value is None:
            return None
        cleaned = value.strip()
        if len(cleaned) > 64:
            raise ValueError("rubric_code must be 64 characters or fewer")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", cleaned):
            raise ValueError("rubric_code may only contain letters, digits, hyphens or underscores")
        return cleaned


class WriterPublishOut(BaseModel):
    """Response returned after the mock publication is stored."""

    status: Literal["published"]
    slug: str
    url: str
    id: int
