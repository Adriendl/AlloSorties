"""Calcul des mercredis de la période (§6.1)."""

from datetime import date, datetime, timedelta

from .config import PERIOD_DAYS, TZ

WEDNESDAY = 2


def today_paris() -> date:
    return datetime.now(TZ).date()


def last_wednesday(day: date) -> date:
    """Mercredi le plus récent <= day."""
    return day - timedelta(days=(day.weekday() - WEDNESDAY) % 7)


def agenda_weeks(today: date, period_days: int = PERIOD_DAYS) -> list[date]:
    """Mercredis W tels que today - period_days <= W <= today, du plus ancien au plus récent."""
    start = today - timedelta(days=period_days)
    week = last_wednesday(today)
    weeks = []
    while week >= start:
        weeks.append(week)
        week -= timedelta(days=7)
    return weeks[::-1]
