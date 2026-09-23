from datetime import date

import httpx
import pytest
import respx

from sorties_fr.models import AgendaFilm
from sorties_fr.state import FilmState, TmdbMatch
from sorties_fr.tmdb import (
    API_URL,
    TmdbAuthError,
    TmdbClient,
    director_match,
    link_film,
    match_film,
    normalize,
    poster_url,
    short_title,
    title_similarity,
    year_penalty,
)

TODAY = date(2026, 9, 23)
ODYSSEE = AgendaFilm(
    cfilm_id="1000013045",
    title_fr="L'Odyssée",
    title_original="The Odyssey",
    release_date=date(2026, 7, 15),
    production_year=2026,
    directors=["Christopher Nolan"],
    agenda_week=date(2026, 7, 15),
)

# Trois homonymes 2026 : seul le réalisateur les départage.
SEARCH = {
    "results": [
        {"id": 2, "title": "The Odyssey", "original_title": "The Odyssey",
         "release_date": "2026-07-03", "popularity": 50},
        {"id": 1, "title": "L'Odyssée", "original_title": "The Odyssey",
         "release_date": "2026-07-15", "popularity": 10, "poster_path": "/s.jpg"},
        {"id": 3, "title": "The Odyssey", "original_title": "The Odyssey",
         "release_date": "2026-07-14", "popularity": 5},
    ]
}


def details(tmdb_id, director, imdb_id):
    return {
        "id": tmdb_id,
        "poster_path": f"/p{tmdb_id}.jpg",
        "external_ids": {"imdb_id": imdb_id},
        "credits": {"crew": [{"name": director, "job": "Director"}]},
    }


@pytest.fixture
def client():
    return TmdbClient("eyJ.fake.token", sleep=lambda s: None, min_interval=0)


@pytest.fixture
def api():
    with respx.mock(base_url=API_URL, assert_all_called=False) as mock:
        yield mock


def test_normalize():
    assert normalize("L'Odyssée") == "odyssee"
    assert normalize("The Odyssey") == "odyssey"
    assert normalize("Les Parfait(s) : arnaques en famille") == "parfait s arnaques en famille"
    assert normalize("Cœur & âme") == "coeur and ame"
    assert normalize("Le") == "le"  # un titre réduit à un article est conservé
    assert normalize("団塚唯我") == ""


def test_title_similarity_uses_both_titles():
    cand = {"title": "L'Odyssée", "original_title": "Odysseia"}
    assert title_similarity(ODYSSEE, cand) == 1.0
    assert title_similarity(ODYSSEE, {"title": "", "original_title": ""}) == 0.0


@pytest.mark.parametrize(
    "cand_date, penalty",
    [("2026-07-15", 0.0), ("2025-05-20", 0.0), ("2024-01-01", 0.1), ("2011-01-01", 0.3), ("", 0.1)],
)
def test_year_penalty(cand_date, penalty):
    assert year_penalty(ODYSSEE, {"release_date": cand_date}) == penalty


def test_short_title():
    assert short_title("La Bataille de Gaulle - Partie 2 : J’écris ton nom") == "La Bataille de Gaulle"
    assert short_title("Haute solitude, Jean Zay prisonnier politique") == "Haute solitude"
    assert short_title("Kill Bill: The Whole Bloody Affair") == "Kill Bill"
    assert short_title("L'Odyssée") is None
    assert short_title("Mission: Impossible") == "Mission"
    assert short_title("M - le maudit") is None  # trop court


def test_short_title_similarity_has_malus():
    film = ODYSSEE.model_copy(update={"title_fr": "Haute solitude, Jean Zay prisonnier politique",
                                      "title_original": "Haute solitude, Jean Zay prisonnier politique"})
    assert title_similarity(film, {"title": "Haute solitude", "original_title": "Haute solitude"}) == 0.8


def test_year_penalty_uses_production_year():
    # Film de 2021 sorti en France en 2026 (« La Dernière séance »).
    film = ODYSSEE.model_copy(update={"production_year": 2021})
    assert year_penalty(film, {"release_date": "2021-10-14"}) == 0.0


def test_director_match_variants():
    film = ODYSSEE.model_copy(update={"directors": ["Christophe Réveille"]})
    assert director_match(film, details(1, "Christophe Dimitri Réveille", None)) is True
    film = ODYSSEE.model_copy(update={"directors": ["Anthony Benna"]})
    assert director_match(film, details(1, "Tony Benna", None)) is True
    assert director_match(ODYSSEE, details(1, "Jane Doe", None)) is False
    # Nom en écriture non latine : inconnu, pas de malus.
    assert director_match(ODYSSEE, details(1, "団塚唯我", None)) is None
    assert director_match(ODYSSEE, {"credits": {"crew": []}}) is None


def test_match_uses_director_to_break_ties(api, client):
    search = api.get("/search/movie").respond(json=SEARCH)
    api.get("/movie/1").respond(json=details(1, "Christopher Nolan", "tt1"))
    api.get("/movie/2").respond(json=details(2, "Someone Else", "tt2"))
    api.get("/movie/3").respond(json=details(3, "Another One", "tt3"))
    match = match_film(client, ODYSSEE, TODAY)
    assert match.status == "ok"
    assert (match.tmdb_id, match.imdb_id, match.poster_path) == (1, "tt1", "/p1.jpg")
    assert match.score == 1.0
    # Première requête : titre original + année, en français.
    params = search.calls[0].request.url.params
    assert (params["query"], params["year"], params["language"]) == ("The Odyssey", "2026", "fr-FR")
    assert search.call_count == 1
    assert client.client.headers["Authorization"] == "Bearer eyJ.fake.token"


def test_search_fallbacks_without_year_then_french_title(api, client):
    search = api.get("/search/movie").mock(
        side_effect=[
            httpx.Response(200, json={"results": []}),
            httpx.Response(200, json={"results": []}),
            httpx.Response(200, json={"results": [SEARCH["results"][1]]}),
        ]
    )
    api.get("/movie/1").respond(json=details(1, "Christopher Nolan", "tt1"))
    assert match_film(client, ODYSSEE, TODAY).imdb_id == "tt1"
    queries = [(c.request.url.params["query"], c.request.url.params.get("year")) for c in search.calls]
    assert queries == [("The Odyssey", "2026"), ("The Odyssey", None), ("L'Odyssée", "2026")]


def test_no_result_fails(api, client):
    api.get("/search/movie").respond(json={"results": []})
    match = match_film(client, ODYSSEE, TODAY)
    assert match.status == "failed" and match.reason == "aucun résultat TMDB"


def test_low_score_fails(api, client):
    api.get("/search/movie").respond(
        json={"results": [{"id": 9, "title": "Odyssey 5", "original_title": "Odyssey 5",
                           "release_date": "2002-06-07"}]}
    )
    api.get("/movie/9").respond(json=details(9, "Someone", "tt9"))
    match = match_film(client, ODYSSEE, TODAY)
    assert match.status == "failed"
    assert "Odyssey 5 (2002) #9" in match.reason


def test_missing_imdb_id_fails(api, client):
    api.get("/search/movie").respond(json={"results": [SEARCH["results"][1]]})
    api.get("/movie/1").respond(json=details(1, "Christopher Nolan", None))
    match = match_film(client, ODYSSEE, TODAY)
    assert match.status == "failed" and "pas d'imdb_id" in match.reason


def _entry(tmdb=None):
    return FilmState(
        title_fr="L'Odyssée", first_seen=TODAY, last_seen=TODAY,
        last_seances=1, peak_seances=1, tmdb=tmdb,
    )


def test_link_reuses_cached_match(api, client):
    route = api.get("/search/movie")
    cached = TmdbMatch(status="ok", checked_at=date(2026, 1, 1), imdb_id="tt1")
    assert link_film(client, ODYSSEE, _entry(cached), None, TODAY) is cached
    assert not route.called


def test_link_retries_failure_after_a_week(api, client):
    route = api.get("/search/movie").respond(json={"results": []})
    recent = TmdbMatch(status="failed", checked_at=date(2026, 9, 20))
    assert link_film(client, ODYSSEE, _entry(recent), None, TODAY) is recent
    assert not route.called
    old = TmdbMatch(status="failed", checked_at=date(2026, 9, 16))
    entry = _entry(old)
    assert link_film(client, ODYSSEE, entry, None, TODAY).checked_at == TODAY
    assert route.called and entry.tmdb.checked_at == TODAY


def test_link_override_wins(api, client):
    api.get("/find/tt42").respond(json={"movie_results": [{"id": 7, "poster_path": "/o.jpg"}]})
    cached = TmdbMatch(status="ok", checked_at=TODAY, imdb_id="tt1")
    entry = _entry(cached)
    match = link_film(client, ODYSSEE, entry, {"imdb_id": "tt42"}, TODAY)
    assert (match.imdb_id, match.tmdb_id, match.poster_path, match.reason) == (
        "tt42", 7, "/o.jpg", "override"
    )
    assert entry.tmdb is match


def test_retry_on_429_then_auth_error(api):
    sleeps = []
    client = TmdbClient("abc", sleep=sleeps.append, min_interval=0)
    route = api.get("/search/movie").mock(
        side_effect=[httpx.Response(429, headers={"Retry-After": "1"}), httpx.Response(200, json={"results": []})]
    )
    assert client.search("x", None) == []
    assert sleeps == [1.0] and route.call_count == 2
    assert route.calls[0].request.url.params["api_key"] == "abc"  # clé v3 en paramètre
    api.get("/movie/1").respond(401)
    with pytest.raises(TmdbAuthError):
        client.details(1)


def test_missing_token():
    with pytest.raises(TmdbAuthError):
        TmdbClient("")


def test_poster_url():
    assert poster_url(TmdbMatch(status="ok", checked_at=TODAY, poster_path="/a.jpg"), "x") == (
        "https://image.tmdb.org/t/p/w500/a.jpg"
    )
    assert poster_url(None, "https://allocine/x.jpg") == "https://allocine/x.jpg"
