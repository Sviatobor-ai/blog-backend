"""Parallel.ai Deep Search integration helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, List
from urllib.parse import urlparse
import time

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
    """Small HTTP client talking to Parallel.ai's Deep Research Task API."""

    def __init__(self, *, api_key: str | None, base_url: str, timeout_s: float = 60.0) -> None:
        if not api_key:
            raise DeepSearchError("PARALLELAI_API_KEY is not configured")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_s

    @property
    def _headers(self) -> dict[str, str]:
        return {"x-api-key": self._api_key, "Content-Type": "application/json"}

    def search(self, *, title: str, lead: str) -> DeepSearchResult:
        """Call Parallel.ai Deep Research and return structured insights."""

        prompt = self._build_prompt(title=title, lead=lead)
        started_at = time.monotonic()
        try:
            run = self._create_task_run(prompt)
            run_id = run.get("run_id") or run.get("id")
            if not run_id:
                raise DeepSearchError("Parallel.ai response missing run_id")
            result_url = run.get("result_url")
            completed_run = self._poll_run(run_id=run_id, result_url=result_url, started_at=started_at)
        except httpx.HTTPStatusError as exc:  # pragma: no cover - network guard
            status = exc.response.status_code
            if status in {401, 403}:
                raise DeepSearchError(
                    "Parallel.ai request failed: unauthorized (check PARALLELAI_API_KEY or base URL)"
                ) from exc
            raise DeepSearchError(f"Parallel.ai request failed: {exc}") from exc
        except httpx.HTTPError as exc:  # pragma: no cover - network guard
            raise DeepSearchError(f"Parallel.ai request failed: {exc}") from exc

        return self._parse_result(completed_run)

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

    def _create_task_run(self, prompt: str) -> dict[str, Any]:
        url = f"{self._base_url}/v1/tasks/runs"
        payload = {
            "input": prompt,
            "processor": "ultra",
            "task_spec": {"output_schema": {"type": "text"}},
        }
        response = httpx.post(url, json=payload, headers=self._headers, timeout=self._timeout)
        response.raise_for_status()
        return response.json()

    def _poll_run(self, *, run_id: str, result_url: str | None, started_at: float) -> dict[str, Any]:
        poll_url = result_url or f"{self._base_url}/v1/tasks/runs/{run_id}"
        while True:
            elapsed = time.monotonic() - started_at
            if elapsed >= self._timeout:
                raise DeepSearchError("Parallel.ai task polling exceeded timeout")
            response = httpx.get(poll_url, headers=self._headers, timeout=self._timeout)
            response.raise_for_status()
            data = response.json()
            status = data.get("status") or data.get("run_status")
            if status == "completed":
                return data
            if status == "failed":
                error_message = data.get("error") or data.get("error_message") or "task failed"
                raise DeepSearchError(f"Parallel.ai task failed: {error_message}")
            time.sleep(1.0)

    def _parse_result(self, payload: dict[str, Any]) -> DeepSearchResult:
        run_result = payload.get("run_result") or {}
        output = payload.get("output") or run_result.get("output")
        basis = payload.get("basis") or run_result.get("basis") or []
        summary: str | None = None
        if isinstance(output, str):
            summary = output
        elif isinstance(output, dict):
            summary = output.get("text") or output.get("report")

        sources = self._extract_sources(basis)
        return DeepSearchResult(summary=summary, sources=sources)

    def _extract_sources(self, items: Iterable[Any]) -> List[DeepSearchSource]:
        sources: List[DeepSearchSource] = []
        seen: set[str] = set()
        for raw in items:
            citations = raw.get("citations") if isinstance(raw, dict) else None
            if citations:
                for citation in citations:
                    url = str(citation.get("url") or "").strip()
                    if not url:
                        continue
                    parsed = urlparse(url)
                    if not parsed.scheme.startswith("http"):
                        continue
                    if url in seen:
                        continue
                    seen.add(url)
                    excerpts = citation.get("excerpts") or []
                    description = str(excerpts[0]) if excerpts else None
                    sources.append(
                        DeepSearchSource(
                            url=url,
                            title=(citation.get("title") or citation.get("name")),
                            description=description,
                            published_at=citation.get("published_at") or citation.get("date"),
                            score=citation.get("score"),
                        )
                    )
                continue

            getter = raw.get if isinstance(raw, dict) else getattr(raw, "get", None)
            if getter is None:
                continue
            url = str(getter("url") or "").strip()
            if not url:
                continue
            parsed = urlparse(url)
            if not parsed.scheme.startswith("http") or url in seen:
                continue
            seen.add(url)
            sources.append(
                DeepSearchSource(
                    url=url,
                    title=(getter("title") or getter("name")),
                    description=(getter("description") or getter("snippet") or getter("summary")),
                    published_at=getter("published_at") or getter("date"),
                    score=getter("score") or getter("relevance"),
                )
            )
        return sources


__all__ = ["ParallelDeepSearchClient", "DeepSearchResult", "DeepSearchSource", "DeepSearchError"]
