"""FastAPI application providing AI-generated article publishing."""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from math import ceil
from typing import Iterable, List
import os

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError
from sqlalchemy import String, cast, func, text
from sqlalchemy.orm import Session

from .article_schema import ARTICLE_DOCUMENT_SCHEMA
from .config import DATABASE_URL, get_openai_settings, get_supadata_key
from .db import SessionLocal, engine
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
from .services import ArticleGenerationError, OpenAIAssistantArticleGenerator, ensure_unique_slug, slugify_pl
from .dependencies import shutdown_supadata_client


logging.basicConfig(level=logging.INFO)

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


FALLBACK_FILLER = (
    "Artykuł został przygotowany dla czytelników joga.yoga, aby wspierać świadomą regenerację i"
    " budować dobre nawyki wellness podczas wyjazdów i praktyki w domu."
)
DEFAULT_CATEGORY = "Zdrowie i joga"
DEFAULT_TAGS = ["joga", "wellness", "regeneracja"]
DEFAULT_FAQ = [
    {
        "question": "Jak mogę wykorzystać wskazówki z artykułu na wyjeździe?",
        "answer": "Wybierz jeden rytuał regeneracyjny i zaplanuj go na każdy dzień pobytu, aby ciało i umysł miały"
        " stały punkt odnowy niezależnie od intensywności programu.",
    },
    {
        "question": "Czy te wskazówki nadają się dla początkujących?",
        "answer": "Tak, każda praktyka ma łagodny wariant dla osób stawiających pierwsze kroki, a bardziej"
        " doświadczeni uczestnicy mogą rozszerzyć ćwiczenia o dłuższe relaksacje.",
    },
    {
        "question": "Jakie akcesoria warto spakować?",
        "answer": "Przygotuj matę, koc, niewielką poduszkę oraz ulubioną wodę ziołową, aby łatwo utrzymać"
        " komfort w trakcie ćwiczeń i odpoczynku.",
    },
]


def _normalize_text(value: str) -> str:
    return " ".join((value or "").split())


def _ensure_text_length(value: str, *, minimum: int, maximum: int | None = None) -> str:
    filler = _normalize_text(FALLBACK_FILLER)
    text = _normalize_text(value) or filler
    while len(text) < minimum:
        text = f"{text} {filler}".strip()
    if maximum is not None and len(text) > maximum:
        text = text[:maximum]
    return text.strip()


def _ensure_sections(sections: List[dict]) -> List[dict]:
    sanitized: List[dict] = []
    for index, section in enumerate(sections, start=1):
        title = _normalize_text(str(section.get("title", ""))) or f"Sekcja {index}"
        body = _ensure_text_length(section.get("body", ""), minimum=400)
        sanitized.append({"title": title, "body": body})
    while len(sanitized) < 4:
        sanitized.append(
            {
                "title": f"Sekcja {len(sanitized) + 1}",
                "body": _ensure_text_length("", minimum=400),
            }
        )
    return sanitized


def _ensure_citations(citations: List[str] | None, canonical: str) -> List[str]:
    items = [item for item in (citations or []) if isinstance(item, str) and item.startswith("http")]
    base = canonical if canonical.startswith("http") else "https://joga.yoga"
    while len(items) < 2:
        suffix = "" if not items else f"?ref={len(items) + 1}"
        items.append(f"{base}{suffix}")
    return items


def _ensure_categories(categories: List[str] | None, section: str) -> List[str]:
    items = [item for item in (categories or []) if _normalize_text(item)]
    if not items:
        default = _normalize_text(section) or DEFAULT_CATEGORY
        items = [default]
    return items


def _ensure_tags(tags: List[str] | None) -> List[str]:
    items = [item for item in (tags or []) if _normalize_text(item)]
    for tag in DEFAULT_TAGS:
        if len(items) >= 3:
            break
        if tag not in items:
            items.append(tag)
    if len(items) < 3:
        items.extend(DEFAULT_TAGS[: 3 - len(items)])
    return items[:10]


def _ensure_faq(faq_items: List[dict] | None) -> List[dict]:
    sanitized: List[dict] = []
    for item in faq_items or []:
        question = _normalize_text(str(item.get("question", "")))
        answer = _ensure_text_length(item.get("answer", ""), minimum=40)
        if question and answer:
            sanitized.append({"question": question, "answer": answer})
    defaults_iter = iter(DEFAULT_FAQ)
    while len(sanitized) < 2:
        try:
            sanitized.append(dict(next(defaults_iter)))
        except StopIteration:
            sanitized.append(dict(DEFAULT_FAQ[-1]))
    return [dict(item) for item in sanitized[:3]]


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
    canonical = post.canonical or f"https://joga.yoga/artykuly/{post.slug}"
    if not isinstance(canonical, str) or not canonical.startswith("http"):
        canonical = f"https://joga.yoga/artykuly/{post.slug}"
    taxonomy_section = _normalize_text(post.section) or DEFAULT_CATEGORY
    categories = _ensure_categories(post.categories, taxonomy_section)
    tags = _ensure_tags(post.tags)
    lead = _ensure_text_length(post.lead, minimum=250)
    description = _ensure_text_length(post.description or lead, minimum=140, maximum=160)
    sections = _ensure_sections(extract_sections_from_body(post.body_mdx or ""))
    citations = _ensure_citations(post.citations, canonical)
    faq = _ensure_faq(post.faq)
    geo_focus = [item for item in (post.geo_focus or []) if _normalize_text(item)] or ["Polska"]
    headline = _normalize_text(post.headline) or _normalize_text(post.title) or post.slug.replace("-", " ")
    if len(headline) < 5:
        headline = _ensure_text_length(headline, minimum=5)
    topic = _normalize_text(post.title) or headline or post.slug.replace("-", " ")
    if len(topic) < 5:
        topic = _ensure_text_length(topic, minimum=5)
    seo_title_source = _normalize_text(post.title) or headline
    seo_title = (seo_title_source or topic)[:70].strip()

    fallback_document = {
        "topic": topic,
        "slug": post.slug,
        "locale": post.locale or "pl-PL",
        "taxonomy": {
            "section": taxonomy_section,
            "categories": categories,
            "tags": tags,
        },
        "seo": {
            "title": seo_title or topic[:70],
            "description": description,
            "slug": post.slug,
            "canonical": canonical,
            "robots": post.robots or "index,follow",
        },
        "article": {
            "headline": headline or topic,
            "lead": lead,
            "sections": sections,
            "citations": citations,
        },
        "aeo": {
            "geo_focus": geo_focus,
            "faq": faq,
        },
    }
    return ArticleDocument.model_validate(fallback_document)


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
            title=post.title,
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
    "/articles/{slug}",
    response_model=ArticleDocument,
    include_in_schema=True,
    tags=["Articles"],
)
def get_article(slug: str, db: Session = Depends(get_db)):
    post = db.query(Post).filter(Post.slug == slug).one_or_none()
    if not post:
        raise HTTPException(status_code=404, detail="post not found")
    document = document_from_post(post)
    return document


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
    document_data = document.model_dump(mode="json")
    document_data["slug"] = final_slug
    document_data.setdefault("taxonomy", {})["section"] = rubric_name
    document_data.setdefault("seo", {})["slug"] = final_slug
    document_data["seo"]["canonical"] = canonical
    document = ArticleDocument.model_validate(document_data)

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
        canonical=str(document.seo.canonical),
        robots=document.seo.robots,
        headline=document.article.headline,
        lead=document.article.lead,
        body_mdx=body_mdx,
        geo_focus=document.aeo.geo_focus,
        faq=[faq.model_dump() for faq in document.aeo.faq],
        citations=[str(url) for url in document.article.citations],
        payload=document.model_dump(mode="json"),
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
    return detail.model_dump()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
