"""FastAPI application entrypoint with writer mock endpoint."""

from __future__ import annotations

import re
from typing import Any, Dict, List

from fastapi import FastAPI, HTTPException, Response, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import DATABASE_URL
from app.db import SessionLocal, engine
from app.models import IngestLog, Post, Rubric
from app.schemas import WriterPublishIn, WriterPublishOut

app = FastAPI(
    title="wyjazdy-blog backend",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Dev CORS — open; will restrict later in prod
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

SLUG_REGEX = re.compile(r"^[a-z0-9-]{3,200}$")


def slugify_pl(value: str) -> str:
    """Create a URL-friendly slug from Polish text."""

    translation_map = str.maketrans(
        {
            "ą": "a",
            "ć": "c",
            "ę": "e",
            "ł": "l",
            "ń": "n",
            "ó": "o",
            "ś": "s",
            "ż": "z",
            "ź": "z",
        }
    )
    normalized = value.lower().translate(translation_map)
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized)
    normalized = re.sub(r"-+", "-", normalized).strip("-")
    if len(normalized) > 200:
        normalized = normalized[:200].strip("-")
    return normalized


def ensure_slug(candidate: str | None, *sources: str) -> str:
    """Validate the slug and regenerate it from sources when required."""

    if candidate and SLUG_REGEX.fullmatch(candidate):
        return candidate
    for source in sources:
        if not source:
            continue
        regenerated = slugify_pl(source)
        if regenerated and len(regenerated) >= 3:
            if len(regenerated) > 200:
                regenerated = regenerated[:200].strip("-")
            if SLUG_REGEX.fullmatch(regenerated):
                return regenerated
    return "artykul-joga"


def build_description(topic: str) -> str:
    """Generate a Polish SEO description within 140-160 characters."""

    topic_clean = " ".join(topic.split())
    if len(topic_clean) > 45:
        truncated = topic_clean[:45].rsplit(" ", 1)[0]
        topic_phrase = truncated or topic_clean[:45]
    else:
        topic_phrase = topic_clean
    description = (
        f"{topic_phrase} przedstawiamy jako drogę do pielęgnowania uważności, odpoczynku i stabilności emocjonalnej "
        "podczas podróży i codziennych rytuałów wellness."
    )
    description = " ".join(description.split())
    if len(description) < 140:
        description += " Poznasz inspirujące praktyki oddechowe, proste rytuały i wskazówki podróżne."
        description = " ".join(description.split())
    if len(description) > 160:
        description = description[:160].rstrip()
        if " " in description:
            description = description.rsplit(" ", 1)[0]
        if description.endswith(","):
            description = description[:-1]
        if len(description) < 140:
            description += " Plan zawiera krótkie rytuały wspierające spokój."
            description = " ".join(description.split())
    return description


def build_lead(topic: str) -> str:
    """Create a lead paragraph of 60-80 words summarising the article."""

    topic_clean = " ".join(topic.split())
    topic_words = topic_clean.split()
    if len(topic_words) > 8:
        topic_phrase = " ".join(topic_words[:8])
    else:
        topic_phrase = topic_clean
    sentences = [
        f"{topic_phrase} to punkt wyjścia do świadomego wypoczynku, który łączy ruch z ciszą natury.",
        "W tym szkicu proponujemy rytuały oddechowe, sekwencje rozgrzewające oraz mikro praktyki regeneracji.",
        "Dowiesz się, jak dopasować tempo dnia do potrzeb ciała, dobrać miejsca do medytacji i zapisać refleksje.",
        "Podpowiadamy też, jak korzystać z lokalnych smaków w zgodzie z uważnym stylem życia podczas podróży.",
        "Na końcu znajdziesz krótkie ćwiczenia wdzięczności, by zabrać atmosferę wyjazdu do codzienności.",
    ]
    lead = " ".join(sentences)
    return lead


def build_body_mdx(topic: str, seed_queries: List[str]) -> str:
    """Compose a markdown body with several sections in Polish."""

    topic_clean = " ".join(topic.split())
    queries_fragment = "; ".join(seed_queries[:3]) if seed_queries else "praca z oddechem i plan dnia"
    body = f"""
## Wprowadzenie do tematu
{topic_clean} opisujemy jako proces świadomego łączenia ruchu, relaksu i obserwacji emocji, który możesz realizować w trakcie wyjazdów po Polsce.

## Plan dnia krok po kroku
Zacznij od krótkiej medytacji o świcie, następnie dodaj rozgrzewkę stawów i sekwencję powitania słońca. W ciągu dnia zaplanuj warsztat inspirowany hasłami: {queries_fragment}. Wieczorem postaw na regenerację w ciszy oraz prowadzone notatki wdzięczności.

## Praca z miejscem i społecznością
Wybierz przestrzenie blisko natury, rozmawiaj z lokalnymi przewodnikami i włącz tradycyjne smaki do mindful posiłków. Dbaj o rytm grupy, aby każdy mógł poczuć spokój i bezpieczeństwo.

## Narzędzia po powrocie
Zapisz lekcje z wyjazdu, zaplanuj mikro praktyki na poranki i wieczory oraz wracaj do nagranych afirmacji, by utrzymać efekty podróży w codzienności.
"""
    return body.strip()


def build_mock_article(payload: WriterPublishIn, section_name: str) -> Dict[str, Any]:
    """Synthesise a mock article JSON structure from the writer input."""

    topic_clean = payload.topic
    title_topic = topic_clean if len(topic_clean) <= 45 else (topic_clean[:45].rsplit(" ", 1)[0] or topic_clean[:45])
    title = f"{title_topic} – joga.yoga"
    if len(title) > 60:
        max_topic_length = 60 - len(" – joga.yoga")
        trimmed = title_topic[:max_topic_length]
        trimmed = trimmed.rsplit(" ", 1)[0] or trimmed
        title = f"{trimmed} – joga.yoga"
    description = build_description(topic_clean)
    slug_candidate = slugify_pl(title)
    slug = ensure_slug(slug_candidate, title, topic_clean)
    headline = f"{title_topic}: świadomy przewodnik wyjazdowy"
    lead = build_lead(topic_clean)
    body_mdx = build_body_mdx(topic_clean, payload.seed_queries)
    geo_focus = ["Polska"]
    faq = [
        {
            "question": f"Jak przygotować się do wyjazdu, którego osią jest {topic_clean.lower()}?",
            "answer": "Zacznij od ustalenia intencji, zaplanuj spokojne rozpoczęcie dnia, spakuj matę oraz dziennik refleksji i poinformuj grupę o rytmie praktyk.",
        },
        {
            "question": "Co zabrać do codziennych praktyk podczas wyjazdu?",
            "answer": "Przygotuj lekkie ubrania do warstwowania, butelkę na wodę, olejek do automasażu, podręczne karty afirmacji oraz przekąski wspierające stabilny poziom energii.",
        },
    ]
    citations: List[str] = []
    if payload.seed_urls:
        citations.extend(payload.seed_urls[:5])
    if len(citations) < 2:
        citations.extend([
            "https://przyklad.pl/inspiracje-joga",
            "https://przyklad.pl/przewodnik-wellness",
        ])
    tags = payload.seed_queries or [topic_clean.lower()]
    taxonomy = {
        "section": section_name,
        "categories": [section_name],
        "tags": tags,
    }
    article = {
        "headline": headline,
        "lead": lead,
        "body_mdx": body_mdx,
        "citations": citations[:5],
    }
    seo = {
        "title": title,
        "description": description,
        "slug": slug,
        "canonical": f"https://joga.yoga/artykuly/{slug}",
        "robots": "index,follow",
    }
    aeo_geo = {
        "geo_focus": geo_focus,
        "faq": faq,
    }
    article_json: Dict[str, Any] = {
        "topic": topic_clean,
        "slug": slug,
        "locale": "pl-PL",
        "taxonomy": taxonomy,
        "article": article,
        "seo": seo,
        "aeo_geo": aeo_geo,
    }
    return article_json


def upsert_post(session: Session, payload_dict: Dict[str, Any]) -> Post:
    """Insert or update a post using the provided mock payload."""

    slug = ensure_slug(
        payload_dict.get("slug"),
        payload_dict.get("seo", {}).get("slug"),
        payload_dict.get("seo", {}).get("title"),
        payload_dict.get("topic"),
    )
    seo = payload_dict.get("seo", {})
    taxonomy = payload_dict.get("taxonomy", {})
    article = payload_dict.get("article", {})
    geo = payload_dict.get("aeo_geo", {})
    post_data = {
        "slug": slug,
        "locale": payload_dict.get("locale", "pl-PL"),
        "section": taxonomy.get("section"),
        "categories": taxonomy.get("categories"),
        "tags": taxonomy.get("tags"),
        "title": seo.get("title"),
        "description": seo.get("description"),
        "canonical": seo.get("canonical"),
        "robots": seo.get("robots"),
        "headline": article.get("headline"),
        "lead": article.get("lead"),
        "body_mdx": article.get("body_mdx"),
        "geo_focus": geo.get("geo_focus"),
        "faq": geo.get("faq"),
        "citations": article.get("citations"),
    }
    if not post_data["title"] or not post_data["lead"] or not post_data["body_mdx"]:
        raise ValueError("mock article is missing required textual content")

    existing_post = session.query(Post).filter(Post.slug == slug).one_or_none()
    created = False
    if existing_post:
        for field, value in post_data.items():
            setattr(existing_post, field, value)
        post = existing_post
    else:
        post = Post(**post_data)
        session.add(post)
        created = True
    session.flush()
    setattr(post, "_was_created", created)
    return post


@app.get("/health")
def health():
    """
    Returns basic service and DB health.
    - status: always "ok" if the app is up
    - db: "ok" if SELECT 1 passes; otherwise error class name
    """
    db_status = "ok"
    try:
        with engine.connect() as conn:
            conn.execute(text("select 1"))
    except Exception as e:
        db_status = f"error: {e.__class__.__name__}"
    return {
        "status": "ok",
        "db": db_status,
        "driver": "sqlalchemy+psycopg",
        "database_url_present": bool(DATABASE_URL),
    }


@app.post("/writer/publish", response_model=WriterPublishOut)
def writer_publish(payload: WriterPublishIn, response: Response) -> WriterPublishOut:
    """Create or update a mock article in the database and log the ingest."""

    session: Session = SessionLocal()
    slug_for_log: str | None = None
    try:
        section_name = "Wyjazdy jogowe"
        if payload.rubric_code:
            rubric = session.query(Rubric).filter(Rubric.code == payload.rubric_code).one_or_none()
            if rubric and rubric.name_pl:
                section_name = rubric.name_pl

        article_json = build_mock_article(payload, section_name)
        slug_for_log = article_json.get("slug")
        post = upsert_post(session, article_json)
        slug_for_log = post.slug

        ingest_entry = IngestLog(slug=post.slug, status="published", error_text=None)
        session.add(ingest_entry)
        session.commit()

        response.status_code = status.HTTP_201_CREATED if getattr(post, "_was_created", False) else status.HTTP_200_OK
        return WriterPublishOut(status="published", slug=post.slug, url=f"/artykuly/{post.slug}", id=post.id)
    except Exception as exc:  # pragma: no cover - defensive error logging
        session.rollback()
        error_text = str(exc)
        try:
            session.add(IngestLog(slug=slug_for_log, status="error", error_text=error_text))
            session.commit()
        except Exception:
            session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Publikacja artykułu nie powiodła się.",
        ) from exc
    finally:
        session.close()

if __name__ == "__main__":
    import uvicorn
    # Local dev runner
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
