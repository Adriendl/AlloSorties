from datetime import date

import pytest

from sorties_fr.collect import EmptyPageError, collect
from tests.conftest import WEEK

TODAY = date(2026, 9, 23)


class FakeFetcher:
    def __init__(self, pages: dict[date, str]):
        self.pages = pages

    def get(self, week, today, refresh_all=False):
        return self.pages[week]


def test_collect_fixture(agenda_html):
    result = collect(FakeFetcher({WEEK: agenda_html}), [WEEK], TODAY, excluded_ids={"305835"})
    assert result.parsed == 22
    assert {f.title_fr for f in result.excluded} == {"L'Aventure rêvée"}
    assert len(result.releases) == 8
    assert len(result.reruns) == 13
    assert result.date_unknown == []


def test_film_on_two_weeks_is_a_release(agenda_html):
    # La même page servie une semaine plus tard : L'Odyssée (15/07) reste dans la tolérance.
    later = date(2026, 7, 22)
    result = collect(FakeFetcher({WEEK: agenda_html, later: agenda_html}), [WEEK, later], TODAY)
    odyssee = [f for f in result.releases if f.cfilm_id == "1000013045"]
    assert len(odyssee) == 1 and odyssee[0].agenda_week == WEEK
    assert len(result.releases) == 9


def test_empty_page_raises():
    with pytest.raises(EmptyPageError):
        collect(FakeFetcher({WEEK: "<html></html>"}), [WEEK], TODAY)
