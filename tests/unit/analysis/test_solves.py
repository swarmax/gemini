"""Nodal well solves against the upstream GEMINI doublet-A reference and their balances.

The configuration is the upstream ``simulator_examples/projects/doublet_plant.json`` producer
and injector: vertical 2400 m and 3100 m wells of 0.15 m bore and 0.01 m roughness, a 10-stage
ESP at 650 m, reservoirs at 250 and 240 bar with 10 m3/h/bar indices, constant-property brine.
"""

import pytest

from gemini.analysis import solves as nodal
from gemini.errors import PhysicsError, ValidationError
from gemini.modules.pumps import ESP, InjectionPump
from gemini.modules.subsurface import InjectionReservoir, ProductionReservoir
from gemini.modules.wells import InjectionWell, ProductionWell
from gemini.physics.geometry import build_path, section_values
from gemini.types.flows import Stream
from tests.fixtures.errors import raises
from tests.fixtures.reading import reading

DENSITY = 1000.0
"""Density [kg/m3] of the default constant-property brine."""

INDEX = 10 / 3.6e8
"""Productivity and injectivity index [m3/s/Pa]: 10 m3/h/bar."""

RESERVOIR = dict(
    temperature=353.15,
    permeability=1e-12,
    aquifer_thickness=100,
    drainage_radius=0,
    wellbore_radius=0.1,
)

UPSTREAM_FLOW_69_HZ = 135.92584228893725
"""Upstream reference rate [m3/h] at 3 bar wellhead pressure and 69 Hz."""

UPSTREAM_ESP_POWER_65_HZ = 174444.715702
"""Upstream reference ESP shaft power [W] at 3 bar wellhead pressure and 65 Hz."""


def vertical_path(depth):
    """Return the upstream survey of a vertical well with a 0.15 m bore to ``depth`` [m]."""
    stations = (0, 300, 400, 600, depth)
    rows = [dict(MD=md, TVD=md, ID=0.15, roughness=0.01) for md in stations]
    return build_path(rows)


def segment_of(path, segment):
    """Return the values of an upstream producer well of ``path``, cut at the ESP at 650 m."""
    return {
        **section_values(path),
        "soil_temperature": 293.15,
        "segment": segment,
        "esp_depth": 650,
    }


@pytest.fixture(scope="module")
def producer():
    """Return reservoir, lower well, ESP and riser of the upstream producer."""
    reservoir = ProductionReservoir().set_params(
        "", {"pressure": 250e5, "productivity_index": INDEX, "top_depth": 2400, **RESERVOIR}
    )
    path = vertical_path(2400)
    well = ProductionWell().set_params("", segment_of(path, "below_esp"))
    riser = ProductionWell().set_params("", segment_of(path, "above_esp"))
    esp = ESP().set_params(
        "",
        {
            "stage_count": 10,
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
        },
    )
    return reservoir, well, esp, riser


@pytest.fixture(scope="module")
def injector():
    """Return the upstream injection well and receiving aquifer."""
    well = InjectionWell().set_params(
        "", {**section_values(vertical_path(3100)), "soil_temperature": 293.15}
    )
    sink = InjectionReservoir().set_params(
        "", {"pressure": 240e5, "injectivity_index": INDEX, "top_depth": 3100, **RESERVOIR}
    )
    return well, sink


def solve(producer, frequency):
    """Return the production rate [kg/s] at 3 bar wellhead pressure and an ESP frequency."""
    reservoir, well, esp, riser = producer
    esp.frequency = frequency
    return nodal.solve_production_rate(reservoir, well, 3e5, (5, 60), esp=esp, riser=riser)


def test_production_rate_reproduces_the_wellhead_pressure(producer):
    """Commanding the solved rate makes the ordinary chain arrive at the wellhead pressure."""
    reservoir, well, esp, riser = producer
    rate = solve(producer, 65)
    lower = well(bottom_in=reservoir(production_rate=rate).outlets.sandface_out)
    lifted = riser(bottom_in=esp(fluid_in=lower.outlets.wellhead_out).outlets.fluid_out)
    assert lifted.outlets.wellhead_out.p == pytest.approx(3e5, abs=1e-3)


def test_production_rate_and_esp_power_match_the_upstream_reference(producer):
    """Measured gaps: -0.044 % in rate at 69 Hz and -0.022 % in ESP power at 65 Hz.

    Upstream accepts 1 % because its reference simulator uses its own lift correlations. Here
    the same inputs give 135.8666 m3/h (upstream 135.9258) and 174406.5 W (upstream
    174444.7); nothing is tuned.
    """
    flow = solve(producer, 69) / DENSITY * 3600
    assert flow == pytest.approx(UPSTREAM_FLOW_69_HZ, rel=0.01)
    assert flow == pytest.approx(135.8666, abs=1e-4)
    reservoir, well, esp, _ = producer
    rate = solve(producer, 65)
    suction = well(bottom_in=reservoir.sandface_stream(rate)).outlets.wellhead_out
    power = esp(fluid_in=suction).outputs.power
    assert power == pytest.approx(UPSTREAM_ESP_POWER_65_HZ, rel=0.01)


def test_production_rate_without_esp():
    """A free-flowing well solves the same balance through one full-length segment."""
    reservoir = ProductionReservoir().set_params(
        "", {"pressure": 250e5, "productivity_index": INDEX, "top_depth": 2400, **RESERVOIR}
    )
    well = ProductionWell().set_params(
        "", {**section_values(vertical_path(2400)), "soil_temperature": 293.15}
    )
    rate = nodal.solve_production_rate(reservoir, well, 3e5, (1, 60))
    arrived = well(bottom_in=reservoir.sandface_stream(rate)).outlets.wellhead_out
    assert arrived.p == pytest.approx(3e5, abs=1e-3)


def test_injection_rate_balances_well_and_aquifer(injector):
    """The solved rate makes the well's bottom pressure the aquifer's required pressure."""
    well, sink = injector
    wellhead = Stream(m_dot=1, T=293.15, p=1e5)
    rate = nodal.solve_injection_rate(well, sink, wellhead, (1, 200))
    bottom = well(wellhead_in=wellhead.with_(m_dot=rate)).outlets.bottom_out
    assert bottom.p == pytest.approx(sink.required_pressure(bottom), abs=1e-3)


def test_injection_pressure_balances_a_shallow_injector():
    """A 2000 m injector into a 230 bar aquifer needs a pump; the solved pressure balances."""
    well = InjectionWell().set_params(
        "", {**section_values(vertical_path(2000)), "soil_temperature": 293.15}
    )
    sink = InjectionReservoir().set_params(
        "", {"pressure": 230e5, "injectivity_index": INDEX, "top_depth": 2000, **RESERVOIR}
    )
    wellhead = Stream(flow={"value": 129.02, "unit": "m3/h"}, T=293.15, p=2e5)
    pressure = nodal.solve_injection_pressure(well, sink, wellhead, (2e5, 1e8))
    assert pressure > 2e5
    bottom = well(wellhead_in=wellhead.with_(p=pressure)).outlets.bottom_out
    assert bottom.p == pytest.approx(sink.required_pressure(bottom), abs=1e-3)


def test_deep_injector_needs_no_pump_and_draws_no_power(injector):
    """Upstream ``Pout ~ 1e-8 bar``: the 3100 m column over-delivers, so the solve returns None.

    ``None`` is zero pump head: commanding the injection pump to its suction pressure draws no
    electricity.
    """
    well, sink = injector
    wellhead = Stream(flow={"value": 129.02, "unit": "m3/h"}, T=293.15, p=1e3)
    assert nodal.solve_injection_pressure(well, sink, wellhead, (1e3, 1e8)) is None
    pump = InjectionPump().set_params("", {"efficiency": 0.8})
    result = pump(fluid_in=wellhead, pressure_setpoint=wellhead.p)
    assert result.outputs.head == 0 and reading(result).electricity == 0


def test_invalid_requests_raise(producer):
    """A lone ESP, a bracket without a sign change and a trial outside the model's domain."""
    reservoir, well, esp, riser = producer
    esp.frequency = 65
    with raises(ValidationError, "invalid_design", match="expected both or neither"):
        nodal.solve_production_rate(reservoir, well, 3e5, (5, 60), esp=esp)
    with pytest.raises(PhysicsError, match="expected opposite signs"):
        nodal.solve_production_rate(reservoir, well, 3e5, (5, 10), esp=esp, riser=riser)
    with pytest.raises(PhysicsError, match="rate = 1000 kg/s"):
        nodal.solve_production_rate(reservoir, well, 3e5, (5, 1000), esp=esp, riser=riser)


UPSTREAM_INJECTION_PRESSURE = 44.4716458281338e5
"""Upstream ``parallel_hex_plant`` injector wellhead pressure [Pa] at 125.1 m3/h."""

UPSTREAM_GRAVITY = 184.7223e5
"""Upstream DPDT gravity drop [Pa] of the same injector."""


def test_injection_pressure_gap_to_upstream_is_the_friction_sign():
    """Upstream walks the injector down with positive flow, adding friction to the bottom.

    The injected brine flows downward, so friction lowers the bottom pressure; the legacy
    GEMINI injection DPDT (negative flow) and this port subtract it. Density (1000 kg/m3),
    roughness (2e-5 m), the aquifer (180 bar, 2.3 m3/h/bar) and the 5.197 bar friction
    magnitude agree with upstream; the gravity drop differs by 0.0085 bar through the 0.01
    degree inclination rounding of ``build_path``. The 10.39 bar gap (54.86 against 44.47 bar)
    is twice the friction plus that difference.
    """
    stations = [
        (0, 0, 0.1616964),
        (148, 148, 0.1616964),
        (1097, 1034, 0.25273),
        (2109, 1742, 0.1616964),
        (2327, 1883, 0.0995668),
    ]
    rows = [dict(MD=md, TVD=tvd, ID=bore, roughness=2e-5) for md, tvd, bore in stations]
    well = InjectionWell().set_params(
        "", {**section_values(build_path(rows)), "soil_temperature": 293.15}
    )
    sink = InjectionReservoir().set_params(
        "", {"pressure": 180e5, "injectivity_index": 2.3 / 3.6e8, "top_depth": 1883, **RESERVOIR}
    )
    wellhead = Stream(flow={"value": 125.1, "unit": "m3/h"}, T=343.15, p=1e5)
    pressure = nodal.solve_injection_pressure(well, sink, wellhead, (1e5, 1e8))
    out = reading(well(wellhead_in=wellhead.with_(p=pressure)))
    assert out.friction_pressure_drop == pytest.approx(-5.197358519692272e5, rel=1e-9)
    assert out.gravity_pressure_drop - UPSTREAM_GRAVITY == pytest.approx(0.0085e5, abs=10)
    gap = -2 * out.friction_pressure_drop - (out.gravity_pressure_drop - UPSTREAM_GRAVITY)
    assert pressure - UPSTREAM_INJECTION_PRESSURE == pytest.approx(gap, abs=1)
    assert pressure / 1e5 == pytest.approx(54.86, abs=0.005)
