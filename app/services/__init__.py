"""Utilities for generating and handling AI-driven articles."""

from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from typing import Any, Iterable

from jsonschema import Draft7Validator

from ..article_schema import (
    ARTICLE_DOCUMENT_SCHEMA,
    ARTICLE_FAQ_MAX,
    ARTICLE_FAQ_MIN,
    ARTICLE_MIN_CITATIONS,
    ARTICLE_MIN_LEAD,
    ARTICLE_MIN_SECTIONS,
    ARTICLE_MIN_TAGS,
)
from ..config import get_openai_settings, get_site_base_url
from ..integrations.openai_client import OpenAIClient, OpenAIClientError
from .prompt_builders import (
    build_generation_brief_topic,
    build_generation_brief_transcript,
    build_generation_system_instructions,
)


logger = logging.getLogger(__name__)


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


@lru_cache
def _article_canonical_base() -> str:
    """Return the canonical base URL without forcing a fixed path segment."""

    return get_site_base_url().rstrip("/")


def get_article_canonical_base() -> str:
    """Return the canonical base URL for generated articles."""

    return _article_canonical_base()


def build_canonical_for_slug(slug: str) -> str:
    """Return canonical URL for the provided slug within the joga.yoga domain."""

    slug_part = str(slug or "").strip().strip("/")
    base = _article_canonical_base()
    if not slug_part:
        return base
    return f"{base}/{slug_part}"




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

    @property
    def is_configured(self) -> bool:
        """Return True when both API key and assistant id are available."""

        return bool(self._api_key) and bool(self._assistant_id)

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
        if not self._assistant_id:
            raise ArticleGenerationError("OpenAI assistant id is not configured")
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
        try:
            payload = _load_payload(response_text)
        except AssistantInvalidJSON as exc:
            logger.warning(
                "assistant-draft rejected reason=%s preview=%s",
                exc,
                _shorten(response_text, limit=800),
            )
            raise
        try:
            return validate_article_payload(payload)
        except AssistantInvalidJSON as exc:
            try:
                serialized = json.dumps(payload, ensure_ascii=False)
            except TypeError:
                serialized = str(payload)
            logger.warning(
                "assistant-draft schema-fail reason=%s payload=%s",
                exc,
                _shorten(serialized, limit=800),
            )
            raise


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

    def generate_article(
        self,
        *,
        topic: str,
        rubric: str,
        keywords: Iterable[str] | None = None,
        guidance: str | None = None,
        research_content: str | None = None,
        research_sources: Iterable | None = None,
    ) -> dict[str, Any]:
        prompt = self._compose_prompt(
            topic=topic,
            rubric=rubric,
            keywords=keywords,
            guidance=guidance,
            research_content=research_content,
            research_sources=research_sources,
        )
        instructions = build_generation_system_instructions()
        return self._execute(user_message=prompt, run_instructions=instructions)

    def _compose_prompt(
        self,
        *,
        topic: str,
        rubric: str,
        keywords: Iterable[str] | None,
        guidance: str | None,
        research_content: str | None,
        research_sources: Iterable | None,
    ) -> str:
        return build_generation_brief_topic(
            rubric_name=rubric,
            topic=topic,
            keywords=keywords,
            guidance=guidance,
            research_content=research_content,
            research_sources=research_sources,
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

    def generate_from_transcript(
        self,
        *,
        raw_text: str,
        source_url: str,
        research_content: str | None = None,
        research_sources: Iterable | None = None,
    ) -> dict[str, Any]:
        transcript = raw_text.strip()
        user_message = build_generation_brief_transcript(
            rubric_name=None,
            topic=None,
            keywords=None,
            guidance=None,
            transcript_text=transcript,
            research_content=research_content,
            research_sources=research_sources,
        )
        instructions = build_generation_system_instructions(source_url=source_url)
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
