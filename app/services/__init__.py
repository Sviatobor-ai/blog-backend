"""Utilities for generating and handling AI-driven articles."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Any, Iterable

from jsonschema import Draft7Validator

from ..article_schema import ARTICLE_DOCUMENT_SCHEMA
from ..config import get_openai_settings
from ..integrations.openai_client import (
    OpenAIClient,
    OpenAIClientError,
)


class ArticleGenerationError(RuntimeError):
    """Raised when the assistant cannot deliver a usable article payload."""


class AssistantInvalidJSON(ArticleGenerationError):
    """Raised when the assistant response cannot be parsed or validated."""


class OpenAIIntegrationError(ArticleGenerationError):
    """Raised when the OpenAI API request fails or returns an error state."""

    def __init__(self, message: str, *, code: str | int | None = None, status: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


def _shorten(message: str, *, limit: int = 300) -> str:
    if len(message) <= limit:
        return message
    suffix = "…"
    return f"{message[: limit - len(suffix)]}{suffix}"


@lru_cache
def _article_validator() -> Draft7Validator:
    return Draft7Validator(ARTICLE_DOCUMENT_SCHEMA)


def validate_article_payload(payload: Any) -> dict[str, Any]:
    """Validate payload against the article JSON schema."""

    validator = _article_validator()
    errors = list(validator.iter_errors(payload))
    if errors:
        first = sorted(errors, key=lambda err: list(err.path))[0]
        location = ".".join(str(part) for part in first.path) or "payload"
        raise AssistantInvalidJSON(_shorten(f"{location}: {first.message}"))
    if not isinstance(payload, dict):
        raise AssistantInvalidJSON("payload: JSON root must be an object")
    return payload


def _extract_first_json_object(text: str) -> str | None:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    return match.group(0)


def _load_payload(text: str) -> dict[str, Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        candidate = _extract_first_json_object(text)
        if not candidate:
            raise AssistantInvalidJSON("Assistant response did not contain JSON object")
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as exc:
            raise AssistantInvalidJSON(_shorten(f"Assistant returned invalid JSON: {exc}")) from exc


class _BaseAssistantGenerator:
    """Common helpers for OpenAI based article generators."""

    def __init__(
        self,
        *,
        api_key: str | None,
        assistant_id: str | None,
        request_timeout_s: float | None = None,
    ) -> None:
        settings = get_openai_settings()
        self._api_key = api_key if api_key is not None else settings.api_key
        self._assistant_id = assistant_id or settings.assistant_id
        self._request_timeout_s = request_timeout_s if request_timeout_s is not None else settings.request_timeout_s
        self._client: OpenAIClient | None = None
        if not self._assistant_id:
            raise ArticleGenerationError("OpenAI assistant id is not configured")

    def _ensure_client(self) -> OpenAIClient:
        if self._client is None:
            if not self._api_key:
                raise ArticleGenerationError("OpenAI API key is not configured")
            self._client = OpenAIClient(
                api_key=self._api_key,
                request_timeout_s=self._request_timeout_s,
            )
        return self._client

    def _execute(
        self,
        *,
        user_message: str,
        run_instructions: str,
        timeout_s: float | None = None,
    ) -> dict[str, Any]:
        client = self._ensure_client()
        try:
            thread_id = client.create_thread()
            client.add_user_message(thread_id, user_message)
            response_text = client.run_assistant(
                thread_id=thread_id,
                assistant_id=self._assistant_id,
                instructions=run_instructions,
                timeout_s=timeout_s if timeout_s is not None else self._request_timeout_s,
            )
        except OpenAIClientError as exc:
            raise OpenAIIntegrationError(exc.message, code=exc.code, status=exc.status) from exc
        payload = _load_payload(response_text)
        return validate_article_payload(payload)


class OpenAIAssistantArticleGenerator(_BaseAssistantGenerator):
    """Generate structured Polish articles using the configured OpenAI Assistant."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        assistant_id: str | None = None,
        request_timeout_s: float | None = None,
    ) -> None:
        super().__init__(
            api_key=api_key,
            assistant_id=assistant_id,
            request_timeout_s=request_timeout_s,
        )
        self._schema_text = json.dumps(ARTICLE_DOCUMENT_SCHEMA, ensure_ascii=False, indent=2)

    def generate_article(
        self,
        *,
        topic: str,
        rubric: str,
        keywords: Iterable[str] | None = None,
        guidance: str | None = None,
    ) -> dict[str, Any]:
        keyword_text = ", ".join(keywords or [])
        prompt = self._compose_prompt(
            topic=topic,
            rubric=rubric,
            keyword_text=keyword_text,
            guidance=guidance,
        )
        instructions = (
            "Generate the article in Polish (pl-PL). Return only JSON strictly matching "
            "ARTICLE_DOCUMENT_SCHEMA."
        )
        return self._execute(user_message=prompt, run_instructions=instructions)

    def _compose_prompt(
        self,
        *,
        topic: str,
        rubric: str,
        keyword_text: str,
        guidance: str | None,
    ) -> str:
        optional_guidance = f"\nDodatkowe wskazówki: {guidance}." if guidance else ""
        keyword_line = f" Słowa kluczowe SEO: {keyword_text}." if keyword_text else ""
        return (
            "Jesteś redaktorem prowadzącym polskojęzycznego bloga joga.yoga. "
            "Tworzysz długie artykuły z rubryki wellness, zoptymalizowane pod SEO, GEO i AEO. "
            f"Rubryka artykułu: {rubric}. Temat przewodni: {topic}.{keyword_line} "
            "Przygotuj kompletną strukturę artykułu z sekcjami oraz FAQ na końcu (2-3 pytania). "
            "Artykuł musi być napisany w języku polskim, styl: empatyczny, ekspercki, zorientowany na praktykę. "
            "Zwracaj odpowiedź wyłącznie jako JSON zgodny ze schematem. Nie dodawaj komentarzy ani markdown."
            f"\nSchemat JSON: {self._schema_text}{optional_guidance}"
        )


class OpenAIAssistantFromTranscriptGenerator(_BaseAssistantGenerator):
    """Generate articles from raw transcripts using a dedicated assistant."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        assistant_id: str | None = None,
        request_timeout_s: float | None = None,
    ) -> None:
        settings = get_openai_settings()
        super().__init__(
            api_key=api_key,
            assistant_id=assistant_id or settings.assistant_fromvideo_id,
            request_timeout_s=request_timeout_s,
        )
        self._schema_text = json.dumps(ARTICLE_DOCUMENT_SCHEMA, ensure_ascii=False)

    def generate_from_transcript(self, *, raw_text: str, source_url: str) -> dict[str, Any]:
        transcript = raw_text.strip()
        user_message = (
            "Poniżej znajduje się transkrypcja (oryginał może być w innym języku). "
            "Napisz artykuł po polsku zgodnie z wymaganym schematem. "
            f"Ustaw SEO.canonical na: {source_url}."
            f"\n\nSchemat JSON: {self._schema_text}"
            "\n\nTRANSKRYPCJA:\n"
            f"{transcript}"
        )
        instructions = (
            "Generate in Polish (pl-PL), return only JSON strictly matching ARTICLE_DOCUMENT_SCHEMA. "
            f"If needed translate the transcript to Polish. Fill SEO, taxonomy and AEO fields zgodnie z wytycznymi joga.yoga. "
            f"Set seo.canonical to {source_url}."
        )
        # TODO: consider using the Responses API with structured outputs once available.
        return self._execute(user_message=user_message, run_instructions=instructions)


def slugify_pl(value: str) -> str:
    """Slugify Polish strings to lowercase URL fragments."""

    translation_map = str.maketrans("ąćęłńóśżź", "acelnoszz")
    value = value.lower().translate(translation_map)
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return value[:200]


def ensure_unique_slug(existing_slugs: Iterable[str], desired_slug: str) -> str:
    """Return a slug that does not clash with the provided collection."""

    existing = set(existing_slugs)
    if desired_slug not in existing:
        return desired_slug
    base = desired_slug
    index = 2
    candidate = f"{base}-{index}"
    while candidate in existing:
        index += 1
        candidate = f"{base}-{index}"
    return candidate


@lru_cache
def get_transcript_generator() -> OpenAIAssistantFromTranscriptGenerator:
    """Return a cached assistant instance dedicated to transcript processing."""

    settings = get_openai_settings()
    return OpenAIAssistantFromTranscriptGenerator(
        api_key=settings.api_key,
        assistant_id=settings.assistant_fromvideo_id,
        request_timeout_s=settings.request_timeout_s,
    )
