"""Tri du catalogue (§6.4)."""

from dataclasses import dataclass
from datetime import date

from .models import AgendaFilm
from .state import FilmState


@dataclass
class Ranked:
    film: AgendaFilm
    entry: FilmState


def sort_key(item: Ranked) -> tuple:
    """peak_seances décroissant, puis sortie la plus récente, puis titre."""
    release = item.film.release_date or date.min
    return (-item.entry.peak_seances, -release.toordinal(), item.film.title_fr.casefold())


def rank(items: list[Ranked]) -> list[Ranked]:
    return sorted(items, key=sort_key)
