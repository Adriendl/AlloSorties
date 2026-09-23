import httpx
import respx

from sorties_fr.wikidata import SPARQL_URL, imdb_ids_for_allocine


def _binding(allo, imdb):
    return {"allo": {"value": allo}, "imdb": {"value": imdb}}


@respx.mock
def test_maps_allocine_to_imdb():
    route = respx.post(SPARQL_URL).respond(
        json={"results": {"bindings": [
            _binding("1000028944", "tt44687714"),
            _binding("1000028944", "tt99999999"),  # doublon : le premier gagne
            _binding("42", "nm0000001"),  # pas un film
        ]}}
    )
    found = imdb_ids_for_allocine(["1000028944", "42", "abc"])
    assert found == {"1000028944": "tt44687714"}
    body = route.calls.last.request.content.decode()
    assert "P1265" in body and "1000028944" in body and "abc" not in body


def test_nothing_to_query():
    assert imdb_ids_for_allocine([]) == {}


@respx.mock
def test_errors_are_not_fatal():
    respx.post(SPARQL_URL).mock(side_effect=httpx.ConnectTimeout("t"))
    assert imdb_ids_for_allocine(["1"]) == {}
    respx.post(SPARQL_URL).respond(503)
    assert imdb_ids_for_allocine(["1"]) == {}
