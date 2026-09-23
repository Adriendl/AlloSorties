from datetime import date

from sorties_fr.models import AgendaFilm
from sorties_fr.ranking import Ranked, rank
from sorties_fr.state import FilmState


def item(title, release, peak):
    film = AgendaFilm(
        cfilm_id=title, title_fr=title, title_original=title,
        release_date=release, agenda_week=date(2026, 7, 15),
    )
    entry = FilmState(
        title_fr=title, first_seen=date(2026, 9, 23), last_seen=date(2026, 9, 23),
        last_seances=0, peak_seances=peak,
    )
    return Ranked(film, entry)


def test_peak_then_most_recent_then_title():
    items = [
        item("Ancien", date(2026, 7, 1), 100),
        item("Récent", date(2026, 9, 16), 100),
        item("Populaire", date(2026, 6, 24), 900),
        item("B", date(2026, 8, 5), 10),
        item("a", date(2026, 8, 5), 10),
        item("Sans date", None, 10),
    ]
    assert [i.film.title_fr for i in rank(items)] == [
        "Populaire", "Récent", "Ancien", "a", "B", "Sans date",
    ]
