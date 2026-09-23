"""Téléchargement poli des pages agenda, avec cache disque (§8)."""

import logging
import random
import time
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path

import httpx

from . import config

log = logging.getLogger(__name__)


class FetchError(RuntimeError):
    """Échec définitif de récupération d'une page."""


class FetchBlocked(FetchError):
    """403/429 : on s'arrête immédiatement, sans retenter."""


def agenda_url(week: date) -> str:
    return config.AGENDA_URL.format(date=week.isoformat())


class AgendaFetcher:
    def __init__(
        self,
        cache_dir: Path = config.CACHE_DIR / "agenda",
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        delay: tuple[float, float] = config.REQUEST_DELAY_S,
        retries: int = config.HTTP_RETRIES,
    ):
        self.cache_dir = cache_dir
        self.client = client or httpx.Client(
            headers={
                "User-Agent": config.USER_AGENT,
                "Accept-Language": "fr-FR,fr;q=0.9",
            },
            timeout=config.HTTP_TIMEOUT_S,
            follow_redirects=True,
        )
        self.sleep = sleep
        self.delay = delay
        self.retries = retries
        self.network_requests = 0
        self._last_request: float | None = None

    def cache_path(self, week: date) -> Path:
        return self.cache_dir / f"sem-{week.isoformat()}.html"

    def get(self, week: date, today: date, refresh_all: bool = False) -> str:
        """HTML de la page agenda de `week`.

        Les semaines de plus de CACHE_FRESH_AFTER_DAYS jours sont relues depuis le cache,
        sauf si `refresh_all` (pour rafraîchir les compteurs de séances).
        """
        path = self.cache_path(week)
        old_enough = week < today - timedelta(days=config.CACHE_FRESH_AFTER_DAYS)
        if path.exists() and old_enough and not refresh_all:
            log.info("Cache : %s", path.name)
            return path.read_text(encoding="utf-8")
        html = self._download(agenda_url(week))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html, encoding="utf-8")
        return html

    def _throttle(self) -> None:
        if self._last_request is not None:
            wait = random.uniform(*self.delay) - (time.monotonic() - self._last_request)
            if wait > 0:
                self.sleep(wait)
        self._last_request = time.monotonic()

    def _download(self, url: str) -> str:
        for attempt in range(1, self.retries + 1):
            self._throttle()
            self.network_requests += 1
            log.info("GET %s (tentative %d)", url, attempt)
            try:
                resp = self.client.get(url)
            except httpx.TransportError as exc:
                error = f"{type(exc).__name__}: {exc}"
            else:
                if resp.status_code in (403, 429):
                    raise FetchBlocked(f"{url} -> HTTP {resp.status_code}, arrêt sans retente")
                if resp.status_code < 400:
                    return resp.text
                if resp.status_code < 500:
                    raise FetchError(f"{url} -> HTTP {resp.status_code}")
                error = f"HTTP {resp.status_code}"
            if attempt < self.retries:
                backoff = 2**attempt
                log.warning("%s sur %s, nouvel essai dans %d s", error, url, backoff)
                self.sleep(backoff)
        raise FetchError(f"{url} -> {error} après {self.retries} tentatives")
