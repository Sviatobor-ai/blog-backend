"""CLI entry point that enhances all eligible posts."""

from __future__ import annotations

import argparse
import logging
from datetime import datetime, timezone

from ..config import get_openai_settings, get_parallel_search_settings
from ..db import SessionLocal
from . import select_articles_for_enhancement
from .deep_search import ParallelDeepSearchClient
from .pipeline import ArticleEnhancer
from .writer import EnhancementWriter

logger = logging.getLogger(__name__)


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="[%(asctime)s] %(levelname)s %(name)s: %(message)s")


def run_batch(limit: int | None = None, *, verbose: bool = False) -> None:
    """Enhance a batch of posts older than 17 days."""

    _setup_logging(verbose)
    now = datetime.now(timezone.utc)
    search_settings = get_parallel_search_settings()
    search_client = ParallelDeepSearchClient(
        api_key=search_settings.api_key,
        base_url=search_settings.base_url,
        timeout_s=search_settings.request_timeout_s,
    )
    openai_settings = get_openai_settings()
    writer = EnhancementWriter(api_key=openai_settings.api_key, timeout_s=openai_settings.request_timeout_s)
    pipeline = ArticleEnhancer(search_client=search_client, writer=writer)

    with SessionLocal() as db:
        posts = select_articles_for_enhancement(db, now=now)
        if limit:
            posts = posts[:limit]
        logger.info("found %s posts eligible for enhancement", len(posts))
        for post in posts:
            try:
                pipeline.enhance_post(db, post, now=now)
            except Exception as exc:  # pragma: no cover - runtime guard
                logger.exception("enhancement failed for slug=%s: %s", post.slug, exc)


def main() -> None:
    parser = argparse.ArgumentParser(description="Enhance published joga.yoga posts")
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of posts to enhance")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    args = parser.parse_args()
    run_batch(limit=args.limit, verbose=args.verbose)


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    main()
