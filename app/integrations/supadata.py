"""Client for interacting with SupaData APIs."""

from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Iterable, List, Optional

import httpx
from fastapi import HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_CONNECT_TIMEOUT = 10.0
_SEARCH_TIMEOUT = 10.0
_TRANSCRIPT_REQUEST_TIMEOUT = 10.0
_ASR_REQUEST_TIMEOUT = 15.0
# Single-operation budgets (seconds) to keep transcript/ASR calls bounded.
_TRANSCRIPT_TOTAL_BUDGET = 90.0
_ASR_TOTAL_BUDGET = 180.0
MIN_TRANSCRIPT_CHARS = int(os.getenv("MIN_TRANSCRIPT_CHARS", "200"))


class TranscriptResult(BaseModel):
    text: str
    lang: str | None = None
    available_langs: list[str] = Field(default_factory=list)
    content_chars: int = 0

    @property
    def content(self) -> str:  # pragma: no cover - compatibility shim
        return self.text


class SupadataTranscriptError(Exception):
    """Raised when SupaData cannot return a transcript."""

    def __init__(
        self,
        *,
        status_code: int | None,
        video_url: str,
        error_body: Any | None = None,
        message: str | None = None,
    ) -> None:
        label = f"Supadata transcript error status={status_code}" if status_code else "Supadata transcript error"
        super().__init__(message or label)
        self.status_code = status_code
        self.video_url = video_url
        self.error_body = error_body


class SupadataTranscriptTooShortError(SupadataTranscriptError):
    """Raised when SupaData returns a transcript below the minimum length."""

    def __init__(self, *, video_url: str, content_chars: int, threshold: int) -> None:
        super().__init__(status_code=422, video_url=video_url, message="Transcript too short")
        self.content_chars = content_chars
        self.threshold = threshold


@dataclass
class SDVideo:
    """Simplified representation of a YouTube video returned by SupaData."""

    video_id: str
    url: str
    title: str
    channel: Optional[str]
    duration_seconds: Optional[int]
    published_at: Optional[str]
    description_snippet: Optional[str]


class SupaDataClient:
    """Synchronous HTTP client talking to SupaData endpoints."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://api.supadata.ai/v1",
        client: httpx.Client | None = None,
        asr_poll_interval: float = 5.0,
        asr_poll_attempts: int | None = None,
        transcript_total_timeout: float = _TRANSCRIPT_TOTAL_BUDGET,
        asr_total_timeout: float = _ASR_TOTAL_BUDGET,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._owns_client = client is None
        headers = {"x-api-key": self.api_key}
        if client is None:
            self._client = httpx.Client(
                base_url=self.base_url,
                headers=headers,
                timeout=_make_timeout(_SEARCH_TIMEOUT),
            )
        else:
            self._client = client
            self._client.headers.update(headers)
        self._asr_poll_interval = max(0.0, asr_poll_interval)
        self._transcript_budget = max(1.0, transcript_total_timeout)
        self._asr_budget = max(1.0, asr_total_timeout)
        if asr_poll_attempts is None:
            interval = max(self._asr_poll_interval, 0.5)
            derived_attempts = int(self._asr_budget // interval)
            self._asr_poll_attempts = max(1, derived_attempts)
        else:
            self._asr_poll_attempts = max(1, asr_poll_attempts)

    def close(self) -> None:
        """Close the underlying HTTP client if owned by this instance."""

        if self._owns_client:
            self._client.close()

    # --- 1) SEARCH ---
    def search_youtube(
        self,
        query: str,
        limit: int | None = None,
        *,
        type_: str | None = None,
        duration: str | None = None,
        features: Optional[List[str]] = None,
    ) -> List[SDVideo]:
        """Call SupaData search endpoint and normalise the payload."""

        params: dict[str, Any] = {"query": query}
        if limit:
            params["limit"] = int(limit)
        if type_:
            params["type"] = type_
        if duration:
            params["duration"] = duration
        if features:
            params["features"] = ",".join(features)

        try:
            response = self._client.get(
                "/youtube/search",
                params=params,
                timeout=_make_timeout(_SEARCH_TIMEOUT),
            )
        except httpx.HTTPError as exc:  # pragma: no cover - network failures are logged
            logger.warning("supadata-search error query=%s err=%s", query, exc)
            raise HTTPException(status_code=502, detail="supadata search failed") from exc

        if response.status_code // 100 != 2:
            logger.warning(
                "supadata-search status=%s query=%s",
                response.status_code,
                query,
            )
            raise HTTPException(status_code=502, detail="supadata search failed")

        data = response.json()
        raw_items: Iterable[dict[str, Any]] = _extract_items(data)
        videos: List[SDVideo] = []
        for item in raw_items:
            duration_seconds = _parse_duration_seconds(
                item.get("duration_seconds")
                or item.get("duration")
                or item.get("contentDetails", {}).get("duration")
            )
            video_id = str(
                item.get("video_id")
                or item.get("id")
                or item.get("videoId")
                or ""
            ).strip()
            if not video_id:
                continue
            url = item.get("url") or f"https://www.youtube.com/watch?v={video_id}"
            title = item.get("title") or item.get("name") or video_id
            channel = (
                item.get("channel")
                or item.get("channel_title")
                or item.get("channelTitle")
            )
            description = (
                item.get("description_snippet")
                or item.get("description")
                or item.get("snippet", {}).get("description")
            )
            published_at = (
                item.get("published_at")
                or item.get("publishedAt")
                or item.get("snippet", {}).get("publishedAt")
            )
            videos.append(
                SDVideo(
                    video_id=video_id,
                    url=str(url),
                    title=str(title),
                    channel=str(channel) if channel else None,
                    duration_seconds=duration_seconds,
                    published_at=str(published_at) if published_at else None,
                    description_snippet=str(description) if description else None,
                )
            )
        return videos

    # --- 2) GET TRANSCRIPT ---
    def get_transcript(
        self,
        *,
        url: str,
        lang: str | None = None,
        mode: str = "auto",
        text: bool = True,
        poll_interval: float = 5.0,
        poll_timeout: float = 300.0,
    ) -> TranscriptResult:
        """Fetch a transcript for the given URL using the universal endpoint."""

        logger.info(
            "event=supadata.transcript.request video_url=%s lang=%s mode=%s",
            url,
            lang,
            mode,
        )
        params: dict[str, Any] = {"url": url, "mode": mode, "text": str(text).lower()}
        if lang:
            params["lang"] = lang

        try:
            response = self._client.get(
                "/transcript",
                params=params,
                timeout=_make_timeout(_TRANSCRIPT_REQUEST_TIMEOUT),
            )
        except httpx.TimeoutException as exc:
            logger.warning("event=supadata.transcript.error video_url=%s err=%s", url, exc)
            raise SupadataTranscriptError(status_code=503, video_url=url, error_body=str(exc)) from exc
        except httpx.HTTPError as exc:
            logger.warning("event=supadata.transcript.error video_url=%s err=%s", url, exc)
            raise SupadataTranscriptError(status_code=502, video_url=url, error_body=str(exc)) from exc

        if response.status_code == httpx.codes.ACCEPTED:
            payload = _safe_json(response)
            job_id = None
            if isinstance(payload, dict):
                job_id = payload.get("jobId") or payload.get("job_id") or payload.get("id")
            if not job_id:
                logger.warning(
                    "event=supadata.transcript.error video_url=%s status_code=%s err=%s",
                    url,
                    response.status_code,
                    payload,
                )
                raise SupadataTranscriptError(
                    status_code=response.status_code,
                    video_url=url,
                    error_body=payload,
                )
            logger.info(
                "event=supadata.transcript.job-start video_url=%s job_id=%s lang=%s mode=%s",
                url,
                job_id,
                lang,
                mode,
            )
            payload = self._poll_transcript_job(job_id=job_id, url=url, poll_interval=poll_interval, poll_timeout=poll_timeout)
            return self._build_transcript_result(url=url, payload=payload)

        if response.status_code // 100 != 2:
            logger.warning(
                "event=supadata.transcript.error video_url=%s status_code=%s",
                url,
                response.status_code,
            )
            raise SupadataTranscriptError(
                status_code=response.status_code,
                video_url=url,
                error_body=_safe_json(response) or response.text,
            )

        payload = _safe_json(response) or {}
        return self._build_transcript_result(url=url, payload=payload)

    def get_transcript_raw(self, url: str, *, lang: str | None = None, min_chars: int = 0) -> Optional[str]:
        """Fetch transcript text without timestamps when available."""

        try:
            result = self.get_transcript(url=url, lang=lang, mode="auto", text=True)
        except SupadataTranscriptError:
            return None
        content = (result.text or "").strip()
        if min_chars and len(content) < min_chars:
            logger.info(
                "event=supadata.transcript.too_short video_url=%s content_chars=%s threshold=%s",
                url,
                len(content),
                min_chars,
            )
            return None
        if not content:
            logger.info(
                "event=supadata.transcript.too_short video_url=%s content_chars=0 threshold=%s",
                url,
                min_chars,
            )
            return None
        return content

    # --- 3) ASR (AUDIO → TEXT) ---
    def asr_transcribe_raw(self, url: str) -> Optional[str]:
        """Run the ASR pipeline and return recognised text when transcript missing."""

        deadline = time.monotonic() + self._asr_budget
        flows = (
            ("/transcript", "/transcript/{job_id}", {"url": url, "mode": "generate", "text": True}),
            ("/youtube/asr", "/youtube/asr/{job_id}", {"url": url, "text": True}),
        )
        for start_path, poll_path, payload in flows:
            timeout_value = _remaining_timeout(deadline, _ASR_REQUEST_TIMEOUT)
            if timeout_value is None:
                break
            try:
                response = self._client.post(
                    start_path,
                    json=payload,
                    timeout=_make_timeout(timeout_value),
                )
            except httpx.HTTPError as exc:
                logger.warning("supadata-asr error url=%s err=%s", url, exc)
                continue
            if response.status_code == httpx.codes.NOT_FOUND:
                continue
            if response.status_code // 100 != 2:
                logger.warning(
                    "supadata-asr status=%s url=%s",
                    response.status_code,
                    url,
                )
                continue
            payload_data = _safe_json(response)
            text = _normalise_text(payload_data if payload_data is not None else response.text)
            if text:
                return text
            job_id = _extract_job_id(payload_data)
            if not job_id:
                continue
            status = _extract_status(payload_data)
            if status and status.lower() in {"failed", "error"}:
                continue
            text = self._poll_asr_job(poll_path, job_id, deadline)
            if text:
                return text
        return None

    def _poll_transcript_job(
        self,
        *,
        job_id: str,
        url: str,
        poll_interval: float,
        poll_timeout: float,
    ) -> dict[str, Any]:
        """Poll transcript job endpoint until completion or timeout."""

        deadline = time.monotonic() + max(1.0, poll_timeout)
        poll_interval = max(0.1, poll_interval)
        job_path = f"/transcript/{job_id}"
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                logger.warning(
                    "event=supadata.transcript.timeout video_url=%s job_id=%s timeout=%s",
                    url,
                    job_id,
                    poll_timeout,
                )
                raise SupadataTranscriptError(
                    status_code=504,
                    video_url=url,
                    error_body=f"transcript polling timed out after {poll_timeout}s",
                )

            try:
                response = self._client.get(job_path, timeout=_make_timeout(min(_TRANSCRIPT_REQUEST_TIMEOUT, remaining)))
            except httpx.TimeoutException as exc:
                logger.warning("event=supadata.transcript.error video_url=%s err=%s", url, exc)
                raise SupadataTranscriptError(status_code=503, video_url=url, error_body=str(exc)) from exc
            except httpx.HTTPError as exc:
                logger.warning("event=supadata.transcript.error video_url=%s err=%s", url, exc)
                raise SupadataTranscriptError(status_code=502, video_url=url, error_body=str(exc)) from exc

            payload = _safe_json(response)
            status = _extract_status(payload)
            if status:
                lowered = status.lower()
                if lowered in {"queued", "active", "processing"}:
                    elapsed = poll_timeout - remaining
                    logger.info(
                        "event=supadata.transcript.job-status video_url=%s job_id=%s status=%s elapsed=%.1f",
                        url,
                        job_id,
                        status,
                        elapsed,
                    )
                elif lowered == "completed":
                    return payload or {}
                elif lowered == "failed":
                    logger.warning(
                        "event=supadata.transcript.error video_url=%s status_code=%s err=%s",
                        url,
                        response.status_code,
                        payload,
                    )
                    raise SupadataTranscriptError(status_code=response.status_code, video_url=url, error_body=payload)

            # Content may arrive without explicit status
            if isinstance(payload, dict) and payload.get("content"):
                return payload

            sleep_for = min(poll_interval, max(0.0, remaining))
            time.sleep(sleep_for)

    def _build_transcript_result(self, *, url: str, payload: dict[str, Any] | None) -> TranscriptResult:
        content = ""
        lang_value: str | None = None
        available_langs: list[str] = []

        if isinstance(payload, dict):
            raw_content = payload.get("content")
            if raw_content is not None:
                content = _normalise_content(raw_content)
            lang_value = payload.get("lang") if isinstance(payload.get("lang"), str) else None
            raw_available_langs = payload.get("availableLangs")
            if isinstance(raw_available_langs, list):
                available_langs = [str(item) for item in raw_available_langs if str(item).strip()]

        if not content:
            content = _normalise_text(payload) or ""

        text = (content or "").strip()
        content_chars = len(text)
        if content_chars < MIN_TRANSCRIPT_CHARS:
            logger.info(
                "event=supadata.transcript.too_short video_url=%s content_chars=%s threshold=%s",
                url,
                content_chars,
                MIN_TRANSCRIPT_CHARS,
            )
            raise SupadataTranscriptTooShortError(video_url=url, content_chars=content_chars, threshold=MIN_TRANSCRIPT_CHARS)

        result = TranscriptResult(
            text=text,
            lang=lang_value,
            available_langs=available_langs,
            content_chars=content_chars,
        )
        logger.info(
            "event=supadata.transcript.success video_url=%s lang=%s available_langs_count=%s content_chars=%s",
            url,
            result.lang,
            len(result.available_langs),
            result.content_chars,
        )
        return result

    def _poll_asr_job(self, path_template: str, job_id: str, deadline: float) -> Optional[str]:
        """Poll SupaData job endpoint until finished or timeout."""

        for _ in range(self._asr_poll_attempts):
            timeout_value = _remaining_timeout(deadline, _ASR_REQUEST_TIMEOUT)
            if timeout_value is None:
                break
            try:
                response = self._client.get(
                    path_template.format(job_id=job_id),
                    timeout=_make_timeout(timeout_value),
                )
            except httpx.HTTPError as exc:
                logger.warning("supadata-asr error job=%s err=%s", job_id, exc)
                return None
            if response.status_code // 100 != 2:
                logger.warning(
                    "supadata-asr status=%s job=%s",
                    response.status_code,
                    job_id,
                )
                return None
            payload = _safe_json(response)
            text = _normalise_text(payload if payload is not None else response.text)
            if text:
                return text
            status = _extract_status(payload)
            if status and status.lower() in {"failed", "error"}:
                return None
            if self._asr_poll_interval:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                time.sleep(min(self._asr_poll_interval, max(0.0, remaining)))
        return None


def _extract_items(data: Any) -> Iterable[dict[str, Any]]:
    if not isinstance(data, dict):
        return []
    # прямые массивы
    for key in ("items", "videos", "results", "data"):
        val = data.get(key)
        if isinstance(val, list):
            return [x for x in val if isinstance(x, dict)]
    # вложенные контейнеры вида {"results": {"items":[...]}} или {"data":{"results":[...]}}
    for key in ("results", "data"):
        val = data.get(key)
        if isinstance(val, dict):
            for sub in ("items", "videos", "results"):
                seq = val.get(sub)
                if isinstance(seq, list):
                    return [x for x in seq if isinstance(x, dict)]
    return []



def _safe_json(response: httpx.Response) -> Any | None:
    try:
        return response.json()
    except ValueError:
        logger.warning("supadata-invalid-json path=%s", response.request.url.path)
        return None


def _remaining_timeout(deadline: float, default: float) -> float | None:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return None
    return min(default, remaining)


def _make_timeout(total: float) -> httpx.Timeout:
    total = max(0.1, total)
    connect = min(_CONNECT_TIMEOUT, total)
    return httpx.Timeout(timeout=total, connect=connect)



def _normalise_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "y"}:
            return True
        if lowered in {"false", "0", "no", "n"}:
            return False
    return None


def _normalise_text(data: Any) -> Optional[str]:
    parts: list[str] = []
    seen: set[str] = set()

    def _collect(value: Any) -> None:
        if isinstance(value, str):
            stripped = value.strip()
            if stripped and stripped not in seen:
                parts.append(stripped)
                seen.add(stripped)
            return
        if isinstance(value, dict):
            primary_keys = (
                "text",
                "content",
                "caption",
                "value",
                "transcript",
            )
            for key in primary_keys:
                if key in value:
                    _collect(value[key])
            for key in (
                "segments",
                "results",
                "items",
                "data",
                "payload",
                "captions",
                "chunks",
                "paragraphs",
            ):
                if key in value:
                    _collect(value[key])
            return
        if isinstance(value, (list, tuple)):
            for item in value:
                _collect(item)
            return

    _collect(data)
    if parts:
        return " ".join(parts)
    return None


def _normalise_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        pieces = []
        for item in content:
            if isinstance(item, dict) and "text" in item:
                pieces.append(str(item.get("text") or "").strip())
            elif isinstance(item, str):
                pieces.append(item.strip())
        return "\n".join([piece for piece in pieces if piece])
    return _normalise_text(content) or ""


def _extract_job_id(data: Any) -> Optional[str]:
    if not isinstance(data, dict):
        return None
    job_id = (
        data.get("job_id")
        or data.get("id")
        or data.get("job", {}).get("id")
    )
    if job_id:
        return str(job_id)
    return None


def _extract_status(data: Any) -> Optional[str]:
    if isinstance(data, dict):
        status = data.get("status")
        if isinstance(status, str):
            return status
        job = data.get("job")
        if isinstance(job, dict):
            status = job.get("status")
            if isinstance(status, str):
                return status
    return None


def _parse_duration_seconds(value: Any) -> Optional[int]:
    """Return the duration in seconds from various representations."""

    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if value < 0:
            return None
        return int(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        if stripped.isdigit():
            return int(stripped)
        match = _DURATION_RE.match(stripped)
        if match:
            hours = int(match.group("hours") or 0)
            minutes = int(match.group("minutes") or 0)
            seconds = int(match.group("seconds") or 0)
            return hours * 3600 + minutes * 60 + seconds
        if ":" in stripped:
            parts = stripped.split(":")
            if all(part.isdigit() for part in parts):
                parts_int = [int(part) for part in parts]
                if len(parts_int) == 3:
                    hours, minutes, seconds = parts_int
                elif len(parts_int) == 2:
                    hours = 0
                    minutes, seconds = parts_int
                elif len(parts_int) == 1:
                    hours = 0
                    minutes = 0
                    seconds = parts_int[0]
                else:
                    return None
                return hours * 3600 + minutes * 60 + seconds
    return None


_DURATION_RE = re.compile(
    r"^PT(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?$",
    re.IGNORECASE,
)
