import importlib
import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_seo_defaults.db")
os.environ.setdefault("SUPADATA_KEY", "test-key")

from app.article_schema import ARTICLE_FAQ_MAX, ARTICLE_FAQ_MIN


def test_build_canonical_uses_artykuly_prefix(monkeypatch):
    monkeypatch.setenv("NEXT_PUBLIC_SITE_URL", "https://wiedza.joga.yoga")
    import app.config as config
    import app.services as services

    importlib.reload(config)
    services._article_canonical_base.cache_clear()
    importlib.reload(services)

    assert (
        services.build_canonical_for_slug("zimna-kapiel")
        == "https://wiedza.joga.yoga/artykuly/zimna-kapiel"
    )


def test_ensure_faq_respects_minimum_defaults():
    from app import main

    faq_items = main._ensure_faq([])

    assert len(faq_items) >= ARTICLE_FAQ_MIN
    assert len(faq_items) <= ARTICLE_FAQ_MAX
    for item in faq_items:
        assert item["question"]
        assert item["answer"]
