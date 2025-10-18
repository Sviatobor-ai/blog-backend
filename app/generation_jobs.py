"""Helpers for storing and executing generation jobs."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from sqlalchemy.orm import Session

from .integrations.supadata import SupaDataClient
from .models import GenerationJob
logger = logging.getLogger(__name__)


class GenerationJobStatus(str, Enum):
    """Enumeration describing job lifecycle states."""

    PENDING = "pending"
    READY = "ready"
    SKIPPED_NO_RAW = "skipped_no_raw"
    FAILED = "failed"


def fetch_raw_text_from_youtube(client: SupaDataClient, url: str) -> tuple[Optional[str], Optional[str]]:
    """Return transcript/ASR text and mode used for the provided URL."""

    transcript = client.get_transcript_raw(url)
    if transcript:
        return transcript, "transcript"
    asr = client.asr_transcribe_raw(url)
    if asr:
        return asr, "asr"
    return None, None


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
