"""``gm.case.Demand`` and ``Service``: the demand file of a case."""

import pytest

import gemini as gm
from gemini.units import Quantity
from tests.fixtures.errors import raises


def demand(folder, **override):
    """Return a demand of the sample file, heating and cooling."""
    services = {
        "heating": gm.case.Service(
            column="heat_MW", unit="MW", supply_temperature=Quantity(100, "degC")
        ),
        "cooling": gm.case.Service(column="cold_MW", unit="MW"),
    }
    return gm.case.Demand(
        file=str(folder / "demand.csv"), time_column="date", **(services | override)
    )


def test_the_file_is_read_into_a_frame_of_watts(folder):
    """MW become W, the services then state W and the file keeps its name only."""
    result = demand(folder)
    assert result.frame["heating_demand"].iloc[0] == 1e6
    assert list(result.frame) == ["heating_demand", "cooling_demand"]
    assert result.heating.unit == "W" and result.file == "demand.csv"
    assert result.heating.supply_temperature == pytest.approx(373.15)
    assert (
        result.frame.index.name == "time" and result.frame.attrs["units"]["heating_demand"] == "W"
    )


def test_one_service_is_enough(folder):
    """Heating only is a demand."""
    assert list(demand(folder, cooling=None).frame) == ["heating_demand"]


def test_a_demand_needs_a_service(folder):
    """Neither heating nor cooling is ``missing_value``."""
    with raises(gm.errors.ValidationError, "missing_value"):
        demand(folder, heating=None, cooling=None)


def test_a_missing_file_is_invalid_format(folder):
    """The file is read when the demand is built."""
    with raises(gm.errors.ValidationError, "invalid_format") as caught:
        gm.case.Demand(
            file=str(folder / "none.csv"), heating=gm.case.Service(column="x", unit="MW")
        )
    assert "demand.file" in str(caught.value)


def test_a_missing_column_is_named(folder):
    """The column must be in the file."""
    with raises(gm.errors.ValidationError, "missing_column"):
        demand(folder, heating=gm.case.Service(column="other", unit="MW"))


def test_a_unit_that_is_no_power_is_invalid_unit():
    """A service unit is a power."""
    with raises(gm.errors.ValidationError, "invalid_unit"):
        gm.case.Service(column="x", unit="m")


def test_to_dict_leaves_the_frame_out(folder):
    """The dict holds the file name and the services, not the numbers."""
    data = demand(folder).to_dict()
    assert set(data) == {"file", "time_column", "heating", "cooling"}
    assert data["heating"]["unit"] == "W"
