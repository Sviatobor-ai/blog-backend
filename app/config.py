"""Application configuration helpers."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import find_dotenv, load_dotenv


load_dotenv(find_dotenv(), override=True)


@dataclass(frozen=True)
class OpenAISettings:
    """Container for OpenAI related configuration values."""

    api_key: str | None
    assistant_id: str | None
    assistant_fromvideo_id: str | None
    request_timeout_s: float


@dataclass(frozen=True)
class ParallelSearchSettings:
    """Configuration for the Parallel.ai Deep Search integration."""

    api_key: str | None
    base_url: str
    request_timeout_s: float


@lru_cache
def get_database_url() -> str:
    """Return the configured database URL or fail fast when missing."""

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set")
    return database_url


@lru_cache
def get_openai_settings() -> OpenAISettings:
    """Return OpenAI related configuration loaded from the environment."""

    timeout_raw = os.getenv("OPENAI_REQUEST_TIMEOUT_S")
    try:
        timeout = float(timeout_raw) if timeout_raw else 120.0
    except ValueError as exc:  # pragma: no cover - guardrail for invalid configuration
        raise RuntimeError("OPENAI_REQUEST_TIMEOUT_S must be numeric") from exc

    return OpenAISettings(
        api_key=os.getenv("OPENAI_API_KEY"),
        assistant_id=os.getenv("OPENAI_ASSISTANT_ID", "asst_N0YcJg0jXoqHJQeesdWtiiIc"),
        assistant_fromvideo_id=os.getenv(
            "OPENAI_ASSISTANT_FROMVIDEO_ID",
            "asst_Vwus3Hrvn5jXMitwjqoYyRpe",
        ),
        request_timeout_s=timeout,
    )


@lru_cache
def get_parallel_search_settings() -> ParallelSearchSettings:
    """Return configuration for Parallel.ai Deep Search requests."""

    return ParallelSearchSettings(
        api_key=os.getenv("PARALLELAI_API_KEY"),
        base_url=os.getenv("PARALLELAI_BASE_URL", "https://api.parallel.ai"),
        request_timeout_s=float(os.getenv("PARALLELAI_TIMEOUT_S", "120")),
    )

@lru_cache
def get_site_base_url() -> str:
    """Return the public base URL for the published site."""

    base_url = os.getenv("NEXT_PUBLIC_SITE_URL") or "https://joga.yoga"
    return base_url.rstrip("/")


@lru_cache
def get_supadata_key() -> str:
    """Return the configured SupaData API key or fail fast when missing."""

    key = os.getenv("SUPADATA_KEY")
    if not key:
        raise RuntimeError("SUPADATA_KEY environment variable is required")
    logging.getLogger(__name__).debug("supadata key loaded from environment")
    return key


DATABASE_URL = get_database_url()
