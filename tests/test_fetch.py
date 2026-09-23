from datetime import date

import httpx
import pytest
import respx

from sorties_fr.fetch import AgendaFetcher, FetchBlocked, FetchError

URL = "https://www.allocine.fr/film/agenda/sem-2026-07-15/"
TODAY = date(2026, 9, 23)


@pytest.fixture
def sleeps():
    return []


@pytest.fixture
def fetcher(tmp_path, sleeps):
    return AgendaFetcher(cache_dir=tmp_path, sleep=sleeps.append, delay=(2.0, 3.0))


@respx.mock
def test_downloads_and_caches(fetcher, tmp_path):
    route = respx.get(URL).respond(200, text="<html>ok</html>")
    assert fetcher.get(date(2026, 7, 15), TODAY) == "<html>ok</html>"
    assert (tmp_path / "sem-2026-07-15.html").read_text() == "<html>ok</html>"
    assert "sorties-fr-stremio" in route.calls.last.request.headers["user-agent"]

    # Semaine de plus de 14 jours : relue depuis le cache...
    assert fetcher.get(date(2026, 7, 15), TODAY) == "<html>ok</html>"
    assert route.call_count == 1
    # ... sauf avec refresh_all.
    fetcher.get(date(2026, 7, 15), TODAY, refresh_all=True)
    assert route.call_count == 2


@respx.mock
def test_recent_week_always_refetched(fetcher):
    route = respx.get("https://www.allocine.fr/film/agenda/sem-2026-09-16/").respond(200, text="x")
    fetcher.get(date(2026, 9, 16), TODAY)
    fetcher.get(date(2026, 9, 16), TODAY)
    assert route.call_count == 2


@respx.mock
def test_polite_delay_between_requests(fetcher, sleeps):
    respx.get(URL).respond(200, text="x")
    fetcher.get(date(2026, 7, 15), TODAY, refresh_all=True)
    fetcher.get(date(2026, 7, 15), TODAY, refresh_all=True)
    assert len(sleeps) == 1 and 1.9 < sleeps[0] <= 3.0


@respx.mock
def test_retries_on_5xx_with_backoff(tmp_path, sleeps):
    fetcher = AgendaFetcher(cache_dir=tmp_path, sleep=sleeps.append, delay=(0.0, 0.0))
    route = respx.get(URL).mock(
        side_effect=[httpx.Response(503), httpx.ConnectTimeout("t"), httpx.Response(200, text="ok")]
    )
    assert fetcher.get(date(2026, 7, 15), TODAY) == "ok"
    assert route.call_count == 3
    assert sleeps == [2, 4]


@respx.mock
def test_gives_up_after_three_attempts(fetcher):
    route = respx.get(URL).respond(502)
    with pytest.raises(FetchError, match="3 tentatives"):
        fetcher.get(date(2026, 7, 15), TODAY)
    assert route.call_count == 3


@pytest.mark.parametrize("status", [403, 429])
@respx.mock
def test_no_retry_when_blocked(fetcher, status):
    route = respx.get(URL).respond(status)
    with pytest.raises(FetchBlocked):
        fetcher.get(date(2026, 7, 15), TODAY)
    assert route.call_count == 1
