"""Détection des ressorties (§6.3)."""

from datetime import timedelta

from .config import RERELEASE_TOLERANCE_DAYS
from .models import AgendaFilm


def is_rerelease(film: AgendaFilm) -> bool:
    """Date affichée = sortie originale : trop ancienne par rapport à la semaine -> ressortie.

    Une date absente ou illisible n'est pas considérée comme une ressortie.
    """
    if film.release_date is None:
        return False
    return film.release_date < film.agenda_week - timedelta(days=RERELEASE_TOLERANCE_DAYS)


def split_releases(
    films: list[AgendaFilm], excluded_ids: set[str] = frozenset()
) -> tuple[list[AgendaFilm], list[AgendaFilm], list[AgendaFilm]]:
    """Retourne (conservés, ressorties, exclus manuellement)."""
    kept, reruns, manual = [], [], []
    for film in films:
        if film.cfilm_id in excluded_ids:
            manual.append(film)
        elif is_rerelease(film):
            reruns.append(film)
        else:
            kept.append(film)
    return kept, reruns, manual
