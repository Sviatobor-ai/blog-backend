"""Parallel.ai Deep Search integration helpers."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Iterable, List
from urllib.parse import urlparse
import time

import httpx

logger = logging.getLogger(__name__)


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
    run_id: str | None = None


class ParallelDeepSearchClient:
    """Small HTTP client talking to Parallel.ai's Deep Research Task API."""

    RESULTS_EXPANSION = "output,basis"

    def __init__(self, *, api_key: str | None, base_url: str, timeout_s: float = 1200.0) -> None:
        if not api_key:
            raise DeepSearchError("PARALLELAI_API_KEY is not configured")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._base_netloc = urlparse(self._base_url).netloc
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
            completed_metadata = self._poll_run(run_id=run_id, started_at=started_at)
            results_payload = self._fetch_results(
                run_id=run_id,
                result_url=result_url or completed_metadata.get("result_url"),
            )
        except httpx.HTTPStatusError as exc:  # pragma: no cover - network guard
            status = exc.response.status_code
            if status in {401, 403}:
                raise DeepSearchError(
                    "Parallel.ai request failed: unauthorized (check PARALLELAI_API_KEY or base URL)"
                ) from exc
            raise DeepSearchError(f"Parallel.ai request failed: {exc}") from exc
        except httpx.HTTPError as exc:  # pragma: no cover - network guard
            raise DeepSearchError(f"Parallel.ai request failed: {exc}") from exc

        return self._parse_result(results_payload, run_id=run_id)

    def _build_prompt(self, *, title: str, lead: str) -> str:
        lines = [
            "Przeprowadź pogłębione, ale zwięzłe badanie tematu związanego z artykułem na blogu wiedza.joga.yoga.",
            "Potrzebujemy aktualnych i wiarygodnych informacji, które pomogą uzupełnić istniejący tekst,",
            "a nie napisać zupełnie nowy artykuł od zera.",
            "",
            "Zbieraj przede wszystkim:",
            "- fakty i dane liczbowe (badania, statystyki, raporty),",
            "- aktualne trendy, obserwacje i dobre praktyki,",
            "- komentarze i perspektywy ekspertów (psychologia, zdrowie, joga, ajurweda itp.).",
            "",
            "Preferowane źródła (ale nie traktuj tego jako twardego filtra):",
            "- duże europejskie i anglojęzyczne media o dobrej reputacji,",
            "- instytucje akademickie i medyczne (uniwersytety, szpitale, organizacje zdrowotne),",
            "- organizacje międzynarodowe (WHO, UE, UNESCO itp.),",
            "- uznane organizacje i nauczyciele jogi/ajurwedy,",
            "- Wikipedia jako punkt wyjścia, jeśli jest sensowna dla tematu.",
            "",
            "Jeśli temat ma charakter praktyczny lub lifestylowy (np. porady, ćwiczenia, codzienna praktyka),",
            "możesz swobodnie korzystać z rzetelnych blogów, portali branżowych i poradników,",
            "pod warunkiem że treść jest spójna, nienachalnie marketingowa i ma realną wartość dla czytelnika.",
            "",
            "Unikaj, o ile to możliwe, źródeł o niskiej wiarygodności (clickbaity, spam, treści silnie propagandowe).",
            "Źródła rosyjskojęzyczne i domeny .ru traktuj bardzo ostrożnie i wybieraj je tylko wtedy,",
            "gdy są naprawdę konieczne i wyraźnie eksperckie.",
            "",
            "Na wyjściu przygotuj:",
            "1) Krótkie, syntetyczne podsumowanie najważniejszych ustaleń (1–3 akapity).",
            "2) Wypunktowaną listę kluczowych wniosków lub obserwacji (3–7 punktów).",
            "3) Listę 5–10 proponowanych źródeł do cytowania:",
            "   dla każdego podaj tytuł, bardzo krótkie streszczenie, URL",
            "   oraz datę publikacji, jeśli jest dostępna.",
            "",
            "Temat artykułu:",
            title.strip(),
            "",
            "Lead artykułu:",
            lead.strip(),
        ]
        return "\n".join(line for line in lines if line)


    def _create_task_run(self, prompt: str) -> dict[str, Any]:
        url = f"{self._base_url}/v1/tasks/runs"
        payload = {"input": prompt, "processor": "base"}
        logger.debug(
            "creating Parallel.ai task run with processor=%s and payload keys=%s",
            payload.get("processor"),
            sorted(payload.keys()),
        )
        response = httpx.post(url, json=payload, headers=self._headers, timeout=self._timeout)
        response.raise_for_status()
        return response.json()

    def _poll_run(self, *, run_id: str, started_at: float) -> dict[str, Any]:
        poll_url = f"{self._base_url}/v1/tasks/runs/{run_id}"
        while True:
            elapsed = time.monotonic() - started_at
            if elapsed >= self._timeout:
                raise DeepSearchError("Parallel.ai task polling exceeded timeout")
            response = httpx.get(poll_url, headers=self._headers, timeout=self._timeout)
            response.raise_for_status()
            data = response.json()
            status = data.get("status") or data.get("run_status")
            status_value = str(status).lower() if status else ""
            if status_value in {"completed", "succeeded", "success", "finished"}:
                return data
            if status_value in {"failed", "error", "cancelled"}:
                error_message = data.get("error") or data.get("error_message") or "task failed"
                raise DeepSearchError(f"Parallel.ai task failed: {error_message}")
            time.sleep(1.0)

    def _fetch_results(self, *, run_id: str, result_url: str | None) -> dict[str, Any]:
        """
        Fetch the final Deep Research result payload for a completed Parallel.ai task run.

        Priority:
        1. If Parallel returned a fully-qualified result_url, trust it as-is (except when it is
        a relative path, in which case we join it with our base_url).
        2. Otherwise, construct the official Task API result endpoint:
        {base_url}/v1/tasks/runs/{run_id}/result

        For foreign hosts (netloc different from our configured base host), we assume the URL
        may be a signed URL and therefore:
        - do not modify the query string (no expand=...),
        - do not override headers unless explicitly required.
        """
        # Step 1: choose base URL for the results call
        if result_url:
            parsed_raw = urlparse(result_url)

            # If Parallel returned a relative path like "/v1/tasks/runs/{run_id}/result"
            # we need to join it with our configured base URL.
            if not parsed_raw.scheme and not parsed_raw.netloc:
                base = self._base_url.rstrip("/")
                url = f"{base}/{result_url.lstrip('/')}"
            else:
                # Fully-qualified URL: use as-is
                url = result_url
        else:
            # Fallback: construct the official results endpoint from base_url + run_id
            base = self._base_url.rstrip("/")
            url = f"{base}/v1/tasks/runs/{run_id}/result"

        parsed = urlparse(url)
        using_foreign_host = bool(parsed.netloc and parsed.netloc != self._base_netloc)

        # For foreign hosts we assume the URL might be signed and should not be altered.
        # In that case we also avoid forcing our default headers unless we know it's required.
        headers = None if using_foreign_host else self._headers

        # Optionally append expand=... only when talking to our own Parallel host
        # and only if it is not already present in the query string.
        if not using_foreign_host and self.RESULTS_EXPANSION:
            current_query = parsed.query or ""
            if "expand=" not in current_query:
                separator = "&" if current_query else "?"
                url = f"{url}{separator}expand={self.RESULTS_EXPANSION}"

        logger.debug(
            "fetching Parallel.ai results from %s (foreign_host=%s)",
            url,
            using_foreign_host,
        )

        response = httpx.get(url, headers=headers, timeout=self._timeout)
        response.raise_for_status()
        payload = response.json()

        logger.debug(
            "Parallel.ai results status=%s keys=%s",
            response.status_code,
            sorted(payload.keys()),
        )
        return payload

    def _parse_result(self, payload: dict[str, Any], *, run_id: str | None) -> DeepSearchResult:
        run_result = payload.get("run_result") or {}
        output = payload.get("output") or run_result.get("output") or {}
        summary: str | None = None
        structured_sources: list[Any] = []
        if isinstance(output, str):
            summary = output
        elif isinstance(output, dict):
            summary = (
                output.get("summary")
                or output.get("insights")
                or output.get("text")
                or output.get("report")
            )
            if not summary:
                content = output.get("content")
                if isinstance(content, dict):
                    summary = content.get("summary") or content.get("text")
                elif isinstance(content, str):
                    summary = content
            structured_sources = (
                output.get("sources")
                or output.get("references")
                or output.get("citations")
                or []
            )

        basis = (
            payload.get("basis")
            or run_result.get("basis")
            or (output.get("basis") if isinstance(output, dict) else None)
            or []
        )

        if not isinstance(structured_sources, list):
            structured_sources = []
        logger.debug(
            "Parallel.ai result keys=%s output_keys=%s basis_items=%s",
            sorted(payload.keys()),
            sorted(output.keys()) if isinstance(output, dict) else type(output).__name__,
            len(basis) if isinstance(basis, list) else 0,
        )
        source_payload: list[Any] = list(structured_sources)
        if isinstance(basis, list):
            source_payload.extend(basis)
        sources = self._extract_sources(source_payload)
        return DeepSearchResult(summary=summary, sources=sources, run_id=run_id)

    def _extract_sources(self, items: Iterable[Any]) -> List[DeepSearchSource]:
        sources: List[DeepSearchSource] = []
        seen: set[str] = set()
        for raw in items:
            if len(sources) >= 5:
                break
            if not isinstance(raw, dict):
                continue
            citations = raw.get("citations")
            if isinstance(citations, list) and citations:
                for citation in citations:
                    if len(sources) >= 5:
                        break
                    source = self._build_source(citation)
                    if source and source.url not in seen:
                        seen.add(source.url)
                        sources.append(source)
                continue

            source = self._build_source(raw)
            if source and source.url not in seen:
                seen.add(source.url)
                sources.append(source)
        return sources

    def _build_source(self, payload: Any) -> DeepSearchSource | None:
        if not isinstance(payload, dict):
            return None
        url = str(payload.get("url") or payload.get("link") or "").strip()
        if not url:
            return None
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return None
        domain = parsed.hostname or ""
        if any(domain.endswith(suffix) for suffix in (".ru", ".su")):
            return None
        excerpts = payload.get("excerpts") or payload.get("snippet") or payload.get("snippets")
        description: str | None = None
        if isinstance(excerpts, list) and excerpts:
            description = str(excerpts[0])
        elif isinstance(excerpts, str):
            description = excerpts
        else:
            description = (
                payload.get("description")
                or payload.get("summary")
                or payload.get("insight")
            )
            if description is not None:
                description = str(description)
        title = payload.get("title") or payload.get("name")
        if title is not None:
            title = str(title)
        published_at = payload.get("published_at") or payload.get("date")
        score_value = payload.get("score") or payload.get("confidence") or payload.get("relevance")
        score: float | None
        try:
            score = float(score_value) if score_value is not None else None
        except (TypeError, ValueError):  # pragma: no cover - defensive guard
            score = None
        return DeepSearchSource(
            url=url,
            title=title,
            description=description,
            published_at=str(published_at) if published_at else None,
            score=score,
        )


__all__ = ["ParallelDeepSearchClient", "DeepSearchResult", "DeepSearchSource", "DeepSearchError"]