"""Utilities for generating and handling AI-driven articles."""

from __future__ import annotations

import json
import re
import time
from typing import Any, Dict, Iterable

try:  # pragma: no cover - optional dependency for tests
    from openai import OpenAI
except ImportError:  # pragma: no cover - allow running without the package during tests
    OpenAI = None  # type: ignore[assignment]

from .article_schema import ARTICLE_DOCUMENT_SCHEMA
from .config import get_openai_settings


class ArticleGenerationError(RuntimeError):
    """Raised when the assistant cannot deliver a usable article payload."""


class OpenAIAssistantArticleGenerator:
    """Generate structured Polish articles using the configured OpenAI Assistant."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        assistant_id: str | None = None,
    ) -> None:
        settings = get_openai_settings()
        self.api_key = api_key if api_key is not None else settings.get("api_key")
        self.assistant_id = assistant_id or settings.get("assistant_id")
        if not self.assistant_id:
            raise ArticleGenerationError("OpenAI assistant id is not configured")
        if OpenAI and self.api_key:
            self._client = OpenAI(api_key=self.api_key)
        else:
            self._client = None
        self.schema = ARTICLE_DOCUMENT_SCHEMA

    @property
    def is_configured(self) -> bool:
        """Return True when the OpenAI client is ready to send requests."""

        return self._client is not None

    def generate_article(
        self,
        *,
        topic: str,
        rubric: str,
        keywords: Iterable[str] | None = None,
        guidance: str | None = None,
    ) -> Dict[str, Any]:
        """Call the Assistant and transform the JSON response into Python objects."""

        if not self._client:
            raise ArticleGenerationError("OpenAI API key is not configured")

        keyword_text = ", ".join(keywords or [])
        instructions = self._compose_prompt(
            topic=topic,
            rubric=rubric,
            keyword_text=keyword_text,
            guidance=guidance,
        )
        thread = self._client.beta.threads.create(
            messages=[
                {
                    "role": "user",
                    "content": instructions,
                }
            ]
        )

        run = self._client.beta.threads.runs.create(
            thread_id=thread.id,
            assistant_id=self.assistant_id,
        )
        run = self._poll_run(thread_id=thread.id, run_id=run.id)
        if run.status != "completed":
            raise ArticleGenerationError(f"Assistant returned status {run.status}")

        messages = self._client.beta.threads.messages.list(
            thread_id=thread.id,
            order="desc",
            limit=1,
        )
        article_payload = self._extract_payload(messages.data)
        return article_payload

    def _poll_run(self, *, thread_id: str, run_id: str, timeout: float = 120.0) -> Any:
        """Poll the assistant run until completion or timeout."""

        start = time.time()
        while time.time() - start < timeout:
            run = self._client.beta.threads.runs.retrieve(
                thread_id=thread_id,
                run_id=run_id,
            )
            if run.status in {"completed", "failed", "expired"}:
                return run
            time.sleep(2)
        raise ArticleGenerationError("Assistant run polling timed out")

    def _compose_prompt(
        self,
        *,
        topic: str,
        rubric: str,
        keyword_text: str,
        guidance: str | None,
    ) -> str:
        """Compose the prompt that is sent to the assistant."""

        schema_text = json.dumps(self.schema, ensure_ascii=False, indent=2)
        optional_guidance = f"\nDodatkowe wskazówki: {guidance}." if guidance else ""
        keyword_line = f" Słowa kluczowe SEO: {keyword_text}." if keyword_text else ""
        return (
            "Jesteś redaktorem prowadzącym polskojęzycznego bloga joga.yoga. "
            "Tworzysz długie artykuły z rubryki wellness, w pełni zoptymalizowane pod SEO, GEO i AEO. "
            f"Rubryka artykułu: {rubric}. Temat przewodni: {topic}.{keyword_line} "
            "Przygotuj kompletną strukturę artykułu z sekcjami oraz FAQ na końcu (2-3 pytania). "
            "Artykuł musi być napisany w języku polskim, styl: empatyczny, ekspercki, zorientowany na praktykę. "
            "Zwracaj odpowiedź wyłącznie jako JSON zgodny ze schematem. Nie dodawaj komentarzy ani markdown."
            f"\nSchemat JSON: {schema_text}{optional_guidance}"
        )

    def _extract_payload(self, messages: Any) -> Dict[str, Any]:
        """Extract and validate JSON content from the assistant message list."""

        for message in messages:
            for content in getattr(message, "content", []) or []:
                if getattr(content, "type", "") == "text":
                    text = getattr(content.text, "value", "")
                    data = self._parse_json(text)
                    if data:
                        return data
        raise ArticleGenerationError("Assistant response did not include valid JSON payload")

    def _parse_json(self, text: str) -> Dict[str, Any] | None:
        """Try to load the first JSON object found within the text."""

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if not match:
                return None
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                return None


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
