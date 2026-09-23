"""Modèles de données."""

from datetime import date

from pydantic import BaseModel


class AgendaFilm(BaseModel):
    cfilm_id: str
    title_fr: str
    title_original: str
    release_date: date | None = None
    production_year: int | None = None
    genres: list[str] = []
    directors: list[str] = []
    cast: list[str] = []
    press_rating: float | None = None
    user_rating: float | None = None
    synopsis: str | None = None
    seances: int = 0
    poster_url: str | None = None
    agenda_week: date
