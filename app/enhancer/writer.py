"""OpenAI based helper that generates the enhancement block."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import Any, List

try:  # pragma: no cover - optional dependency guard
    from openai import OpenAI
except ImportError:  # pragma: no cover - optional dependency guard
    OpenAI = None  # type: ignore[assignment]


class EnhancementWriterError(RuntimeError):
    """Raised when the OpenAI writer fails."""


@dataclass(slots=True)
class EnhancementRequest:
    """Context passed to the OpenAI writer."""

    headline: str
    lead: str
    sections: List[dict[str, str]]
    faq: List[dict[str, str]]
    insights: str | None
    citations: List[dict[str, str]]
    enhancement_date: date


@dataclass(slots=True)
class EnhancementResponse:
    """Structured output from the OpenAI writer."""

    added_section: dict[str, str]
    added_faq: dict[str, str]


class EnhancementWriter:
    """Generate the "Dopelniono" block and FAQ entry via OpenAI Responses API."""

    def __init__(self, *, api_key: str | None, model: str = "gpt-4.1-mini", timeout_s: float = 120.0) -> None:
        if not api_key:
            raise EnhancementWriterError("OPENAI_API_KEY is not configured")
        if OpenAI is None:  # pragma: no cover - optional dependency guard
            raise EnhancementWriterError("openai package is not installed")
        self._client = OpenAI(api_key=api_key, timeout=timeout_s)
        self._model = model

    def generate(self, request: EnhancementRequest) -> EnhancementResponse:
        """Request new content from OpenAI and return the parsed response."""

        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(request)
        try:
            response = self._client.responses.create(
                model=self._model,
                input=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.4,
            )
        except Exception as exc:  # pragma: no cover - network guard
            raise EnhancementWriterError(f"OpenAI request failed: {exc}") from exc

        text = self._extract_text(response)
        payload = self._parse_payload(text)
        return EnhancementResponse(
            added_section=payload["added_section"],
            added_faq=payload["added_faq"],
        )

    def _build_system_prompt(self) -> str:
        return (
            "Jesteś redaktorem joga.yoga. Piszesz po polsku, ciepłym i eksperckim tonem."
            " Masz dodać jedną sekcję 'Dopelniono {data}' oraz jedno pytanie FAQ bazując na"
            " najnowszych materiałach. Zwracasz wyłącznie JSON zgodny z poleceniem."
        )

    def _build_user_prompt(self, request: EnhancementRequest) -> str:
        section_summaries = "\n".join(
            f"- {section['title']}: {section['body'][:400]}" for section in request.sections
        )
        faq_summary = "\n".join(f"- {item['question']}: {item['answer'][:200]}" for item in request.faq)
        citation_lines = "\n".join(
            f"- {item.get('label') or item['url']}: {item['url']}" for item in request.citations
        )
        insights = request.insights or "Brak dodatkowego streszczenia — wykorzystaj kontekst z linków."
        enhancement_date = request.enhancement_date.isoformat()
        return (
            "Aktualny artykuł joga.yoga:\n"
            f"Nagłówek: {request.headline}\n"
            f"Lead: {request.lead}\n"
            f"Sekcje:\n{section_summaries}\n\n"
            f"FAQ:\n{faq_summary or '- brak'}\n\n"
            f"Nowe materiały z Parallel.ai:\n{insights}\n\n"
            f"Źródła (3-4):\n{citation_lines}\n\n"
            "Polecenie:\n"
            f"1. Napisz nową sekcję zatytułowaną dokładnie 'Dopelniono {enhancement_date}'.\n"
            "   Sekcja ma mieć 2-4 akapity i jasno pokazywać, co się zmieniło względem oryginału.\n"
            "2. Dodaj jedno nowe pytanie FAQ wraz z odpowiedzią na bazie świeżych informacji.\n"
            "3. Nie przepisuj starej treści, korzystaj z linków i streszczenia powyżej.\n"
            "4. Odpowiedz WYŁĄCZNIE w formacie JSON: {\"added_section\": {title, body}, \"added_faq\": {question, answer}}."
        )

    def _extract_text(self, response: Any) -> str:
        output_text = getattr(response, "output_text", None)
        if output_text:
            return str(output_text)
        output = getattr(response, "output", None) or []
        if isinstance(output, list):
            for item in output:
                content = getattr(item, "content", None)
                if isinstance(content, list):
                    for part in content:
                        text = getattr(part, "text", None)
                        if text and getattr(text, "value", None):
                            return str(text.value)
                elif getattr(item, "text", None):
                    return str(item.text)
        raise EnhancementWriterError("Assistant response did not contain text content")

    def _parse_payload(self, text: str) -> dict[str, Any]:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise EnhancementWriterError(f"Assistant returned invalid JSON: {exc}") from exc
        if "added_section" not in payload or "added_faq" not in payload:
            raise EnhancementWriterError("Assistant response missing required keys")
        return payload


__all__ = [
    "EnhancementWriter",
    "EnhancementWriterError",
    "EnhancementRequest",
    "EnhancementResponse",
]
