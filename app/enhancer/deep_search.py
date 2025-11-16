"""Parallel.ai Deep Search integration helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, List
from urllib.parse import urlparse

import httpx


class DeepSearchError(RuntimeError):
    """Raised when Parallel.ai Deep Search request fails."""


@dataclass(slots=True)
class DeepSearchSource:
    """Single search source entry."""

    url: str
    title: str | None = None
    description: str | None = None
    published_at: str | None = None
    score: float | None = None


@dataclass(slots=True)
class DeepSearchResult:
    """Structured insights returned from Parallel.ai."""

    summary: str | None
    sources: List[DeepSearchSource]


class ParallelDeepSearchClient:
    """Small HTTP client talking to Parallel.ai's Deep Search endpoint."""

    def __init__(self, *, api_key: str | None, base_url: str, timeout_s: float = 60.0) -> None:
        if not api_key:
            raise DeepSearchError("PARALLELAI_API_KEY is not configured")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_s

    def search(self, *, title: str, lead: str) -> DeepSearchResult:
        """Call Deep Search and return structured insights."""

        prompt = self._build_prompt(title=title, lead=lead)
        payload = {
            "query": prompt,
            "focus": "latest",
            "max_results": 12,
        }
        headers = {"Authorization": f"Bearer {self._api_key}"}
        url = f"{self._base_url}/v1/deepsearch"
        try:
            response = httpx.post(url, json=payload, headers=headers, timeout=self._timeout)
            response.raise_for_status()
        except httpx.HTTPError as exc:  # pragma: no cover - network guard
            raise DeepSearchError(f"Parallel.ai request failed: {exc}") from exc

        data = response.json()
        summary = self._extract_summary(data)
        sources = self._extract_sources(data.get("sources") or data.get("results") or [])
        return DeepSearchResult(summary=summary, sources=sources)

    def _build_prompt(self, *, title: str, lead: str) -> str:
        lines = [
            "Zbierz najnowsze i wiarygodne informacje powiązane z artykułem joga.yoga.",
            "Potrzebne są fakty, dane liczbowe, trendy i komentarze ekspertów.",
            "Preferuj źródła: duże europejskie/US media, instytucje akademickie i medyczne, WHO, UE, UNESCO,",
            "uznane organizacje jogi/ajurwedy z Indii oraz Wikipedia.",
            "Unikaj źródeł .ru lub rosyjskojęzycznych. Jeśli temat ma charakter konsumencki, dopuszczalne są",
            "rzetelne poradniki lifestylowe.",
            "Dla każdej pozycji podaj tytuł, krótkie streszczenie, URL i datę publikacji (jeśli dostępna).",
            "Temat:",
            title.strip(),
            "Lead artykułu:",
            lead.strip(),
        ]
        return "\n".join(line for line in lines if line)

    def _extract_summary(self, payload: dict[str, Any]) -> str | None:
        return (
            payload.get("summary")
            or payload.get("insights")
            or payload.get("highlights")
            or None
        )

    def _extract_sources(self, items: Iterable[Any]) -> List[DeepSearchSource]:
        sources: List[DeepSearchSource] = []
        for raw in items:
            url = str(raw.get("url") or raw.get("link") or "").strip()
            if not url:
                continue
            parsed = urlparse(url)
            if not parsed.scheme.startswith("http"):
                continue
            sources.append(
                DeepSearchSource(
                    url=url,
                    title=(raw.get("title") or raw.get("name")),
                    description=(raw.get("description") or raw.get("snippet") or raw.get("summary")),
                    published_at=raw.get("published_at") or raw.get("date"),
                    score=(raw.get("score") or raw.get("relevance")),
                )
            )
        return sources


__all__ = ["ParallelDeepSearchClient", "DeepSearchResult", "DeepSearchSource", "DeepSearchError"]
