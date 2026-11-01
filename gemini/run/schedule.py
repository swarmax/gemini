"""The controls of a plant from its case at each step: an energy balance on design values.

``gm.schedule`` runs no simulation. It returns run input whose columns are named after what they
drive, the dotted path of a control or boundary or ``port.field`` of a plant inlet, in the SI units
``attrs["units"]`` states, so ``gm.simulate(plant, case, plan)`` binds them by the rule of a
run: nothing is stored on the plant and no caller writes a binding. The demand may have any
constant time step, hourly or daily; the plan has one row per step. The role of each unit comes
from the wiring, ``gemini/run/_utils/roles.py``, and the limits from the constraints of the
case, ``gemini/run/_utils/limits.py``. Sources load from the cheapest to the dearest marginal
cost, ``gemini/run/_utils/sources.py``.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from gemini import runtime
from gemini._utils.strings import join_path
from gemini._utils.time import to_utc_index
from gemini.case import roletable
from gemini.errors import ValidationError
from gemini.modules.environment import Atmosphere
from gemini.modules.grids import CoolingGrid, HeatingGrid
from gemini.modules.heating import Boiler, ElectricBoiler
from gemini.modules.piping import Splitter
from gemini.physics import constants, dispatch
from gemini.physics.fluid import mixture_mass_flow
from gemini.plants._utils.plan import members, split_end
from gemini.plants.doublet import Doublet
from gemini.run._utils import limits as limit_forms
from gemini.run._utils import roles, sources
from gemini.run._utils.apply import apply_case

ARRAY_BACKEND = "numpy"
"""A plan is a balance over the steps, on arrays whatever backend the run takes after it."""


@dataclass(frozen=True)
class Source:
    """A heat source at each step: its module path, capacity [W] and marginal cost [currency/J]."""

    path: str
    capacity: np.ndarray
    cost: np.ndarray


def _of_type(plant, kind):
    return [(path, module) for path, module in members(plant) if isinstance(module, kind)]


def _single(plant, kind):
    """Return ``(path, module)`` of the one module of ``kind``, or ``(None, None)``."""
    found = _of_type(plant, kind)
    if len(found) > 1:
        raise ValidationError(
            f"schedule: {len(found)} modules of type {kind.__name__}; expected at most one",
            code="invalid_design",
        )
    return found[0] if found else (None, None)


def _outage_count(demand, step, duration, path):
    """Return the number of outage steps of a doublet that runs ``duration`` of the demand."""
    steps = len(demand)
    running = int(np.floor(duration / step + 0.5))
    if not 0 <= running <= steps:
        raise ValidationError(
            f"schedule: {path} duration = {duration}; expected 0 to {steps} steps of the demand",
            path=f"constraints.{path}",
            code="invalid_value",
        )
    return steps - running


def _lowest_demand_outages(demand, step, limits):
    """Return the outage steps of each doublet that has a duration, ``{path: DatetimeIndex}``.

    The steps of lowest total demand go to the first doublet, the lowest of the rest to the next,
    so at most one doublet is off on a step; of equal steps the earliest goes first. A duration
    that is not a whole number of steps rounds to the nearest whole step. A doublet without a
    duration has no outage.
    """
    index = to_utc_index(demand.index)
    counts = {
        path: (
            0
            if item.operating_time is None
            else _outage_count(demand, step, item.operating_time, path)
        )
        for path, item in limits.items()
    }
    if sum(counts.values()) > len(demand):
        raise ValidationError(
            f"schedule: the durations leave {sum(counts.values())} outage steps for "
            f"{len(counts)} doublets, more than the {len(demand)} steps of the demand",
            path="constraints",
            code="invalid_value",
        )
    heat, cool = _demand_columns(demand)
    ranked = np.argsort(heat + cool, kind="stable")
    outages, place = {}, 0
    for path, count in counts.items():
        outages[path] = index[np.sort(ranked[place : place + count])]
        place += count
    return outages


def _target(plant, path, port):
    """Return the module path that the outlet ``path.port`` feeds, or ``None``."""
    target = plant.target_of(join_path(path, port))
    return split_end(target)[0] if target else None


def _doublets_below(plant, path, doublets):
    """Return the doublets the module at ``path`` feeds, through splitters."""
    if path in doublets:
        return [path]
    if path is None or not isinstance(plant.get_submodule(path), Splitter):
        return []
    return [
        doublet
        for port in ("branch1_out", "branch2_out")
        for doublet in _doublets_below(plant, _target(plant, path, port), doublets)
    ]


def _source_of(plant, path, port):
    """Return ``(path, port)`` of what feeds the inlet ``path.port``, or ``None`` for no module."""
    source = plant.source_of(join_path(path, port))
    return split_end(source) if source else None


def _inlets_behind(plant, path, port):
    """Return the stream inlets of the module at ``path`` that feed its outlet ``port``.

    An outlet follows the inlet of its own circuit (``hot_out``, ``hot_in``); otherwise the module
    has one circuit, and it follows ``fluid_in`` or the branches.
    """
    inlets = plant.get_submodule(path).inlets()
    same = f"{port.removesuffix('_out')}_in"
    if same in inlets:
        return [same]
    return [name for name in inlets if name == "fluid_in" or name.startswith("branch")]


def _doublets_above(plant, path, port, doublets, seen):
    """Return the doublets whose brine reaches the inlet ``path.port``, following the circuit."""
    source = _source_of(plant, path, port)
    if source is None or source in seen:
        return set()
    seen.add(source)
    if source[0] in doublets:
        return {source[0]}
    found = set()
    for inlet in _inlets_behind(plant, *source):
        found |= _doublets_above(plant, source[0], inlet, doublets, seen)
    return found


def _heat_pump_stopped(plant, off, rows):
    """Return, per row, whether every doublet that feeds the heat pump's source is off.

    Its source then carries no flow, which stops it in the run too; a source that no doublet feeds
    never stops it.
    """
    path, _ = roles.heat_pumps(plant)
    if path is None or not any(item.any() for item in off.values()):
        return np.zeros(rows, dtype=bool)
    feeding = _doublets_above(plant, path, "source_in", off, set())
    if not feeding:
        return np.zeros(rows, dtype=bool)
    return np.logical_and.reduce([off[doublet] for doublet in feeding])


def _brine_splits(plant, flows):
    """Return the ``split_fraction`` columns of the splitters that share the injected brine."""
    columns = {}
    for path, _ in _of_type(plant, Splitter):
        first = _doublets_below(plant, _target(plant, path, "branch1_out"), flows)
        second = _doublets_below(plant, _target(plant, path, "branch2_out"), flows)
        if first and second:
            columns[f"{path}.split_fraction"] = dispatch.flow_share(
                sum(flows[item] for item in second), sum(flows[item] for item in first)
            )
    return columns


def _first_load(plant, outlet, loads):
    """Return the first of ``loads`` the outlet ``outlet`` reaches, or ``None``."""
    return next((path for path in plant.feeds(outlet) if path in loads), None)


def _bypass_splits(plant, consumer, chiller, heat, generator):
    """Return the ``split_fraction`` of the splitter that sends drive water past the users.

    The drive water leaves at the setpoint, as the water of the users does, and both come back at
    the return temperature, so the flows divide as the heats do.
    """
    columns = {}
    for path, _ in _of_type(plant, Splitter):
        first = _first_load(plant, join_path(path, "branch1_out"), (consumer, chiller))
        second = _first_load(plant, join_path(path, "branch2_out"), (consumer, chiller))
        if {first, second} == {consumer, chiller}:
            shares = (generator, heat) if first == consumer else (heat, generator)
            columns[f"{path}.split_fraction"] = dispatch.flow_share(*shares)
    return columns


def _return_flow(path, grid, heat, supply):
    """Return the ``flow`` column of a grid whose return carries ``heat`` up to ``supply``."""
    if path is None or grid.return_temperature is None:
        return {}
    specific_heat = grid.fluid.properties(0, 0).cp_l
    difference = abs(supply - grid.return_temperature)
    return {f"{path}.flow": dispatch.circuit_flow(heat, specific_heat, difference)}


def _demand_columns(demand):
    """Return the demand of the steps as arrays [W], cooling zero when the column is absent."""
    if "heating_demand" not in demand:
        raise ValidationError(
            "schedule: demand has no column heating_demand", path="demand", code="missing_column"
        )
    heat = demand["heating_demand"].to_numpy(dtype=float)
    if "cooling_demand" not in demand:
        return heat, np.zeros_like(heat)
    return heat, demand["cooling_demand"].to_numpy(dtype=float)


def _doublet_source(path, doublet, item, off, costs):
    """Return the ``Source`` of a doublet: up to its maximum flow, at the cost of its pump."""
    fluid = doublet.reservoir.fluid.properties(0, 0)
    per_flow = fluid.rho_l * fluid.cp_l * item.brine_cooling
    efficiency = sources.pump_efficiency(doublet, item.brine_cooling, item.maximum_flow)
    capacity = np.where(off[path], 0.0, item.maximum_flow * per_flow)
    return Source(path, capacity, costs.electric(path, efficiency))


def _heat_pump_source(plant, path, limits, stopped, costs):
    """Return the ``Source`` of the heating heat pump: its capacity while it runs, at its COP.

    NOTE(refactor): the source outlet of the COP is the coldest brine of the doublets that feed
    the pump, cooled by their maximum brine cooling.
    """
    module = plant.get_submodule(path)
    feeding = _doublets_above(plant, path, "source_in", limits, set())
    if not feeding:
        raise ValidationError(
            f"schedule: {path}.source_in is fed by no doublet; expected one, because the COP "
            "of the heat pump is estimated from the brine",
            path=f"{path}.source_in",
            code="invalid_design",
        )
    source = min(
        plant.get_submodule(item).reservoir.temperature - limits[item].brine_cooling
        for item in feeding
    )
    cop = sources.heat_pump_cop(module, True, roles.setpoint(plant, path), source)
    return Source(path, np.where(stopped, 0.0, module.capacity), costs.electric(path, cop))


def _heat_sources(plant, limits, off, stopped, costs):
    """Return the heat sources of ``plant`` in plant order: doublets, heat pump, boilers."""
    pump = roles.heat_pumps(plant)[0]
    gas, electric = _single(plant, Boiler)[0], _single(plant, ElectricBoiler)[0]
    found = []
    for path, module in members(plant):
        if path in limits:
            found.append(_doublet_source(path, module, limits[path], off, costs))
        elif path == pump:
            found.append(_heat_pump_source(plant, path, limits, stopped, costs))
        elif path in (gas, electric):
            cost = costs.gas if path == gas else costs.electric
            found.append(_boiler_source(path, module, cost, len(stopped)))
    return found


def _boiler_source(path, module, cost, steps):
    """Return the ``Source`` of a boiler: its capacity, at its efficiency."""
    return Source(path, np.full(steps, float(module.capacity)), cost(path, module.efficiency))


def _drawn_cold(plant, path, kind, heat_costs, costs):
    """Return the cost of a joule of cold from the unit of ``kind`` at ``path``."""
    module = plant.get_submodule(path)
    if kind in roles.HEAT_DRIVEN:
        return sources.drive_cost(heat_costs, module.thermal_cop)
    return sources.compression_cost(costs, plant, path, module)


def _cold_taken(plant, cool, heat_costs, costs):
    """Return ``{kind: cold}`` [W] of each cooling unit, the cheapest first, up to its capacity.

    What no unit takes stays unmet, which the run reports. Without a cold demand no unit loads and
    no price is read.
    """
    units = roles.cooling_units(plant)
    if not cool.any():
        return {kind: np.zeros_like(cool) for kind in units}
    plant_order = [path for path, _ in members(plant)]
    kinds = sorted(units, key=lambda kind: plant_order.index(units[kind]))
    capacities = [np.full_like(cool, plant.get_submodule(units[kind]).capacity) for kind in kinds]
    prices = [_drawn_cold(plant, units[kind], kind, heat_costs, costs) for kind in kinds]
    return dict(zip(kinds, dispatch.loaded_by_cost(cool, capacities, prices)))


def _doublet_columns(plant, limits, takes, off):
    """Return the flow of each doublet [m3/s] and the columns that drive them.

    A doublet off on a step has no flow and leaves its heat to the next source. A doublet with an
    operating duration runs every other step, at the minimum flow without a heat to give.
    """
    flows, columns = {}, {}
    for path, doublet in _of_type(plant, Doublet):
        item = limits[path]
        brine = doublet.reservoir.fluid
        fluid = brine.properties(0, 0)
        heat_per_flow = fluid.rho_l * fluid.cp_l * item.brine_cooling
        flow, _ = dispatch.doublet_flow(
            takes[path], heat_per_flow, item.minimum_flow, item.maximum_flow
        )
        least = 0.0 if item.operating_time is None else item.minimum_flow
        flow = np.where(off[path], 0.0, np.maximum(flow, least))
        flows[path] = flow
        columns[f"{path}.flow"] = flow
        columns[f"{path}.is_running"] = flow > 0
        columns[f"{path}.reservoir.production_rate"] = mixture_mass_flow(
            flow, brine.gas_mass_fraction, fluid.rho_l
        )
        columns[f"{path}.esp.frequency"] = np.full_like(
            flow, float(constants.ESP_REFERENCE_FREQUENCY)
        )
    return flows, columns


def _heating_columns(plant, heat, carried):
    """Return the columns of the heat users, the heat pump, the boilers and the return flow.

    The users take ``heat``; ``carried`` is the heat of the water that passes them.
    """
    columns, supply = {}, None
    path, grid = _single(plant, HeatingGrid)
    if path is not None:
        columns[f"{path}.heat_demand"] = heat
    units = (
        roles.heat_pumps(plant)[0],
        _single(plant, Boiler)[0],
        _single(plant, ElectricBoiler)[0],
    )
    for unit_path in units:
        if unit_path is not None:
            supply = roles.setpoint(plant, unit_path)
            columns[f"{unit_path}.temperature_setpoint"] = np.full_like(heat, supply)
    if supply is not None:
        columns |= _return_flow(path, grid, carried, supply)
    return columns


def _in_series(plant, grid_path, units):
    """Return the paths of the cooling units in the order the chilled water meets them."""
    met = [] if grid_path is None else plant.feeds(join_path(grid_path, "return_out"))
    return sorted(units, key=lambda path: met.index(path) if path in met else len(met))


def _unit_setpoints(path, grid, chain, taken, cool, supply):
    """Return the setpoint of each cooling unit of a chain on one chilled water circuit.

    The last unit brings the water to ``supply``. A unit before it stops at the temperature that
    leaves the rest of the cold to the units after it.
    """
    setpoints = {chain[-1]: np.full_like(cool, supply)}
    if len(chain) == 1 or grid.return_temperature is None:
        return setpoints | {unit: setpoints[chain[-1]] for unit in chain}
    done = np.zeros_like(cool)
    for unit in chain[:-1]:
        done = done + taken[unit]
        setpoints[unit] = dispatch.temperature_after(
            grid.return_temperature, supply, dispatch.flow_share(done, cool - done)
        )
    return setpoints


def _cooling_columns(plant, cool, taken):
    """Return the columns of the cooling users, the cooling units and the return flow."""
    columns = {}
    path, grid = _single(plant, CoolingGrid)
    if path is not None:
        columns[f"{path}.sensible_cooling_demand"] = cool
        columns[f"{path}.latent_cooling_demand"] = np.zeros_like(cool)
    units = roles.cooling_units(plant)
    if not units:
        return columns
    chain = _in_series(plant, path, list(units.values()))
    supply = roles.setpoint(plant, chain[-1])
    by_path = {units[kind]: taken.get(kind, np.zeros_like(cool)) for kind in units}
    for unit, setpoint in _unit_setpoints(path, grid, chain, by_path, cool, supply).items():
        columns[f"{unit}.temperature_setpoint"] = setpoint
    return columns | _return_flow(path, grid, cool, supply)


def schedule(plant, case):
    """Return the run input of ``plant`` for each step of the demand of ``case``.

    An energy balance of each step on the design values, with no simulation inside. The values of
    the case are set for the plan on a copy (``apply_case``), ``plant`` itself never changes.
    Roles come from the wiring (``gemini/run/_utils/roles.py``): a unit that feeds the
    ``CoolingGrid`` is a cooling unit, a ``HeatPump`` included, which is then the compression
    chiller.

    Every heat and cold source gets a marginal cost at each step, ``price / efficiency +
    co2_price * emission``, from ``case.assumptions`` (``finance.opex``, ``emissions``) and the
    efficiency of its module (the COP of a heat pump or chiller, the efficiency of a boiler, the
    pump electricity of a doublet, the ``thermal_cop`` of a heat-driven chiller on the cheapest
    heat). Sources load from the cheapest
    to the dearest up to their capacity, ties in plant order. Unmet demand is no error: the run
    reports it. A heat-driven unit needs its cold over its ``thermal_cop`` of heat, which adds to
    the heat need, and the compression chiller adds electricity, its condenser heat going to its
    cooler. Doublets, in plant order, each run at the flow that gives their heat at no more than
    the maximum brine cooling, clipped to the flow range, and below the minimum at the minimum
    with less cooling.

    The schedule enforces the constraints it knows by role and quantity (``_utils/limits.py``),
    each applying to every ``doublet``: a flow range (``production_flow``, ``over="each"``,
    ``when="running"``, ``min`` and ``max``), a maximum brine cooling (``brine_cooling``, ``max``)
    and optionally an operating duration (``production_flow``, ``over="duration"``,
    ``when="running"``, ``max`` or ``equals``, such as 330 d). The outage steps are the steps of
    lowest total demand, heating plus cooling, the first doublet taking the lowest, the next the
    lowest left, so at most one doublet is off on a step; a duration rounds to the nearest whole
    step of ``case.time``. On an outage step a doublet has no flow and its heat
    goes to the next sources, and a heat pump fed only by doublets that are off stops. Every other
    step a doublet with a duration runs, at the minimum flow when no heat is left for it. Every
    other constraint is listed in ``attrs["check_only"]``.

    Parameters
    ----------
    plant : Plant
        The design: its ``Doublet`` children, at most one unit per role and kind (a heating
        ``HeatPump``, a ``Boiler``, an ``ElectricBoiler``, an absorption, an adsorption and a
        compression chiller) and at most one ``HeatingGrid`` and ``CoolingGrid``, with the
        ``temperature_setpoint`` of the heat pump, the boilers and the last cooling unit set with
        ``set_inputs``, and that of the cooler of the compression chiller when cold is demanded.
        ``ATESPlant`` is not scheduled: its three seasonal commands are inputs of a run. Plant
        ports named ``heating_return`` and ``cooling_return`` take their temperature from the
        inputs (``heating_return.T``) and get their flow from the plan.
    case : Case
        The time, environment, demand (``case.demand.frame``, in W on ``case.time.index``),
        constraints and the assumptions with the prices.

    Returns
    -------
    DataFrame
        The index of the demand, the demand columns, one column per scheduled control, named
        after its dotted path, ``port.m_dot`` of the return ports, and ``boiler_duty``,
        ``<doublet>.flow``, ``<doublet>.is_running`` and ``<heat pump>.is_running`` for reading,
        in SI with units in ``attrs["units"]``. ``attrs["outages"]`` is
        ``{doublet path: [time]}``, the ISO time of each outage step and ``attrs["check_only"]``
        the ``to_dict()`` of each constraint left to the check. ``gm.simulate(plant, case,
        plan=plan)`` needs no bindings: a run binds a control to a column of that name.

    Raises
    ------
    ValidationError
        ``missing_value`` for a flow range or brine cooling constraint of a doublet that the
        case lacks, or a value of the environment the plant needs; ``missing_assumption`` for a
        price a source of the plant needs; ``invalid_value`` for a duration that needs more outage
        steps than the demand has; ``invalid_design`` for a missing setpoint or a role that breaks
        the wiring.
    """
    return scheduled(apply_case(plant, case), case)


def scheduled(plant, case):
    """Return the plan of ``schedule`` for a ``plant`` that already has the values of ``case``."""
    plant._check_design()
    demand = case.demand.frame
    doublets = roletable.units_of(plant, "doublet")
    limits, check_only = limit_forms.split(case.constraints, doublets)
    step = pd.Timedelta(seconds=case.time.step)
    outages = _lowest_demand_outages(demand, step, limits)
    costs = sources.Costs(case)
    with runtime.settings(backend=ARRAY_BACKEND):
        columns = _plan_columns(plant, demand, limits, outages, costs)
        columns |= _air_columns(plant, case)
        return _frame(plant, demand, columns, outages, check_only)


def _air_columns(plant, case):
    """Return the air temperature of each step as a column of each ``Atmosphere``, for a profile."""
    air = case.environment.air.temperature if case.environment and case.environment.air else None
    if not isinstance(air, np.ndarray):
        return {}
    return {
        f"{path}.temperature": air
        for path, module in members(plant)
        if isinstance(module, Atmosphere)
    }


def _plan_columns(plant, demand, limits, outages, costs):
    """Return the columns of the plan, computed on arrays over the steps."""
    heat, cool = _demand_columns(demand)
    index = to_utc_index(demand.index)
    off = {path: index.isin(times) for path, times in outages.items()}
    stopped = _heat_pump_stopped(plant, off, len(demand))
    found = _heat_sources(plant, limits, off, stopped, costs)
    taken = _cold_taken(plant, cool, [item.cost for item in found], costs)
    generator = _drive_heat(plant, taken, heat)
    loads = dispatch.loaded_by_cost(
        heat + generator, [item.capacity for item in found], [item.cost for item in found]
    )
    takes = {item.path: load for item, load in zip(found, loads)}
    flows, columns = _doublet_columns(plant, limits, takes, off)
    columns |= _brine_splits(plant, flows)
    consumer, _ = _single(plant, HeatingGrid)
    bypass = _bypass_splits(plant, consumer, _first_driven(plant), heat, generator)
    columns |= bypass
    columns |= _heating_columns(plant, heat, heat if bypass else heat + generator)
    heat_pump = roles.heat_pumps(plant)[0]
    if heat_pump is not None:
        columns[f"{heat_pump}.is_running"] = ~stopped
    columns |= _cooling_columns(plant, cool, taken)
    columns["boiler_duty"] = _boiler_duty(plant, takes, heat + generator, flows, limits)
    return columns


def _first_driven(plant):
    """Return the path of the first heat-driven cooling unit, or ``None``."""
    units = roles.cooling_units(plant)
    return next((units[kind] for kind in roles.HEAT_DRIVEN if kind in units), None)


def _drive_heat(plant, taken, heat):
    """Return the heat [W] the heat-driven cooling units draw for the cold they take."""
    units = roles.cooling_units(plant)
    drive = np.zeros_like(heat)
    for kind in roles.HEAT_DRIVEN:
        if kind in taken:
            drive = drive + taken[kind] / plant.get_submodule(units[kind]).thermal_cop
    return drive


def _boiler_duty(plant, takes, need, flows, limits):
    """Return the heat [W] that the doublets and the other sources leave for the gas boiler.

    On design values: the need less the heat of the doublets at their flows, the heat pump and the
    electric boiler.
    """
    heat = need.copy()
    for path, doublet in _of_type(plant, Doublet):
        fluid = doublet.reservoir.fluid.properties(0, 0)
        heat -= flows[path] * fluid.rho_l * fluid.cp_l * limits[path].brine_cooling
    for path in (roles.heat_pumps(plant)[0], _single(plant, ElectricBoiler)[0]):
        if path is not None:
            heat -= takes[path]
    return np.maximum(heat, 0.0)


def _frame(plant, demand, columns, outages, check_only):
    """Return the plan on the index of ``demand`` with its units and outages in ``attrs``.

    A column that drives an input states the SI unit of it, which wins over the unit of a binding
    of that name, so a run reads the plan in SI whatever the plant was measured in.
    """
    data = {name: demand[name].to_numpy() for name in demand}
    frame = pd.DataFrame(data | columns, index=demand.index)
    driven = {path: item.unit for path, item in plant.inputs().items() if path in columns}
    frame.attrs["units"] = dict(demand.attrs.get("units", {})) | driven
    frame.attrs["outages"] = {
        path: [time.isoformat() for time in times] for path, times in outages.items()
    }
    frame.attrs["check_only"] = check_only
    return frame
