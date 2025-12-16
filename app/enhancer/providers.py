"""Dependency providers for enhancer integrations."""

from __future__ import annotations

from ..config import get_parallel_search_settings
from .deep_search import ParallelDeepSearchClient


def get_parallel_deep_search_client() -> ParallelDeepSearchClient:
    """Return a configured Parallel.ai Deep Search client."""

    settings = get_parallel_search_settings()
    return ParallelDeepSearchClient(
        api_key=settings.api_key,
        base_url=settings.base_url,
        timeout_s=settings.request_timeout_s,
    )


__all__ = ["get_parallel_deep_search_client"]
