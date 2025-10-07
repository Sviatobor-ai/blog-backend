"""Application configuration helpers."""

import os
from functools import lru_cache

from dotenv import find_dotenv, load_dotenv


load_dotenv(find_dotenv(), override=True)


@lru_cache
def get_database_url() -> str:
    """Return the configured database URL or fail fast when missing."""

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set")
    return database_url


@lru_cache
def get_openai_settings() -> dict[str, str | None]:
    """Return OpenAI related configuration loaded from the environment."""

    return {
        "api_key": os.getenv("OPENAI_API_KEY"),
        "assistant_id": os.getenv("OPENAI_ASSISTANT_ID", "asst_N0YcJg0jXoqHJQeesdWtiiIc"),
    }


DATABASE_URL = get_database_url()
