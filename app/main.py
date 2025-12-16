"""FastAPI application providing AI-generated article publishing."""

from __future__ import annotations

import logging
from functools import lru_cache
from math import ceil
from typing import Callable, Iterable
import os

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import String, cast, func, text
from sqlalchemy.orm import Session

from .article_schema import ARTICLE_DOCUMENT_SCHEMA
from .config import DATABASE_URL, get_openai_settings, get_supadata_key
from .db import SessionLocal, engine
from .dependencies import get_supadata_client, shutdown_supadata_client
from .integrations.supadata import SupaDataClient
from .models import Post, Rubric
from .routers.admin_api import admin_api_router
from .routers.admin_page import admin_page_router
from .schemas import (
    ArticleCreateRequest,
    ArticleDocument,
    ArticleListResponse,
    ArticlePublishResponse,
    ArticleSummary,
)
from .services import OpenAIAssistantArticleGenerator, get_transcript_generator
from .services.generated_article_service import GeneratedArticleService
from .services.article_publication import document_from_post


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="wyjazdy-blog backend",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)


@app.exception_handler(RequestValidationError)
async def admin_request_validation_exception_handler(request: Request, exc: RequestValidationError):
    for error in exc.errors():
        loc = error.get("loc") or ()
        if "features" in loc:
            detail = error.get("msg", "Invalid features")
            prefix = "Value error, "
            if detail.startswith(prefix):
                detail = detail[len(prefix) :]
            return JSONResponse(status_code=400, content={"detail": detail})
    extra_fields = sorted(
        {
            str(error["loc"][-1])
            for error in exc.errors()
            if error.get("type") == "extra_forbidden" and error.get("loc")
        }
    )
    if extra_fields:
        detail = f"Unsupported filters: {', '.join(extra_fields)}"
        return JSONResponse(status_code=400, content={"detail": detail})
    return await request_validation_exception_handler(request, exc)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(admin_page_router)
app.include_router(admin_api_router)


# Trigger SupaData configuration check at startup.
get_supadata_key()


@app.on_event("shutdown")
def _shutdown_supadata_client() -> None:
    shutdown_supadata_client()


def get_db() -> Iterable[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _supadata_client_provider() -> Callable[[], SupaDataClient]:
    return get_supadata_client

@app.get("/health/openai")
def health_openai():
    return {
        "OPENAI_API_KEY": bool(os.getenv("OPENAI_API_KEY")),
        "OPENAI_ASSISTANT_ID": bool(os.getenv("OPENAI_ASSISTANT_ID")),
        "OPENAI_API_KEY_len": len(os.getenv("OPENAI_API_KEY") or ""),
    }

@lru_cache
def get_generator() -> OpenAIAssistantArticleGenerator:
    settings = get_openai_settings()
    return OpenAIAssistantArticleGenerator(
        api_key=settings.api_key,
        assistant_id=settings.assistant_id,
        request_timeout_s=settings.request_timeout_s,
    )



SUMMARY_TITLE_MAX_CHARS = 60
SUMMARY_TITLE_ELLIPSIS = "…"


def _normalize_text(value: str) -> str:
    return " ".join((value or "").split())


def _truncate_summary_title(value: str) -> str:
    text = _normalize_text(value)
    if not text:
        return ""
    if len(text) <= SUMMARY_TITLE_MAX_CHARS:
        return text
    allowed = max(1, SUMMARY_TITLE_MAX_CHARS - len(SUMMARY_TITLE_ELLIPSIS))
    truncated = text[:allowed].rstrip()
    if " " in truncated:
        truncated = truncated.rsplit(" ", 1)[0]
    truncated = truncated.rstrip(" ,.;:-")
    if not truncated:
        truncated = text[:allowed].rstrip(" ,.;:-")
    return f"{truncated}{SUMMARY_TITLE_ELLIPSIS}"


def _build_summary_title(post: Post) -> str:
    candidates = [post.headline, post.title]
    for candidate in candidates:
        truncated = _truncate_summary_title(candidate or "")
        if truncated:
            return truncated
    fallback = post.slug.replace("-", " ")
    return _truncate_summary_title(fallback)


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


# NOTE: Keep query parameters aligned with frontend expectations.
@app.get(
    "/artykuly",
    response_model=ArticleListResponse,
    include_in_schema=True,
    tags=["Artykuly"],
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
            | func.lower(func.coalesce(cast(Post.tags, String), "")).like(like)
        )
    total_items = (
        query.order_by(None)
        .with_entities(func.count(Post.id))
        .scalar()
    )
    total_items = int(total_items or 0)
    total_pages = 0
    if total_items > 0:
        total_pages = max(1, ceil(total_items / per_page))
    posts = (
        query.order_by(Post.updated_at.desc(), Post.created_at.desc())
        .offset(offset)
        .limit(per_page)
        .all()
    )
    items = [
        ArticleSummary(
            slug=post.slug,
            title=_build_summary_title(post),
            headline=post.headline,
            lead=post.lead,
            section=post.section,
            tags=post.tags or [],
            created_at=post.created_at,
            updated_at=post.updated_at,
        )
        for post in posts
    ]
    return ArticleListResponse(
        meta={
            "page": page,
            "per_page": per_page,
            "total_items": total_items,
            "total_pages": total_pages,
        },
        items=items,
    )


@app.get(
    "/artykuly/{slug}",
    response_model=ArticleDocument,
    include_in_schema=True,
    tags=["Artykuly"],
)
def get_article(slug: str, db: Session = Depends(get_db)):
    post = db.query(Post).filter(Post.slug == slug).one_or_none()
    if not post:
        raise HTTPException(status_code=404, detail="post not found")
    document = document_from_post(post)
    return document


@app.post("/artykuly", response_model=ArticlePublishResponse, status_code=201)
def create_article(
    payload: ArticleCreateRequest,
    db: Session = Depends(get_db),
    generator: OpenAIAssistantArticleGenerator = Depends(get_generator),
    transcript_generator=Depends(get_transcript_generator),
    supadata_provider: Callable[[], SupaDataClient] = Depends(_supadata_client_provider),
):
    service = GeneratedArticleService()
    return service.generate_and_publish(
        payload=payload,
        db=db,
        generator=generator,
        transcript_generator=transcript_generator,
        supadata_provider=supadata_provider,
    )


@app.get("/rubrics")
def list_rubrics(db: Session = Depends(get_db)):
    rubrics = db.query(Rubric).filter(Rubric.is_active.is_(True)).order_by(Rubric.name_pl).all()
    return [
        {"code": rubric.code, "name_pl": rubric.name_pl, "is_active": rubric.is_active}
        for rubric in rubrics
    ]


@app.get("/artykuly", include_in_schema=False)
def list_posts_legacy(
    page: int = Query(1, ge=1),
    per_page: int = Query(10, ge=1, le=50),
    section: str | None = Query(None),
    q: str | None = Query(None),
    db: Session = Depends(get_db),
):
    response = list_articles(page=page, per_page=per_page, section=section, q=q, db=db)
    return response.model_dump()


@app.get("/artykuly/{slug}", include_in_schema=False)
def get_post_legacy(slug: str, db: Session = Depends(get_db)):
    detail = get_article(slug, db)
    return detail.model_dump()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
