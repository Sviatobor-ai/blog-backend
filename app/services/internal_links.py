from __future__ import annotations

from typing import Iterable, List

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import Post


def _normalize_preview(text: str, max_length: int = 200) -> str:
    normalized = " ".join((text or "").split())
    if len(normalized) > max_length:
        return f"{normalized[:max_length].rstrip()}…"
    return normalized


def _build_recommendation_item(post: Post) -> dict:
    preview_source = post.lead or post.description or post.title or post.headline or ""
    return {
        "slug": post.slug,
        "title": post.title or post.headline or post.slug,
        "section": post.section or "",
        "url": f"/artykuly/{post.slug}",
        "preview": _normalize_preview(preview_source, max_length=210),
    }


def _select_unique_posts(posts: Iterable[Post], *, seen: set[str], limit: int) -> List[dict]:
    selected: List[dict] = []
    for post in posts:
        if len(selected) >= limit:
            break
        if not post or not getattr(post, "slug", None):
            continue
        if post.slug in seen:
            continue
        seen.add(post.slug)
        selected.append(_build_recommendation_item(post))
    return selected


def build_internal_recommendations(
    db: Session,
    *,
    current_slug: str,
    current_section: str,
    max_same_section: int = 3,
    min_same_section: int = 2,
    total_limit: int = 4,
) -> List[dict]:
    """Return a mix of same-section and cross-section recommendations."""

    seen: set[str] = {current_slug}
    same_section_posts = (
        db.query(Post)
        .filter(Post.slug != current_slug, Post.section == current_section)
        .order_by(Post.updated_at.desc())
        .limit(8)
        .all()
    )
    other_section_posts = (
        db.query(Post)
        .filter(Post.slug != current_slug, Post.section != current_section)
        .order_by(func.random())
        .limit(4)
        .all()
    )

    recommendations = _select_unique_posts(same_section_posts, seen=seen, limit=max_same_section)
    if len(recommendations) < min_same_section:
        extra_needed = min_same_section - len(recommendations)
        recommendations.extend(
            _select_unique_posts(other_section_posts, seen=seen, limit=extra_needed)
        )

    cross_needed = total_limit - len(recommendations)
    if cross_needed > 0:
        recommendations.extend(
            _select_unique_posts(other_section_posts, seen=seen, limit=max(1, cross_needed))
        )

    return recommendations[:total_limit]


def format_recommendations_section(recommendations: List[dict]) -> str:
    """Compose markdown with internal recommendations."""

    if not recommendations:
        content = (
            "Przeczytaj również:\n\n"
            "- Więcej artykułów znajdziesz w naszej bibliotece joga.yoga, pełnej praktycznych inspiracji."
        )
        while len(content) < 420:
            content = f"{content}\n\nPozostań z nami — te rekomendacje rozwijają wątki z artykułu."
        return content

    lines = ["Przeczytaj również:", ""]
    for item in recommendations:
        lines.append(f"- [{item['title']}]({item['url']})")
        if item.get("preview"):
            lines.append(f"  {item['preview']}")
    content = "\n".join(lines).strip()
    while len(content) < 420:
        content = (
            f"{content}\n\nPozostań z nami — te rekomendacje rozwijają wątki z artykułu i prowadzą do kolejnych historii."
        )
    return content
