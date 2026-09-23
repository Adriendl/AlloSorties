"""Repli pour les films sans imdb_id côté TMDB : Wikidata relie l'ID Allociné (P1265)
à l'ID IMDb (P345). Correspondance exacte, une seule requête SPARQL par exécution."""

import logging
import re

import httpx

from . import config

log = logging.getLogger(__name__)

SPARQL_URL = "https://query.wikidata.org/sparql"
_IMDB_RE = re.compile(r"^tt\d+$")


def imdb_ids_for_allocine(
    cfilm_ids: list[str], client: httpx.Client | None = None
) -> dict[str, str]:
    """{cfilm_id: imdb_id} pour les films connus de Wikidata. Erreur réseau -> {} (non bloquant)."""
    ids = [i for i in cfilm_ids if i.isdigit()]
    if not ids:
        return {}
    values = " ".join(f'"{i}"' for i in ids)
    query = f"SELECT ?allo ?imdb WHERE {{ VALUES ?allo {{ {values} }} ?f wdt:P1265 ?allo ; wdt:P345 ?imdb . }}"
    client = client or httpx.Client(timeout=config.HTTP_TIMEOUT_S)
    try:
        resp = client.post(
            SPARQL_URL,
            data={"query": query},
            headers={
                "Accept": "application/sparql-results+json",
                "User-Agent": config.USER_AGENT,
            },
        )
        resp.raise_for_status()
        bindings = resp.json()["results"]["bindings"]
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        log.warning("Wikidata indisponible, repli ignoré : %s", exc)
        return {}
    found: dict[str, str] = {}
    for b in bindings:
        imdb = b["imdb"]["value"]
        if _IMDB_RE.match(imdb):
            found.setdefault(b["allo"]["value"], imdb)
    return found
