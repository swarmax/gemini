"""The cost catalogue in ``docs/cost-sources`` parses, and its 2015 values hold."""

import csv
import json

from tests.fixtures import ROOT

FOLDER = ROOT / "docs/cost-sources"
TOLERANCE = 0.005
"""Largest relative difference [-] allowed between a stored and a recomputed 2015 value."""


def _rows():
    """Return the rows of the catalogue."""
    with open(FOLDER / "sources.csv", newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def _hicp():
    """Return the euro-area index by year, 2015 = 100, from the copied Eurostat file."""
    dataset = json.loads((FOLDER / "data/eurostat_prc_hicp_aind_EA_CP00.json").read_text())
    years = dataset["dimension"]["time"]["category"]["index"]
    return {int(year): dataset["value"][str(index)] for year, index in years.items()}


def test_ids_are_unique():
    """Every row parses with an ``id``, and a project can cite each one."""
    ids = [row["id"] for row in _rows()]
    assert all(ids)
    assert len(ids) == len(set(ids))


def test_every_row_with_a_source_has_url_and_quote():
    """Only a placeholder may stand without a url and a quote."""
    sourced = [row for row in _rows() if row["status"] != "placeholder"]
    assert sourced
    assert [row["id"] for row in sourced if not (row["url"] and row["quote"])] == []


def test_value_2015_matches_the_hicp_conversion():
    """``value_2015`` is the value deflated with the index, the latest index for a later year."""
    hicp = _hicp()
    converted = [row for row in _rows() if row["value_2015"]]
    assert converted
    for row in converted:
        index = hicp[min(int(row["price_year"]), max(hicp))]
        expected = float(row["value"]) * 100 / index
        assert abs(float(row["value_2015"]) / expected - 1) <= TOLERANCE, row["id"]
