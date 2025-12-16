"""Shared prompt builders for article generation assistants."""

from __future__ import annotations

from typing import Iterable

from ..config import get_site_base_url
from .author_context import AuthorContext


def _format_author_context(author_context: AuthorContext | None) -> list[str]:
    if not author_context:
        return []

    lines = ["AuthorContext:"]
    if author_context.voice_markers:
        markers = "; ".join(author_context.voice_markers[:6])
        lines.append(f"- Głos/narracja: {markers}.")
    if author_context.key_theses:
        thesis_text = " | ".join(author_context.key_theses[:9])
        lines.append(f"- Kluczowe tezy: {thesis_text}.")
    if author_context.key_terms:
        terms = ", ".join(author_context.key_terms[:9])
        lines.append(f"- Słowa/zwroty autora: {terms}.")
    if author_context.practical_steps:
        steps = " | ".join(author_context.practical_steps[:5])
        lines.append(f"- Wskazówki praktyczne: {steps}.")
    if author_context.cautions:
        cautions = " | ".join(author_context.cautions[:4])
        lines.append(f"- Ostrzeżenia autora: {cautions}.")
    if author_context.short_quotes:
        quotes = " | ".join(author_context.short_quotes[:6])
        lines.append(f"- Cytaty: {quotes}.")
    return lines


def _compose_generation_brief(
    *,
    rubric: str | None,
    topic: str | None,
    keywords: Iterable[str] | None,
    guidance: str | None,
    transcript: str | None = None,
    research_content: str | None = None,
    research_sources: Iterable | None = None,
    author_context: AuthorContext | None = None,
    user_guidance: str | None = None,
) -> str:
    keyword_text = ", ".join(keyword.strip() for keyword in (keywords or []) if keyword and keyword.strip())
    lines: list[str] = [
        "Tworzysz długą, empatyczną i ekspercką publikację dla bloga joga.yoga.",
        "Budujesz narrację z wyraźnymi akapitami, przykładami oraz wskazówkami do wdrożenia w codzienności.",
        "Preserve author voice i rytm narracji z AuthorContext; artykuł ma brzmieć jak mówiony przez autora, nie jak encyklopedia.",
        "Honoruj wytyczne użytkownika jako nadrzędne dla tonu i struktury.",
        "Dopasuj strukturę do materiału i nie wymuszaj sztywnej liczby sekcji.",
        "FAQ powinno odpowiadać na pozostające praktyczne pytania (nie pytaj o to samo co w nagłówkach); jeśli nic nie pozostaje do wyjaśnienia, FAQ może być puste.",
        "Cytuj twierdzenia faktograficzne najlepiej dopasowanymi źródłami z researchu zamiast listowania wielu linków.",
    ]
    if rubric:
        lines.append(f"Rubryka redakcyjna: {rubric}.")
    if topic:
        lines.append(f"Temat przewodni artykułu: {topic}.")
    if keyword_text:
        lines.append(f"Wpleć naturalnie słowa kluczowe SEO: {keyword_text}.")
    if guidance:
        lines.append(f"Wytyczne redakcyjne: {guidance}.")
    if user_guidance:
        lines.append(f"Najważniejsze wskazówki od użytkownika (priorytet): {user_guidance}.")
    if research_content or research_sources:
        lines.extend(
            [
                "Kontrakt kompozycji:",
                "- Primary voice is the author (lub wskazówki użytkownika). Narracja ma brzmieć naturalnie i ludzko.",
                "- Research używaj do: (a) doprecyzowania pojęć, (b) krótkich wtrąceń faktograficznych, (c) cytowań faktów.",
                "- Nie przerabiaj całości na ton akademicki.",
                "- Gdy coś jest opinią autora, oznacz to wprost (np. 'Autor podkreśla…').",
                "- Gdy podajesz fakt, wesprzyj go dostępnym źródłem.",
                "- Preferuj krótkie wstawki z researchu (1–2 zdania) blisko powiązanych akapitów.",
                "Dodaj opcjonalny blok 'Kontekst i źródła (dla ciekawych)' przed FAQ, tylko gdy masz research_summary lub źródła; ma być zwięzły (definicje w punktach + 3–8 źródeł).",
                "FAQ ma odpowiadać na pozostałe praktyczne pytania, bez powtarzania tytułów sekcji; jeśli brak sensownych pytań, FAQ może być puste.",
                "Cytowania: korzystaj z dostarczonych źródeł do twierdzeń faktograficznych, wybieraj linki najlepiej pasujące do tezy (unikaj nadmiaru).",
            ]
        )
    lines.extend(_format_author_context(author_context))
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
        "Opracuj sugestywny nagłówek, rozbudowany lead i sekcje odpowiadające na potrzeby odbiorców joga.yoga bez sztywnego schematu."
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
    author_context: AuthorContext | None = None,
    user_guidance: str | None = None,
) -> str:
    """Compose a user brief for topic-driven article generation."""

    return _compose_generation_brief(
        rubric=rubric_name,
        topic=topic,
        keywords=keywords,
        guidance=guidance,
        transcript=None,
        research_content=research_content,
        research_sources=research_sources,
        author_context=author_context,
        user_guidance=user_guidance or guidance,
    )


def build_generation_brief_transcript(
    *,
    transcript_text: str,
    rubric_name: str | None,
    keywords: Iterable[str] | None,
    guidance: str | None,
    research_content: str | None = None,
    research_sources: Iterable | None = None,
    author_context: AuthorContext | None = None,
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
        author_context=author_context,
        user_guidance=guidance,
    )


def build_generation_system_instructions(*, source_url: str | None = None) -> str:
    """Return Polish system instructions shared by assistant generators."""

    canonical_base = get_site_base_url().rstrip("/")
    parts = [
        "You are the content architect for joga.yoga and respond exclusively in Polish (pl-PL).",
        "Always return exactly one JSON object containing: topic, slug, locale, taxonomy, seo, article, aeo.",
        "Craft a captivating lead made of several rich paragraphs that invite the reader in.",
        "Twórz rozbudowane sekcje dopasowane do materiału, zamiast powtarzalnego układu.",
        "Dodawaj cytowania do twierdzeń faktograficznych korzystając z research_sources, wybieraj 2-3 najlepiej pasujące linki bez przeładowania.",
        "Populate taxonomy.tags with at least two precise joga.yoga-friendly keywords and ensure taxonomy.categories is never empty.",
        "Produce complete SEO metadata and set seo.canonical to a URL that begins with ",
        f"{canonical_base}.",
        "Keep seo.title and article.headline in Polish under 60 characters, single-line, free of colons, and naturally containing at least one strategic keyword.",
        "Ensure aeo.geo_focus lists meaningful Polish or European localisations. FAQ ma odpowiadać na pozostałe praktyczne pytania (nie powtarzaj tytułów sekcji); jeśli brak nowych pytań, FAQ może być puste.",
        "Jeśli dodajesz suplement 'Kontekst i źródła (dla ciekawych)', umieść go na końcu sekcji przed FAQ, zwięźle (krótka lista pojęć + 3–8 wybranych źródeł).",
        "Return JSON only — no comments, markdown, or surrounding prose.",
    ]
    if source_url:
        parts.append(
            f"Incorporate the supplied source URL ({source_url}) as one of the citations whenever it genuinely supports the piece."
        )
    return " ".join(parts)
