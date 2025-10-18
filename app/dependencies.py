"""Shared FastAPI dependency helpers."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .config import get_supadata_key
from .db import SessionLocal
from .integrations.supadata import SupaDataClient

_SUPADATA_CLIENT: SupaDataClient | None = None


def get_db() -> Iterator[Session]:
    """Yield a database session for request handlers."""

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_supadata_client() -> SupaDataClient:
    """Return a cached SupaData client instance or raise when not configured."""

    global _SUPADATA_CLIENT
    if _SUPADATA_CLIENT is None:
        try:
            api_key = get_supadata_key()
        except RuntimeError as exc:
            raise HTTPException(
                status_code=503,
                detail=str(exc),
            ) from exc
        _SUPADATA_CLIENT = SupaDataClient(api_key=api_key)
    return _SUPADATA_CLIENT


def shutdown_supadata_client() -> None:
    """Close the cached SupaData client on application shutdown."""

    global _SUPADATA_CLIENT
    if _SUPADATA_CLIENT is not None:
        _SUPADATA_CLIENT.close()
        _SUPADATA_CLIENT = None
