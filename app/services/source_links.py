"""Utilities for normalising and presenting external source links."""

from __future__ import annotations

import re
from typing import Iterable, List, Sequence
from urllib.parse import urlparse, urlunparse


_MARKDOWN_LINK_PATTERN = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")
_BARE_URL_PATTERN = re.compile(r"(https?://[^\s<>\]]+)")
_COMBINED_PATTERN = re.compile(
    r"\[([^\]]+)\]\((https?://[^\s)]+)\)|(https?://[^\s<>\]]+)",
    re.IGNORECASE,
)

_HOST_LABEL_OVERRIDES = {
    "health.harvard.edu": "Harvard Health Publishing",
}


def normalize_url(url: str) -> str:
    """Return a normalised URL used for deduplication."""

    if not url:
        return ""

    trimmed = url.strip()
    if not trimmed:
        return ""

    parsed = urlparse(trimmed)
    if not parsed.scheme or not parsed.netloc:
        return trimmed

    hostname = (parsed.hostname or "").lower()
    path = parsed.path or "/"
    normalized_path = path if path == "/" else path.rstrip("/")

    normalized = parsed._replace(netloc=hostname, fragment="", path=normalized_path or "/")
    return urlunparse(normalized)


def extract_urls(text: str) -> List[str]:
    """Find URLs from markdown links and bare HTTP(S) occurrences."""

    if not text:
        return []

    urls: List[str] = []
    for match in _COMBINED_PATTERN.finditer(text):
        url = match.group(2) or match.group(3)
        if url:
            urls.append(url)
    return urls


def build_source_label(url: str) -> str:
    """Compose a human readable label for a source URL."""

    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    host = host[4:] if host.startswith("www.") else host

    base_label = _HOST_LABEL_OVERRIDES.get(host)
    if not base_label:
        host_parts = [part for part in host.split(".") if part]
        base_candidate = host_parts[-2] if len(host_parts) >= 2 else host_parts[0] if host_parts else url
        base_label = base_candidate.replace("-", " ").title()

    path = parsed.path or ""
    segments = [segment for segment in path.split("/") if segment]
    hint_segment = segments[-1] if segments else ""
    hint_segment = re.sub(r"\.[a-zA-Z0-9]+$", "", hint_segment)
    hint_parts = [part for part in re.split(r"[-_]+", hint_segment) if part]
    hint = " ".join(word.capitalize() for word in hint_parts[:8])

    if hint:
        return f"{base_label} — {hint}"
    return base_label


def dedupe_preserve_order(urls: Sequence[str]) -> List[str]:
    """Remove duplicates while keeping the original order."""

    seen = set()
    unique: List[str] = []
    for url in urls:
        normalized = normalize_url(url)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique.append(normalized)
    return unique


def enforce_single_hyperlink_per_url(text: str, seen: Iterable[str] | None = None) -> tuple[str, set[str]]:
    """Ensure each URL appears as a hyperlink only once within the provided text."""

    seen_normalized = set(seen or [])
    rewritten_parts: List[str] = []
    last_index = 0

    for match in _COMBINED_PATTERN.finditer(text):
        start, end = match.span()
        rewritten_parts.append(text[last_index:start])

        label = match.group(1)
        url = match.group(2) or match.group(3)
        normalized = normalize_url(url) if url else ""

        if normalized and normalized in seen_normalized:
            if label:
                replacement = label
            else:
                replacement = _strip_scheme(url)
        elif normalized:
            seen_normalized.add(normalized)
            replacement = match.group(0)
        else:
            replacement = match.group(0)

        rewritten_parts.append(replacement)
        last_index = end

    rewritten_parts.append(text[last_index:])
    return "".join(rewritten_parts), seen_normalized


def _strip_scheme(url: str) -> str:
    return re.sub(r"^https?://", "", url, flags=re.IGNORECASE)


__all__ = [
    "build_source_label",
    "dedupe_preserve_order",
    "enforce_single_hyperlink_per_url",
    "extract_urls",
    "normalize_url",
]
