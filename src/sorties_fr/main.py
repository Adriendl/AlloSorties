"""Orchestration du pipeline, rapport final et codes de sortie."""

import argparse
import logging
import sys
from datetime import date

from . import config
from .collect import EmptyPageError, collect
from .fetch import AgendaFetcher, FetchError
from .state import load_overrides, load_state, save_state
from .weeks import agenda_weeks, today_paris

log = logging.getLogger("sorties_fr")

EXIT_OK = 0
EXIT_GUARD = 1
EXIT_FETCH = 2


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="sorties-fr", description=__doc__)
    p.add_argument("--today", type=date.fromisoformat, help="date de référence (AAAA-MM-JJ)")
    p.add_argument(
        "--refresh-all",
        action="store_true",
        help="retélécharger toutes les semaines (rafraîchit les séances ; défaut en CI)",
    )
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    today = args.today or today_paris()
    weeks = agenda_weeks(today)
    overrides = load_overrides(config.OVERRIDES_PATH)
    excluded_ids = {k for k, v in overrides.items() if v.get("exclude")}
    state = load_state(config.STATE_PATH)

    fetcher = AgendaFetcher()
    try:
        collected = collect(fetcher, weeks, today, excluded_ids, args.refresh_all)
    except EmptyPageError as exc:
        log.error("Garde-fou : %s", exc)
        return EXIT_GUARD
    except FetchError as exc:
        log.error("Récupération impossible : %s", exc)
        return EXIT_FETCH

    for film in collected.releases:
        state.observe(film, today)
    pruned = state.prune(today)
    save_state(state, config.STATE_PATH)

    log.info(
        "%d semaines (%s → %s), %d requêtes réseau, %d films parsés, "
        "%d nouveautés, %d ressorties exclues, %d exclusions manuelles, "
        "%d dates inconnues, %d entrées purgées",
        len(weeks), weeks[0], weeks[-1], fetcher.network_requests, collected.parsed,
        len(collected.releases), len(collected.reruns), len(collected.excluded),
        len(collected.date_unknown), pruned,
    )
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
