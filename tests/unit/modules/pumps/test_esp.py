"""ESP reference checks, fitting and drift monitoring (TNO 2022 R11363)."""

import numpy as np
import pytest

import gemini as gm
from gemini import analysis, units
from gemini.analysis import wells
from gemini.modules.pumps import ESP
from gemini.ops import kernels
from gemini.types.flows import Stream
from tests.fixtures.equivalence import assert_health_matches, assert_module_matches

ESP_PARAMS = {
    "pump_type": "HC27000",
    "stage_count": 12,
    "head_coefficients": [
        83.08389282,
        -0.000460444,
        -1.19e-07,
        1.69e-11,
        -6.36e-16,
        6.69e-21,
    ],
    "power_coefficients": [
        10.02089977,
        -0.000160233,
        6.52e-08,
        -2.13e-12,
        1.71e-17,
        1.38e-23,
    ],
}


def test_original_nonzero_power_reference():
    """Preserve the original 200 m3/h, 60 Hz reference beyond the zero-power example."""
    output = (
        ESP()
        .set_params("", ESP_PARAMS)(
            frequency=60,
            fluid_in=Stream(m_dot=units.m3h_to_m3s(200) * 1000, T=300, p=100000),
        )
        .outputs
    )
    assert units.pa_to_bar(output.head) == pytest.approx(23.37, abs=0.01)
    assert output.power == pytest.approx(183890, abs=10)
    assert output.efficiency == pytest.approx(0.7053, abs=0.0001)


def test_fit_recovers_curve_and_health_threshold():
    """Synthetic curve fitting predicts withheld operating points and flags measured drift."""
    pump = ESP().set_params("", ESP_PARAMS)
    flows = np.linspace(0.01, 0.06, 20)
    freq = np.linspace(40, 60, 20)
    heads = [pump.head_function(q, f) for q, f in zip(flows, freq)]
    fitted = analysis.fit_head_coefficients(flows, freq, heads, 12)["value"]
    other = ESP().set_params("", dict(ESP_PARAMS, head_coefficients=fitted))
    assert other.head_function(0.037, 53) == pytest.approx(pump.head_function(0.037, 53), rel=1e-9)
    result = pump(frequency=60, fluid_in=Stream(m_dot=40, T=300, p=1e5))
    power = result.outputs.power
    assert not pump.health(result, {"power": power}).alarm
    assert pump.health(result, {"power": power * 1.11}).alarm
    correction = analysis.fit_head_correction([1, 2, 3], [3, 5, 7])
    assert correction["slope"]["value"] == pytest.approx(2)
    assert correction["offset"]["value"] == pytest.approx(1)
    assert len(wells._head_curve(pump, 50)) == wells.PUMP_CURVE_POINTS


def test_the_esp_alone_asks_for_a_plain_scope_under_float32_precision():
    """Float32 keeps Python floats next to the float32 coefficients; a stopped pump still runs."""
    esp = ESP().set_params("", ESP_PARAMS)
    stopped = dict(frequency=60, fluid_in=Stream(m_dot=0.0, T=300, p=100000))
    assert esp._scalar_mode() == kernels.WRAP
    reference = esp(**stopped).outputs.efficiency
    with gm.runtime.settings(precision="float32"):
        assert esp._scalar_mode() == kernels.PLAIN
        assert esp(**stopped).outputs.efficiency == reference == 0.0
    assert kernels.scope_mode() is None


def _health_rows(pump, flows_kg_s):
    return [pump(frequency=60, fluid_in=Stream(m_dot=m_dot, T=300, p=1e5)) for m_dot in flows_kg_s]


def test_health_on_arrays_equals_one_call_per_row():
    """Worst key, drift, window and message of every row match, with and without drifts."""
    pump = ESP().set_params("", {**ESP_PARAMS, "maximum_flow": 0.05})
    results = _health_rows(pump, [20.0, 40.0, 40.0, 60.0, 30.0])
    outputs = [result.outputs for result in results]
    scales = [(1.0, 1.3), (1.2, 0.5), (1.0, 1.0), (0.8, 1.5), (1.05, 0.99)]
    measured = [
        {"power": out.power * a, "head": out.head * b, "discharge_pressure": out.discharge_pressure}
        for out, (a, b) in zip(outputs, scales)
    ]
    assert_health_matches(pump, results, measured)
    assert_health_matches(pump, results, [{"power": row["power"]} for row in measured])
    assert_health_matches(pump, results, [{} for _ in measured])


def test_traced_call_matches_one_call_per_row_on_every_backend():
    """Low, nominal and high flow, a trickle and a low frequency, on every backend."""
    rows = [
        dict(fluid_in=Stream(m_dot=m_dot, T=300, p=1e5), frequency=frequency)
        for m_dot, frequency in ((5, 60), (60, 60), (200, 50), (500, 60), (1e-3, 60), (60, 35))
    ]
    assert_module_matches(ESP().set_params("", ESP_PARAMS), rows)


def _design():
    """Return an ESP with the values of the example doublet."""
    design = gm.plants.example("Doublet").esp
    values = {name: parameter.value for name, parameter in design.named_parameters()}
    return ESP().set_params("", values)


def test_keyword_mapping_and_positional_calls_agree():
    """Every way to pass the inlet gives one head, and a persisted command is that of the call."""
    esp, stream = _design(), Stream(
        flow={"value": 150, "unit": "m3/h"},
        T={"value": 80, "unit": "degC"},
        p={"value": 20, "unit": "bar"},
    )
    head = esp(fluid_in=stream, frequency={"value": 50, "unit": "Hz"}).outputs.head
    assert head == esp({"fluid_in": stream}, frequency={"value": 50, "unit": "Hz"}).outputs.head
    assert head == esp(stream, frequency={"value": 50, "unit": "Hz"}).outputs.head
    esp.frequency = 50.0
    assert head == esp(fluid_in=stream).outputs.head


def test_no_outputs_keeps_the_outlet_of_a_full_call():
    """Skipping the outputs leaves the outlet stream as it was."""
    esp, stream = _design(), Stream(
        flow={"value": 150, "unit": "m3/h"},
        T={"value": 80, "unit": "degC"},
        p={"value": 20, "unit": "bar"},
    )
    full = esp(fluid_in=stream, frequency={"value": 50, "unit": "Hz"})
    with gm.modules.no_outputs():
        fast = esp(fluid_in=stream, frequency={"value": 50, "unit": "Hz"})
    assert dict(fast.outputs) == {}
    assert fast.outlets.fluid_out == full.outlets.fluid_out


def test_a_new_esp_names_what_it_misses():
    """A new pump is not initialized and lists its parameters until they are assigned."""
    esp = ESP()
    assert not esp.is_initialized and "stage_count" in esp.missing_parameters()
    esp.stage_count = 120
    assert esp.stage_count == 120 and "stage_count" not in esp.missing_parameters()
