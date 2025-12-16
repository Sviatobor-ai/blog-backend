"""Helper functions shared by the article enhancer flow."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable, List, Tuple
from urllib.parse import urlparse

from ..article_schema import ARTICLE_FAQ_MAX
from ..schemas import ArticleDocument
from .deep_search import DeepSearchResult, DeepSearchSource, ParallelDeepSearchClient
from .writer import EnhancementResponse

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CitationCandidate:
    url: str
    label: str | None = None
    score: float | None = None
    published_at: str | None = None


CitationMergeResult = Tuple[List[str], str]


def run_research_step(
    search_client: ParallelDeepSearchClient, document: ArticleDocument
) -> DeepSearchResult:
    """Execute the research request for the provided document."""

    return search_client.search(
        title=document.seo.title or document.article.headline,
        lead=document.article.lead,
    )


def select_citations(sources: Iterable[DeepSearchSource]) -> List[CitationCandidate]:
    candidates: List[CitationCandidate] = []
    seen: set[str] = set()
    for source in sources:
        url = (source.url or "").strip()
        if not url or url in seen:
            continue
        if not _is_allowed_domain(url):
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


def merge_citations(existing: List[str], selected: List[CitationCandidate]) -> CitationMergeResult:
    if len(selected) >= 2:
        return [item.url for item in selected], "replace"
    if len(selected) == 1:
        merged = merge_single_citation(existing, selected[0].url)
        return merged, "merge_single"
    return existing, "keep_existing"


def merge_single_citation(existing: List[str], new_url: str) -> List[str]:
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


def apply_enhancement_updates(
    *, document: ArticleDocument, response: EnhancementResponse, citations: List[str]
) -> ArticleDocument:
    data = document.model_dump(mode="json")
    sections = data["article"]["sections"]
    new_sections = _prepare_sections(response.added_sections)
    if not new_sections:
        raise RuntimeError("writer response missing usable sections")
    sections.extend(new_sections)
    faq_items = data["aeo"].setdefault("faq", [])
    new_question = (response.added_faq.get("question") or "").strip()
    if new_question and not any(
        item.get("question", "").strip().lower() == new_question.lower() for item in faq_items
    ):
        faq_items.append({"question": new_question, "answer": response.added_faq.get("answer")})
    if len(faq_items) > ARTICLE_FAQ_MAX:
        del faq_items[0 : len(faq_items) - ARTICLE_FAQ_MAX]
    data["article"]["citations"] = citations
    return ArticleDocument.model_validate(data)


def _prepare_sections(raw_sections: Iterable[dict[str, str]]) -> List[dict[str, str]]:
    prepared: List[dict[str, str]] = []
    for index, raw in enumerate(raw_sections):
        title = str(raw.get("title") or "").strip()
        body = str(raw.get("body") or "").strip()
        if not title or not body:
            logger.warning("writer returned incomplete section idx=%s", index)
            continue
        prepared.append({"title": title, "body": body})
    return prepared


def _is_allowed_domain(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    domain = parsed.hostname or ""
    blocked_suffixes = (".ru", ".su")
    if any(domain.endswith(suffix) for suffix in blocked_suffixes):
        return False
    return True


__all__ = [
    "CitationCandidate",
    "CitationMergeResult",
    "apply_enhancement_updates",
    "merge_citations",
    "merge_single_citation",
    "run_research_step",
    "select_citations",
]
