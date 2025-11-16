"""Helpers for selecting articles that qualify for enhancement."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from ..models import Post


MIN_AGE_DAYS = 17


def select_articles_for_enhancement(db: Session, *, now: datetime) -> list[Post]:
    """Return posts that are older than :data:`MIN_AGE_DAYS` and have payloads."""

    threshold = now - timedelta(days=MIN_AGE_DAYS)
    query = (
        db.query(Post)
        .filter(Post.created_at <= threshold)
        .filter(Post.payload.isnot(None))
        .order_by(Post.created_at.asc())
    )
    return list(query.all())


__all__ = ["select_articles_for_enhancement", "MIN_AGE_DAYS"]
