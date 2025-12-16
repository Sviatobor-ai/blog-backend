"""Typing helpers for generation runner dependencies."""

from __future__ import annotations

from typing import Protocol

from sqlalchemy.orm import Session

from ..schemas import ArticlePublishResponse


class ArticleJobGenerator(Protocol):
    """Callable that turns a GenJob payload into a published article."""

    def __call__(self, db: Session, payload: dict) -> ArticlePublishResponse:  # pragma: no cover - protocol
        ...
