"""Shared helpers for formatting article body content."""

from __future__ import annotations

import re
from typing import List


def compose_body_mdx(sections: List[dict]) -> str:
    """Turn article sections into an MDX body string."""

    parts: List[str] = []
    for section in sections:
        title = str(section.get("title", "")).strip()
        body = str(section.get("body", "")).strip()
        if not title or not body:
            continue
        parts.append(f"## {title}\n\n{body}")
    return "\n\n".join(parts)


_SECTION_PATTERN = re.compile(r"^## +(.+)$", re.MULTILINE)


def extract_sections_from_body(body: str) -> List[dict]:
    """Split an MDX body back into section dictionaries."""

    if not body:
        return []
    sections: List[dict] = []
    matches = list(_SECTION_PATTERN.finditer(body))
    if not matches:
        return []
    for index, match in enumerate(matches):
        title = match.group(1).strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        content = body[start:end].strip()
        if not title or not content:
            continue
        sections.append({"title": title, "body": content})
    return sections
