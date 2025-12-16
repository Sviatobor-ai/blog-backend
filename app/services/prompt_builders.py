"""Shared prompt builders for article generation assistants."""

from __future__ import annotations

from typing import Iterable

from ..config import get_site_base_url


def _compose_generation_brief(
    *,
    rubric: str | None,
    topic: str | None,
    keywords: Iterable[str] | None,
    guidance: str | None,
    transcript: str | None = None,
    research_content: str | None = None,
    research_sources: Iterable | None = None,
) -> str:
    keyword_text = ", ".join(keyword.strip() for keyword in (keywords or []) if keyword and keyword.strip())
    lines: list[str] = [
        "Tworzysz długą, empatyczną i ekspercką publikację dla bloga joga.yoga.",
        "Budujesz narrację z wyraźnymi akapitami, przykładami oraz wskazówkami do wdrożenia w codzienności.",
        "Dbasz o logiczne przejścia między sekcjami i konsekwentny ton głosu marki.",
        "Lead musi liczyć co najmniej dwie akapity, a każda sekcja rozwija temat w sposób pogłębiony, a nie skrótowy.",
        "FAQ zawiera 2-4 pytania i wyczerpujące odpowiedzi wynikające z treści artykułu.",
    ]
    if rubric:
        lines.append(f"Rubryka redakcyjna: {rubric}.")
    if topic:
        lines.append(f"Temat przewodni artykułu: {topic}.")
    if keyword_text:
        lines.append(f"Wpleć naturalnie słowa kluczowe SEO: {keyword_text}.")
    if guidance:
        lines.append(f"Dodatkowe wytyczne redakcyjne: {guidance}.")
    if research_content or research_sources:
        lines.append(
            "Wykorzystaj dostarczone ustalenia z researchu jako wsparcie merytoryczne i cytowania faktów."
        )
    if research_content:
        lines.append("Podsumowanie researchu:")
        lines.append(str(research_content))
    if research_sources:
        lines.append("Proponowane źródła do cytowania:")
        for idx, source in enumerate(research_sources):
            if idx >= 6:
                break
            url = getattr(source, "url", None)
            if isinstance(source, dict):
                url = source.get("url") or url
                title = source.get("title") or source.get("description")
            else:
                title = getattr(source, "title", None) or getattr(source, "description", None)
            url_text = str(url) if url else ""
            title_text = str(title) if title else ""
            if url_text or title_text:
                lines.append(f"- {title_text} {url_text}".strip())
    lines.append(
        "Przygotuj jednowierszowy tytuł SEO i nagłówek (55-60 znaków), bez dwukropków i dopisków, wykorzystując naturalnie przynajmniej jedno kluczowe słowo z tematu lub listy słów kluczowych."
    )
    lines.append(
        "Opracuj sugestywny nagłówek, rozbudowany lead i sekcje, które odpowiadają na potrzeby odbiorców joga.yoga."
    )
    if transcript:
        lines.append(
            "Bazuj na poniższej transkrypcji (przetłumacz ją na polski, jeśli jest w innym języku), rozwiń ją w pełnoprawny artykuł i unikaj streszczania."
        )
        lines.append("TRANSKRYPCJA:")
        lines.append(transcript)
    return "\n".join(lines)


def build_generation_brief_topic(
    *,
    topic: str,
    rubric_name: str,
    keywords: Iterable[str] | None,
    guidance: str | None,
    research_content: str | None = None,
    research_sources: Iterable | None = None,
) -> str:
    """Compose a user brief for topic-driven article generation."""

    return _compose_generation_brief(
        rubric=rubric_name,
        topic=topic,
        keywords=keywords,
        guidance=guidance,
        research_content=research_content,
        research_sources=research_sources,
    )


def build_generation_brief_transcript(
    *,
    transcript_text: str,
    rubric_name: str | None,
    keywords: Iterable[str] | None,
    guidance: str | None,
    research_content: str | None = None,
    research_sources: Iterable | None = None,
) -> str:
    """Compose a user brief for transcript-driven article generation."""

    return _compose_generation_brief(
        rubric=rubric_name,
        topic=None,
        keywords=keywords,
        guidance=guidance,
        transcript=transcript_text,
        research_content=research_content,
        research_sources=research_sources,
    )


def build_generation_system_instructions(*, source_url: str | None = None) -> str:
    """Return Polish system instructions shared by assistant generators."""

    canonical_base = get_site_base_url().rstrip("/")
    parts = [
        "You are the content architect for joga.yoga and respond exclusively in Polish (pl-PL).",
        "Always return exactly one JSON object containing: topic, slug, locale, taxonomy, seo, article, aeo.",
        "Craft a captivating lead made of several rich paragraphs that invite the reader in.",
        "Create at least four long-form sections; each body must exceed 400 characters, flow naturally across 4-6 paragraphs and deliver actionable, expert guidance.",
        "Add a minimum of two high-quality citation URLs under article.citations and prefer three when available.",
        "Populate taxonomy.tags with at least two precise joga.yoga-friendly keywords and ensure taxonomy.categories is never empty.",
        "Produce complete SEO metadata and set seo.canonical to a URL that begins with ",
        f"{canonical_base}.",
        "Keep seo.title and article.headline in Polish under 60 characters, single-line, free of colons, and naturally containing at least one strategic keyword.",
        "Ensure aeo.geo_focus lists meaningful Polish or European localisations and compose 2-4 FAQ entries that resolve outstanding reader questions with thorough answers.",
        "Return JSON only — no comments, markdown, or surrounding prose.",
    ]
    if source_url:
        parts.append(
            f"Incorporate the supplied source URL ({source_url}) as one of the citations whenever it genuinely supports the piece."
        )
    return " ".join(parts)
