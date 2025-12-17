import os
import sys
from copy import deepcopy

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app.services.article_publication import sanitize_faq


def test_sanitize_faq_removes_empty_and_dedupes():
    faq_items = [
        {"question": " Jak oddychać? ", "answer": "  Powoli i świadomie.  "},
        {"question": "jak oddychać?", "answer": "Druga odpowiedź"},
        {"question": "Pozycja góry", "answer": "  Stabilna postawa\n"},
        {"question": " ", "answer": "Brak"},
    ]

    sanitized = sanitize_faq(deepcopy(faq_items))

    assert sanitized == [
        {"question": "Jak oddychać?", "answer": "Powoli i świadomie."},
        {"question": "Pozycja góry", "answer": "Stabilna postawa"},
    ]
