"""Sequential background runner for automatic generation jobs."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Callable, Optional

from sqlalchemy.orm import Session

from ..integrations.supadata import MIN_TRANSCRIPT_CHARS, SupaDataClient
from ..models import GenJob
from ..services import ArticleGenerationError, get_transcript_generator
from .video_pipeline import generate_article_from_raw

logger = logging.getLogger(__name__)


SupaFactory = Callable[[], SupaDataClient]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _fetch_raw_text(supadata: SupaDataClient, url: str) -> Optional[str]:
    try:
        transcript = supadata.get_transcript(url=url, mode="auto", text=True)
    except Exception as exc:
        logger.warning("supadata.transcript.error url=%s err=%s", url, exc)
        return None
    text = (transcript.content or "").strip()
    if len(text) < MIN_TRANSCRIPT_CHARS:
        logger.info(
            "event=supadata.transcript.too_short video_url=%s content_chars=%s threshold=%s",
            url,
            len(text),
            MIN_TRANSCRIPT_CHARS,
        )
        return None
    return text


def _finalise_job(
    session: Session,
    job: GenJob,
    *,
    status: str,
    error: Optional[str] = None,
    article_id: Optional[int] = None,
) -> None:
    job.status = status
    job.error = error
    job.last_error = error
    job.article_id = article_id
    job.finished_at = _now()
    session.add(job)
    session.commit()


def process_url_once(
    db: Session,
    *,
    supadata: SupaDataClient,
    url: str,
) -> tuple[bool, Optional[int], Optional[str]]:
    """Execute the transcript→article pipeline synchronously."""

    try:
        text = _fetch_raw_text(supadata, url)
    except Exception as exc:
        logger.warning("pipeline supadata-fail url=%s err=%s", url, exc)
        return False, None, str(exc)
    if not text:
        return False, None, "no transcript text"
    generator = get_transcript_generator()
    try:
        post = generate_article_from_raw(
            db,
            raw_text=text,
            source_url=url,
            generator=generator,
        )
    except ArticleGenerationError as exc:
        return False, None, str(exc)
    except Exception as exc:  # pragma: no cover - safety net for unexpected errors
        logger.exception("pipeline failure url=%s", url)
        return False, None, str(exc)
    return True, post.id, None


class GenRunner:
    """Single-threaded background worker that processes queued jobs."""

    def __init__(
        self,
        *,
        session_factory: Callable[[], Session],
        supadata_factory: SupaFactory,
    ) -> None:
        self._session_factory = session_factory
        self._supadata_factory = supadata_factory
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._runner_on = False

    def start(self) -> bool:
        with self._lock:
            if self._runner_on:
                return False
            self._runner_on = True
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run_loop, daemon=True)
            self._thread.start()
            logger.info("gen-runner started")
            return True

    def stop(self) -> bool:
        with self._lock:
            if not self._runner_on:
                return False
            self._stop_event.set()
            logger.info("gen-runner stop requested")
            return True

    def is_on(self) -> bool:
        with self._lock:
            return self._runner_on

    def _mark_done(self) -> None:
        with self._lock:
            self._runner_on = False
            self._thread = None
            self._stop_event.clear()

    def _run_loop(self) -> None:
        try:
            while True:
                if self._stop_event.is_set():
                    break
                with self._session_factory() as session:
                    job = self._next_pending(session)
                    if not job:
                        break
                    self._process_job(session, job)
                if self._stop_event.is_set():
                    break
        finally:
            self._mark_done()
            logger.info("gen-runner stopped")

    def _next_pending(self, session: Session) -> GenJob | None:
        job = (
            session.query(GenJob)
            .filter(GenJob.status == "pending")
            .order_by(GenJob.id.asc())
            .first()
        )
        if not job:
            return None
        job.status = "running"
        job.error = None
        job.last_error = None
        job.started_at = _now()
        session.add(job)
        session.commit()
        session.refresh(job)
        logger.info("gen-runner job-start id=%s url=%s", job.id, job.url or job.source_url)
        return job

    def _process_job(self, session: Session, job: GenJob) -> None:
        start_time = _now()
        url = job.url or job.source_url
        if not url:
            job.status = "skipped"
            job.error = "missing url"
            job.last_error = job.error
            job.finished_at = _now()
            session.add(job)
            session.commit()
            logger.warning("gen-runner job-skip id=%s reason=missing-url", job.id)
            return

        try:
            supadata = self._supadata_factory()
            text = _fetch_raw_text(supadata, url)
        except Exception as exc:
            error_message = str(exc)[:500]
            _finalise_job(session, job, status="failed", error=error_message)
            logger.warning("gen-runner job-fail id=%s reason=supadata err=%s", job.id, exc)
            return
        if not text:
            _finalise_job(session, job, status="skipped", error="no transcript text")
            logger.warning("gen-runner job-skip id=%s reason=no-text", job.id)
            return

        generator = get_transcript_generator()
        text_chars = len(text)
        try:
            text_bytes = len(text.encode("utf-8"))
        except Exception:  # pragma: no cover - very unlikely encoding errors
            text_bytes = text_chars
        logger.info(
            "gen-runner text-length id=%s chars=%s bytes=%s",
            job.id,
            text_chars,
            text_bytes,
        )
        try:
            post = generate_article_from_raw(
                session,
                raw_text=text,
                source_url=url,
                generator=generator,
            )
        except ArticleGenerationError as exc:
            error_message = str(exc)[:500]
            _finalise_job(session, job, status="failed", error=error_message)
            logger.warning("gen-runner job-fail id=%s err=%s", job.id, exc)
            return
        except Exception as exc:  # pragma: no cover - defensive guard
            error_message = str(exc)[:500]
            _finalise_job(session, job, status="failed", error=error_message)
            logger.exception("gen-runner unexpected failure id=%s", job.id)
            return

        session.refresh(post)
        _finalise_job(session, job, status="done", article_id=post.id, error=None)
        elapsed = (job.finished_at - start_time).total_seconds()
        logger.info(
            "gen-runner job-done id=%s article_id=%s secs=%.2f",
            job.id,
            post.id,
            elapsed,
        )


_runner: GenRunner | None = None


def get_runner(session_factory: Callable[[], Session], supadata_factory: SupaFactory) -> GenRunner:
    global _runner
    if _runner is None:
        _runner = GenRunner(session_factory=session_factory, supadata_factory=supadata_factory)
    return _runner
