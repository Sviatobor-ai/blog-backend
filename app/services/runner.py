"""Sequential background runner for automatic generation jobs."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Callable, Optional

from sqlalchemy.orm import Session

from ..integrations.supadata import SupaDataClient
from ..models import GenJob
from ..services import ArticleGenerationError, get_transcript_generator
from .video_pipeline import generate_article_from_raw

logger = logging.getLogger(__name__)


SupaFactory = Callable[[], SupaDataClient]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _fetch_raw_text(supadata: SupaDataClient, url: str) -> Optional[str]:
    text = supadata.get_transcript_raw(url)
    if text:
        return text
    return supadata.asr_transcribe_raw(url)


def process_url_once(
    db: Session,
    *,
    supadata: SupaDataClient,
    url: str,
) -> tuple[bool, Optional[int], Optional[str]]:
    """Execute the transcript→article pipeline synchronously."""

    text = _fetch_raw_text(supadata, url)
    if not text:
        return False, None, "no transcript/asr text"
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

        supadata = self._supadata_factory()
        text = _fetch_raw_text(supadata, url)
        if not text:
            job.status = "skipped"
            job.error = "no transcript/asr text"
            job.last_error = job.error
            job.finished_at = _now()
            session.add(job)
            session.commit()
            logger.warning("gen-runner job-skip id=%s reason=no-text", job.id)
            return

        generator = get_transcript_generator()
        try:
            post = generate_article_from_raw(
                session,
                raw_text=text,
                source_url=url,
                generator=generator,
            )
        except ArticleGenerationError as exc:
            job.status = "failed"
            job.error = str(exc)[:500]
            job.last_error = job.error
            job.finished_at = _now()
            session.add(job)
            session.commit()
            logger.warning("gen-runner job-fail id=%s err=%s", job.id, exc)
            return
        except Exception as exc:  # pragma: no cover - defensive guard
            job.status = "failed"
            job.error = str(exc)[:500]
            job.last_error = job.error
            job.finished_at = _now()
            session.add(job)
            session.commit()
            logger.exception("gen-runner unexpected failure id=%s", job.id)
            return

        session.refresh(post)
        job.status = "done"
        job.article_id = post.id
        job.finished_at = _now()
        job.error = None
        job.last_error = None
        session.add(job)
        session.commit()
        elapsed = (job.finished_at - start_time).total_seconds()
        logger.info("gen-runner job-done id=%s article_id=%s secs=%.2f", job.id, post.id, elapsed)


_runner: GenRunner | None = None


def get_runner(session_factory: Callable[[], Session], supadata_factory: SupaFactory) -> GenRunner:
    global _runner
    if _runner is None:
        _runner = GenRunner(session_factory=session_factory, supadata_factory=supadata_factory)
    return _runner
