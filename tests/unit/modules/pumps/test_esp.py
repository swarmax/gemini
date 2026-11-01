"""ESP reference checks, fitting and drift monitoring (TNO 2022 R11363)."""

import numpy as np
import pytest

import gemini as gm
from gemini import analysis, units
from gemini.analysis import wells
from gemini.errors import PhysicsError
from gemini.modules.pumps import ESP
from gemini.ops import kernels
from gemini.types.flows import Stream
from tests.fixtures import si
from tests.fixtures.equivalence import assert_health_matches, assert_module_matches
from tests.fixtures.errors import raises
from tests.fixtures.esp_design import ESP_MODULE
from tests.fixtures.sample_cases import example_plant

ESP_PARAMS = ESP_MODULE | {
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
    output = si.set_params(ESP(), "", ESP_PARAMS)(
        frequency=60,
        fluid_in=Stream(
            m_dot=gm.units.Quantity(units.m3h_to_m3s(200) * 1000, "kg/s"),
            T=gm.units.Quantity(300, "K"),
            p=gm.units.Quantity(100000, "Pa"),
        ),
    ).outputs
    assert units.pa_to_bar(output.head) == pytest.approx(23.37, abs=0.01)
    assert output.power == pytest.approx(183890, abs=10)
    assert output.efficiency == pytest.approx(0.7053, abs=0.0001)


def test_fit_recovers_curve_and_health_threshold():
    """Synthetic curve fitting predicts withheld operating points and flags measured drift."""
    pump = si.set_params(ESP(), "", ESP_PARAMS)
    flows = np.linspace(0.01, 0.06, 20)
    freq = np.linspace(40, 60, 20)
    heads = [pump.head_function(q, f) for q, f in zip(flows, freq)]
    fitted = analysis.fit_head_coefficients(flows, freq, heads, 12)["value"]
    other = si.set_params(ESP(), "", dict(ESP_PARAMS, head_coefficients=fitted))
    assert other.head_function(0.037, 53) == pytest.approx(pump.head_function(0.037, 53), rel=1e-9)
    result = pump(
        frequency=60,
        fluid_in=Stream(
            m_dot=gm.units.Quantity(40, "kg/s"),
            T=gm.units.Quantity(300, "K"),
            p=gm.units.Quantity(1e5, "Pa"),
        ),
    )
    power = result.outputs.power
    assert not pump.health(result, {"power": power}).alarm
    assert pump.health(result, {"power": power * 1.11}).alarm
    correction = analysis.fit_head_correction([1, 2, 3], [3, 5, 7])
    assert correction["slope"]["value"] == pytest.approx(2)
    assert correction["offset"]["value"] == pytest.approx(1)
    assert len(wells._head_curve(pump, 50)) == wells.PUMP_CURVE_POINTS


def test_the_esp_alone_asks_for_a_plain_scope_under_float32_precision():
    """Float32 keeps Python floats next to the float32 coefficients; a stopped pump still runs."""
    esp = si.set_params(ESP(), "", ESP_PARAMS)
    stopped = dict(
        frequency=60,
        fluid_in=Stream(
            m_dot=gm.units.Quantity(0.0, "kg/s"),
            T=gm.units.Quantity(300, "K"),
            p=gm.units.Quantity(100000, "Pa"),
        ),
    )
    assert esp._scalar_mode() == kernels.WRAP
    reference = esp(**stopped).outputs.efficiency
    with gm.runtime.settings(precision="float32"):
        assert esp._scalar_mode() == kernels.PLAIN
        assert esp(**stopped).outputs.efficiency == reference == 0.0
    assert kernels.scope_mode() is None


def _health_rows(pump, flows_kg_s):
    return [
        pump(
            frequency=60,
            fluid_in=Stream(
                m_dot=gm.units.Quantity(m_dot, "kg/s"),
                T=gm.units.Quantity(300, "K"),
                p=gm.units.Quantity(1e5, "Pa"),
            ),
        )
        for m_dot in flows_kg_s
    ]


def test_health_on_arrays_equals_one_call_per_row():
    """Worst key, drift, window and message of every row match, with and without drifts."""
    pump = si.set_params(
        ESP(),
        "",
        {
            **ESP_PARAMS,
            "minimum_flow": gm.units.Quantity(0.03, "m3/s"),
            "maximum_flow": gm.units.Quantity(0.07, "m3/s"),
        },
    )
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
        dict(
            fluid_in=Stream(
                m_dot=gm.units.Quantity(m_dot, "kg/s"),
                T=gm.units.Quantity(300, "K"),
                p=gm.units.Quantity(1e5, "Pa"),
            ),
            frequency=frequency,
        )
        for m_dot, frequency in ((5, 60), (60, 60), (200, 50), (60, 60), (1e-3, 60), (60, 35))
    ]
    assert_module_matches(si.set_params(ESP(), "", ESP_PARAMS), rows)


def _design():
    """Return an ESP with the values of the example doublet."""
    design = example_plant("Doublet").esp
    values = {name: parameter.value for name, parameter in design.named_parameters()}
    return si.set_params(ESP(), "", values)


def test_keyword_mapping_and_positional_calls_agree():
    """Every way to pass the inlet gives one head, and a persisted command is that of the call."""
    esp, stream = _design(), Stream(
        flow={"value": 140, "unit": "m3/h"},
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
        flow={"value": 140, "unit": "m3/h"},
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
    missing = [item["path"] for item in esp.missing_parameters()]
    assert not esp.is_initialized and "stage_count" in missing
    esp.stage_count = 120
    missing = [item["path"] for item in esp.missing_parameters()]
    assert esp.stage_count == 120 and "stage_count" not in missing


def test_a_flow_where_the_curves_extrapolate_is_a_failed_row_with_the_code():
    """A head or power below zero is the polynomial outside its range: ``out_of_range``."""
    pump = si.set_params(ESP(), "", ESP_PARAMS)
    inside = pump(
        frequency=60,
        fluid_in=Stream(
            m_dot=gm.units.Quantity(55.0, "kg/s"),
            T=gm.units.Quantity(300, "K"),
            p=gm.units.Quantity(1e5, "Pa"),
        ),
    ).outputs
    assert inside.power > 0
    with raises(PhysicsError, "out_of_range", match=r"esp: flow = .*head and power at least 0"):
        pump(
            frequency=60,
            fluid_in=Stream(
                m_dot=gm.units.Quantity(90.0, "kg/s"),
                T=gm.units.Quantity(300, "K"),
                p=gm.units.Quantity(1e5, "Pa"),
            ),
        )


def test_a_negative_power_is_outside_the_curve():
    """A power polynomial below zero is the curve outside its range."""
    curves = {**ESP_PARAMS, "power_coefficients": [-10.0, 0, 0, 0, 0, 0]}
    with raises(PhysicsError, "out_of_range", match="head and power at least 0"):
        si.set_params(ESP(), "", curves)(
            frequency=60,
            fluid_in=Stream(
                m_dot=gm.units.Quantity(40.0, "kg/s"),
                T=gm.units.Quantity(300, "K"),
                p=gm.units.Quantity(1e5, "Pa"),
            ),
        )


def test_a_stopped_pump_is_inside_its_curve():
    """No flow is no extrapolation."""
    pump = si.set_params(ESP(), "", ESP_PARAMS)
    assert (
        pump(
            frequency=60,
            fluid_in=Stream(
                m_dot=gm.units.Quantity(0.0, "kg/s"),
                T=gm.units.Quantity(300, "K"),
                p=gm.units.Quantity(1e5, "Pa"),
            ),
        ).outputs.efficiency
        == 0
    )


def test_a_flow_above_the_speed_scaled_maximum_flow_is_a_failed_row_with_the_range():
    """The curves are valid up to ``maximum_flow`` scaled by the speed; above, the row fails."""
    pump = si.set_params(ESP(), "", {**ESP_PARAMS, "maximum_flow": gm.units.Quantity(0.05, "m3/s")})
    assert (
        pump(
            frequency=60,
            fluid_in=Stream(
                m_dot=gm.units.Quantity(45.0, "kg/s"),
                T=gm.units.Quantity(300, "K"),
                p=gm.units.Quantity(1e5, "Pa"),
            ),
        ).outputs.power
        > 0
    )
    with raises(PhysicsError, "out_of_range", match=r"esp: flow = 0\.06.*0\.05"):
        pump(
            frequency=60,
            fluid_in=Stream(
                m_dot=gm.units.Quantity(60.0, "kg/s"),
                T=gm.units.Quantity(300, "K"),
                p=gm.units.Quantity(1e5, "Pa"),
            ),
        )
    with raises(PhysicsError, "out_of_range"):
        pump(
            frequency=30,
            fluid_in=Stream(
                m_dot=gm.units.Quantity(30.0, "kg/s"),
                T=gm.units.Quantity(300, "K"),
                p=gm.units.Quantity(1e5, "Pa"),
            ),
        )


GASSY = gm.Fluid(
    density=gm.units.Quantity(1030.0, "kg/m3"),
    gas_liquid_ratio={"value": 0.8, "unit": "Nm3/m3"},
    gas_composition={"CH4": 1.0},
)


def test_intake_pressure_and_gas_volume_fraction_follow_the_suction_stream():
    """The intake pressure is the suction pressure; the gas share falls as it rises."""
    pump = si.set_params(ESP(), "", ESP_PARAMS)
    low = pump(
        frequency=60,
        fluid_in=Stream(
            m_dot=gm.units.Quantity(40.0, "kg/s"),
            T=gm.units.Quantity(330, "K"),
            p=gm.units.Quantity(2e5, "Pa"),
            fluid=GASSY,
        ),
    ).outputs
    high = pump(
        frequency=60,
        fluid_in=Stream(
            m_dot=gm.units.Quantity(40.0, "kg/s"),
            T=gm.units.Quantity(330, "K"),
            p=gm.units.Quantity(40e5, "Pa"),
            fluid=GASSY,
        ),
    ).outputs
    assert low.intake_pressure == 2e5 and high.intake_pressure == 40e5
    assert 0 < high.gas_volume_fraction < low.gas_volume_fraction < 1
    rho = GASSY.gas_density_at(2e5, 330)
    mass = GASSY.gas_mass_fraction
    assert low.gas_volume_fraction == pytest.approx(
        mass / rho / (mass / rho + (1 - mass) / 1030.0), rel=1e-9
    )


def test_a_liquid_without_gas_has_no_gas_at_the_intake():
    """The constant-property brine has a zero fraction."""
    pump = si.set_params(ESP(), "", ESP_PARAMS)
    outputs = pump(
        frequency=60,
        fluid_in=Stream(
            m_dot=gm.units.Quantity(40.0, "kg/s"),
            T=gm.units.Quantity(300, "K"),
            p=gm.units.Quantity(1e5, "Pa"),
        ),
    ).outputs
    assert outputs.gas_volume_fraction == 0 and outputs.intake_pressure == 1e5


def test_a_stopped_pump_has_defined_intake_values():
    """No flow still has a pressure and a gas share at the intake."""
    pump = si.set_params(ESP(), "", ESP_PARAMS)
    outputs = pump(
        frequency=60,
        fluid_in=Stream(
            m_dot=gm.units.Quantity(0.0, "kg/s"),
            T=gm.units.Quantity(330, "K"),
            p=gm.units.Quantity(3e5, "Pa"),
            fluid=GASSY,
        ),
    ).outputs
    assert outputs.intake_pressure == 3e5 and 0 < outputs.gas_volume_fraction < 1


def test_intake_values_match_one_call_per_row_on_every_backend():
    """Gas and pressure over a range from near vacuum to deep, on every backend."""
    rows = [
        dict(
            fluid_in=Stream(
                m_dot=gm.units.Quantity(m_dot, "kg/s"),
                T=gm.units.Quantity(330, "K"),
                p=gm.units.Quantity(p, "Pa"),
                fluid=GASSY,
            ),
            frequency=60,
        )
        for m_dot, p in ((0.0, 1e3), (40, 2e5), (40, 40e5), (0.0, 5e5))
    ]
    assert_module_matches(si.set_params(ESP(), "", ESP_PARAMS), rows)


def test_an_out_of_range_row_names_the_intake_that_inflated_its_flow():
    """The failure carries the intake pressure and the gas share, so a low suction is seen."""
    pump = si.set_params(ESP(), "", {**ESP_PARAMS, "maximum_flow": gm.units.Quantity(0.05, "m3/s")})
    with raises(PhysicsError, "out_of_range", match=r"intake pressure = 20000\.0 Pa and gas.*"):
        pump(
            frequency=60,
            fluid_in=Stream(
                m_dot=gm.units.Quantity(90.0, "kg/s"),
                T=gm.units.Quantity(330, "K"),
                p=gm.units.Quantity(2e4, "Pa"),
                fluid=GASSY,
            ),
        )
