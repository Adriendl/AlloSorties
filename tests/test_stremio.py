import json
from datetime import date

from sorties_fr.models import AgendaFilm
from sorties_fr.ranking import Ranked
from sorties_fr.state import FilmState, TmdbMatch
from sorties_fr.stremio import catalog_pages, description, manifest, meta, write_addon

TODAY = date(2026, 9, 23)


def item(n: int, imdb: str | None = None, **film_kw) -> Ranked:
    film = AgendaFilm(
        cfilm_id=str(n), title_fr=f"Film {n}", title_original=f"Film {n}",
        release_date=date(2026, 7, 15), agenda_week=date(2026, 7, 15), **film_kw,
    )
    entry = FilmState(
        title_fr=film.title_fr, first_seen=TODAY, last_seen=TODAY, last_seances=0,
        peak_seances=0,
        tmdb=TmdbMatch(status="ok", checked_at=TODAY, imdb_id=imdb or f"tt{n:07d}"),
    )
    return Ranked(film, entry)


def test_manifest():
    m = manifest()
    assert m["id"] == "perso.sorties-fr.allocine"
    assert m["version"] == "1.0.0"
    assert m["resources"] == ["catalog"] and m["types"] == ["movie"] and m["idPrefixes"] == ["tt"]
    assert m["catalogs"] == [
        {"type": "movie", "id": "sorties-fr", "name": "Dernières sorties en France"}
    ]


def test_meta_odyssee():
    it = item(
        1, "tt33764258",
        genres=["Action", "Fantastique"], seances=592, press_rating=4.1, user_rating=4.3,
        synopsis="Ulysse rentre à Ithaque.", poster_url="https://fr.web.img5.acsta.net/x.jpg",
    )
    it.entry.tmdb.poster_path = "/abc.jpg"
    assert meta(it) == {
        "id": "tt33764258",
        "type": "movie",
        "name": "Film 1",
        "poster": "https://image.tmdb.org/t/p/w500/abc.jpg",
        "releaseInfo": "2026",
        "genres": ["Action", "Fantastique"],
        "description": "Sortie le 15 juillet 2026 · 592 séances · Presse 4,1 · Spectateurs 4,3"
        "\n\nUlysse rentre à Ithaque.",
    }


def test_meta_fallbacks():
    it = item(2, poster_url="https://fr.web.img5.acsta.net/y.jpg", seances=1)
    m = meta(it)
    assert m["poster"] == "https://fr.web.img5.acsta.net/y.jpg"  # repli Allociné
    assert m["description"] == "Sortie le 15 juillet 2026 · 1 séance"
    assert "genres" not in m
    it.film.poster_url = None
    it.film.release_date = None
    it.film.production_year = 1980
    it.film.seances = 0
    m = meta(it)
    assert "poster" not in m and m["releaseInfo"] == "1980"
    assert description(it) == "0 séance"


def test_pagination_250(tmp_path):
    pages = write_addon([item(n) for n in range(250)], tmp_path)
    assert pages == {
        "catalog/movie/sorties-fr.json": 100,
        "catalog/movie/sorties-fr/skip=100.json": 100,
        "catalog/movie/sorties-fr/skip=200.json": 50,
    }
    first = json.loads((tmp_path / "catalog/movie/sorties-fr.json").read_text())
    last = json.loads((tmp_path / "catalog/movie/sorties-fr/skip=200.json").read_text())
    assert first["metas"][0]["id"] == "tt0000000"
    assert last["metas"][-1]["id"] == "tt0000249"
    assert json.loads((tmp_path / "manifest.json").read_text()) == manifest()


def test_pagination_exact_multiple_ends_with_empty_page():
    pages = catalog_pages([{"id": str(i)} for i in range(200)])
    assert [len(v) for v in pages.values()] == [100, 100, 0]
    assert list(pages)[-1] == "catalog/movie/sorties-fr/skip=200.json"
    assert [len(v) for v in catalog_pages([]).values()] == [0]


def test_duplicate_imdb_ids_keep_best_ranked(tmp_path):
    pages = write_addon([item(1, "tt1"), item(2, "tt1"), item(3)], tmp_path)
    data = json.loads((tmp_path / "catalog/movie/sorties-fr.json").read_text())
    assert [m["name"] for m in data["metas"]] == ["Film 1", "Film 3"]
    assert pages == {"catalog/movie/sorties-fr.json": 2}


def test_dist_is_cleaned(tmp_path):
    (tmp_path / "catalog/movie/sorties-fr").mkdir(parents=True)
    stale = tmp_path / "catalog/movie/sorties-fr/skip=900.json"
    stale.write_text("{}")
    write_addon([item(1)], tmp_path)
    assert not stale.exists()
