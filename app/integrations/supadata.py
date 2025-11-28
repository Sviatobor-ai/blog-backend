"""Client for interacting with SupaData APIs."""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Iterable, List, Optional

import httpx
from fastapi import HTTPException

logger = logging.getLogger(__name__)

_CONNECT_TIMEOUT = 10.0
_SEARCH_TIMEOUT = 10.0
_TRANSCRIPT_REQUEST_TIMEOUT = 10.0
_ASR_REQUEST_TIMEOUT = 15.0
# Single-operation budgets (seconds) to keep transcript/ASR calls bounded.
_TRANSCRIPT_TOTAL_BUDGET = 90.0
_ASR_TOTAL_BUDGET = 180.0


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
    def get_transcript_raw(self, url: str) -> Optional[str]:
        """Fetch transcript text without timestamps when available."""

        deadline = time.monotonic() + self._transcript_budget
        endpoints = (
            ("/transcript", {"url": url, "text": "true"}),
            ("/youtube/transcript", {"url": url, "text": "true"}),
        )
        for path, params in endpoints:
            timeout_value = _remaining_timeout(deadline, _TRANSCRIPT_REQUEST_TIMEOUT)
            if timeout_value is None:
                break
            try:
                response = self._client.get(
                    path,
                    params=params,
                    timeout=_make_timeout(timeout_value),
                )
            except httpx.HTTPError as exc:
                logger.warning("supadata-transcript error url=%s err=%s", url, exc)
                continue
            if response.status_code == httpx.codes.NOT_FOUND:
                continue
            if response.status_code // 100 != 2:
                logger.warning(
                    "supadata-transcript status=%s url=%s",
                    response.status_code,
                    url,
                )
                continue
            payload = _safe_json(response)
            text = _normalise_text(payload if payload is not None else response.text)
            if text:
                return text
        return None

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
