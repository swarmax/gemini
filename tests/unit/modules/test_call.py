"""One call of one module from plain JSON: shapes, units and errors."""

import json

import pytest

import gemini as gm
from gemini.units import Quantity
from tests.fixtures import si
from tests.fixtures.errors import raises
from tests.fixtures.esp_design import ESP_MODULE

ESP_PARAMETERS = {
    "stage_count": 12,
    "head_coefficients": [1.2e-10, -2.5e-6, 4e-3, 0.2, 5.0, 100.0],
    "power_coefficients": [1.0e-10, -1.0e-6, 3.0e-3, 0.3, 4.0, 200.0],
} | ESP_MODULE
SUCTION = {
    "fluid_in": {
        "flow": {"value": 150, "unit": "m3/h"},
        "T": {"value": 80, "unit": "degC"},
        "p": {"value": 20, "unit": "bar"},
    }
}


def call(**changes):
    """Evaluate the ESP with the default JSON arguments, changed by keywords."""
    arguments = dict(
        module="ESP",
        parameters=ESP_PARAMETERS,
        inlets=SUCTION,
        controls={"frequency": {"value": 50, "unit": "Hz"}},
    )
    return gm.call(**(arguments | changes))


def test_evaluate_returns_outlets_and_outputs_with_units():
    """Outlet streams and outputs are ``{value, unit}`` in SI and the result is plain JSON."""
    result = call()
    assert result["errors"] == []
    discharge = result["outlets"]["fluid_out"]
    assert set(discharge) == {"m_dot", "T", "p"}
    assert discharge["m_dot"]["unit"] == "kg/s" and discharge["T"]["unit"] == "K"
    assert discharge["p"]["unit"] == "Pa" and discharge["p"]["value"] > 20e5
    assert result["outputs"]["head"]["unit"] == "Pa"
    json.dumps(result, allow_nan=False)


def test_evaluate_equals_a_direct_call_bit_for_bit():
    """The JSON call is the same call: a class, a name and a built module agree."""
    from gemini.modules.pumps import ESP

    direct = si.set_params(ESP(), "", ESP_PARAMETERS)(
        gm.Stream(
            flow={"value": 150, "unit": "m3/h"},
            T={"value": 80, "unit": "degC"},
            p={"value": 20, "unit": "bar"},
        ),
        frequency={"value": 50, "unit": "Hz"},
    )
    for module in ("ESP", ESP):
        result = call(module=module)
        assert result["outlets"]["fluid_out"]["p"]["value"] == direct.outlets.fluid_out.p
        assert result["outputs"]["head"]["value"] == direct.outputs.head


def test_evaluate_accepts_quantities_in_any_unit_of_the_dimension():
    """A ``Quantity`` or its dict converts: the same call in K and in degC gives the same result."""
    kelvin = {"m_dot": Quantity(12.0, "kg/s"), "T": Quantity(353.15, "K"), "p": Quantity(2e6, "Pa")}
    celsius = {"m_dot": Quantity(12.0, "kg/s"), "T": Quantity(80, "degC"), "p": Quantity(20, "bar")}
    first = call(inlets={"fluid_in": kelvin})
    assert first["errors"] == []
    assert call(inlets={"fluid_in": celsius})["outlets"] == first["outlets"]


@pytest.mark.parametrize(
    ("changes", "path", "quantity"),
    [
        ({"parameters": ESP_PARAMETERS | {"setting_depth": 0}}, "setting_depth", "length"),
        ({"controls": {"frequency": 50.0}}, "frequency", "frequency"),
        (
            {"inlets": {"fluid_in": SUCTION["fluid_in"] | {"T": 353.15}}},
            "fluid_in.T",
            "temperature",
        ),
        ({"inlets": {"fluid_in": SUCTION["fluid_in"] | {"p": 2e6}}}, "fluid_in.p", "pressure"),
        (
            {"inlets": {"fluid_in": SUCTION["fluid_in"] | {"flow": 0.04}}},
            "fluid_in.flow",
            "volume flow",
        ),
        (
            {"inlets": {"fluid_in": SUCTION["fluid_in"] | {"m_dot": 12.0}}},
            "fluid_in.m_dot",
            "mass flow",
        ),
    ],
)
def test_a_bare_number_with_a_dimension_is_refused_naming_path_quantity_and_units(
    changes, path, quantity
):
    """Zero too: the message names the path, the quantity and the accepted units."""
    with raises(gm.errors.ValidationError, "invalid_value", match=quantity) as caught:
        call(**changes)
    assert caught.value.path == path and "accepted units" in str(caught.value)
    recorded = call(on_error="record", **changes)["errors"]
    assert [item["code"] for item in recorded] == ["invalid_value"]
    assert recorded[0]["path"] == path


def test_a_dimensionless_parameter_stays_a_plain_number():
    """The stage count and a fraction are numbers without a unit."""
    assert call(parameters=ESP_PARAMETERS | {"motor_efficiency": 0.9})["errors"] == []


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"module": "ESp"}, "unknown_name"),
        ({"module": 3}, "invalid_value"),
        ({"parameters": {}}, "missing_value"),
        ({"parameters": {"stage_count": "many"}}, "invalid_value"),
        ({"inlets": {}}, "invalid_call"),
        ({"controls": {"frequency": {"value": 50, "unit": "bar"}}}, "invalid_unit"),
        (
            {
                "inlets": {
                    "fluid_in": {
                        "flow": {"value": 1, "unit": "m3/h"},
                        "T": {"value": -5, "unit": "K"},
                        "p": {"value": 1, "unit": "bar"},
                    }
                }
            },
            "invalid_call",
        ),
    ],
)
def test_a_recorded_failure_returns_errors_instead_of_raising(changes, code):
    """Every failure is one ``GeminiError.to_dict()`` and the other parts are empty."""
    result = call(on_error="record", **changes)
    assert result["outlets"] == {} and result["outputs"] == {}
    assert [error["code"] for error in result["errors"]] == [code]
    assert set(result["errors"][0]) == {"path", "code", "message", "suggestions"}


def test_a_failing_call_raises_by_default():
    """``gm.evaluate`` has no never-raises rule: the same error reaches the caller."""
    with raises(gm.errors.ValidationError, "unknown_name") as caught:
        call(module="ESp")
    assert caught.value.suggestions == ("ESP",)
    with pytest.raises(gm.errors.ValidationError, match="on_error"):
        call(on_error="ignore")


def test_an_unknown_name_comes_with_suggestions():
    """The registry's close matches reach the error."""
    assert call(module="ESp", on_error="record")["errors"][0]["suggestions"] == ["ESP"]


def test_units_convert_outlets_and_outputs():
    """Stream fields and outputs say the unit used; the numbers are those of SI."""
    plain = call()
    converted = call(units={"pressure": "bar", "temperature": "degC", "power": "kW"})
    outlet, stored = converted["outlets"]["fluid_out"], plain["outlets"]["fluid_out"]
    assert outlet["p"] == {"value": stored["p"]["value"] / 1e5, "unit": "bar"}
    assert outlet["T"]["value"] == pytest.approx(stored["T"]["value"] - 273.15)
    assert outlet["m_dot"] == stored["m_dot"]
    assert converted["outputs"]["power"]["unit"] == "kW"
    assert converted["outputs"]["head"]["unit"] == "bar"


def test_a_wrong_map_of_units_follows_on_error():
    """It is wrong input: raised by default, in ``errors`` when recorded."""
    with raises(gm.errors.ValidationError, "unknown_name"):
        call(units={"powr": "kW"})
    assert call(units={"powr": "kW"}, on_error="record")["errors"][0]["code"] == "unknown_name"


def test_a_volume_flow_goes_in_as_flow_with_the_fluid_of_the_inlet():
    """``flow`` converts with the density of the fluid given for the inlet, at any unit."""
    brine = {"density": {"value": 1030.0, "unit": "kg/m3"}}
    for flow in ({"value": 150, "unit": "m3/h"}, {"value": 41.666666666666664, "unit": "l/s"}):
        inlets = {
            "fluid_in": {
                "flow": flow,
                "T": {"value": 80, "unit": "degC"},
                "p": {"value": 20, "unit": "bar"},
                "fluid": brine,
            }
        }
        discharge = call(inlets=inlets)["outlets"]["fluid_out"]
        assert discharge["m_dot"]["value"] == pytest.approx(150 / 3600 * 1030)


@pytest.mark.parametrize(
    "flow",
    [{"value": 150, "unit": "m3/h"}, {"value": 150, "unit": "m3/s"}, {"value": 40, "unit": "l/s"}],
)
def test_a_volume_flow_given_as_m_dot_points_to_flow(flow):
    """The code stays that of a wrong inlet; the path, message and suggestion name ``flow``."""
    inlets = {
        "fluid_in": {
            "m_dot": flow,
            "T": {"value": 80, "unit": "degC"},
            "p": {"value": 20, "unit": "bar"},
        }
    }
    with raises(gm.errors.ValidationError, "invalid_call", match="give it as 'flow'") as caught:
        call(inlets=inlets)
    assert caught.value.path == "fluid_in.m_dot"
    assert caught.value.suggestions == ("flow",)
    recorded = call(inlets=inlets, on_error="record")["errors"][0]
    assert recorded["code"] == "invalid_call" and recorded["suggestions"] == ["flow"]


@pytest.mark.parametrize("flow", [{"value": 40, "unit": "kg/s"}, {"value": 144, "unit": "t/h"}])
def test_a_mass_flow_stays_a_mass_flow(flow):
    """A mass unit goes through ``m_dot`` unchanged."""
    inlets = {
        "fluid_in": {
            "m_dot": flow,
            "T": {"value": 80, "unit": "degC"},
            "p": {"value": 20, "unit": "bar"},
        }
    }
    assert call(inlets=inlets)["outlets"]["fluid_out"]["m_dot"]["value"] == pytest.approx(40.0)


def test_another_wrong_unit_of_m_dot_keeps_its_error():
    """Only a volume flow has the suggestion."""
    inlets = {
        "fluid_in": {
            "m_dot": {"value": 40, "unit": "bar"},
            "T": {"value": 80, "unit": "degC"},
            "p": {"value": 20, "unit": "bar"},
        }
    }
    with raises(gm.errors.ValidationError, "invalid_call") as caught:
        call(inlets=inlets)
    assert caught.value.suggestions == ()


class _Broken(gm.modules.Module):
    """A module whose forward has a programming error."""

    def __init__(self):
        super().__init__()
        self.fluid_in = gm.modules.Inlet(gm.Stream)
        self.fluid_out = gm.modules.Outlet(gm.Stream)

    def forward(self, inlets):
        """Raise a TypeError that is no input error."""
        raise TypeError("forward bug")


def test_an_error_inside_forward_is_not_reported_as_bad_input():
    """A TypeError of the module's own code stays a TypeError, also under on_error record."""
    for on_error in ("raise", "record"):
        with pytest.raises(TypeError, match="forward bug"):
            gm.call(module=_Broken, parameters={}, inlets=SUCTION, controls={}, on_error=on_error)
