"""Récupération + parsing + filtrage de toutes les semaines de la période."""

import logging
from dataclasses import dataclass, field
from datetime import date

from .fetch import AgendaFetcher
from .filters import is_rerelease
from .models import AgendaFilm
from .parse import parse_agenda

log = logging.getLogger(__name__)


class EmptyPageError(RuntimeError):
    """Page agenda sans aucun film parsé : structure HTML probablement modifiée."""


@dataclass
class Collected:
    weeks: list[date]
    parsed: int = 0
    releases: list[AgendaFilm] = field(default_factory=list)
    reruns: list[AgendaFilm] = field(default_factory=list)
    excluded: list[AgendaFilm] = field(default_factory=list)

    @property
    def date_unknown(self) -> list[AgendaFilm]:
        return [f for f in self.releases if f.release_date is None]


def collect(
    fetcher: AgendaFetcher,
    weeks: list[date],
    today: date,
    excluded_ids: set[str] = frozenset(),
    refresh_all: bool = False,
) -> Collected:
    result = Collected(weeks=weeks)
    releases: dict[str, AgendaFilm] = {}
    reruns: dict[str, AgendaFilm] = {}
    excluded: dict[str, AgendaFilm] = {}
    for week in weeks:
        films = parse_agenda(fetcher.get(week, today, refresh_all=refresh_all), week)
        log.info("Semaine %s : %d films", week, len(films))
        if not films:
            raise EmptyPageError(f"Aucun film parsé sur la semaine {week}")
        result.parsed += len(films)
        for film in films:
            if film.cfilm_id in excluded_ids:
                excluded.setdefault(film.cfilm_id, film)
            elif is_rerelease(film):
                reruns.setdefault(film.cfilm_id, film)
            else:
                # Un film listé sur plusieurs semaines : on garde la 1re apparition
                # (les séances sont de toute façon le compteur courant).
                releases.setdefault(film.cfilm_id, film)
    result.releases = list(releases.values())
    # Nouveauté sur une page, « ressortie » sur une page ultérieure : c'est une nouveauté.
    result.reruns = [f for k, f in reruns.items() if k not in releases]
    result.excluded = list(excluded.values())
    return result
