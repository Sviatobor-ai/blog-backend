"""Core orchestration logic for the article enhancer."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable, List
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from ..article_schema import ARTICLE_FAQ_MAX
from ..models import Post
from ..schemas import ArticleDocument
from ..services.article_utils import compose_body_mdx
from .deep_search import DeepSearchSource, ParallelDeepSearchClient
from .writer import EnhancementRequest, EnhancementResponse, EnhancementWriter

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CitationCandidate:
    url: str
    label: str | None = None
    score: float | None = None
    published_at: str | None = None


class ArticleEnhancer:
    """Processes stored posts and appends the enhancement block."""

    def __init__(self, *, search_client: ParallelDeepSearchClient, writer: EnhancementWriter) -> None:
        self._search_client = search_client
        self._writer = writer

    def enhance_post(self, db: Session, post: Post, *, now: datetime) -> bool:
        """Enhance a single post. Returns ``True`` when changes were applied."""

        document = self._load_document(post)
        enhancement_date = now.date()
        if self._has_section_for_date(document, enhancement_date):
            logger.info("post %s already enhanced for %s", post.slug, enhancement_date)
            return False

        search_result = self._search_client.search(
            title=document.seo.title or document.article.headline,
            lead=document.article.lead,
        )
        citations = self._select_citations(search_result.sources)
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
            enhancement_date=enhancement_date,
        )
        response = self._writer.generate(request)

        if citations:
            citation_urls = [item.url for item in citations]
        else:
            citation_urls = list(document.article.citations)

        updated_document = self._apply_updates(
            document=document,
            response=response,
            citations=citation_urls,
            enhancement_title=f"Dopelniono {enhancement_date.isoformat()}",
        )

        self._persist(db, post, updated_document, now=now)
        return True

    def _load_document(self, post: Post) -> ArticleDocument:
        if not post.payload:
            raise RuntimeError(f"Post {post.slug} does not have payload")
        return ArticleDocument.model_validate(post.payload)

    def _has_section_for_date(self, document: ArticleDocument, enhancement_date: date) -> bool:
        target = f"dopelniono {enhancement_date.isoformat()}"
        for section in document.article.sections:
            if section.title.strip().lower() == target:
                return True
        return False

    def _select_citations(self, sources: Iterable[DeepSearchSource]) -> List[CitationCandidate]:
        candidates: List[CitationCandidate] = []
        seen: set[str] = set()
        for source in sources:
            url = (source.url or "").strip()
            if not url or url in seen:
                continue
            if not self._is_allowed_domain(url):
                continue
            seen.add(url)
            candidates.append(
                CitationCandidate(
                    url=url,
                    label=source.title or source.description,
                    score=source.score,
                    published_at=source.published_at,
                )
            )
        candidates.sort(key=lambda item: (item.published_at or "", item.score or 0), reverse=True)
        return candidates[:6]

    def _is_allowed_domain(self, url: str) -> bool:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return False
        domain = parsed.hostname or ""
        blocked_suffixes = (".ru", ".su")
        if any(domain.endswith(suffix) for suffix in blocked_suffixes):
            return False
        return True

    def _apply_updates(
        self,
        *,
        document: ArticleDocument,
        response: EnhancementResponse,
        citations: List[str],
        enhancement_title: str,
    ) -> ArticleDocument:
        data = document.model_dump(mode="json")
        sections = data["article"]["sections"]
        section_title = response.added_section.get("title") or enhancement_title
        section_body = response.added_section.get("body") or ""
        sections.append(
            {
                "title": section_title,
                "body": section_body,
            }
        )
        faq_items = data["aeo"].setdefault("faq", [])
        new_question = (response.added_faq.get("question") or "").strip()
        if new_question and not any(item.get("question", "").strip().lower() == new_question.lower() for item in faq_items):
            faq_items.append(
                {
                    "question": new_question,
                    "answer": response.added_faq.get("answer"),
                }
            )
        if len(faq_items) > ARTICLE_FAQ_MAX:
            del faq_items[0 : len(faq_items) - ARTICLE_FAQ_MAX]
        data["article"]["citations"] = citations
        return ArticleDocument.model_validate(data)

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


__all__ = ["ArticleEnhancer", "CitationCandidate"]
