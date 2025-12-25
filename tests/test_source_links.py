import os
import sys

os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_source_links.db")
os.environ.setdefault("NEXT_PUBLIC_SITE_URL", "https://wiedza.joga.yoga")

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app.services.source_links import (
    build_source_label,
    enforce_single_hyperlink_per_url,
    normalize_url,
)


def test_normalize_url_removes_fragments_and_trailing_slash():
    assert (
        normalize_url(" https://Example.com/Path/To/Segment/#fragment ")
        == "https://example.com/Path/To/Segment"
    )


def test_enforce_single_hyperlink_per_url_keeps_first_link_only():
    text = (
        "Źródło bazowe [Pierwszy](https://example.com/page/) oraz "
        "[Duplikat](https://example.com/page#ref) i ponownie https://example.com/page/."
    )

    rewritten, seen = enforce_single_hyperlink_per_url(text, set())

    assert "[Pierwszy](https://example.com/page/)" in rewritten
    assert "[Duplikat]" not in rewritten
    assert "example.com/page/" in rewritten
    assert "https://example.com/page#ref" not in rewritten
    assert normalize_url("https://example.com/page#ref") in seen


def test_build_source_label_maps_known_hosts():
    label = build_source_label(
        "https://www.health.harvard.edu/blog/more-than-just-a-game-yoga-for-school-age-children-201601299055"
    )
    assert "Harvard Health Publishing" in label
    assert len(label) > 10
