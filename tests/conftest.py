from datetime import date
from pathlib import Path

import pytest

from sorties_fr.parse import parse_agenda

FIXTURES = Path(__file__).parent / "fixtures"
WEEK = date(2026, 7, 15)


@pytest.fixture(scope="session")
def agenda_html() -> str:
    return (FIXTURES / "agenda_2026-07-15.html").read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def agenda_films(agenda_html):
    return {f.title_fr: f for f in parse_agenda(agenda_html, WEEK)}
