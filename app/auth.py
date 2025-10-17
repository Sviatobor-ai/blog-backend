"""Admin token authentication helpers."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query

from .db import SessionLocal
from .models import User


def get_user_by_token(token: str | None) -> Optional[User]:
    """Return the active user matching the provided token."""

    if not token:
        return None
    with SessionLocal() as session:
        return (
            session.query(User)
            .filter(User.token == token)
            .filter(User.is_active.is_(True))
            .one_or_none()
        )


def require_token(
    t: str | None = Query(default=None),
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
    authorization: str | None = Header(default=None),
) -> User:
    """FastAPI dependency ensuring a valid admin token is provided."""

    token: str | None = None
    if t:
        token = t.strip()
    elif x_admin_token:
        token = x_admin_token.strip()
    elif authorization:
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() == "bearer" and value:
            token = value.strip()
    user = get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="invalid admin token")
    return user


admin_api_router = APIRouter(prefix="/admin/api", tags=["admin-api"])
