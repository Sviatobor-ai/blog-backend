"""Database models."""

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Integer,
    JSON,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.ext.mutable import MutableDict, MutableList

from .db import Base


ARRAY_TEXT = MutableList.as_mutable(ARRAY(Text))
ARRAY_TEXT = ARRAY_TEXT.with_variant(MutableList.as_mutable(JSON()), "sqlite")

JSONB_DICT = MutableDict.as_mutable(JSONB())
JSONB_DICT = JSONB_DICT.with_variant(MutableDict.as_mutable(JSON()), "sqlite")

JSONB_LIST = MutableList.as_mutable(JSONB())
JSONB_LIST = JSONB_LIST.with_variant(MutableList.as_mutable(JSON()), "sqlite")


class Post(Base):
    __tablename__ = "posts"
    __table_args__ = {"sqlite_autoincrement": True}

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    slug = Column(String(200), unique=True, index=True, nullable=False)
    locale = Column(String(10), nullable=False, default="pl-PL")
    section = Column(String(100), nullable=True)
    categories = Column(ARRAY_TEXT, nullable=True)
    tags = Column(ARRAY_TEXT, nullable=True)
    title = Column(String(200), nullable=False)
    description = Column(String(255), nullable=True)
    canonical = Column(String(255), nullable=True)
    robots = Column(String(50), nullable=True)
    headline = Column(String(200), nullable=True)
    lead = Column(Text, nullable=True)
    body_mdx = Column(Text, nullable=False)
    geo_focus = Column(ARRAY_TEXT, nullable=True)
    faq = Column(JSONB_LIST, nullable=True)
    citations = Column(JSONB_LIST, nullable=True)
    payload = Column(JSONB_DICT, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class IngestLog(Base):
    __tablename__ = "ingest_log"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    slug = Column(String(200), nullable=True)
    status = Column(String(50), nullable=False)
    error_text = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Rubric(Base):
    __tablename__ = "rubrics"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    code = Column(String(64), unique=True, nullable=False, index=True)
    name_pl = Column(String(128), nullable=False)
    is_active = Column(Boolean, nullable=False, server_default=text("true"))
