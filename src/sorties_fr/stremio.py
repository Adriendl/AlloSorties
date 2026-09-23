"""Génération de l'addon statique : manifest + pages de catalogue (§7)."""

import json
import shutil
from pathlib import Path
from typing import Any

from . import config
from .dates import format_french_date
from .ranking import Ranked
from .tmdb import poster_url


def manifest() -> dict[str, Any]:
    return {
        "id": config.ADDON_ID,
        "version": config.MANIFEST_VERSION,
        "name": "Sorties ciné France",
        "description": (
            "Nouveautés sorties en salles en France sur les 3 derniers mois, "
            "sans ressorties, triées par nombre de séances."
        ),
        "resources": ["catalog"],
        "types": ["movie"],
        "idPrefixes": ["tt"],
        "catalogs": [{"type": "movie", "id": config.CATALOG_ID, "name": config.CATALOG_NAME}],
    }


def _rating(value: float | None) -> str | None:
    return f"{value:.1f}".replace(".", ",") if value is not None else None


def description(item: Ranked) -> str:
    film = item.film
    parts = []
    if film.release_date:
        parts.append(f"Sortie le {format_french_date(film.release_date)}")
    parts.append(f"{film.seances} séance{'s' if film.seances > 1 else ''}")
    if press := _rating(film.press_rating):
        parts.append(f"Presse {press}")
    if users := _rating(film.user_rating):
        parts.append(f"Spectateurs {users}")
    text = " · ".join(parts)
    return f"{text}\n\n{film.synopsis}" if film.synopsis else text


def meta(item: Ranked) -> dict[str, Any]:
    film, match = item.film, item.entry.tmdb
    year = film.release_date.year if film.release_date else film.production_year
    data = {
        "id": match.imdb_id,
        "type": "movie",
        "name": film.title_fr,
        "poster": poster_url(match, film.poster_url),
        "releaseInfo": str(year) if year else None,
        "genres": film.genres,
        "description": description(item),
    }
    return {k: v for k, v in data.items() if v not in (None, [])}


def catalog_pages(metas: list[dict[str, Any]], size: int = config.PAGE_SIZE) -> dict[str, list]:
    """{chemin relatif: metas}. Page vide finale si le total est un multiple de `size`."""
    base = f"catalog/movie/{config.CATALOG_ID}"
    pages = {}
    for skip in range(0, len(metas) + 1, size):
        chunk = metas[skip : skip + size]
        if skip and not chunk and len(metas) % size:
            break
        pages[f"{base}.json" if skip == 0 else f"{base}/skip={skip}.json"] = chunk
    return pages


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def write_addon(items: list[Ranked], dist: Path) -> dict[str, int]:
    """Écrit manifest + catalogue dans `dist` (vidé au préalable). Retourne {page: nb metas}."""
    metas, seen = [], set()
    for item in items:
        m = meta(item)
        if m["id"] not in seen:  # deux fiches Allociné -> même film IMDb : on garde la mieux classée
            seen.add(m["id"])
            metas.append(m)
    if dist.exists():
        shutil.rmtree(dist)
    write_json(dist / "manifest.json", manifest())
    pages = catalog_pages(metas)
    for rel, chunk in pages.items():
        write_json(dist / rel, {"metas": chunk})
    return {rel: len(chunk) for rel, chunk in pages.items()}
