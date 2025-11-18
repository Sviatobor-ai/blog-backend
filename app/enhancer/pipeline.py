"""Core orchestration logic for the article enhancer."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
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
        )
        response = self._writer.generate(request)
        logger.info(
            "writer produced %d sections and %s FAQ for slug=%s",
            len(response.added_sections),
            "a new" if response.added_faq else "no",
            post.slug,
        )

        existing_citation_urls = [str(url) for url in document.article.citations]
        if len(citations) >= 2:
            citation_urls = [item.url for item in citations]
            logger.info(
                "replacing citations with %d new links for slug=%s",
                len(citation_urls),
                post.slug,
            )
        elif len(citations) == 1:
            citation_urls = self._merge_single_citation(existing_citation_urls, citations[0].url)
            logger.info(
                "merging single new citation with %d existing for slug=%s",
                len(existing_citation_urls),
                post.slug,
            )
        else:
            citation_urls = existing_citation_urls
            logger.info(
                "retaining %d existing citations for slug=%s",
                len(citation_urls),
                post.slug,
            )

        updated_document = self._apply_updates(
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
    ) -> ArticleDocument:
        data = document.model_dump(mode="json")
        sections = data["article"]["sections"]
        new_sections = self._prepare_sections(response.added_sections)
        if not new_sections:
            raise RuntimeError("writer response missing usable sections")
        sections.extend(new_sections)
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

    def _prepare_sections(self, raw_sections: Iterable[dict[str, str]]) -> List[dict[str, str]]:
        prepared: List[dict[str, str]] = []
        for index, raw in enumerate(raw_sections):
            title = str(raw.get("title") or "").strip()
            body = str(raw.get("body") or "").strip()
            if not title or not body:
                logger.warning("writer returned incomplete section idx=%s", index)
                continue
            prepared.append({"title": title, "body": body})
        return prepared

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

    def _merge_single_citation(self, existing: List[str], new_url: str) -> List[str]:
        merged: List[str] = []
        if new_url:
            merged.append(new_url)
        for url in existing:
            if not url:
                continue
            if url in merged:
                continue
            merged.append(url)
            if len(merged) >= 6:
                break
        return merged


__all__ = ["ArticleEnhancer", "CitationCandidate"]
