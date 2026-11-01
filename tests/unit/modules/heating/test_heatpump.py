"""Heat pump and electric chiller duties, Carnot- and Lorenz-fraction COP and limits."""

import pytest

from gemini import runtime
from gemini.errors import PhysicsError, ValidationError
from gemini.modules._utils.balance import energy_balance, mass_balance
from gemini.modules.heating import HeatPump
from gemini.physics import refrigeration
from gemini.types.flows import Stream
from gemini.types.fluid import Fluid
from gemini.units import Quantity
from tests.fixtures import si
from tests.fixtures.designs import with_values
from tests.fixtures.equivalence import assert_module_matches
from tests.fixtures.errors import raises
from tests.fixtures.parity import BACKENDS
from tests.fixtures.reading import reading

CP = 4217.4


def heat_pump(mode, **params):
    """Return a configured heat pump."""
    return si.set_params(
        with_values(HeatPump()), "", {"mode": mode, "capacity": Quantity(2e6, "W")} | params
    )


def test_heating_hand_value_and_closure():
    """Sink at setpoint; the closed-form source outlet gives COP = 0.5 * 340 / 47.2 = 3.6."""
    pump = heat_pump("heating")
    source, sink = Stream(
        m_dot=Quantity(20, "kg/s"), T=Quantity(300, "K"), p=Quantity(3e5, "Pa")
    ), Stream(m_dot=Quantity(10, "kg/s"), T=Quantity(320, "K"), p=Quantity(3e5, "Pa"))
    result = pump(source_in=source, sink_in=sink, temperature_setpoint=340)
    out = reading(result)
    assert out.useful_duty == out.condenser_duty == pytest.approx(10 * CP * 20)
    assert out.sink_out_T == 340
    assert out.source_out_T == pytest.approx(310 / (1 + 10 / 170))
    assert out.cop == pytest.approx(3.6)
    assert out.cop == pytest.approx(0.5 * 340 / (340 - out.source_out_T))
    assert out.electricity == pytest.approx(out.useful_duty / 3.6)
    assert out.evaporator_duty == pytest.approx(20 * CP * (300 - out.source_out_T))
    assert out.temperature_lift == pytest.approx(340 - out.source_out_T)
    assert out.is_running and not out.is_capped
    assert result.outlets.sink_out.p == sink.p and result.outlets.source_out.m_dot == 20
    assert energy_balance(pump, result)["relative_residual"] < 1e-12
    assert mass_balance(pump, result)["residual"] == 0


def test_cooling_mode_is_an_electric_chiller():
    """Chilled outlet at setpoint; condenser takes evaporator duty plus electricity."""
    chiller = heat_pump("cooling")
    source, sink = Stream(
        m_dot=Quantity(20, "kg/s"), T=Quantity(285, "K"), p=Quantity(3e5, "Pa")
    ), Stream(m_dot=Quantity(30, "kg/s"), T=Quantity(300, "K"), p=Quantity(3e5, "Pa"))
    result = chiller(source_in=source, sink_in=sink, temperature_setpoint=280)
    out = reading(result)
    load = 20 * CP * 5 / (30 * CP)
    assert out.evaporator_duty == pytest.approx(20 * CP * 5)
    assert out.source_out_T == 280
    assert out.sink_out_T == pytest.approx((300 - load) / (1 - load / 140))
    assert out.cop == pytest.approx(0.5 * 280 / (out.sink_out_T - 280))
    assert out.condenser_duty == pytest.approx(out.evaporator_duty * (1 + 1 / out.cop))
    assert energy_balance(chiller, result)["relative_residual"] < 1e-12
    assert mass_balance(chiller, result)["residual"] == 0


def test_capacity_cap_and_lift_floor():
    """The useful duty stops at capacity; a small lift uses the floor in the COP."""
    pump = heat_pump("heating", capacity=5e5)
    source, sink = Stream(
        m_dot=Quantity(20, "kg/s"), T=Quantity(300, "K"), p=Quantity(3e5, "Pa")
    ), Stream(m_dot=Quantity(10, "kg/s"), T=Quantity(320, "K"), p=Quantity(3e5, "Pa"))
    out = reading(pump(source_in=source, sink_in=sink, temperature_setpoint=340))
    assert out.is_capped and out.useful_duty == pytest.approx(5e5)
    assert out.sink_out_T == pytest.approx(320 + 5e5 / (10 * CP)) and out.sink_out_T < 340
    warm = Stream(m_dot=Quantity(40, "kg/s"), T=Quantity(330, "K"), p=Quantity(3e5, "Pa"))
    result = pump(source_in=warm, sink_in=sink, temperature_setpoint=330)
    out = reading(result)
    assert out.temperature_lift < 10
    assert out.cop == pytest.approx(0.5 * 330 / 10)
    assert energy_balance(pump, result)["relative_residual"] < 1e-12
    cooled = reading(
        heat_pump("cooling")(
            source_in=Stream(
                m_dot=Quantity(20, "kg/s"), T=Quantity(300, "K"), p=Quantity(3e5, "Pa")
            ),
            sink_in=Stream(
                m_dot=Quantity(200, "kg/s"), T=Quantity(290, "K"), p=Quantity(3e5, "Pa")
            ),
            temperature_setpoint=295,
        )
    )
    assert cooled.cop == pytest.approx(0.5 * 295 / 10)


def test_machine_off_without_demand_flow_or_part_load():
    """No request, a stopped circuit or a load below the minimum leaves both streams as they are."""
    pump = heat_pump("heating", minimum_part_load=0.3)
    source, sink = Stream(
        m_dot=Quantity(20, "kg/s"), T=Quantity(300, "K"), p=Quantity(3e5, "Pa")
    ), Stream(m_dot=Quantity(10, "kg/s"), T=Quantity(320, "K"), p=Quantity(3e5, "Pa"))
    cases = [
        dict(source_in=source, sink_in=sink, temperature_setpoint=310),
        dict(source_in=source.with_(m_dot=0), sink_in=sink, temperature_setpoint=340),
        dict(source_in=source, sink_in=sink.with_(m_dot=0), temperature_setpoint=340),
        dict(source_in=source, sink_in=sink, temperature_setpoint=321),
    ]
    for case in cases:
        result = pump(**case)
        out = reading(result)
        assert out.cop is None and not out.is_running and not out.is_capped
        assert out.useful_duty == out.electricity == out.evaporator_duty == 0
        assert result.outlets.source_out.T == case["source_in"].T
        assert result.outlets.sink_out.T == case["sink_in"].T


def test_invalid_operating_points_raise():
    """Negative flow, a hopeless heating lift and a too small sink flow are out of range."""
    source, sink = Stream(
        m_dot=Quantity(20, "kg/s"), T=Quantity(300, "K"), p=Quantity(3e5, "Pa")
    ), Stream(m_dot=Quantity(10, "kg/s"), T=Quantity(320, "K"), p=Quantity(3e5, "Pa"))
    with pytest.raises(PhysicsError, match="source_in.m_dot = -1"):
        heat_pump("heating")(
            source_in=source.with_(m_dot=-1), sink_in=sink, temperature_setpoint=340
        )
    with pytest.raises(PhysicsError, match="heating COP above 1"):
        heat_pump("heating", carnot_fraction=0.2)(
            source_in=source.with_(T=270), sink_in=sink, temperature_setpoint=340
        )
    with pytest.raises(PhysicsError, match="to reject the cooling duty"):
        heat_pump("cooling")(
            source_in=Stream(
                m_dot=Quantity(100, "kg/s"), T=Quantity(290, "K"), p=Quantity(3e5, "Pa")
            ),
            sink_in=Stream(
                m_dot=Quantity(0.1, "kg/s"), T=Quantity(300, "K"), p=Quantity(3e5, "Pa")
            ),
            temperature_setpoint=280,
        )


def test_lorenz_heating_reproduces_the_upstream_gemini_case():
    """Upstream GEMINI ``HeatpumpBasic`` Lorenz case: 30 -> 80 C sink, 40 C source.

    Upstream (Nelder-Mead) reports COP 6.5310, source outlet 18.8279 C, 580694.44 W and
    88913.32 W; the root found here gives 88913.17 W, the duty divided by the same COP
    without the optimizer's tolerance.
    """
    water = Fluid(
        kind="water", density=Quantity(1000, "kg/m3"), specific_heat=Quantity(4181, "J/kg/K")
    )
    pump = heat_pump("heating", capacity=1e7, cop_model="lorenz")
    source = Stream(
        flow={"value": 20, "unit": "m3/h"},
        T={"value": 40, "unit": "C"},
        p=Quantity(3e5, "Pa"),
        fluid=water,
    )
    sink = Stream(
        flow={"value": 10, "unit": "m3/h"},
        T={"value": 30, "unit": "C"},
        p=Quantity(3e5, "Pa"),
        fluid=water,
    )
    result = pump(source_in=source, sink_in=sink, temperature_setpoint={"value": 80, "unit": "C"})
    out = reading(result)
    assert out.cop == pytest.approx(6.5310, abs=1e-4)
    assert out.source_out_T - 273.15 == pytest.approx(18.8279, abs=1e-4)
    assert out.useful_duty == pytest.approx(580694.44, abs=0.01)
    assert out.electricity == pytest.approx(88913.17, abs=0.01)
    expected = 0.5 * refrigeration.lorenz_cop_heating(
        sink.T, out.sink_out_T, source.T, out.source_out_T, 10
    )
    assert out.cop == pytest.approx(expected, rel=1e-12)
    assert energy_balance(pump, result)["relative_residual"] < 1e-12
    assert mass_balance(pump, result)["residual"] == 0


def test_lorenz_mode_limits():
    """Lorenz cooling is undefined and a source too cold for a COP above 1 is out of range."""
    source, sink = Stream(
        m_dot=Quantity(20, "kg/s"), T=Quantity(300, "K"), p=Quantity(3e5, "Pa")
    ), Stream(m_dot=Quantity(10, "kg/s"), T=Quantity(320, "K"), p=Quantity(3e5, "Pa"))
    with raises(ValidationError, "invalid_design", match="cop_model = 'lorenz'"):
        heat_pump("cooling", cop_model="lorenz")(
            source_in=source, sink_in=sink, temperature_setpoint=290
        )
    with pytest.raises(PhysicsError, match="heating COP above 1"):
        heat_pump("heating", cop_model="lorenz", lorenz_fraction=0.1)(
            source_in=source.with_(T=250), sink_in=sink, temperature_setpoint=340
        )


@pytest.mark.parametrize("cop_model", ["carnot", "lorenz"])
def test_minimum_source_outlet_caps_the_heating_duty(cop_model):
    """A source that would leave below the minimum caps the duty; the sink outlet drops.

    Upstream GEMINI ``Ts_in_minimum`` behaviour: unconstrained, this source leaves at
    292.78 K (Carnot); with a 295 K minimum the evaporator takes exactly C (300 - 295).
    """
    pump = heat_pump("heating", cop_model=cop_model, minimum_source_outlet_temperature=295)
    source, sink = Stream(
        m_dot=Quantity(20, "kg/s"), T=Quantity(300, "K"), p=Quantity(3e5, "Pa")
    ), Stream(m_dot=Quantity(10, "kg/s"), T=Quantity(320, "K"), p=Quantity(3e5, "Pa"))
    result = pump(source_in=source, sink_in=sink, temperature_setpoint=340)
    out = reading(result)
    assert out.source_out_T == 295 and result.outlets.source_out.T == 295
    assert 320 < out.sink_out_T < 340 and out.is_capped and out.is_running
    assert out.evaporator_duty == pytest.approx(20 * CP * 5, rel=1e-10)
    assert out.useful_duty == pytest.approx(10 * CP * (out.sink_out_T - 320))
    assert energy_balance(pump, result)["relative_residual"] < 1e-12
    unconstrained = heat_pump("heating", cop_model=cop_model)(
        source_in=source, sink_in=sink, temperature_setpoint=340
    )
    assert reading(unconstrained).source_out_T < 295


def test_minimum_source_outlet_switches_off_or_raises_a_cooling_setpoint():
    """A source inlet at the minimum leaves no heating duty; a colder chiller setpoint is raised."""
    source, sink = Stream(
        m_dot=Quantity(20, "kg/s"), T=Quantity(300, "K"), p=Quantity(3e5, "Pa")
    ), Stream(m_dot=Quantity(10, "kg/s"), T=Quantity(320, "K"), p=Quantity(3e5, "Pa"))
    pump = heat_pump("heating", minimum_source_outlet_temperature=300)
    out = reading(pump(source_in=source, sink_in=sink, temperature_setpoint=340))
    assert not out.is_running and out.useful_duty == 0 and out.sink_out_T == 320
    chiller = heat_pump("cooling", minimum_source_outlet_temperature=283)
    result = chiller(
        source_in=Stream(m_dot=Quantity(20, "kg/s"), T=Quantity(285, "K"), p=Quantity(3e5, "Pa")),
        sink_in=Stream(m_dot=Quantity(30, "kg/s"), T=Quantity(300, "K"), p=Quantity(3e5, "Pa")),
        temperature_setpoint=280,
    )
    assert reading(result).source_out_T == pytest.approx(283)
    assert result.outputs.is_capped
    assert reading(result).evaporator_duty == pytest.approx(20 * CP * 2)
    assert energy_balance(chiller, result)["relative_residual"] < 1e-12


def _rows(cases):
    return [
        dict(
            source_in=Stream(
                m_dot=Quantity(source_flow, "kg/s"),
                T=Quantity(source_T, "K"),
                p=Quantity(3e5, "Pa"),
            ),
            sink_in=Stream(
                m_dot=Quantity(sink_flow, "kg/s"), T=Quantity(sink_T, "K"), p=Quantity(3e5, "Pa")
            ),
            temperature_setpoint=setpoint,
        )
        for source_flow, source_T, sink_flow, sink_T, setpoint in cases
    ]


HEATING_CASES = [
    (20, 300, 10, 320, 340),
    (20, 300, 10, 320, 330),
    (40, 330, 10, 320, 330),
    (20, 300, 10, 320, 321),
    (20, 300, 10, 320, 310),
    (0, 300, 10, 320, 340),
    (20, 300, 0, 320, 340),
    (100, 305, 10, 320, 350),
]


@pytest.mark.parametrize(
    "params",
    [
        dict(),
        dict(capacity=5e5),
        dict(minimum_part_load=0.3),
        dict(cop_model="lorenz"),
        dict(minimum_source_outlet_temperature=295),
        dict(cop_model="lorenz", minimum_source_outlet_temperature=295),
        dict(minimum_source_outlet_temperature=300),
    ],
    ids=["carnot", "capped", "part-load", "lorenz", "carnot-limit", "lorenz-limit", "at-limit"],
)
def test_heating_traced_call_matches_one_call_per_row(params):
    """Running, capped, floored-lift, off, stopped and source-limited rows trace and agree."""
    assert_module_matches(heat_pump("heating", **params), _rows(HEATING_CASES))


@pytest.mark.parametrize(
    "params",
    [dict(), dict(capacity=5e5), dict(minimum_source_outlet_temperature=283)],
    ids=["chiller", "capped", "limit"],
)
def test_cooling_traced_call_matches_one_call_per_row(params):
    """Running, capped, floored-lift, off, stopped and raised-setpoint rows trace and agree."""
    cases = [
        (20, 285, 30, 300, 280),
        (20, 300, 200, 290, 295),
        (20, 285, 30, 300, 290),
        (0, 285, 30, 300, 280),
        (20, 285, 0, 300, 280),
        (20, 285, 30, 300, 270),
    ]
    assert_module_matches(heat_pump("cooling", **params), _rows(cases))


def test_a_stopped_heat_pump_has_no_cop_on_every_backend():
    """At zero flow the COP is ``None`` also when a backend gives it as a NaN of no dimension."""
    pump = with_values(HeatPump()).set_params(
        "", {"mode": "heating", "capacity": {"value": 2, "unit": "MW"}, "carnot_fraction": 0.5}
    )
    stopped = Stream(m_dot=Quantity(0.0, "kg/s"), T=Quantity(300.0, "K"), p=Quantity(3e5, "Pa"))
    for backend in BACKENDS:
        with runtime.settings(backend=backend):
            result = pump(source_in=stopped, sink_in=stopped, temperature_setpoint=313.15)
        assert result.outputs.cop is None
