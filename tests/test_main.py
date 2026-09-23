import json
import re
from datetime import date
from functools import partial

import httpx
import pytest
import respx

from sorties_fr import config, main
from sorties_fr.fetch import AgendaFetcher
from sorties_fr.state import LastRun, State, load_state, save_state
from sorties_fr.tmdb import API_URL, TmdbClient
from sorties_fr.wikidata import SPARQL_URL

TODAY = date(2026, 9, 23)


def tmdb_search(request):
    """Un résultat parfait pour chaque titre cherché, avec imdb_id dérivé de l'id TMDB."""
    query = request.url.params["query"]
    year = request.url.params.get("year") or "2026"
    tmdb_id = abs(hash(query)) % 10**6
    return httpx.Response(200, json={"results": [
        {"id": tmdb_id, "title": query, "original_title": query, "release_date": f"{year}-07-15"}
    ]})


def tmdb_movie(request):
    tmdb_id = int(request.url.path.rsplit("/", 1)[1])
    return httpx.Response(200, json={
        "id": tmdb_id, "poster_path": f"/{tmdb_id}.jpg",
        "external_ids": {"imdb_id": f"tt{tmdb_id:08d}"}, "credits": {"crew": []},
    })


@pytest.fixture
def env(tmp_path, monkeypatch, agenda_html):
    monkeypatch.setenv("TMDB_API_KEY", "eyJ.test")
    monkeypatch.setattr(main, "AgendaFetcher", partial(AgendaFetcher, sleep=lambda s: None))
    monkeypatch.setattr(main, "TmdbClient", partial(TmdbClient, sleep=lambda s: None, min_interval=0))
    with respx.mock(assert_all_called=False) as mock:
        # Même page servie pour les 14 semaines : 9 nouveautés distinctes.
        mock.get(url__regex=r"https://www\.allocine\.fr/film/agenda/sem-.*").respond(
            200, text=agenda_html
        )
        mock.get(f"{API_URL}/search/movie").mock(side_effect=tmdb_search)
        mock.get(url__regex=re.escape(API_URL) + r"/movie/\d+").mock(side_effect=tmdb_movie)
        mock.post(SPARQL_URL).respond(json={"results": {"bindings": []}})
        yield tmp_path, mock


def args(tmp_path, *extra):
    return main.parse_args([
        "--today", TODAY.isoformat(), "--refresh-all",
        "--dist", str(tmp_path / "dist"), "--state", str(tmp_path / "state.json"),
        "--overrides", str(tmp_path / "overrides.json"), "--cache", str(tmp_path / "cache"),
        *extra,
    ])


def test_end_to_end(env, monkeypatch):
    tmp_path, _ = env
    monkeypatch.setattr(config, "MIN_CATALOG_SIZE", 5)
    (tmp_path / "overrides.json").write_text('{"305835": {"exclude": true}}')
    assert main.run(args(tmp_path)) == main.EXIT_OK

    dist = tmp_path / "dist"
    assert json.loads((dist / "manifest.json").read_text())["id"] == "perso.sorties-fr.allocine"
    metas = json.loads((dist / "catalog/movie/sorties-fr.json").read_text())["metas"]
    assert [m["name"] for m in metas][:2] == ["L'Odyssée", "The Last Viking"]
    assert len(metas) == 8  # 9 nouveautés - 1 exclusion manuelle
    assert "Playtime" not in {m["name"] for m in metas}

    report = json.loads((dist / "report.json").read_text())
    assert report["weeks"] == 14 and report["allocine_requests"] == 14
    assert report["reruns_excluded"] == 13 and report["manual_excluded"] == ["L'Aventure rêvée"]
    assert report["catalog_size"] == 8 and report["tmdb_failed"] == 0

    state = load_state(tmp_path / "state.json")
    assert state.last_run == LastRun(date=TODAY, catalog_size=8)
    assert state.films["1000013045"].peak_seances == 537


def test_guard_min_catalog_size(env):
    tmp_path, _ = env
    assert main.run(args(tmp_path)) == main.EXIT_GUARD  # 9 films < 20
    assert not (tmp_path / "dist/manifest.json").exists()
    report = json.loads((tmp_path / "dist/report.json").read_text())
    assert "< 20" in report["guard_error"]


def test_guard_catalog_drop(env, monkeypatch):
    tmp_path, _ = env
    monkeypatch.setattr(config, "MIN_CATALOG_SIZE", 5)
    save_state(State(last_run=LastRun(date=date(2026, 9, 16), catalog_size=30)), tmp_path / "state.json")
    assert main.run(args(tmp_path)) == main.EXIT_GUARD  # 9 < 30 / 2
    assert "baisse" in json.loads((tmp_path / "dist/report.json").read_text())["guard_error"]


def test_empty_page_guard(env):
    tmp_path, mock = env
    mock.get(url__regex=r"https://www\.allocine\.fr/film/agenda/sem-.*").respond(200, text="<html/>")
    assert main.run(args(tmp_path)) == main.EXIT_GUARD


def test_blocked_by_allocine(env):
    tmp_path, mock = env
    mock.get(url__regex=r"https://www\.allocine\.fr/film/agenda/sem-.*").respond(429)
    assert main.run(args(tmp_path)) == main.EXIT_FETCH


def test_missing_token(env, monkeypatch):
    tmp_path, _ = env
    monkeypatch.delenv("TMDB_API_KEY")
    assert main.run(args(tmp_path)) == main.EXIT_CONFIG


def test_check_guards():
    assert main.check_guards(20, None) is None
    assert main.check_guards(19, None) is not None
    prev = LastRun(date=TODAY, catalog_size=100)
    assert main.check_guards(50, prev) is None
    assert main.check_guards(49, prev) is not None
