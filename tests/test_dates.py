from datetime import date

import pytest

from sorties_fr.dates import format_french_date, parse_french_date


@pytest.mark.parametrize(
    "text, expected",
    [
        ("1 juillet 2026", date(2026, 7, 1)),
        ("1er juillet 2026", date(2026, 7, 1)),
        ("16 décembre 1967", date(1967, 12, 16)),
        ("15 juillet 2026", date(2026, 7, 15)),
        ("25 février 1953", date(1953, 2, 25)),
        ("3 août 2026", date(2026, 8, 3)),
        ("  15   Juillet 2026 ", date(2026, 7, 15)),
        ("", None),
        (None, None),
        ("Date de sortie inconnue", None),
        ("31 février 2026", None),
        ("12 brumaire 2026", None),
    ],
)
def test_parse_french_date(text, expected):
    assert parse_french_date(text) == expected


def test_format_french_date():
    assert format_french_date(date(2026, 7, 15)) == "15 juillet 2026"
    assert format_french_date(date(2026, 8, 1)) == "1er août 2026"
