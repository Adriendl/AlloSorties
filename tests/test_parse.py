from datetime import date

from sorties_fr.parse import _decode_obfuscated, parse_agenda
from tests.conftest import WEEK


def test_all_cards_parsed(agenda_films):
    assert len(agenda_films) == 22


def test_odyssee(agenda_films):
    f = agenda_films["L'Odyssée"]
    assert f.cfilm_id == "1000013045"
    assert f.release_date == date(2026, 7, 15)
    assert f.seances == 537  # valeur relevée à la capture de la fixture (23/09/2026)
    assert f.title_original == "The Odyssey"
    assert f.genres == ["Action", "Fantastique"]
    assert f.directors == ["Christopher Nolan"]
    assert f.cast == ["Matt Damon", "Tom Holland", "Anne Hathaway"]
    assert f.press_rating == 4.1
    assert f.user_rating == 4.3
    assert f.synopsis.startswith("L’Odyssée est une épopée mythique")
    assert f.poster_url.startswith("https://") and "acsta.net" in f.poster_url
    assert f.agenda_week == WEEK


def test_production_year(agenda_films):
    assert agenda_films["L'Odyssée"].production_year == 2026
    assert agenda_films["La Dernière séance"].production_year == 2021
    assert agenda_films["Playtime"].production_year == 1967


def test_last_viking(agenda_films):
    f = agenda_films["The Last Viking"]
    assert f.seances == 43
    assert f.title_original == "Den Sidste Viking"


def test_lazy_poster_uses_data_src(agenda_films):
    assert agenda_films["Comète"].poster_url.startswith("https://fr.web.img")


def test_missing_seances_defaults_to_zero(agenda_films):
    assert agenda_films["Ça tourne à Séoul ! Cobweb"].seances == 0
    assert agenda_films["Foul King"].seances == 0


def test_title_original_defaults_to_title_fr(agenda_films):
    assert agenda_films["Comète"].title_original == "Comète"
    assert agenda_films["Playtime"].title_original == "Playtime"


def test_decode_obfuscated_link():
    cls = "ACrL2ZACrpbG0vZmljaGVmaWxtX2dlbl9jZmlsbT0xMDAwMDEzMDQ1Lmh0bWw= thumbnail-link"
    assert _decode_obfuscated(cls) == "/film/fichefilm_gen_cfilm=1000013045.html"
    assert _decode_obfuscated("dark-grey-link") is None


CARD = """
<div class="card entity-card">
  <div class="meta"><h2 class="meta-title">{title}</h2>
    <div class="meta-body"><div class="meta-body-item meta-body-info">
      <span class="date">{date}</span></div></div></div>
</div>
"""


def test_card_with_obfuscated_title_link():
    title = (
        '<span class="ACrL2ZACrpbG0vZmljaGVmaWxtX2dlbl9jZmlsbT0xMDAwMDEzMDQ1Lmh0bWw='
        ' meta-title-link">Film X</span>'
    )
    [film] = parse_agenda(CARD.format(title=title, date="1er juillet 2026"), WEEK)
    assert film.cfilm_id == "1000013045"
    assert film.release_date == date(2026, 7, 1)
    assert film.seances == 0
    assert film.poster_url is None


def test_card_without_cfilm_id_is_skipped(caplog):
    films = parse_agenda(CARD.format(title="<span>Sans lien</span>", date=""), WEEK)
    assert films == []
    assert "sans cfilm_id" in caplog.text


def test_card_with_unreadable_date():
    title = '<a class="meta-title-link" href="/film/fichefilm_gen_cfilm=42.html">Y</a>'
    [film] = parse_agenda(CARD.format(title=title, date="Prochainement"), WEEK)
    assert film.release_date is None
