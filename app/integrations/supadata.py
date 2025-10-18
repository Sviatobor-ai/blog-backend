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

_SEARCH_TIMEOUT = httpx.Timeout(60.0, connect=10.0)
_TRANSCRIPT_TIMEOUT = httpx.Timeout(60.0, connect=10.0)
_ASR_TIMEOUT = httpx.Timeout(300.0, connect=10.0)


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
    has_transcript: Optional[bool]


class SupaDataClient:
    """Synchronous HTTP client talking to SupaData endpoints."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://api.supadata.ai/v1",
        client: httpx.Client | None = None,
        asr_poll_interval: float = 5.0,
        asr_poll_attempts: int = 3,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._owns_client = client is None
        headers = {"x-api-key": self.api_key}
        if client is None:
            self._client = httpx.Client(
                base_url=self.base_url,
                headers=headers,
                timeout=_SEARCH_TIMEOUT,
            )
        else:
            self._client = client
            self._client.headers.update(headers)
        self._asr_poll_interval = max(0.0, asr_poll_interval)
        self._asr_poll_attempts = max(0, asr_poll_attempts)

    def close(self) -> None:
        """Close the underlying HTTP client if owned by this instance."""

        if self._owns_client:
            self._client.close()

    # --- 1) SEARCH ---
    def search_youtube(
        self,
        query: str,
        limit: int,
        min_duration_seconds: int,
        max_duration_seconds: int,
        region: Optional[str] = None,
        language: Optional[str] = None,
    ) -> List[SDVideo]:
        """Call SupaData search endpoint and normalise the payload."""

        params: dict[str, Any] = {"query": query}
        if limit:
            params["limit"] = int(max(1, limit))

        try:
            response = self._client.get(
                "/youtube/search",
                params=params,
                timeout=_SEARCH_TIMEOUT,
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
            has_transcript_raw = item.get("has_transcript")
            has_transcript = _normalise_bool(has_transcript_raw)
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
                    has_transcript=has_transcript,
                )
            )
        filtered: List[SDVideo] = []
        for video in videos:
            duration_seconds = video.duration_seconds
            if duration_seconds is not None:
                if duration_seconds < min_duration_seconds:
                    continue
                if duration_seconds > max_duration_seconds:
                    continue
            filtered.append(video)
            if limit and len(filtered) >= limit:
                break
        return filtered

    # --- 2) PROBE/GET TRANSCRIPT ---
    def get_transcript_raw(self, url: str) -> Optional[str]:
        """Fetch transcript text without timestamps when available."""

        endpoints = (
            ("/youtube/transcript", {"url": url, "text": "true"}),
            ("/transcript", {"url": url, "text": "true"}),
        )
        for path, params in endpoints:
            try:
                response = self._client.get(
                    path,
                    params=params,
                    timeout=_TRANSCRIPT_TIMEOUT,
                )
            except httpx.HTTPError as exc:
                logger.warning("supadata-transcript error url=%s err=%s", url, exc)
                return None
            if response.status_code == httpx.codes.NOT_FOUND:
                continue
            if response.status_code // 100 != 2:
                logger.warning(
                    "supadata-transcript status=%s url=%s",
                    response.status_code,
                    url,
                )
                return None
            text = _normalise_text(response.json())
            if text:
                return text
            return None
        return None

    # --- 3) ASR (AUDIO → TEXT) ---
    def asr_transcribe_raw(self, url: str) -> Optional[str]:
        """Run the ASR pipeline and return recognised text when transcript missing."""

        payload = {"url": url, "text": "true"}
        try:
            response = self._client.post(
                "/youtube/asr",
                json=payload,
                timeout=_ASR_TIMEOUT,
            )
        except httpx.HTTPError as exc:
            logger.warning("supadata-asr error url=%s err=%s", url, exc)
            return None
        if response.status_code == httpx.codes.NOT_FOUND:
            return None
        if response.status_code // 100 != 2:
            logger.warning(
                "supadata-asr status=%s url=%s",
                response.status_code,
                url,
            )
            return None
        data = response.json()
        text = _normalise_text(data)
        if text:
            return text
        job_id = _extract_job_id(data)
        if not job_id:
            return None
        status = _extract_status(data)
        if status and status.lower() in {"failed", "error"}:
            return None
        for _ in range(self._asr_poll_attempts):
            if self._asr_poll_interval:
                time.sleep(self._asr_poll_interval)
            try:
                poll_response = self._client.get(
                    f"/youtube/asr/{job_id}",
                    timeout=_ASR_TIMEOUT,
                )
            except httpx.HTTPError as exc:
                logger.warning("supadata-asr error url=%s err=%s", url, exc)
                return None
            if poll_response.status_code // 100 != 2:
                logger.warning(
                    "supadata-asr status=%s url=%s",
                    poll_response.status_code,
                    url,
                )
                return None
            poll_data = poll_response.json()
            text = _normalise_text(poll_data)
            if text:
                return text
            status = _extract_status(poll_data)
            if status and status.lower() in {"failed", "error"}:
                return None
        return None


def _extract_items(data: Any) -> Iterable[dict[str, Any]]:
    if isinstance(data, dict):
        items = data.get("items") or data.get("videos")
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    return []


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
    if isinstance(data, dict):
        text = data.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()
        segments = data.get("segments") or data.get("results") or []
        parts = []
        for segment in segments if isinstance(segments, list) else []:
            if isinstance(segment, dict):
                segment_text = segment.get("text")
            else:
                segment_text = segment
            if isinstance(segment_text, str) and segment_text.strip():
                parts.append(segment_text.strip())
        if parts:
            return " ".join(parts)
    elif isinstance(data, list):
        parts = [str(part).strip() for part in data if str(part).strip()]
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
