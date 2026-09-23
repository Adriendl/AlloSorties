from datetime import date

import pytest

from sorties_fr.filters import is_rerelease, split_releases
from sorties_fr.models import AgendaFilm
from tests.conftest import WEEK

NEW = ["L'Odyssée", "The Last Viking", "Comète", "Kayara, Princesse inca"]
RERUNS = [
    "Playtime",
    "Mon oncle",
    "Le Crime était presque parfait",
    "2 soeurs",
    "Ça tourne à Séoul ! Cobweb",
    "Foul King",
]


@pytest.mark.parametrize("title", NEW)
def test_new_releases_kept(agenda_films, title):
    assert not is_rerelease(agenda_films[title])


@pytest.mark.parametrize("title", RERUNS)
def test_reruns_excluded(agenda_films, title):
    assert is_rerelease(agenda_films[title])


def test_fixture_split(agenda_films):
    kept, reruns, manual = split_releases(list(agenda_films.values()))
    assert len(kept) == 9
    assert len(reruns) == 13
    assert manual == []


def _film(release: date | None) -> AgendaFilm:
    return AgendaFilm(
        cfilm_id="1", title_fr="X", title_original="X", release_date=release, agenda_week=WEEK
    )


def test_boundary_seven_days():
    assert not is_rerelease(_film(date(2026, 7, 8)))  # W - 7 j : conservé
    assert is_rerelease(_film(date(2026, 7, 7)))  # W - 8 j : ressortie


def test_unknown_date_is_kept():
    assert not is_rerelease(_film(None))


def test_manual_exclusion():
    film = _film(date(2026, 7, 15))
    kept, reruns, manual = split_releases([film], excluded_ids={"1"})
    assert kept == [] and reruns == [] and manual == [film]
