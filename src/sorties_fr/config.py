"""Constantes du projet."""

import os
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Paris")

# Période couverte : mercredis W tels que aujourd'hui - PERIOD_DAYS <= W <= aujourd'hui.
PERIOD_DAYS = 91
# Une date de sortie antérieure à (mercredi de la page - RERELEASE_TOLERANCE_DAYS) = ressortie.
RERELEASE_TOLERANCE_DAYS = 7

AGENDA_URL = "https://www.allocine.fr/film/agenda/sem-{date}/"
# En CI, GitHub fournit GITHUB_REPOSITORY ; en local, surcharger via SORTIES_FR_REPO_URL.
REPO_URL = os.environ.get("SORTIES_FR_REPO_URL") or (
    f"https://github.com/{os.environ['GITHUB_REPOSITORY']}"
    if os.environ.get("GITHUB_REPOSITORY")
    else "https://github.com/<user>/<repo>"
)
USER_AGENT = f"sorties-fr-stremio/1.0 (usage personnel; +{REPO_URL})"

# Politesse HTTP (§8).
REQUEST_DELAY_S = (2.0, 3.0)
HTTP_TIMEOUT_S = 30.0
HTTP_RETRIES = 3
# Au-delà de cet âge, une semaine peut être relue depuis le cache (sauf --refresh-all).
CACHE_FRESH_AFTER_DAYS = 14

ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = ROOT / ".cache"
DATA_DIR = ROOT / "data"
DIST_DIR = ROOT / "dist"
STATE_PATH = DATA_DIR / "state.json"
OVERRIDES_PATH = DATA_DIR / "overrides.json"

# Stremio.
ADDON_ID = "perso.sorties-fr.allocine"
CATALOG_ID = "sorties-fr"
CATALOG_NAME = "Dernières sorties en France"
PAGE_SIZE = 100
