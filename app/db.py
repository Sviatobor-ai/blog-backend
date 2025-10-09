"""Database session and engine configuration."""

from sqlalchemy import create_engine
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import DATABASE_URL


class Base(DeclarativeBase):
    """Base class for declarative models."""

    pass


_database_url = make_url(DATABASE_URL) if isinstance(DATABASE_URL, str) else DATABASE_URL

_connect_args: dict[str, object] = {}
if isinstance(_database_url, URL) and _database_url.get_backend_name() == "sqlite":
    _connect_args["check_same_thread"] = False

engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
