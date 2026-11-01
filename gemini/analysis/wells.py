"""Well performance: nodal analysis, injectivity and the pump head curve."""

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

import numpy as np

from gemini import units as physics_units
from gemini._utils.jsonable import to_plain
from gemini._utils.strings import split_path
from gemini.analysis import solves
from gemini.analysis.fits import fit_head_correction
from gemini.errors import GeminiError, NotImplementedYet, PhysicsError, ValidationError
from gemini.errors.base import check_on_error
from gemini.modules.pumps import ESP
from gemini.modules.subsurface import InjectionReservoir, ProductionReservoir
from gemini.modules.wells import InjectionWell, ProductionWell
from gemini.physics import constants
from gemini.types.flows import Stream
from gemini.types.shapes import OutputUnits, value

CURVE_POINTS = 21
"""Number of rates on the IPR and VLP curves of ``nodal``, from the low to the high bracket end."""
PUMP_CURVE_POINTS = 50
"""Number of flows on the head curve of ``pump_curve``, from zero to twice the maximum flow."""
WELLHEAD_PRESSURES = (101325.0, 1e8)
"""The bracket [Pa] of an injection wellhead: the lowest is one atmosphere, the highest 1000 bar."""
NO_PUMP = "the column of brine delivers what the aquifer needs: no pump, a choke holds the well"


@dataclass(frozen=True)
class _Chain:
    """The production chain of a well: reservoir, lower well, optional ESP and upper well."""

    reservoir: Any
    lower: Any
    esp: Any
    upper: Any


@dataclass(frozen=True)
class _Injection:
    """The injection chain of a well: the well and the aquifer it feeds."""

    well: Any
    sink: Any


def _injection_chain(plant, well, module, inside):
    """Return the injection chain at ``well``, or ``None`` when it has no part of one.

    A path of the well or of the aquifer finds the other in the same parent, which is how to reach
    the injection side of a doublet, whose own path is its production chain.
    """
    alone = isinstance(module, (InjectionWell, InjectionReservoir))
    scope = list(plant.get_submodule(split_path(well)[0]).modules()) if alone else inside
    wells = [item for item in scope if isinstance(item, InjectionWell)]
    sinks = [item for item in scope if isinstance(item, InjectionReservoir)]
    if not wells and not sinks:
        return None
    if len(wells) != 1 or len(sinks) != 1:
        raise ValidationError(
            f"nodal: well = {well!r}; {len(wells)} injection wells, {len(sinks)} aquifers; "
            "expected one of each",
            path=well,
            code="invalid_design",
        )
    return _Injection(wells[0], sinks[0])


def _chain(plant, well):
    """Return the production or injection chain at the plant path ``well``."""
    module = plant.get_submodule(well)
    inside = list(module.modules())
    reservoirs = [item for item in inside if isinstance(item, ProductionReservoir)]
    if not reservoirs:
        injection = _injection_chain(plant, well, module, inside)
        if injection is not None:
            return injection
        raise ValidationError(
            f"nodal: well = {well!r}; expected a path that holds a ProductionReservoir, or an "
            "injection well and its aquifer",
            path=well,
        )
    wells = {item.segment: item for item in inside if isinstance(item, ProductionWell)}
    esps = [item for item in inside if isinstance(item, ESP)]
    if esps and {"below_esp", "above_esp"} <= wells.keys():
        return _Chain(reservoirs[0], wells["below_esp"], esps[0], wells["above_esp"])
    if not esps and "full" in wells:
        return _Chain(reservoirs[0], wells["full"], None, None)
    raise ValidationError(
        f"nodal: well = {well!r}; segments = {sorted(wells)}, ESPs = {len(esps)}; expected one "
        "ProductionWell 'full', or an ESP with the segments 'below_esp' and 'above_esp'",
        code="invalid_design",
    )


def _required(conditions, name):
    if name not in conditions:
        raise ValidationError(
            f"nodal: conditions.{name} is missing; expected it", path=name, code="missing_value"
        )
    return conditions[name]


def _case_inputs(chain, conditions):
    """Return the SI wellhead pressure [Pa], rate bracket [kg/s] and ESP frequency [Hz]."""
    pressure = physics_units.value_in_si(
        _required(conditions, "wellhead_pressure"), "Pa", "conditions.wellhead_pressure", "pressure"
    )
    low, high = (
        physics_units.value_in_si(value, "kg/s", "conditions.rates", "mass_flow")
        for value in _required(conditions, "rates")
    )
    frequency = None
    if chain.esp is not None:
        frequency = physics_units.value_in_si(
            _required(conditions, "frequency"), "Hz", "conditions.frequency", "frequency"
        )
    return float(pressure), (float(low), float(high)), frequency


def _lift(chain, rate):
    """Return the wellhead pressure [Pa] that the well lifts the inflow of ``rate`` to."""
    inflow = chain.reservoir.sandface_stream(rate)
    stream = chain.lower._trial(bottom_in=inflow).outlets.wellhead_out
    if chain.esp is not None:
        stream = chain.esp._trial(fluid_in=stream).outlets.fluid_out
        stream = chain.upper._trial(bottom_in=stream).outlets.wellhead_out
    return stream.p


def _curve(rates, pressures, output):
    """Return one curve of 21 points, each list a value."""
    return {
        "rate": output.value(rates, "kg/s", "mass_flow"),
        "pressure": output.value(pressures, "Pa", "pressure"),
    }


def _curves(chain, pressure, rates, output):
    """Return the IPR, the VLP and the operating point for a rate bracket."""
    low, high = rates
    sampled = np.linspace(low, high, CURVE_POINTS)
    inflow = [chain.reservoir.sandface_stream(rate).p for rate in sampled]
    lift = [_lift(chain, rate) for rate in sampled]
    rate = solves.solve_production_rate(
        chain.reservoir, chain.lower, pressure, rates, esp=chain.esp, riser=chain.upper
    )
    point = {
        "rate": output.value(rate, "kg/s", "mass_flow"),
        "wellhead_pressure": output.value(pressure, "Pa", "pressure"),
        "sandface_pressure": output.value(
            chain.reservoir.sandface_stream(rate).p, "Pa", "pressure"
        ),
    }
    return _curve(sampled, inflow, output), _curve(sampled, lift, output), point


def _in_si(conditions, name, unit, quantity):
    """Return the condition ``name`` as a float in SI."""
    return float(physics_units.value_in_si(conditions[name], unit, f"conditions.{name}", quantity))


def _injection_inputs(conditions):
    """Return the SI temperature [K], rate bracket [kg/s] and what the case gives of a point."""
    _required(conditions, "temperature")
    temperature = _in_si(conditions, "temperature", "K", "temperature")
    low, high = (
        physics_units.value_in_si(value, "kg/s", "conditions.rates", "mass_flow")
        for value in _required(conditions, "rates")
    )
    if "rate" not in conditions and "wellhead_pressure" not in conditions:
        raise ValidationError(
            "nodal: conditions has no rate and no wellhead_pressure; expected one of them",
            path="wellhead_pressure",
            code="missing_value",
        )
    return temperature, (float(low), float(high))


def _needed_pressure(chain, temperature, rate):
    """Return the wellhead pressure [Pa] that injects ``rate``, or ``None`` with no pump."""
    stream = Stream(m_dot=rate, T=temperature, p=WELLHEAD_PRESSURES[0], fluid=chain.well.fluid)
    return solves.solve_injection_pressure(chain.well, chain.sink, stream, WELLHEAD_PRESSURES)


def _injected_rate(chain, temperature, pressure, rates):
    """Return the rate [kg/s] the wellhead pressure [Pa] pushes into the aquifer."""
    stream = Stream(m_dot=rates[0], T=temperature, p=pressure, fluid=chain.well.fluid)
    return solves.solve_injection_rate(chain.well, chain.sink, stream, rates)


def _aquifer_pressure(chain, temperature, rate):
    """Return the sandface pressure [Pa] the aquifer needs to take ``rate``."""
    stream = Stream(m_dot=rate, T=temperature, p=WELLHEAD_PRESSURES[0], fluid=chain.sink.fluid)
    return chain.sink.required_pressure(stream)


def _injection_point(chain, conditions, temperature, rates, output):
    """Return the operating point: the rate and pressure of the case, the other one solved."""
    if "rate" in conditions:
        rate = _in_si(conditions, "rate", "kg/s", "mass_flow")
        pressure = _needed_pressure(chain, temperature, rate)
    else:
        pressure = _in_si(conditions, "wellhead_pressure", "Pa", "pressure")
        rate = _injected_rate(chain, temperature, pressure, rates)
    return {
        "rate": output.value(rate, "kg/s", "mass_flow"),
        "wellhead_pressure": output.value(
            pressure, "Pa", "pressure", None if pressure is not None else NO_PUMP
        ),
        "sandface_pressure": output.value(
            _aquifer_pressure(chain, temperature, rate), "Pa", "pressure"
        ),
    }


def _injection_curves(chain, conditions, output):
    """Return the aquifer's curve, the well's curve and the operating point of a case."""
    temperature, rates = _injection_inputs(conditions)
    sampled = np.linspace(*rates, CURVE_POINTS)
    aquifer = [_aquifer_pressure(chain, temperature, rate) for rate in sampled]
    needed = [_needed_pressure(chain, temperature, rate) for rate in sampled]
    well = [np.nan if pressure is None else pressure for pressure in needed]
    point = _injection_point(chain, conditions, temperature, rates, output)
    return _curve(sampled, aquifer, output), _curve(sampled, well, output), point


def _production_curves(chain, conditions, output):
    """Return the IPR, the VLP and the operating point of a case of a production well."""
    pressure, rates, frequency = _case_inputs(chain, conditions)
    if chain.esp is not None:
        chain.esp.frequency = frequency
    return _curves(chain, pressure, rates, output)


def _case(chain, conditions, on_error, output):
    """Return the curves and the operating point of one set of conditions."""
    case = {
        "conditions": conditions,
        "ipr": None,
        "vlp": None,
        "operating_point": None,
        "error": None,
    }
    try:
        curves = _injection_curves if isinstance(chain, _Injection) else _production_curves
        case["ipr"], case["vlp"], case["operating_point"] = curves(chain, conditions, output)
    except GeminiError as error:
        if on_error == "raise":
            raise
        case["error"] = error.to_dict()
    return case


def nodal(plant, well, conditions, on_error="raise", units=None):
    """Return the IPR and VLP curves and the operating point of a production or injection well.

    The IPR (inflow performance) is the sandface pressure the reservoir delivers at each rate.
    The VLP (vertical lift performance) is the wellhead pressure the well, the ESP and the riser
    deliver from that inflow at each rate: the node is the wellhead, and the operating point is
    where the VLP falls to the wellhead pressure the surface plant holds. The solve is the one
    of ``solves.solve_production_rate``. The plant is not changed: the ESP frequency
    of a case is set on a copy.

    An injection well has the same shape. ``ipr`` is the sandface pressure the aquifer needs at
    each rate and ``vlp`` the wellhead pressure that delivers it down the well, ``solves.
    solve_injection_pressure``; the operating point is the pressure a case's rate needs, or the
    rate a case's pressure pushes in. A rate the column of brine injects alone needs no pump: its
    point on ``vlp`` is ``None``, and in ``operating_point`` a value ``None`` with a ``reason``.

    Parameters
    ----------
    plant : Module
        A plant with parameter values.
    well : str
        Dotted path of the module that holds the whole chain, for example ``"doublet"``: one
        ``ProductionReservoir`` and either one full ``ProductionWell`` or an ``ESP`` with the
        ``below_esp`` and ``above_esp`` segments. For injection, the path of an
        ``InjectionWell`` or of its ``InjectionReservoir``, ``"doublet.injector"``, or of what
        holds one of each and no production chain.
    conditions : dict or list of dict
        One case, or several for a what-if. Each has ``wellhead_pressure`` [Pa], ``rates``, the
        ``[low, high]`` bracket [kg/s] of the curves and of the solve (a trial outside the well
        model's domain fails the case), and ``frequency`` [Hz] when the chain has an ESP. Numbers
        are SI, or a ``Quantity``. An injection case has ``rates``,
        ``temperature`` [K], the temperature at the wellhead, and ``rate`` or
        ``wellhead_pressure``, which says what to solve for.
    on_error : {"raise", "record"}, optional
        A case that fails raises; ``"record"`` puts its problem in ``error`` and runs the others.
    units : dict, optional
        A map from quantity to unit for the returned values, such as ``{"pressure": "bar"}``.

    Returns
    -------
    dict
        Plain JSON ``{well, cases}``. Each case holds ``conditions`` as given, ``ipr`` and ``vlp``
        as ``{rate, pressure}``, each a value with 21 points from the low to the high rate,
        ``operating_point`` as ``{rate, wellhead_pressure, sandface_pressure}``, each a value, and
        ``error``. Under ``on_error="record"`` a case whose bracket leaves the well model's domain
        or has no sign change has ``None`` curves and operating point and its problem in ``error``.
    """
    check_on_error(on_error)
    output = OutputUnits(units)
    chain_plant = deepcopy(plant)
    chain = _chain(chain_plant, well)
    cases = [conditions] if isinstance(conditions, dict) else list(conditions)
    return to_plain(
        {
            "well": well,
            "cases": [_case(chain, case, on_error, output) for case in cases],
        }
    )


def injectivity(data, well, units=None):
    """Return the Hall integral, its derivative and the skin lines of an injection well.

    Parameters
    ----------
    data : Dataset or DataFrame
        Injection history with a UTC time index: wellhead or bottomhole pressure [Pa] and
        injection rate [m3/s].
    well : str
        Dotted path of the injection well in the plant the data belongs to.
    units : dict, optional
        A map from quantity to unit for the returned values.

    Returns
    -------
    dict
        Plain JSON with the Hall integral [Pa s], its derivative against cumulative injected
        volume [Pa s/m3] and the fitted skin lines, each with its unit.

    Raises
    ------
    NotImplementedYet
        Always: the Hall analysis is not built yet.
    """
    raise NotImplementedYet("analysis.injectivity")


def _points(measured):
    """Return the measured head points in SI as a list of ``{flow, frequency, head}``."""
    return [
        {
            "flow": float(
                physics_units.value_in_si(point["flow"], "m3/s", "measured.flow", "volume_flow")
            ),
            "frequency": float(
                physics_units.value_in_si(
                    point["frequency"], "Hz", "measured.frequency", "frequency"
                )
            ),
            "head": float(
                physics_units.value_in_si(
                    point["head"], "Pa", "measured.head", "pressure_difference"
                )
            ),
        }
        for point in measured or ()
    ]


def _correction(points, units):
    """Return the affine correction of theoretical head on measured head, or why it has none."""
    if not points:
        return value(None, "-", "no measured points")
    try:
        return fit_head_correction(
            [point["head"] for point in points],
            [point["theoretical_head"] for point in points],
            units,
        )
    except PhysicsError as error:
        return value(None, "-", str(error))


def _measured_point(point, output):
    """Return one measured point with every number as a value."""
    return {
        "flow": output.value(point["flow"], "m3/s", "volume_flow"),
        "frequency": output.value(point["frequency"], "Hz", "frequency"),
        "head": output.value(point["head"], "Pa", "pressure_difference"),
        "theoretical_head": output.value(point["theoretical_head"], "Pa", "pressure_difference"),
    }


def _head_curve(module, frequency):
    """Return plotting points (flow [m3/s], head [Pa]) of an ESP at a frequency [Hz].

    The flows run from zero to twice the speed-scaled maximum flow; the head is evaluated at the
    flow referred to the reference speed.
    """
    if frequency <= 0:
        raise ValidationError(
            f"{module.path}: positive frequency required; got frequency = {frequency} Hz",
            code="invalid_design",
        )
    scale = frequency / constants.ESP_REFERENCE_FREQUENCY
    return [
        (float(flow), module.head_function(flow / scale, frequency))
        for flow in np.linspace(0, 2 * module.maximum_flow * scale, PUMP_CURVE_POINTS)
    ]


def pump_curve(plant, pump, measured=None, units=None):
    """Return an ESP's head curve at the reference frequency and the fit of measured points.

    The curve is the pump's polynomial head curve (``_head_curve``) at the reference
    frequency of 60 Hz, for flows from zero to twice the maximum flow. Head is a pressure
    difference in Pa; the head of a fluid column in metres is ``head / (density * g)`` with the
    density of the pumped fluid.

    Parameters
    ----------
    plant : Module
        A plant with parameter values.
    pump : str
        Dotted path of an ``ESP``, for example ``"doublet.esp"``.
    measured : list of dict, optional
        Points ``{flow, frequency, head}`` in m3/s, Hz and Pa (SI numbers or ``Quantity`` values).
    units : dict, optional
        A map from quantity to unit for the returned values.

    Returns
    -------
    dict
        Plain JSON ``{pump, frequency, curve, measured, correction}``, every number a value.
        ``curve`` is ``{flow, head}``. Each measured point gains ``theoretical_head`` [Pa], the
        pump's head at its flow and frequency. ``correction`` is ``{slope, offset}`` of the
        least-squares line ``theoretical_head = slope * head + offset`` (offset in Pa), or a value
        ``None`` with a ``reason`` when fewer than two distinct measured heads are given. This is
        the retained ``fit_head_correction``; no module applies the correction yet, so it is a
        diagnosis, not a parameter to set.
    """
    output = OutputUnits(units)
    module = plant.get_submodule(pump)
    if not isinstance(module, ESP):
        raise ValidationError(
            f"pump_curve: pump = {pump!r}; expected the path of an ESP", path=pump
        )
    points = _points(measured)
    for point in points:
        point["theoretical_head"] = float(module.head_function(point["flow"], point["frequency"]))
    reference = constants.ESP_REFERENCE_FREQUENCY.value
    flows, heads = zip(*_head_curve(module, reference))
    return {
        "pump": pump,
        "frequency": output.value(reference, "Hz", "frequency"),
        "curve": {
            "flow": output.value(flows, "m3/s", "volume_flow"),
            "head": output.value(heads, "Pa", "pressure_difference"),
        },
        "measured": [_measured_point(point, output) for point in points],
        "correction": _correction(points, units),
    }


def calibrate_pump(plant, pump, measured):
    """Return the pump parameters that make the model match measured operation.

    Parameters
    ----------
    plant : Module
        A plant with parameter values.
    pump : str
        Dotted path of an ``ESP``.
    measured : Dataset or DataFrame
        Operation with bound ``head``, ``power`` or ``discharge_pressure`` columns and at least
        six distinct flows.

    Returns
    -------
    dict
        Plain JSON ``{pump, params, rms_before, rms_after}``, ``params`` ready for
        ``plant.set_params(pump, params)`` (``head_coefficients`` and ``power_coefficients``).

    Raises
    ------
    NotImplementedYet
        Always: it will run ``gm.analysis.calibrate`` and report the result in this form.
    """
    raise NotImplementedYet("analysis.calibrate_pump")
