"""Core orchestration logic for the article enhancer."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import List

from sqlalchemy.orm import Session

from ..models import Post
from ..schemas import ArticleDocument
from ..services.article_utils import compose_body_mdx
from .deep_search import ParallelDeepSearchClient
from .helpers import (
    CitationCandidate,
    apply_enhancement_updates,
    merge_citations,
    run_research_step,
    select_citations,
)
from .writer import EnhancementRequest, EnhancementWriter

logger = logging.getLogger(__name__)


class ArticleEnhancer:
    """Processes stored posts and appends the enhancement block."""

    def __init__(
        self, *, search_client: ParallelDeepSearchClient, writer: EnhancementWriter
    ) -> None:
        self._search_client = search_client
        self._writer = writer

    def enhance_post(self, db: Session, post: Post, *, now: datetime) -> bool:
        """Enhance a single post. Returns ``True`` when changes were applied."""

        document = self._load_document(post)

        search_result = run_research_step(self._search_client, document)
        citations = select_citations(search_result.sources)
        logger.info(
            "deep search returned %d sources, %d usable citations for slug=%s",
            len(search_result.sources),
            len(citations),
            post.slug,
        )
        if not citations:
            logger.info("continuing without new citations for slug=%s", post.slug)

        request = EnhancementRequest(
            headline=document.article.headline,
            lead=document.article.lead,
            sections=[section.model_dump() for section in document.article.sections],
            faq=[faq.model_dump() for faq in document.aeo.faq],
            insights=search_result.summary,
            citations=[{"url": item.url, "label": item.label or item.url} for item in citations],
        )
        response = self._writer.generate(request)
        logger.info(
            "writer produced %d sections and %s FAQ for slug=%s",
            len(response.added_sections),
            "a new" if response.added_faq else "no",
            post.slug,
        )

        existing_citation_urls = [str(url) for url in document.article.citations]
        citation_urls, merge_strategy = merge_citations(existing_citation_urls, citations)
        self._log_citation_strategy(post.slug, merge_strategy, citation_urls, existing_citation_urls)

        updated_document = apply_enhancement_updates(
            document=document,
            response=response,
            citations=citation_urls,
        )

        self._persist(db, post, updated_document, now=now)
        return True

    def _load_document(self, post: Post) -> ArticleDocument:
        if not post.payload:
            raise RuntimeError(f"Post {post.slug} does not have payload")
        return ArticleDocument.model_validate(post.payload)

    def _persist(self, db: Session, post: Post, document: ArticleDocument, *, now: datetime) -> None:
        post.payload = document.model_dump(mode="json")
        post.body_mdx = compose_body_mdx([section.model_dump() for section in document.article.sections])
        post.citations = [str(url) for url in document.article.citations]
        post.faq = [faq.model_dump() for faq in document.aeo.faq]
        post.lead = document.article.lead
        post.headline = document.article.headline
        post.updated_at = now
        db.add(post)
        db.commit()
        db.refresh(post)
        logger.info("post %s enhanced", post.slug)

    def _log_citation_strategy(
        self, slug: str, strategy: str, citations: List[str], existing: List[str]
    ) -> None:
        if strategy == "replace":
            logger.info(
                "replacing citations with %d new links for slug=%s",
                len(citations),
                slug,
            )
        elif strategy == "merge_single":
            logger.info(
                "merging single new citation with %d existing for slug=%s",
                len(existing),
                slug,
            )
        else:
            logger.info(
                "retaining %d existing citations for slug=%s",
                len(citations),
                slug,
            )


__all__ = ["ArticleEnhancer", "CitationCandidate"]
