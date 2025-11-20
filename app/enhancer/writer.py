"""OpenAI based helper that generates the enhancement sections and FAQ."""

from __future__ import annotations

import json
from dataclasses import dataclass
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


@dataclass(slots=True)
class EnhancementResponse:
    """Structured output from the OpenAI writer."""

    added_sections: List[dict[str, str]]
    added_faq: dict[str, str]


class EnhancementWriter:
    """Generate fresh sections and FAQ entry via the OpenAI Chat Completions API."""

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
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
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
            added_sections=payload["added_sections"],
            added_faq=payload["added_faq"],
        )

    def _build_system_prompt(self) -> str:
        return (
            "Jesteś redaktorem joga.yoga. Piszesz po polsku, ciepłym i eksperckim tonem."
            " Uzupełniasz istniejący artykuł o co najmniej dwie nowe sekcje H2 bazując"
            " na świeżych materiałach zewnętrznych oraz dodajesz jedno pytanie FAQ."
            " Nie używasz technicznych nagłówków ani dat w tytułach. Odpowiadasz tylko JSON-em."
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
        return (
            "Aktualny artykuł joga.yoga:\n"
            f"Nagłówek: {request.headline}\n"
            f"Lead: {request.lead}\n"
            f"Sekcje:\n{section_summaries}\n\n"
            f"FAQ:\n{faq_summary or '- brak'}\n\n"
            f"Nowe materiały z Parallel.ai:\n{insights}\n\n"
            f"Źródła (max 6):\n{citation_lines}\n\n"
            "Polecenie:\n"
            "1. Na bazie powyższych informacji przygotuj 2–3 zupełnie nowe sekcje artykułu.\n"
            "   Każda sekcja ma mieć chwytliwy tytuł H2 po polsku (bez dat, bez frazy 'Dopelniono').\n"
            "   W treści umieść konkretne wskazówki, przykłady lub dane zaczerpnięte z badań.\n"
            "2. Dodaj jedno nowe pytanie FAQ wraz z odpowiedzią, inspirowane świeżymi insightami.\n"
            "3. Nie kopiuj istniejących akapitów. Korzystaj z linków i streszczenia powyżej, łącząc je z kontekstem joga.yoga.\n"
            "4. Odpowiedz WYŁĄCZNIE w formacie JSON: {\"added_sections\": [{title, body}, ...], \"added_faq\": {question, answer}}."
        )

    def _extract_text(self, response: Any) -> str:
        choices = getattr(response, "choices", None) or []
        for choice in choices:
            message = getattr(choice, "message", None)
            if not message:
                continue
            content = getattr(message, "content", None)
            if isinstance(content, str) and content.strip():
                return content.strip()
            if isinstance(content, list):
                for part in content:
                    text_value = self._extract_text_value(part)
                    if text_value:
                        return text_value
        raise EnhancementWriterError("Assistant response did not contain text content")

    @staticmethod
    def _extract_text_value(part: Any) -> str | None:
        """Return textual content from a message part if present."""

        if isinstance(part, dict):
            if part.get("type") == "text":
                text = part.get("text")
                if isinstance(text, dict) and text.get("value"):
                    return str(text["value"]).strip()
            if part.get("text") and isinstance(part.get("text"), str):
                return str(part["text"]).strip()
        text_attr = getattr(part, "text", None)
        if isinstance(text_attr, str) and text_attr.strip():
            return text_attr.strip()
        if hasattr(text_attr, "value") and str(text_attr.value).strip():
            return str(text_attr.value).strip()
        return None

    def _parse_payload(self, text: str) -> dict[str, Any]:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.removeprefix("```").strip()
            if "\n" in cleaned:
                cleaned = "\n".join(cleaned.splitlines()[1:])
            if cleaned.endswith("```"):
                cleaned = cleaned[: -len("```")].strip()
        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise EnhancementWriterError(f"Assistant returned invalid JSON: {exc}") from exc
        if "added_sections" not in payload or "added_faq" not in payload:
            raise EnhancementWriterError("Assistant response missing required keys")
        sections = payload["added_sections"]
        if not isinstance(sections, list):
            raise EnhancementWriterError("added_sections must be a list")
        cleaned_sections: list[dict[str, str]] = []
        for item in sections:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            body = str(item.get("body") or "").strip()
            if not title or not body:
                continue
            cleaned_sections.append({"title": title, "body": body})
        if not cleaned_sections:
            raise EnhancementWriterError("Assistant response did not include any valid sections")
        faq = payload["added_faq"]
        if not isinstance(faq, dict):
            raise EnhancementWriterError("added_faq must be an object")
        question = str(faq.get("question") or "").strip()
        answer = str(faq.get("answer") or "").strip()
        if not question or not answer:
            raise EnhancementWriterError("added_faq must include question and answer")

        payload["added_sections"] = cleaned_sections
        payload["added_faq"] = {"question": question, "answer": answer}
        return payload


__all__ = [
    "EnhancementWriter",
    "EnhancementWriterError",
    "EnhancementRequest",
    "EnhancementResponse",
]
