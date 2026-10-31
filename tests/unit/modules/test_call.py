"""One call of one module from plain JSON: shapes, units and errors."""

import json

import pytest

import gemini as gm
from tests.fixtures.errors import raises

ESP_PARAMETERS = {
    "stage_count": 12,
    "head_coefficients": [1.2e-10, -2.5e-6, 4e-3, 0.2, 5.0, 100.0],
    "power_coefficients": [1.0e-10, -1.0e-6, 3.0e-3, 0.3, 4.0, 200.0],
}
SUCTION = {"fluid_in": {"flow": "150 m3/h", "T": "80 degC", "p": "20 bar"}}


def call(**changes):
    """Evaluate the ESP with the default JSON arguments, changed by keywords."""
    arguments = dict(
        module="ESP", parameters=ESP_PARAMETERS, inlets=SUCTION, controls={"frequency": "50 Hz"}
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

    direct = ESP().set_params("", ESP_PARAMETERS)(
        gm.Stream(flow="150 m3/h", T="80 degC", p="20 bar"), frequency="50 Hz"
    )
    for module in ("ESP", ESP):
        result = call(module=module)
        assert result["outlets"]["fluid_out"]["p"]["value"] == direct.outlets.fluid_out.p
        assert result["outputs"]["head"]["value"] == direct.outputs.head


def test_evaluate_accepts_si_numbers_as_well_as_unit_strings():
    """Plain numbers are SI."""
    inlets = {"fluid_in": {"m_dot": 12.0, "T": 353.15, "p": 2e6}}
    assert call(inlets=inlets)["errors"] == []


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"module": "ESp"}, "unknown_name"),
        ({"module": 3}, "invalid_value"),
        ({"parameters": {}}, "missing_value"),
        ({"parameters": {"stage_count": "many"}}, "invalid_value"),
        ({"inlets": {}}, "invalid_call"),
        ({"controls": {"frequency": "50 bar"}}, "invalid_unit"),
        ({"inlets": {"fluid_in": {"flow": "1 m3/h", "T": "-5 K", "p": "1 bar"}}}, "invalid_call"),
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
    brine = {"density": 1030.0}
    for flow in ("150 m3/h", "41.666666666666664 l/s"):
        inlets = {"fluid_in": {"flow": flow, "T": "80 degC", "p": "20 bar", "fluid": brine}}
        discharge = call(inlets=inlets)["outlets"]["fluid_out"]
        assert discharge["m_dot"]["value"] == pytest.approx(150 / 3600 * 1030)


@pytest.mark.parametrize("flow", ["150 m3/h", "150  m3/s", "40 l/s"])
def test_a_volume_flow_given_as_m_dot_points_to_flow(flow):
    """The code stays that of a wrong inlet; the path, message and suggestion name ``flow``."""
    inlets = {"fluid_in": {"m_dot": flow, "T": "80 degC", "p": "20 bar"}}
    with raises(gm.errors.ValidationError, "invalid_call", match="give it as 'flow'") as caught:
        call(inlets=inlets)
    assert caught.value.path == "fluid_in.m_dot"
    assert caught.value.suggestions == ("flow",)
    recorded = call(inlets=inlets, on_error="record")["errors"][0]
    assert recorded["code"] == "invalid_call" and recorded["suggestions"] == ["flow"]


@pytest.mark.parametrize("flow", ["40 kg/s", "144 t/h", 40.0])
def test_a_mass_flow_stays_a_mass_flow(flow):
    """A number or a mass unit goes through ``m_dot`` unchanged."""
    inlets = {"fluid_in": {"m_dot": flow, "T": "80 degC", "p": "20 bar"}}
    assert call(inlets=inlets)["outlets"]["fluid_out"]["m_dot"]["value"] == pytest.approx(40.0)


def test_another_wrong_unit_of_m_dot_keeps_its_error():
    """Only a volume flow has the suggestion."""
    inlets = {"fluid_in": {"m_dot": "40 bar", "T": "80 degC", "p": "20 bar"}}
    with raises(gm.errors.ValidationError, "invalid_call") as caught:
        call(inlets=inlets)
    assert caught.value.suggestions == ()
