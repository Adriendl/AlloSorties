from datetime import date

from sorties_fr.weeks import agenda_weeks, last_wednesday


def test_weeks_for_wednesday_23_09_2026():
    weeks = agenda_weeks(date(2026, 9, 23))
    assert weeks[0] == date(2026, 6, 24)
    assert weeks[-1] == date(2026, 9, 23)
    assert len(weeks) == 14
    assert all(w.weekday() == 2 for w in weeks)


def test_never_future_week():
    weeks = agenda_weeks(date(2026, 9, 22))  # mardi
    assert weeks[-1] == date(2026, 9, 16)
    assert weeks[0] == date(2026, 6, 24)  # 22/09 - 91 j = 23/06


def test_last_wednesday():
    assert last_wednesday(date(2026, 9, 23)) == date(2026, 9, 23)
    assert last_wednesday(date(2026, 9, 29)) == date(2026, 9, 23)
