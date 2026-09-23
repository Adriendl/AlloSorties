"""Orchestration du pipeline, rapport final et codes de sortie."""

import argparse
import logging
import os
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

from . import config
from .collect import Collected, EmptyPageError, collect
from .fetch import AgendaFetcher, FetchError
from .ranking import Ranked, rank
from .state import LastRun, State, load_overrides, load_state, save_state
from .stremio import write_addon, write_json
from .tmdb import TmdbAuthError, TmdbClient, TmdbError, link_film, match_from_imdb
from .weeks import agenda_weeks, today_paris
from .wikidata import imdb_ids_for_allocine

log = logging.getLogger("sorties_fr")

EXIT_OK = 0
EXIT_GUARD = 1  # garde-fou déclenché : rien n'est publié
EXIT_FETCH = 2  # Allociné inaccessible ou bloquant
EXIT_CONFIG = 3  # jeton TMDB absent ou refusé

ALLOCINE_FILM_URL = "https://www.allocine.fr/film/fichefilm_gen_cfilm={}.html"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="sorties-fr", description=__doc__)
    p.add_argument("--today", type=date.fromisoformat, help="date de référence (AAAA-MM-JJ)")
    p.add_argument(
        "--refresh-all",
        action="store_true",
        help="retélécharger toutes les semaines (rafraîchit les séances ; défaut en CI)",
    )
    p.add_argument("--dist", type=Path, default=config.DIST_DIR)
    p.add_argument("--state", type=Path, default=config.STATE_PATH)
    p.add_argument("--overrides", type=Path, default=config.OVERRIDES_PATH)
    p.add_argument("--cache", type=Path, default=config.CACHE_DIR / "agenda")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def load_dotenv(path: Path = config.ROOT / ".env") -> None:
    """Confort local : charge `.env` (KEY=valeur) sans écraser l'environnement."""
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.partition("=")
            if sep and not key.strip().startswith("#"):
                os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def check_guards(catalog_size: int, previous: LastRun | None) -> str | None:
    if catalog_size < config.MIN_CATALOG_SIZE:
        return f"catalogue de {catalog_size} films (< {config.MIN_CATALOG_SIZE})"
    if previous and catalog_size < previous.catalog_size * (1 - config.MAX_CATALOG_DROP):
        return (
            f"catalogue de {catalog_size} films contre {previous.catalog_size} "
            f"le {previous.date} (baisse > {config.MAX_CATALOG_DROP:.0%})"
        )
    return None


def build_report(
    today: date,
    collected: Collected,
    state: State,
    network_requests: int,
    tmdb_requests: int,
) -> dict[str, Any]:
    linked, failures = 0, []
    for film in collected.releases:
        match = state.films[film.cfilm_id].tmdb
        if match and match.status == "ok":
            linked += 1
        else:
            failures.append(
                {
                    "cfilm_id": film.cfilm_id,
                    "title_fr": film.title_fr,
                    "title_original": film.title_original,
                    "release_date": film.release_date and film.release_date.isoformat(),
                    "seances": film.seances,
                    "reason": match.reason if match else "non rattaché",
                    "allocine_url": ALLOCINE_FILM_URL.format(film.cfilm_id),
                }
            )
    failures.sort(key=lambda f: -f["seances"])
    return {
        "generated_at": datetime.now(config.TZ).isoformat(timespec="seconds"),
        "today": today.isoformat(),
        "weeks": len(collected.weeks),
        "first_week": collected.weeks[0].isoformat(),
        "last_week": collected.weeks[-1].isoformat(),
        "allocine_requests": network_requests,
        "tmdb_requests": tmdb_requests,
        "films_parsed": collected.parsed,
        "releases": len(collected.releases),
        "reruns_excluded": len(collected.reruns),
        "manual_excluded": [f.title_fr for f in collected.excluded],
        "date_unknown": [f.title_fr for f in collected.date_unknown],
        "tmdb_linked": linked,
        "wikidata_linked": sum(
            1
            for f in collected.releases
            if (m := state.films[f.cfilm_id].tmdb) and m.reason == "wikidata"
        ),
        "tmdb_failed": len(failures),
        "failures": failures,
    }


def log_report(report: dict[str, Any]) -> None:
    log.info(
        "Rapport : %d semaines (%s → %s), %d films parsés, %d nouveautés, "
        "%d ressorties exclues, %d exclusions manuelles, %d dates inconnues, "
        "rattachements %d réussis / %d échoués, catalogue %s films",
        report["weeks"], report["first_week"], report["last_week"], report["films_parsed"],
        report["releases"], report["reruns_excluded"], len(report["manual_excluded"]),
        len(report["date_unknown"]), report["tmdb_linked"], report["tmdb_failed"],
        report.get("catalog_size", "?"),
    )
    if report["failures"]:
        log.info("À corriger via data/overrides.json :")
        for f in report["failures"]:
            log.info(
                "  %s  %s (%s séances) : %s", f["cfilm_id"], f["title_fr"], f["seances"], f["reason"]
            )


def run(args: argparse.Namespace) -> int:
    today = args.today or today_paris()
    weeks = agenda_weeks(today)
    overrides = load_overrides(args.overrides)
    excluded_ids = {k for k, v in overrides.items() if v.get("exclude")}
    state = load_state(args.state)

    try:
        tmdb = TmdbClient(os.environ.get("TMDB_API_KEY", ""))
    except TmdbAuthError as exc:
        log.error("%s", exc)
        return EXIT_CONFIG

    fetcher = AgendaFetcher(cache_dir=args.cache)
    try:
        collected = collect(fetcher, weeks, today, excluded_ids, args.refresh_all)
    except EmptyPageError as exc:
        log.error("Garde-fou : %s", exc)
        return EXIT_GUARD
    except FetchError as exc:
        log.error("Récupération impossible : %s", exc)
        return EXIT_FETCH

    items, unmatched = [], []
    try:
        for film in collected.releases:
            entry = state.observe(film, today)
            try:
                match = link_film(tmdb, film, entry, overrides.get(film.cfilm_id), today)
            except TmdbAuthError:
                raise
            except TmdbError as exc:  # erreur passagère : ni cache ni publication pour ce film
                log.warning("TMDB indisponible pour %s : %s", film.title_fr, exc)
                continue
            (items if match.status == "ok" else unmatched).append(Ranked(film, entry))

        # Repli Wikidata (ID Allociné -> IMDb) pour les films que TMDB n'a pas su rattacher.
        wikidata = imdb_ids_for_allocine([i.film.cfilm_id for i in unmatched])
        for item in unmatched:
            if imdb_id := wikidata.get(item.film.cfilm_id):
                failure = item.entry.tmdb.reason
                item.entry.tmdb = match_from_imdb(tmdb, imdb_id, today, "wikidata")
                log.info("Wikidata : %s -> %s (TMDB : %s)", item.film.title_fr, imdb_id, failure)
                items.append(item)
    except TmdbAuthError as exc:
        log.error("%s", exc)
        return EXIT_CONFIG
    state.prune(today)

    report = build_report(today, collected, state, fetcher.network_requests, tmdb.requests)
    ranked = rank(items)
    error = check_guards(len(ranked), state.last_run)
    report["catalog_size"] = len(ranked)
    if error:
        report["guard_error"] = error
        log_report(report)
        log.error("Garde-fou : %s. Rien n'est publié.", error)
        save_state(state, args.state)
        write_json(args.dist / "report.json", report)
        return EXIT_GUARD

    report["pages"] = write_addon(ranked, args.dist)
    report["catalog_size"] = sum(report["pages"].values())
    write_json(args.dist / "report.json", report)
    state.last_run = LastRun(date=today, catalog_size=report["catalog_size"])
    save_state(state, args.state)
    log_report(report)
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    load_dotenv()
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
