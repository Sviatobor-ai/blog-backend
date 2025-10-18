"""Client for interacting with SupaData APIs."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Iterable, List, Optional

import httpx

logger = logging.getLogger(__name__)


_DURATION_RE = re.compile(
    r"^PT(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?$",
    re.IGNORECASE,
)


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
        base_url: str = "https://api.supadata.ai",
        client: httpx.Client | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._owns_client = client is None
        default_headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        self._client = client or httpx.Client(
            base_url=self.base_url,
            headers=default_headers,
            timeout=httpx.Timeout(30.0, connect=10.0),
        )
        if client is not None:
            # Ensure provided client has required headers.
            self._client.headers.update(default_headers)

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

        payload: dict[str, Any] = {
            "query": query,
            "limit": max(1, limit),
            "min_duration_seconds": max(0, min_duration_seconds),
            "max_duration_seconds": max(min_duration_seconds, max_duration_seconds),
        }
        if region:
            payload["region"] = region
        if language:
            payload["language"] = language
        try:
            response = self._client.post(
                "/youtube/search",
                json=payload,
                timeout=httpx.Timeout(30.0, connect=10.0),
            )
        except httpx.HTTPError as exc:  # pragma: no cover - network failures are logged
            logger.warning("supadata-search error url=%s err=%s", payload.get("query"), exc)
            return []
        if response.status_code != httpx.codes.OK:
            logger.warning(
                "supadata-search status=%s query=%s",
                response.status_code,
                query,
            )
            return []
        data = response.json()
        raw_items: Iterable[dict[str, Any]] = data.get("items") or data.get("videos") or []
        videos: List[SDVideo] = []
        for item in raw_items:
            duration_seconds = _parse_duration_seconds(
                item.get("duration_seconds")
                or item.get("duration")
                or item.get("contentDetails", {}).get("duration")
            )
            if duration_seconds is not None:
                if duration_seconds < min_duration_seconds:
                    continue
                if duration_seconds > max_duration_seconds:
                    continue
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
            has_transcript: Optional[bool]
            if isinstance(has_transcript_raw, bool):
                has_transcript = has_transcript_raw
            elif isinstance(has_transcript_raw, str):
                has_transcript = has_transcript_raw.lower() in {"true", "1", "yes"}
            else:
                has_transcript = None
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
            if len(videos) >= limit:
                break
        return videos

    # --- 2) PROBE/GET TRANSCRIPT ---
    def get_transcript_raw(self, url: str) -> Optional[str]:
        """Fetch transcript text without timestamps when available."""

        payload = {"url": url, "format": "text"}
        try:
            response = self._client.post(
                "/youtube/get-transcript",
                json=payload,
                timeout=httpx.Timeout(60.0, connect=10.0),
            )
        except httpx.HTTPError as exc:
            logger.warning("supadata-transcript error url=%s err=%s", url, exc)
            return None
        if response.status_code == httpx.codes.NOT_FOUND:
            return None
        if response.status_code != httpx.codes.OK:
            logger.warning(
                "supadata-transcript status=%s url=%s",
                response.status_code,
                url,
            )
            return None
        data = response.json()
        text = data.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()
        segments = data.get("segments") or data.get("results") or []
        parts: List[str] = []
        for segment in segments:
            segment_text = (
                segment.get("text")
                if isinstance(segment, dict)
                else None
            )
            if not segment_text and isinstance(segment, str):
                segment_text = segment
            if segment_text:
                parts.append(str(segment_text).strip())
        if parts:
            return " ".join(part for part in parts if part)
        return None

    # --- 3) ASR (AUDIO → TEXT) ---
    def asr_transcribe_raw(self, url: str) -> Optional[str]:
        """Run the ASR pipeline and return recognised text when transcript missing."""

        payload = {"url": url, "mode": "raw"}
        try:
            response = self._client.post(
                "/youtube/asr",
                json=payload,
                timeout=httpx.Timeout(240.0, connect=10.0),
            )
        except httpx.HTTPError as exc:
            logger.warning("supadata-asr error url=%s err=%s", url, exc)
            return None
        if response.status_code != httpx.codes.OK:
            logger.warning(
                "supadata-asr status=%s url=%s",
                response.status_code,
                url,
            )
            return None
        data = response.json()
        text = data.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()
        segments = data.get("segments") or []
        parts = [str(segment.get("text")).strip() for segment in segments if isinstance(segment, dict) and segment.get("text")]
        if parts:
            return " ".join(parts)
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
