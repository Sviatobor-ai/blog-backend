"""Helpers for extracting the author voice from transcripts."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable, List


@dataclass(slots=True)
class AuthorContext:
    """Compact summary of the author's voice and key ideas."""

    voice_markers: List[str] = field(default_factory=list)
    key_theses: List[str] = field(default_factory=list)
    key_terms: List[str] = field(default_factory=list)
    practical_steps: List[str] = field(default_factory=list)
    cautions: List[str] = field(default_factory=list)
    short_quotes: List[str] = field(default_factory=list)


def _split_sentences(text: str) -> list[str]:
    separators = re.compile(r"(?<=[.!?])\s+")
    parts = separators.split(text)
    return [part.strip() for part in parts if part.strip()]


def _extract_terms(words: Iterable[str], *, min_len: int = 4, top_n: int = 12) -> list[str]:
    stopwords = {
        "i",
        "oraz",
        "ale",
        "że",
        "to",
        "jest",
        "na",
        "się",
        "w",
        "z",
        "o",
        "nie",
        "do",
        "dla",
        "po",
        "jak",
        "tak",
        "czy",
        "a",
        "od",
        "też",
        "lub",
        "która",
        "które",
        "który",
        "którą",
        "ten",
        "ta",
        "tym",
        "gdy",
        "gdyż",
        "przy",
        "bez",
    }
    freq = Counter()
    for word in words:
        cleaned = re.sub(r"[^\wąćęłńóśżźĄĆĘŁŃÓŚŻŹ-]", "", word.lower())
        if len(cleaned) < min_len or cleaned in stopwords:
            continue
        freq[cleaned] += 1
    return [term for term, _ in freq.most_common(top_n)]


def _pick_sentences(sentences: list[str], *, min_len: int, max_len: int, limit: int) -> list[str]:
    picked: list[str] = []
    for sentence in sentences:
        if len(sentence) < min_len or len(sentence) > max_len:
            continue
        if sentence in picked:
            continue
        picked.append(sentence)
        if len(picked) >= limit:
            break
    return picked


def build_author_context_from_transcript(transcript_text: str) -> AuthorContext:
    """Derive a lightweight author profile from transcript text."""

    cleaned = (transcript_text or "").strip()
    if not cleaned:
        return AuthorContext()

    paragraphs = [block.strip() for block in re.split(r"\n{2,}", cleaned) if block.strip()]
    sentences = _split_sentences(cleaned)

    words = [word for paragraph in paragraphs for word in paragraph.split()]
    key_terms = _extract_terms(words)

    short_quotes = _pick_sentences(sentences, min_len=20, max_len=160, limit=7)

    voice_markers: list[str] = []
    for paragraph in paragraphs:
        snippet = paragraph.split("\n")[0].strip()
        if not snippet:
            continue
        clause = snippet.split(",")[0].strip()
        candidate = clause if 15 <= len(clause) <= 90 else snippet[:90].strip()
        if candidate and candidate not in voice_markers:
            voice_markers.append(candidate)
        if len(voice_markers) >= 6:
            break

    action_keywords = {"spróbuj", "możesz", "warto", "zacznij", "zrób", "ćwicz", "praktykuj", "sprawdź", "dodaj"}
    caution_keywords = {"uważaj", "unikaj", "ostrożnie", "nie przesadzaj", "nie łącz", "nie rób", "uważne"}

    practical_steps = [
        sentence
        for sentence in sentences
        if any(keyword in sentence.lower() for keyword in action_keywords)
    ][:6]

    cautions = [
        sentence
        for sentence in sentences
        if any(keyword in sentence.lower() for keyword in caution_keywords)
    ][:5]

    key_theses = _pick_sentences(sentences, min_len=60, max_len=220, limit=9)

    return AuthorContext(
        voice_markers=voice_markers,
        key_theses=key_theses,
        key_terms=key_terms[:9],
        practical_steps=practical_steps,
        cautions=cautions,
        short_quotes=short_quotes,
    )


__all__ = ["AuthorContext", "build_author_context_from_transcript"]
