"""Seed script for the rubrics taxonomy."""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Iterable, List, Tuple

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

from app.db import SessionLocal
from app.models import Rubric

logger = logging.getLogger(__name__)


RUBRICS: Tuple[Tuple[str, str, bool], ...] = (
    ("wyjazdy", "Wyjazdy jogowe", True),
    ("kalendarz-retreatow", "Kalendarz retreatów", True),
    ("osrodki-miejsca-pl", "Ośrodki i miejsca (Polska)", True),
    ("praktyki-jogowe", "Praktyki jogowe (asany, style)", True),
    ("medytacja-mindfulness", "Medytacja i mindfulness", True),
    ("oddech-pranajama", "Oddech i pranajama", True),
    ("joga-nidra-relaks", "Joga nidra i relaks", True),
    (
        "zdrowie-kregoslup-regeneracja",
        "Zdrowie kręgosłupa i regeneracja",
        True,
    ),
    ("wellness-spa", "Wellness & SPA dla joginów", False),
    ("dieta-ajurweda", "Dieta i ajurweda", False),
    ("sprzet-akcesoria", "Sprzęt i akcesoria (maty, bolstery)", False),
    ("joga-online", "Joga online (kursy, platformy)", False),
    ("warsztaty-jednodniowe", "Warsztaty i wydarzenia jednodniowe", False),
    (
        "podroze-trekking-pl",
        "Podróże i trekking dla joginów (PL)",
        False,
    ),
    ("psychologia-dobrostan", "Psychologia i dobrostan", False),
    ("poradniki-organizatora", "Poradniki organizatora (B2B)", False),
    (
        "prawo-formalnosci-organizatora",
        "Prawo i formalności organizatora (PL)",
        False,
    ),
)


def apply_activation_flags(
    rubrics: Iterable[Tuple[str, str, bool]],
    *,
    activate_all: bool,
    deactivate_all: bool,
) -> List[dict]:
    """Return rubric dictionaries with activation flags applied."""

    data = []
    for code, name_pl, is_active in rubrics:
        if activate_all:
            active_value = True
        elif deactivate_all:
            active_value = False
        else:
            active_value = is_active
        data.append({"code": code, "name_pl": name_pl, "is_active": active_value})
    return data


def seed_rubrics(*, activate_all: bool = False, deactivate_all: bool = False) -> Tuple[int, int]:
    """Upsert the rubrics taxonomy and return counts of inserted/updated rows."""

    if activate_all and deactivate_all:
        raise ValueError("Cannot use --activate-all and --deactivate-all together")

    payload = apply_activation_flags(
        RUBRICS, activate_all=activate_all, deactivate_all=deactivate_all
    )

    inserted_count = 0
    updated_count = 0

    with SessionLocal() as session:
        for rubric in payload:
            insert_stmt = insert(Rubric).values(**rubric)
            upsert_stmt = insert_stmt.on_conflict_do_update(
                index_elements=[Rubric.code],
                set_={
                    "name_pl": insert_stmt.excluded.name_pl,
                    "is_active": insert_stmt.excluded.is_active,
                },
            )
            upsert_stmt = upsert_stmt.returning(text("xmax = 0 AS inserted"))
            result = session.execute(upsert_stmt)
            is_inserted = bool(result.scalar_one())
            if is_inserted:
                inserted_count += 1
            else:
                updated_count += 1
        session.commit()

    return inserted_count, updated_count


def parse_args(argv: List[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed rubrics taxonomy")
    parser.add_argument(
        "--activate-all",
        action="store_true",
        help="Activate all rubrics before seeding",
    )
    parser.add_argument(
        "--deactivate-all",
        action="store_true",
        help="Deactivate all rubrics before seeding",
    )
    return parser.parse_args(argv)


def main(argv: List[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = parse_args(argv)
    try:
        inserted, updated = seed_rubrics(
            activate_all=args.activate_all, deactivate_all=args.deactivate_all
        )
    except Exception:  # pragma: no cover - CLI reporting
        logger.exception("Failed to seed rubrics")
        return 1
    logger.info("Rubrics seeded successfully: %s inserted, %s updated", inserted, updated)
    return 0


if __name__ == "__main__":
    sys.exit(main())
