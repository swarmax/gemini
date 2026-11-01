"""Reservoir IPR and monitoring checks using example design data."""

import pytest

from gemini.errors import ValidationError
from gemini.modules.declarations import Inlet
from gemini.modules.subsurface import InjectionReservoir, ProductionReservoir
from gemini.types.flows import Stream
from gemini.types.fluid import Fluid
from scripts.legacy import tables as mapping
from tests.fixtures import OLD_PROJECT
from tests.fixtures.equivalence import assert_health_matches, assert_module_matches


def test_example_production_and_decline():
    """The example PI controls drawdown, and a 16% decline raises an alarm."""
    p = mapping.reservoir_params_from_gemini(
        mapping.from_property(OLD_PROJECT / "reservoir_c1b5.param"),
        mapping.from_property(OLD_PROJECT / "production_well_c774.param"),
    )
    c = ProductionReservoir().set_params("", p)
    c.fluid = mapping.reservoir_fluid(mapping.from_property(OLD_PROJECT / "reservoir_c1b5.param"))
    result = c(production_rate=40)
    out, flow = result.outputs, 40 / 1068
    assert out.drawdown == pytest.approx(flow / c.productivity_index)
    pressure = out.bottomhole_pressure
    assert not c.health(result, dict(flow=flow, bottomhole_pressure=pressure)).alarm
    assert c.health(result, dict(flow=flow * 0.84, bottomhole_pressure=pressure)).alarm


def test_injection_zero_radius_is_explicit():
    """Unconfigured example drainage radius leaves only radial diagnostics unavailable."""
    p = mapping.reservoir_params_from_gemini(
        mapping.from_property(OLD_PROJECT / "reservoir_28fc.param"),
        mapping.from_property(OLD_PROJECT / "injection_well_a06b.param"),
        "injection",
    )
    c = InjectionReservoir().set_params("", p)
    result = c(sandface_in=Stream(m_dot=-40, T=300, p=23e6))
    out = result.outputs
    assert out.bottomhole_pressure > c.pressure
    assert out.radial_bottomhole_pressure is None
    assert not c.health(
        result, dict(flow=40 / 1068, bottomhole_pressure=out.bottomhole_pressure)
    ).alarm


def test_ipr_helpers_match_the_call_outputs():
    """``sandface_stream`` and ``required_pressure`` give the pressures a call reports."""
    common = dict(
        temperature=353.15,
        permeability=1e-12,
        aquifer_thickness=100,
        drainage_radius=0,
        top_depth=2400,
        wellbore_radius=0.1,
    )
    producer = ProductionReservoir().set_params(
        "", {"pressure": 250e5, "productivity_index": 10 / 3.6e8, **common}
    )
    sandface = producer.sandface_stream(40)
    assert sandface.m_dot == 40 and sandface.T == 353.15
    assert sandface.p == producer(production_rate=40).outputs.bottomhole_pressure
    assert sandface.p == pytest.approx(250e5 - 40 / 1000 * 3.6e8 / 10)
    sink = InjectionReservoir().set_params(
        "", {"pressure": 240e5, "injectivity_index": 10 / 3.6e8, **common}
    )
    arriving = Stream(m_dot=-40, T=300, p=230e5)
    assert (
        sink.required_pressure(arriving) == sink(sandface_in=arriving).outputs.bottomhole_pressure
    )
    assert sink.required_pressure(arriving) == pytest.approx(240e5 + 40 / 1000 * 3.6e8 / 10)


ROW = Stream(m_dot=1.0, T=300.0, p=1e5)


class RowCarrier(ProductionReservoir):
    """A production reservoir with an unused inlet that carries the number of rows."""

    def __init__(self):
        """Declare the reservoir and the row-carrying inlet."""
        super().__init__()
        self.rows = Inlet(Stream)


def _producer(**changes):
    design = dict(
        pressure=250e5,
        temperature=353.15,
        permeability=1e-12,
        aquifer_thickness=100,
        drainage_radius=1000,
        top_depth=2400,
        wellbore_radius=0.1,
        productivity_index=10 / 3.6e8,
        skin=2,
    )
    return RowCarrier().set_params("", design | changes)


def test_production_reservoir_matches_traced():
    """Radial diagnostics, another fluid and several rates equal one call per row."""
    rows = [dict(rows=ROW, production_rate=rate) for rate in (0.0, 5.0, 40.0, 120.0)]
    assert_module_matches(_producer(), rows)
    dense = _producer()
    dense.fluid = Fluid(density=990.0, viscosity=5e-4)
    assert_module_matches(dense, rows)


def test_reservoir_without_drainage_radius_matches_traced():
    """An unconfigured drainage radius leaves the radial diagnostics undefined on every row."""
    producer = _producer(drainage_radius=0)
    assert_module_matches(producer, [dict(rows=ROW, production_rate=rate) for rate in (5.0, 40.0)])


def test_injection_reservoir_matches_traced():
    """Positive and negative sandface flows equal one call per row."""
    sink = InjectionReservoir().set_params(
        "",
        {
            "pressure": 240e5,
            "temperature": 353.15,
            "permeability": 1e-12,
            "aquifer_thickness": 100,
            "drainage_radius": 1000,
            "top_depth": 2400,
            "wellbore_radius": 0.1,
            "injectivity_index": 10 / 3.6e8,
            "skin": 1,
        },
    )
    rows = [
        dict(sandface_in=Stream(m_dot=m_dot, T=300, p=230e5)) for m_dot in (-40.0, -5.0, 0.0, 20.0)
    ]
    assert_module_matches(sink, rows)


def test_the_fluid_owns_the_density_and_viscosity():
    """A reservoir has no density or viscosity of its own: it reads its fluid."""
    producer = _producer()
    producer.fluid = Fluid(density=990.0, viscosity=5e-4)
    assert producer(rows=ROW, production_rate=9.9).outputs.drawdown == pytest.approx(
        0.01 / producer.productivity_index
    )
    with pytest.raises(ValidationError):
        producer.set_params("", {"liquid_density": 990.0})


def _health_rows(module, call):
    """Return results of module(**call) and measurements crossing alarms, clamps, equal pressure."""
    nominal = module.productivity_index or module.injectivity_index
    sign = 1 if module.role == "production" else -1
    pressure = module.pressure
    measured = [
        dict(flow=nominal * 1e5 * scale, bottomhole_pressure=pressure - sign * 1e5)
        for scale in (1.0, 0.9, 0.5, 2.0, -0.3)
    ]
    measured.append(dict(flow=0.01, bottomhole_pressure=pressure))
    return [module(**call) for _ in measured], measured


def test_production_health_matches_on_arrays():
    """Nominal, declining, clamped, reversed and unassessed rows give the same health."""
    producer = _producer()
    results, measured = _health_rows(producer, dict(production_rate=5.0, rows=ROW))
    assert_health_matches(producer, results, measured)
    assert [producer.health(r, m).alarm for r, m in zip(results, measured)] == [
        False,
        False,
        True,
        False,
        True,
        False,
    ]


def test_injection_health_matches_on_arrays():
    """The injectivity comparison agrees on arrays, including the unassessed row."""
    sink = InjectionReservoir().set_params(
        "",
        {
            "pressure": 240e5,
            "temperature": 353.15,
            "permeability": 1e-12,
            "aquifer_thickness": 100,
            "drainage_radius": 1000,
            "top_depth": 2400,
            "wellbore_radius": 0.1,
            "injectivity_index": 10 / 3.6e8,
            "decline_threshold": 0.2,
        },
    )
    results, measured = _health_rows(sink, dict(sandface_in=Stream(m_dot=-5.0, T=300, p=230e5)))
    assert_health_matches(sink, results, measured)


def test_health_without_a_nominal_index_or_measurements_is_not_assessed():
    """A structural lack of data returns None; an equal pressure gives an unassessed health."""
    producer = _producer(productivity_index=None)
    assert producer.health(None, dict(flow=1.0, bottomhole_pressure=1e5)) is None
    producer = _producer()
    assert producer.health(None, dict(flow=1.0)) is None
    health = producer.health(None, dict(flow=1.0, bottomhole_pressure=producer.pressure))
    assert not health.assessed and not health.alarm and health.score == 1
    assert health.message == "No diagnostic model or sufficient measurements"
