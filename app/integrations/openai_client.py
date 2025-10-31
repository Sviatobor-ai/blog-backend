"""Thin wrapper around the OpenAI Assistants API v2."""

from __future__ import annotations

import logging
import time
from typing import Any, Iterable

try:  # pragma: no cover - optional dependency for tests
    from openai import APIError, APIStatusError, OpenAI
except ImportError:  # pragma: no cover - allow running without the package during tests
    APIError = APIStatusError = OpenAI = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


def _shorten(message: str, *, limit: int = 300) -> str:
    """Trim long error messages to a safe size for storage/logging."""

    if len(message) <= limit:
        return message
    suffix = "…"
    return f"{message[: limit - len(suffix)]}{suffix}"


class OpenAIClientError(RuntimeError):
    """Base error raised by :class:`OpenAIClient`."""

    def __init__(self, message: str, *, code: str | int | None = None, status: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status


class OpenAIRunTimeout(OpenAIClientError):
    """Raised when a run does not finish within the configured timeout."""


class OpenAIRunFailed(OpenAIClientError):
    """Raised when the assistant run finishes without completing successfully."""


class OpenAITransportError(OpenAIClientError):
    """Raised when the OpenAI API returns transport/HTTP errors."""


class OpenAIClient:
    """Utility wrapper offering a minimal Assistants v2 API surface."""

    def __init__(self, *, api_key: str, request_timeout_s: float = 120.0) -> None:
        if not api_key:
            raise OpenAIClientError("OpenAI API key is not configured")
        if OpenAI is None:  # pragma: no cover - optional dependency guard
            raise OpenAIClientError("openai package is not installed")
        self._client = OpenAI(api_key=api_key, timeout=request_timeout_s)

    def create_thread(self) -> str:
        """Create an empty thread and return its identifier."""

        try:
            thread = self._client.beta.threads.create()
        except (APIError, APIStatusError) as exc:  # pragma: no cover - network guard
            raise self._translate_error(exc) from exc
        return thread.id

    def add_user_message(self, thread_id: str, text: str) -> None:
        """Append a user message with a single text part to the thread."""

        try:
            self._client.beta.threads.messages.create(
                thread_id=thread_id,
                role="user",
                content=[{"type": "text", "text": text}],
            )
        except (APIError, APIStatusError) as exc:  # pragma: no cover - network guard
            raise self._translate_error(exc) from exc

    def run_assistant(
        self,
        *,
        thread_id: str,
        assistant_id: str,
        instructions: str | None = None,
        timeout_s: float = 120.0,
    ) -> str:
        """Execute the assistant and return the combined assistant message text."""

        start = time.monotonic()
        logger.info("openai-run start thread=%s", thread_id)
        try:
            run = self._client.beta.threads.runs.create(
                thread_id=thread_id,
                assistant_id=assistant_id,
                instructions=instructions,
            )
        except (APIError, APIStatusError) as exc:
            error = self._translate_error(exc)
            logger.error(
                "openai-run error thread=%s code=%s type=%s msg=%s",
                thread_id,
                error.code,
                exc.__class__.__name__,
                error.message,
            )
            raise error from exc

        deadline = start + timeout_s
        while True:
            if time.monotonic() >= deadline:
                error = OpenAIRunTimeout("Assistant run polling timed out", status="timeout")
                logger.error(
                    "openai-run error thread=%s code=%s type=%s msg=%s",
                    thread_id,
                    error.code,
                    error.__class__.__name__,
                    error.message,
                )
                raise error
            try:
                run = self._client.beta.threads.runs.retrieve(
                    thread_id=thread_id,
                    run_id=run.id,
                )
            except (APIError, APIStatusError) as exc:  # pragma: no cover - network guard
                error = self._translate_error(exc)
                logger.error(
                    "openai-run error thread=%s code=%s type=%s msg=%s",
                    thread_id,
                    error.code,
                    exc.__class__.__name__,
                    error.message,
                )
                raise error from exc

            if run.status in {"completed", "failed", "cancelled", "expired"}:
                break
            time.sleep(1.5)

        if run.status != "completed":
            detail = None
            if getattr(run, "last_error", None):
                detail = getattr(run.last_error, "message", None) or getattr(run.last_error, "code", None)
            message = detail or f"Assistant returned status {run.status}"
            error = OpenAIRunFailed(_shorten(message), status=run.status)
            logger.error(
                "openai-run error thread=%s code=%s type=%s msg=%s",
                thread_id,
                error.code,
                error.__class__.__name__,
                error.message,
            )
            raise error

        elapsed = time.monotonic() - start
        logger.info("openai-run done thread=%s elapsed=%.2fs", thread_id, elapsed)

        try:
            messages = self._client.beta.threads.messages.list(
                thread_id=thread_id,
                order="desc",
                limit=5,
            )
        except (APIError, APIStatusError) as exc:  # pragma: no cover - network guard
            error = self._translate_error(exc)
            logger.error(
                "openai-run error thread=%s code=%s type=%s msg=%s",
                thread_id,
                error.code,
                exc.__class__.__name__,
                error.message,
            )
            raise error from exc

        text = self._extract_assistant_text(messages.data)
        size_bytes = len(text.encode("utf-8"))
        logger.info("assistant-json bytes=%s", size_bytes)
        return text

    def _extract_assistant_text(self, messages: Iterable[Any]) -> str:
        """Return concatenated text parts from the latest assistant message."""

        for message in messages:
            role = getattr(message, "role", None) or (message.get("role") if isinstance(message, dict) else None)
            if role != "assistant":
                continue
            parts: list[str] = []
            for content in getattr(message, "content", []) or []:
                content_type = getattr(content, "type", None) or (
                    content.get("type") if isinstance(content, dict) else None
                )
                if content_type != "text":
                    continue
                text_obj = getattr(content, "text", None)
                if isinstance(content, dict):
                    text_obj = content.get("text")
                if isinstance(text_obj, dict):
                    value = text_obj.get("value") or text_obj.get("text")
                else:
                    value = getattr(text_obj, "value", None) or getattr(text_obj, "text", None) or text_obj
                if value:
                    parts.append(str(value))
            if parts:
                return "\n".join(part.strip() for part in parts if part).strip()
        raise OpenAIRunFailed("Assistant did not return text content", status="no-text")

    def _translate_error(self, exc: Exception) -> OpenAITransportError:
        """Convert OpenAI exceptions into a transport error instance."""

        code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
        message = getattr(exc, "message", None) or str(exc)
        return OpenAITransportError(_shorten(message), code=code)
