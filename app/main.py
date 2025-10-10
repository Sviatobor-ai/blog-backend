"""FastAPI application providing AI-generated article publishing."""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from typing import Iterable, List

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from .article_schema import ARTICLE_DOCUMENT_SCHEMA
from .config import DATABASE_URL, get_openai_settings
from .db import SessionLocal, engine
from .models import Post, Rubric
from .schemas import (
    ArticleCreateRequest,
    ArticleDetailResponse,
    ArticleDocument,
    ArticleListResponse,
    ArticlePublishResponse,
    ArticleSummary,
)
from .services import ArticleGenerationError, OpenAIAssistantArticleGenerator, ensure_unique_slug, slugify_pl


logging.basicConfig(level=logging.CRITICAL)

app = FastAPI(
    title="wyjazdy-blog backend",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_db() -> Iterable[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@lru_cache
def get_generator() -> OpenAIAssistantArticleGenerator:
    settings = get_openai_settings()
    return OpenAIAssistantArticleGenerator(
        api_key=settings.get("api_key"),
        assistant_id=settings.get("assistant_id"),
    )


def compose_body_mdx(sections: List[dict]) -> str:
    parts: List[str] = []
    for section in sections:
        title = section.get("title", "").strip()
        body = section.get("body", "").strip()
        if not title or not body:
            continue
        parts.append(f"## {title}\n\n{body}")
    return "\n\n".join(parts)


SECTION_PATTERN = re.compile(r"^## +(.+)$", re.MULTILINE)


def extract_sections_from_body(body: str) -> List[dict]:
    if not body:
        return []
    sections: List[dict] = []
    matches = list(SECTION_PATTERN.finditer(body))
    if not matches:
        return []
    for index, match in enumerate(matches):
        title = match.group(1).strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        content = body[start:end].strip()
        sections.append({"title": title, "body": content})
    return sections


def document_from_post(post: Post) -> ArticleDocument:
    if post.payload:
        try:
            return ArticleDocument.model_validate(post.payload)
        except (ValueError, ValidationError) as exc:
            logging.warning(
                "Stored payload for slug %s is invalid, falling back to columns: %s",
                post.slug,
                exc,
            )
    sections = extract_sections_from_body(post.body_mdx or "")
    return ArticleDocument(
        topic=post.title,
        slug=post.slug,
        locale=post.locale or "pl-PL",
        taxonomy={
            "section": post.section or "",
            "categories": post.categories or [],
            "tags": post.tags or [],
        },
        seo={
            "title": post.title,
            "description": post.description or "",
            "slug": post.slug,
            "canonical": post.canonical or f"https://joga.yoga/artykuly/{post.slug}",
            "robots": post.robots or "index,follow",
        },
        article={
            "headline": post.headline or post.title,
            "lead": post.lead or "",
            "sections": sections,
            "citations": post.citations or [],
        },
        aeo={
            "geo_focus": post.geo_focus or ["Polska"],
            "faq": post.faq or [],
        },
    )


@app.get("/health")
def health() -> dict:
    try:
        with engine.connect() as conn:
            conn.execute(text("select 1"))
        db_status = "ok"
    except Exception:
        db_status = "error"
    return {
        "status": "ok",
        "db": db_status,
        "driver": "sqlalchemy+psycopg",
        "database_url_present": bool(DATABASE_URL),
    }


@app.get("/schemas/article")
def get_article_schema() -> dict:
    """Return the JSON schema used by the OpenAI assistant."""

    return ARTICLE_DOCUMENT_SCHEMA


@app.get(
    "/articles",
    response_model=ArticleListResponse,
    include_in_schema=True,
    tags=["Articles"],
)
def list_articles(
    page: int = Query(1, ge=1),
    per_page: int = Query(10, ge=1, le=50),
    section: str | None = Query(None),
    q: str | None = Query(None),
    db: Session = Depends(get_db),
):
    offset = (page - 1) * per_page
    query = db.query(Post)
    if section:
        query = query.filter(Post.section == section)
    if q:
        like = f"%{q.lower()}%"
        query = query.filter(
            func.lower(Post.title).like(like)
            | func.lower(Post.lead).like(like)
            | func.lower(Post.headline).like(like)
        )
    total = query.count()
    posts = (
        query.order_by(Post.created_at.desc())
        .offset(offset)
        .limit(per_page)
        .all()
    )
    items = [
        ArticleSummary(
            slug=post.slug,
            title=post.title,
            section=post.section,
            tags=post.tags or [],
            created_at=post.created_at,
            updated_at=post.updated_at,
        )
        for post in posts
    ]
    return ArticleListResponse(page=page, per_page=per_page, total=total, items=items)


@app.get(
    "/articles/{slug}",
    response_model=ArticleDetailResponse,
    include_in_schema=True,
    tags=["Articles"],
)
def get_article(slug: str, db: Session = Depends(get_db)):
    post = db.query(Post).filter(Post.slug == slug).one_or_none()
    if not post:
        raise HTTPException(status_code=404, detail="post not found")
    document = document_from_post(post)
    return ArticleDetailResponse(post=document)


@app.post("/articles", response_model=ArticlePublishResponse, status_code=201)
def create_article(
    payload: ArticleCreateRequest,
    db: Session = Depends(get_db),
    generator: OpenAIAssistantArticleGenerator = Depends(get_generator),
):
    if not generator.is_configured:
        raise HTTPException(status_code=503, detail="OpenAI API key is not configured")
    rubric_name = "Zdrowie i joga"
    if payload.rubric_code:
        rubric = db.query(Rubric).filter(Rubric.code == payload.rubric_code).one_or_none()
        if rubric:
            rubric_name = rubric.name_pl
    try:
        raw_document = generator.generate_article(
            topic=payload.topic,
            rubric=rubric_name,
            keywords=payload.keywords,
            guidance=payload.guidance,
        )
    except ArticleGenerationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    try:
        document = ArticleDocument.model_validate(raw_document)
    except (ValueError, ValidationError) as exc:
        raise HTTPException(status_code=502, detail=f"Invalid article payload: {exc}") from exc

    desired_slug_source = document.slug or document.seo.slug or document.seo.title or payload.topic
    desired_slug = slugify_pl(desired_slug_source)
    if not desired_slug:
        desired_slug = slugify_pl(payload.topic)
    existing_slugs = [slug for (slug,) in db.query(Post.slug).all()]
    final_slug = ensure_unique_slug(existing_slugs, desired_slug)
    canonical = f"https://joga.yoga/artykuly/{final_slug}"
    document = document.model_copy(
        update={
            "slug": final_slug,
            "taxonomy": document.taxonomy.model_copy(
                update={"section": rubric_name}
            ),
            "seo": document.seo.model_copy(update={"slug": final_slug, "canonical": canonical}),
        }
    )

    body_mdx = compose_body_mdx([section.model_dump() for section in document.article.sections])
    if not body_mdx:
        raise HTTPException(status_code=502, detail="Assistant returned empty article sections")
    post = Post(
        slug=document.slug,
        locale=document.locale,
        section=document.taxonomy.section,
        categories=document.taxonomy.categories,
        tags=document.taxonomy.tags,
        title=document.seo.title,
        description=document.seo.description,
        canonical=document.seo.canonical,
        robots=document.seo.robots,
        headline=document.article.headline,
        lead=document.article.lead,
        body_mdx=body_mdx,
        geo_focus=document.aeo.geo_focus,
        faq=[faq.model_dump() for faq in document.aeo.faq],
        citations=document.article.citations,
        payload=document.model_dump(),
    )
    db.add(post)
    db.commit()
    db.refresh(post)

    return ArticlePublishResponse(slug=post.slug, id=post.id, post=document)


@app.get("/rubrics")
def list_rubrics(db: Session = Depends(get_db)):
    rubrics = db.query(Rubric).filter(Rubric.is_active.is_(True)).order_by(Rubric.name_pl).all()
    return [
        {"code": rubric.code, "name_pl": rubric.name_pl, "is_active": rubric.is_active}
        for rubric in rubrics
    ]


@app.get("/posts", include_in_schema=False)
def list_posts_legacy(
    page: int = Query(1, ge=1),
    per_page: int = Query(10, ge=1, le=50),
    section: str | None = Query(None),
    q: str | None = Query(None),
    db: Session = Depends(get_db),
):
    response = list_articles(page=page, per_page=per_page, section=section, q=q, db=db)
    return response.model_dump()


@app.get("/posts/{slug}", include_in_schema=False)
def get_post_legacy(slug: str, db: Session = Depends(get_db)):
    detail = get_article(slug, db)
    return detail.post.model_dump()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
