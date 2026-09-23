"""Parsing des dates françaises, indépendant de la locale système."""

import re
from datetime import date

MONTHS = {
    "janvier": 1,
    "fevrier": 2,
    "février": 2,
    "mars": 3,
    "avril": 4,
    "mai": 5,
    "juin": 6,
    "juillet": 7,
    "aout": 8,
    "août": 8,
    "septembre": 9,
    "octobre": 10,
    "novembre": 11,
    "decembre": 12,
    "décembre": 12,
}

_DATE_RE = re.compile(r"(\d{1,2})(?:er)?\s+([a-zéèêûô]+)\s+(\d{4})", re.IGNORECASE)


def parse_french_date(text: str | None) -> date | None:
    """« 15 juillet 2026 », « 1er juillet 2026 » -> date ; None si absent ou illisible."""
    if not text:
        return None
    m = _DATE_RE.search(" ".join(text.split()))
    if not m:
        return None
    day, month_name, year = m.groups()
    month = MONTHS.get(month_name.lower())
    if month is None:
        return None
    try:
        return date(int(year), month, int(day))
    except ValueError:
        return None


def format_french_date(d: date) -> str:
    names = [
        "janvier", "février", "mars", "avril", "mai", "juin",
        "juillet", "août", "septembre", "octobre", "novembre", "décembre",
    ]
    day = "1er" if d.day == 1 else str(d.day)
    return f"{day} {names[d.month - 1]} {d.year}"
