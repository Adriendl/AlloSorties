"""Historique persistant : data/state.json (§6.4) et data/overrides.json (§6.5)."""

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .models import AgendaFilm

STATE_VERSION = 1
# Les films non revus depuis ce délai sont purgés de l'état.
PRUNE_AFTER_DAYS = 180


class TmdbMatch(BaseModel):
    status: str  # "ok" | "failed"
    checked_at: date
    tmdb_id: int | None = None
    imdb_id: str | None = None
    poster_path: str | None = None
    score: float | None = None
    reason: str | None = None


class FilmState(BaseModel):
    title_fr: str
    release_date: date | None = None
    first_seen: date
    last_seen: date
    last_seances: int
    peak_seances: int
    tmdb: TmdbMatch | None = None


class LastRun(BaseModel):
    date: date
    catalog_size: int


class State(BaseModel):
    version: int = STATE_VERSION
    last_run: LastRun | None = None
    films: dict[str, FilmState] = Field(default_factory=dict)

    def observe(self, film: AgendaFilm, today: date) -> FilmState:
        """Met à jour séances courantes et pic observé pour un film vu aujourd'hui."""
        entry = self.films.get(film.cfilm_id)
        if entry is None:
            entry = FilmState(
                title_fr=film.title_fr,
                release_date=film.release_date,
                first_seen=today,
                last_seen=today,
                last_seances=film.seances,
                peak_seances=film.seances,
            )
            self.films[film.cfilm_id] = entry
        else:
            entry.title_fr = film.title_fr
            entry.release_date = film.release_date or entry.release_date
            entry.last_seen = today
            entry.last_seances = film.seances
            entry.peak_seances = max(entry.peak_seances, film.seances)
        return entry

    def prune(self, today: date, after_days: int = PRUNE_AFTER_DAYS) -> int:
        limit = today - timedelta(days=after_days)
        stale = [k for k, v in self.films.items() if v.last_seen < limit]
        for k in stale:
            del self.films[k]
        return len(stale)


def load_state(path: Path) -> State:
    if not path.exists():
        return State()
    return State.model_validate_json(path.read_text(encoding="utf-8"))


def save_state(state: State, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = state.model_dump(mode="json", exclude_none=True)
    data["films"] = dict(sorted(data["films"].items(), key=lambda kv: int(kv[0])))
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def load_overrides(path: Path) -> dict[str, dict[str, Any]]:
    """{cfilm_id: {"imdb_id": "tt…"} | {"exclude": true, "reason": "…"}}."""
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_")}
