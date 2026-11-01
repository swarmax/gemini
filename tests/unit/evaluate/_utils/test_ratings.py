"""The rating of each class of equipment and the use the run made of it."""

import gemini as gm
from gemini.evaluate._utils.ratings import RATINGS, rating_of
from tests.fixtures.result_tables import make_results


def module(kind, params):
    """Return one module of class ``kind`` with ``params``."""
    plant = gm.Plant("One")
    return plant.add(kind, name="unit", params=params)


def test_a_boiler_is_rated_by_its_capacity_in_watts():
    """The rating names the parameter and the unit."""
    rating = rating_of(module("Boiler", {"capacity": 1e6}))
    assert (rating.parameter, rating.unit) == ("capacity", "W")


def test_a_heat_pump_is_read_on_the_side_of_its_mode():
    """Heating mode reads the sink circuit, cooling mode the source circuit."""
    heating = rating_of(module("HeatPump", {"mode": "heating", "capacity": 1e6}))
    cooling = rating_of(module("HeatPump", {"mode": "cooling", "capacity": 1e6}))
    run = make_results(
        {
            "unit": {
                "sink_in.enthalpy_flow": [10.0],
                "sink_out.enthalpy_flow": [13.0],
                "source_in.enthalpy_flow": [20.0],
                "source_out.enthalpy_flow": [18.0],
            }
        }
    )
    frame = run.to_frame()
    assert list(heating.use(frame, "unit")) == [3.0] and list(cooling.use(frame, "unit")) == [2.0]


def test_a_use_the_run_does_not_hold_is_none():
    """No column, no series."""
    frame = make_results({"other": {"x": [1.0]}}).to_frame()
    assert rating_of(module("Boiler", {"capacity": 1e6})).use(frame, "unit") is None


def test_a_module_without_a_rating_has_none():
    """A degasser is a fixed item."""
    assert rating_of(module("Degasser", {})) is None
    assert all(rating.unit for rating in RATINGS.values())
