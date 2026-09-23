from datetime import date

from sorties_fr.models import AgendaFilm
from sorties_fr.state import State, TmdbMatch, load_overrides, load_state, save_state


def _film(seances: int, cfilm="42") -> AgendaFilm:
    return AgendaFilm(
        cfilm_id=cfilm,
        title_fr="Film",
        title_original="Film",
        release_date=date(2026, 7, 15),
        seances=seances,
        agenda_week=date(2026, 7, 15),
    )


def test_peak_is_kept_when_counter_drops():
    state = State()
    state.observe(_film(600), date(2026, 7, 16))
    entry = state.observe(_film(120), date(2026, 8, 20))
    assert entry.first_seen == date(2026, 7, 16)
    assert entry.last_seen == date(2026, 8, 20)
    assert entry.last_seances == 120
    assert entry.peak_seances == 600


def test_roundtrip(tmp_path):
    state = State()
    entry = state.observe(_film(10), date(2026, 9, 23))
    entry.tmdb = TmdbMatch(status="ok", checked_at=date(2026, 9, 23), tmdb_id=1, imdb_id="tt1")
    path = tmp_path / "state.json"
    save_state(state, path)
    assert load_state(path) == state
    assert load_state(tmp_path / "absent.json") == State()


def test_prune():
    state = State()
    state.observe(_film(1, "1"), date(2026, 1, 1))
    state.observe(_film(1, "2"), date(2026, 9, 1))
    assert state.prune(date(2026, 9, 23)) == 1
    assert list(state.films) == ["2"]


def test_overrides(tmp_path):
    path = tmp_path / "overrides.json"
    path.write_text('{"_comment": "x", "1": {"imdb_id": "tt1"}, "2": {"exclude": true}}')
    assert load_overrides(path) == {"1": {"imdb_id": "tt1"}, "2": {"exclude": True}}
