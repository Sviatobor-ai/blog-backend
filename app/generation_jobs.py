"""Helpers for storing and executing generation jobs."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from sqlalchemy.orm import Session

from .integrations.supadata import MIN_TRANSCRIPT_CHARS, SupaDataClient, SupadataTranscriptError
from .models import GenerationJob
logger = logging.getLogger(__name__)


class GenerationJobStatus(str, Enum):
    """Enumeration describing job lifecycle states."""

    PENDING = "pending"
    READY = "ready"
    SKIPPED_NO_RAW = "skipped_no_raw"
    FAILED = "failed"


def fetch_raw_text_from_youtube(client: SupaDataClient, url: str) -> tuple[Optional[str], Optional[str]]:
    """Return transcript text for the provided URL when available."""

    try:
        transcript = client.get_transcript(url=url, mode="auto", text=True)
    except SupadataTranscriptError as exc:
        logger.warning(
            "event=supadata.transcript.error video_url=%s status_code=%s err=%s",
            url,
            exc.status_code,
            exc.error_body,
        )
        return None, None
    content = (transcript.content or "").strip()
    if len(content) < MIN_TRANSCRIPT_CHARS:
        logger.info(
            "event=supadata.transcript.too_short video_url=%s content_chars=%s threshold=%s",
            url,
            len(content),
            MIN_TRANSCRIPT_CHARS,
        )
        return None, None
    return content, "transcript"


def run_generation_job(
    db: Session,
    job: GenerationJob,
    client: SupaDataClient,
    *,
    process_raw_text: Callable[[GenerationJob, str], None] | None = None,
) -> Optional[str]:
    """Fetch raw text for a job and optionally process it downstream."""

    text, mode = fetch_raw_text_from_youtube(client, job.source_url)
    if not text:
        job.status = GenerationJobStatus.SKIPPED_NO_RAW.value
        job.mode = None
        job.text_length = None
        job.last_error = "no raw text"
        job.processed_at = datetime.now(timezone.utc)
        db.add(job)
        db.commit()
        logger.warning("generation-job skipped id=%s url=%s", job.id, job.source_url)
        return None

    job.status = GenerationJobStatus.READY.value
    job.mode = mode
    job.text_length = len(text)
    job.last_error = None
    job.processed_at = datetime.now(timezone.utc)
    db.add(job)
    db.commit()
    logger.info(
        "generation-job prepared id=%s url=%s mode=%s length=%s",
        job.id,
        job.source_url,
        mode,
        len(text),
    )
    if process_raw_text:
        process_raw_text(job, text)
    return text
