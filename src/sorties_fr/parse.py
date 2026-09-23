"""HTML d'une page agenda Allociné -> list[AgendaFilm]."""

import base64
import binascii
import json
import logging
import re
from datetime import date

from selectolax.parser import HTMLParser, Node

from .dates import parse_french_date
from .models import AgendaFilm

log = logging.getLogger(__name__)

_CFILM_RE = re.compile(r"fichefilm_gen_cfilm=(\d+)")
# Autres liens de la carte portant l'identifiant (fiche critiques, séances).
_CFILM_ALT_RE = re.compile(r"/(?:fichefilm|film)-(\d+)/")
_SEANCES_RE = re.compile(r"Séances\s*\((\d+)\)")
_ENTITIES_RE = re.compile(r"var jsEntities\s*=\s*(\{.*?\});\s*$", re.MULTILINE)


def _text(node: Node | None) -> str:
    return " ".join(node.text().split()) if node else ""


def _decode_obfuscated(cls: str) -> str | None:
    """Allociné masque certains liens dans une classe CSS : base64 entrecoupé de « ACr »."""
    token = cls.split()[0] if cls else ""
    if not token.startswith("ACr"):
        return None
    raw = token.replace("ACr", "")
    try:
        return base64.b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return None


def _links(card: Node) -> list[str]:
    """Toutes les URL de la carte, en clair ou obfusquées."""
    urls = []
    for node in card.css("[href], [class^='ACr']"):
        href = node.attributes.get("href")
        if href:
            urls.append(href)
        decoded = _decode_obfuscated(node.attributes.get("class") or "")
        if decoded:
            urls.append(decoded)
    return urls


def _cfilm_id(card: Node) -> str | None:
    links = _links(card)
    for url in links:
        if m := _CFILM_RE.search(url):
            return m.group(1)
    for url in links:
        if m := _CFILM_ALT_RE.search(url):
            return m.group(1)
    return None


def _rating(text: str) -> float | None:
    try:
        return float(text.replace(",", "."))
    except ValueError:
        return None


def _names(item: Node) -> list[str]:
    """Liste de noms d'un bloc « De … » / « Avec … » / genres (hors libellé .light)."""
    return [
        _text(n)
        for n in item.css("a, span")
        if "light" not in (n.attributes.get("class") or "").split()
        and "spacer" not in (n.attributes.get("class") or "").split()
        and "date" not in (n.attributes.get("class") or "").split()
        and _text(n)
    ]


def _production_years(html: str) -> dict[str, int]:
    """Années de production issues du JSON `jsEntities` embarqué (clé = base64 « Movie:<cfilm> »)."""
    m = _ENTITIES_RE.search(html)
    if not m:
        return {}
    try:
        entities = json.loads(m.group(1))
    except json.JSONDecodeError:
        log.warning("jsEntities illisible, années de production ignorées")
        return {}
    years = {}
    for key, entity in entities.items():
        try:
            kind, _, cfilm = base64.b64decode(key).decode().partition(":")
        except (binascii.Error, UnicodeDecodeError):
            continue
        if kind == "Movie" and isinstance(entity.get("productionYear"), int):
            years[cfilm] = entity["productionYear"]
    return years


def parse_card(card: Node, agenda_week: date) -> AgendaFilm | None:
    title_node = card.css_first(".meta-title-link") or card.css_first(".meta-title")
    title_fr = _text(title_node)
    cfilm_id = _cfilm_id(card)
    if not cfilm_id:
        log.warning("Film sans cfilm_id ignoré (semaine %s) : %r", agenda_week, title_fr)
        return None
    if not title_fr:
        log.warning("Film sans titre ignoré (semaine %s) : cfilm=%s", agenda_week, cfilm_id)
        return None

    info = card.css_first(".meta-body-info")
    release_date = parse_french_date(_text(info.css_first(".date"))) if info else None
    genres = _names(info) if info else []

    directors: list[str] = []
    cast: list[str] = []
    title_original: str | None = None
    for item in card.css(".meta-body-item"):
        label = _text(item.css_first(".light"))
        if label == "De":
            directors = _names(item)
        elif label == "Avec":
            cast = _names(item)
        elif label.startswith("Titre original"):
            title_original = _text(item.css_first(".dark-grey")) or None

    press_rating = user_rating = None
    for rating in card.css(".rating-item"):
        label = _text(rating.css_first(".rating-title"))
        note = _rating(_text(rating.css_first(".stareval-note")))
        if label == "Presse":
            press_rating = note
        elif label == "Spectateurs":
            user_rating = note

    seances = 0
    for btn in card.css(".buttons-holder .txt, .buttons-holder .button"):
        if m := _SEANCES_RE.search(_text(btn)):
            seances = int(m.group(1))
            break

    poster_url = None
    if img := card.css_first(".thumbnail-img"):
        for attr in ("data-src", "src"):
            url = img.attributes.get(attr) or ""
            if url.startswith("http"):
                poster_url = url
                break

    return AgendaFilm(
        cfilm_id=cfilm_id,
        title_fr=title_fr,
        title_original=title_original or title_fr,
        release_date=release_date,
        genres=genres,
        directors=directors,
        cast=cast,
        press_rating=press_rating,
        user_rating=user_rating,
        synopsis=_text(card.css_first(".synopsis .content-txt")) or None,
        seances=seances,
        poster_url=poster_url,
        agenda_week=agenda_week,
    )


def parse_agenda(html: str, agenda_week: date) -> list[AgendaFilm]:
    tree = HTMLParser(html)
    years = _production_years(html)
    films: dict[str, AgendaFilm] = {}
    for card in tree.css("div.card.entity-card"):
        film = parse_card(card, agenda_week)
        if film and film.cfilm_id not in films:
            film.production_year = years.get(film.cfilm_id)
            films[film.cfilm_id] = film
    return list(films.values())
