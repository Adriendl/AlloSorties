"""Rattachement d'un film Allociné à un ID IMDb via l'API TMDB (§6.5)."""

import logging
import re
import time
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import httpx
from rapidfuzz import fuzz

from . import config
from .models import AgendaFilm
from .state import FilmState, TmdbMatch

log = logging.getLogger(__name__)

API_URL = "https://api.themoviedb.org/3"
POSTER_URL = "https://image.tmdb.org/t/p/w500{path}"

# Seuil d'acceptation d'un candidat (calibré sur les données réelles, cf. README).
THRESHOLD = 0.85
# Candidats dont on charge la fiche (réalisateur + imdb_id), s'ils dépassent MIN_DETAIL_SCORE.
MAX_DETAILED = 3
MIN_DETAIL_SCORE = 0.6
DIRECTOR_BONUS = 0.1
DIRECTOR_MALUS = 0.2
# Correspondance sur le titre raccourci : acceptée seulement si le réalisateur confirme.
SHORT_TITLE_MALUS = 0.2
# Un échec n'est retenté qu'après ce délai.
RETRY_FAILED_AFTER_DAYS = 7

_ARTICLES = {
    "le", "la", "les", "l", "un", "une", "des",
    "the", "a", "an",
    "der", "die", "das", "el", "los", "las", "il", "lo", "gli",
}


class TmdbError(RuntimeError):
    pass


class TmdbAuthError(TmdbError):
    """Jeton absent ou refusé : erreur de configuration, fatale."""


def normalize(title: str) -> str:
    """Minuscules, sans accents ni ponctuation, sans article initial."""
    text = title.lower().replace("œ", "oe").replace("æ", "ae").replace("&", " and ")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    words = re.sub(r"[^a-z0-9]+", " ", text).split()
    if len(words) > 1 and words[0] in _ARTICLES:
        words = words[1:]
    return " ".join(words)


def _similarity(ours: set[str], cand: dict[str, Any]) -> float:
    theirs = {normalize(cand.get("original_title") or ""), normalize(cand.get("title") or "")}
    return max((fuzz.ratio(a, b) / 100 for a in ours - {""} for b in theirs - {""}), default=0.0)


def title_similarity(film: AgendaFilm, cand: dict[str, Any]) -> float:
    """Meilleure similarité (0..1) entre nos titres (original, FR) et ceux du candidat.

    Les titres raccourcis (avant « : », « - »…) comptent aussi, avec un malus.
    """
    full = _similarity({normalize(film.title_original), normalize(film.title_fr)}, cand)
    shorts = {normalize(t) for t in map(short_title, (film.title_original, film.title_fr)) if t}
    return max(full, _similarity(shorts, cand) - SHORT_TITLE_MALUS if shorts else 0.0)


_SEPARATOR_RE = re.compile(r"\s+[-–—]\s+|\s*:\s+|,\s+")


def short_title(title: str) -> str | None:
    """« La Bataille de Gaulle - Partie 2 : J'écris ton nom » -> « La Bataille de Gaulle »."""
    head = _SEPARATOR_RE.split(title, maxsplit=1)[0].strip()
    return head if head != title.strip() and len(normalize(head)) >= 3 else None


def _year(value: str | None) -> int | None:
    return int(value[:4]) if value and value[:4].isdigit() else None


def year_penalty(film: AgendaFilm, cand: dict[str, Any]) -> float:
    """0 ou 1 an d'écart toléré (festivals) ; compare à la sortie FR et à l'année de production."""
    ours = {y for y in (film.release_date and film.release_date.year, film.production_year) if y}
    theirs = _year(cand.get("release_date"))
    if not ours or theirs is None:
        return 0.1
    gap = min(abs(y - theirs) for y in ours)
    return 0.0 if gap <= 1 else 0.1 if gap == 2 else 0.3


def director_match(film: AgendaFilm, details: dict[str, Any]) -> bool | None:
    """True/False si les deux côtés connaissent le réalisateur, None sinon."""
    crew = (details.get("credits") or {}).get("crew") or []
    # Un nom en écriture non latine se normalise en "" : on le traite comme inconnu.
    theirs = [n for c in crew if c.get("job") == "Director" if (n := normalize(c["name"]))]
    ours = [n for d in film.directors if (n := normalize(d))]
    if not theirs or not ours:
        return None
    return any(_same_person(a, b) for a in ours for b in theirs)


def _same_person(a: str, b: str) -> bool:
    """Tolère 2e prénom, 2e nom, diminutif (« Tony »/« Anthony ») : nom de famille identique."""
    return a.split()[-1] == b.split()[-1] or fuzz.token_set_ratio(a, b) >= 90


@dataclass
class Candidate:
    data: dict[str, Any]
    base: float
    score: float = 0.0
    details: dict[str, Any] | None = None
    notes: list[str] = field(default_factory=list)

    def label(self) -> str:
        return f"{self.data.get('title')} ({self.data.get('release_date', '')[:4]}) #{self.data['id']}"


class TmdbClient:
    def __init__(
        self,
        token: str,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        min_interval: float = 0.25,
        retries: int = 3,
    ):
        if not token:
            raise TmdbAuthError("TMDB_API_KEY manquant")
        # Jeton v4 (JWT « eyJ… ») en en-tête, clé v3 en paramètre.
        bearer = token.startswith("eyJ") or len(token) > 40
        self.client = client or httpx.Client(
            base_url=API_URL,
            timeout=config.HTTP_TIMEOUT_S,
            headers={"User-Agent": config.USER_AGENT}
            | ({"Authorization": f"Bearer {token}"} if bearer else {}),
            params={} if bearer else {"api_key": token},
        )
        self.sleep = sleep
        self.min_interval = min_interval
        self.retries = retries
        self.requests = 0
        self._last: float | None = None

    def get(self, path: str, **params: Any) -> dict[str, Any]:
        for attempt in range(1, self.retries + 1):
            if self._last is not None:
                wait = self.min_interval - (time.monotonic() - self._last)
                if wait > 0:
                    self.sleep(wait)
            self._last = time.monotonic()
            self.requests += 1
            try:
                resp = self.client.get(path, params=params)
            except httpx.TransportError as exc:
                error, backoff = f"{type(exc).__name__}: {exc}", 2**attempt
            else:
                if resp.status_code in (401, 403):
                    raise TmdbAuthError(f"TMDB {path} -> HTTP {resp.status_code} (jeton refusé)")
                if resp.status_code == 429 or resp.status_code >= 500:
                    error = f"HTTP {resp.status_code}"
                    backoff = float(resp.headers.get("Retry-After") or 2**attempt)
                elif resp.status_code >= 400:
                    raise TmdbError(f"TMDB {path} -> HTTP {resp.status_code}")
                else:
                    return resp.json()
            if attempt < self.retries:
                log.warning("TMDB %s : %s, nouvel essai dans %s s", path, error, backoff)
                self.sleep(backoff)
        raise TmdbError(f"TMDB {path} -> {error} après {self.retries} tentatives")

    def search(self, query: str, year: int | None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"query": query, "language": "fr-FR", "include_adult": "false"}
        if year:
            params["year"] = year
        return self.get("/search/movie", **params).get("results") or []

    def details(self, tmdb_id: int) -> dict[str, Any]:
        return self.get(
            f"/movie/{tmdb_id}", language="fr-FR", append_to_response="external_ids,credits"
        )

    def find_imdb(self, imdb_id: str) -> dict[str, Any] | None:
        results = self.get(f"/find/{imdb_id}", external_source="imdb_id", language="fr-FR")
        movies = results.get("movie_results") or []
        return movies[0] if movies else None


def _queries(film: AgendaFilm) -> list[tuple[str, int | None]]:
    """Titre original avec puis sans année, puis titre français (§6.5 étape 3),
    puis leurs versions raccourcies en dernier recours."""
    year = film.release_date.year if film.release_date else None
    titles = [film.title_original, film.title_fr]
    titles += [t for t in map(short_title, titles) if t]
    queries = []
    for title in titles:
        for y in (year, None):
            if (title, y) not in queries:
                queries.append((title, y))
    return queries


def match_film(client: TmdbClient, film: AgendaFilm, today: date) -> TmdbMatch:
    """Recherche, score et récupère l'imdb_id du meilleur candidat."""
    candidates: dict[int, Candidate] = {}
    for query, year in _queries(film):
        for data in client.search(query, year):
            if data["id"] not in candidates:
                base = title_similarity(film, data) - year_penalty(film, data)
                candidates[data["id"]] = Candidate(data=data, base=base)
        if any(c.base >= THRESHOLD for c in candidates.values()):
            break

    if not candidates:
        return TmdbMatch(status="failed", checked_at=today, reason="aucun résultat TMDB")

    ranked = sorted(
        candidates.values(), key=lambda c: (c.base, c.data.get("popularity") or 0), reverse=True
    )
    for cand in ranked:
        cand.score = cand.base
    for cand in [c for c in ranked if c.base >= MIN_DETAIL_SCORE][:MAX_DETAILED]:
        cand.details = client.details(cand.data["id"])
        same = director_match(film, cand.details)
        if same is True:
            cand.score += DIRECTOR_BONUS
        elif same is False:
            cand.score -= DIRECTOR_MALUS
            cand.notes.append("réalisateur différent")

    ranked.sort(key=lambda c: (c.score, c.data.get("popularity") or 0), reverse=True)
    for cand in ranked:
        if cand.score < THRESHOLD:
            break
        if cand.details is None:
            cand.details = client.details(cand.data["id"])
        imdb_id = (cand.details.get("external_ids") or {}).get("imdb_id") or cand.details.get(
            "imdb_id"
        )
        if imdb_id:
            return TmdbMatch(
                status="ok",
                checked_at=today,
                tmdb_id=cand.data["id"],
                imdb_id=imdb_id,
                poster_path=cand.details.get("poster_path") or cand.data.get("poster_path"),
                score=round(min(cand.score, 1.0), 3),
            )
        cand.notes.append("pas d'imdb_id")

    best = ranked[0]
    notes = f", {', '.join(best.notes)}" if best.notes else ""
    return TmdbMatch(
        status="failed",
        checked_at=today,
        tmdb_id=best.data["id"],
        score=round(best.score, 3),
        reason=f"meilleur candidat {best.label()} score {best.score:.2f}{notes}",
    )


def match_from_imdb(client: TmdbClient, imdb_id: str, today: date, source: str) -> TmdbMatch:
    """Rattachement imposé (override, Wikidata) : TMDB ne sert qu'à trouver l'affiche."""
    found = client.find_imdb(imdb_id)
    return TmdbMatch(
        status="ok",
        checked_at=today,
        imdb_id=imdb_id,
        tmdb_id=found and found.get("id"),
        poster_path=found and found.get("poster_path"),
        reason=source,
    )


def link_film(
    client: TmdbClient,
    film: AgendaFilm,
    entry: FilmState,
    override: dict[str, Any] | None,
    today: date,
) -> TmdbMatch:
    """Applique overrides puis cache avant d'interroger TMDB ; met à jour `entry.tmdb`."""
    cached = entry.tmdb
    if override and override.get("imdb_id"):
        imdb_id = override["imdb_id"]
        if not (cached and cached.status == "ok" and cached.imdb_id == imdb_id):
            cached = match_from_imdb(client, imdb_id, today, "override")
    elif cached and cached.status == "ok" and cached.reason != "override":
        pass
    elif (
        cached
        and cached.status == "failed"
        and cached.checked_at > today - timedelta(days=RETRY_FAILED_AFTER_DAYS)
    ):
        pass
    else:
        cached = match_film(client, film, today)
    entry.tmdb = cached
    return cached


def poster_url(match: TmdbMatch | None, fallback: str | None) -> str | None:
    if match and match.poster_path:
        return POSTER_URL.format(path=match.poster_path)
    return fallback
