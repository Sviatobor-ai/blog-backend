"""Utility to export article payloads into data/payloads/*.json."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from .db import SessionLocal
from .main import document_from_post
from .models import Post

logger = logging.getLogger(__name__)


def export_payloads(destination: Path) -> list[Path]:
    destination.mkdir(parents=True, exist_ok=True)
    exported: list[Path] = []
    with SessionLocal() as db:
        posts = db.query(Post).order_by(Post.created_at.asc()).all()
        for post in posts:
            document = document_from_post(post)
            path = destination / f"{document.slug}.json"
            path.write_text(
                json.dumps(document.model_dump(mode="json"), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            exported.append(path)
    logger.info("exported %s payloads to %s", len(exported), destination)
    return exported


def main() -> None:
    parser = argparse.ArgumentParser(description="Export ArticleDocument payloads")
    parser.add_argument(
        "destination",
        nargs="?",
        default=Path("data/payloads"),
        type=Path,
        help="Target directory for payload JSON files",
    )
    args = parser.parse_args()
    export_payloads(Path(args.destination))


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s %(name)s: %(message)s")
    main()
