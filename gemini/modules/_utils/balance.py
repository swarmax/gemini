"""Mass and sensible-energy audits over retained evaluation trees.

A leaf exchanges energy outside its streams through its ports: ``power_in`` and ``power_out`` carry
electricity and ``loss_out`` heat to the surroundings, signed. ``fuel`` is the one energy on no port
of a leaf, and ``heat_accumulation`` the rate of increase of the energy a leaf stores, counted as
an outflow. The legacy isothermal pumps do not allocate electricity to fluid enthalpy, mechanical
work or environmental loss. Report that unresolved energy explicitly; never manufacture heat loss
to force a first-law residual to zero.
"""

from dataclasses import dataclass
from functools import partial

from gemini import ops
from gemini.modules.piping import GasMakeup
from gemini.modules.pumps import ESP, CentrifugalPump, InjectionPump, LineShaftPump
from gemini.modules.subsurface import InjectionReservoir, ProductionReservoir
from gemini.physics import combustion, diagnostics, heat_transfer
from gemini.types.flows import Stream

ENERGY_INPUTS = ("electricity", "fuel", "heat_absorbed")
"""Energy [W] that enters a leaf from outside its streams, as ``collect_flows`` names it."""

ENERGY_OUTPUTS = ("heat_loss", "electricity_generated", "heat_accumulation")
"""Energy [W] that leaves a leaf other than through its streams.

All are nonnegative except ``heat_accumulation``, the signed rate of change of stored energy.
"""


EDGE_CATEGORIES = ("grids", "environment")
"""The categories of the modules at the plant's edge."""


@dataclass
class Ledger:
    """What one leaf exchanges, read from a call or from the columns of a run.

    ``inlets`` and ``outlets`` are the ``(mass [kg/s], enthalpy [W])`` of its one-stream ports,
    without the flue, which is what burning left. ``flows`` are the energies of
    ``ENERGY_INPUTS`` and ``ENERGY_OUTPUTS``, ``burned`` the ``(mass, enthalpy)`` of the gas
    that ends in the leaf and ``flow_work`` [W] the pressure energy a centrifugal pump gives.
    """

    inlets: list
    outlets: list
    flows: dict
    burned: tuple
    flow_work: float


def _port_power(ports, name):
    """Return the power of port ``name`` of a leaf; a grid's list is not the leaf's own energy."""
    power = ports[name] if name in ports else 0.0
    return 0.0 if isinstance(power, list) else power


def _flows(power_in, fuel, loss_out, power_out, accumulation):
    """Return the energy flows [W] of a leaf by the names of ``collect_flows``."""
    loss, absorbed = heat_transfer.signed_parts(loss_out)
    return {
        "electricity": power_in,
        "fuel": fuel,
        "heat_absorbed": absorbed,
        "heat_loss": loss,
        "electricity_generated": power_out,
        "heat_accumulation": accumulation,
    }


def _leaf_flows(result):
    """Return the energy flows of one leaf call, read from its ports."""
    return _flows(
        _port_power(result.inlets, "power_in"),
        result.outputs.get("fuel", 0.0),
        _port_power(result.outlets, "loss_out"),
        _port_power(result.outlets, "power_out"),
        result.outputs.get("heat_accumulation", 0.0),
    )


def _call_ledger(result):
    """Return the ledger of one leaf call."""
    return Ledger(
        [(stream.m_dot, _enthalpy(stream)) for stream in _streams(result.inlets)],
        [(stream.m_dot, _enthalpy(stream)) for stream in _streams(result.outlets)],
        _leaf_flows(result),
        _burned_of_call(result),
        result.outputs.get("hydraulic_power", 0.0),
    )


def _burned_of_call(result):
    """Return the ``(mass, enthalpy)`` of the gas a burner took or a flare burned."""
    port = _burn_port(result.inlets, result.outputs)
    if port is None:
        return 0.0, 0.0
    return result.inlets[port].m_dot, _enthalpy(result.inlets[port])


def _burn_port(inlets, outputs):
    """Return the name of the inlet whose gas ends in the leaf, ``None`` if it has none."""
    if "fuel_in" in inlets:
        return "fuel_in"
    return "gas_in" if "burned_mass_flow" in outputs else None


def _stream_columns(ports, read):
    """Return the ``(mass, enthalpy)`` columns of the one-stream ports of a leaf."""
    return [
        (read(f"{name}.mass_flow"), read(f"{name}.enthalpy_flow"))
        for name, port in ports.items()
        if port.carries_stream and not port.many and name != "flue_out"
    ]


def _power_column(ports, name, read):
    """Return the column of power port ``name``; a grid's list is not the leaf's own energy."""
    return read(name) if name in ports and not ports[name].many else 0.0


def column_ledger(module, read):
    """Return the ledger of leaf ``module`` over a run; ``read(field)`` gives a column or zero."""
    inlets, outlets = module._inlets, module._outlets
    port = _burn_port(inlets, module._outputs)
    burned = (0.0, 0.0)
    if port is not None:
        burned = (read(f"{port}.mass_flow"), read(f"{port}.enthalpy_flow"))
    flows = _flows(
        _power_column(inlets, "power_in", read),
        read("fuel"),
        _power_column(outlets, "loss_out", read),
        _power_column(outlets, "power_out", read),
        read("heat_accumulation"),
    )
    return Ledger(
        _stream_columns(inlets, read),
        _stream_columns(outlets, read),
        flows,
        burned,
        read("hydraulic_power"),
    )


def collect_flows(result_tree):
    """Sum the energy flows of the leaves once, read from their ports [W]."""
    if isinstance(result_tree, dict):
        totals = [collect_flows(child) for child in result_tree.values()]
        return {key: sum(t[key] for t in totals) for key in ENERGY_INPUTS + ENERGY_OUTPUTS}
    if result_tree.children:
        return collect_flows(result_tree.children)
    return _leaf_flows(result_tree)


def emissions(result_tree, fuel_factor, electricity_factor):
    """Return the CO2 emission rate [kg/s] of the fuel burnt and the grid electricity drawn.

    ``fuel * fuel_factor + max(0, electricity - electricity_generated) * electricity_factor``
    over the leaf totals of ``collect_flows``, for any plant topology. Factors are SI [kg/J]:
    divide kg/GJ by 1e9 and kg/kWh by 3.6e6. All on-site generation (``CHP``, ``ORC``, any
    ``power_out``) offsets the electricity of all consumers (ESP, pumps,
    compressors, heat pumps) before grid electricity is charged, and a surplus earns no credit.
    The upstream GEMINI KPI offset only the ESP's electricity by the CHP and charged the
    injection pump in full. Fuel is
    charged on its full lower-heating-value input, also when it feeds a generator, so CHP
    electricity is not charged twice. Gas released reaches ``Atmosphere.gas_in``, which reports
    it in its ``co2_emission`` output, and is not included.
    """
    flows = collect_flows(result_tree)
    grid = ops.maximum(0.0, flows["electricity"] - flows["electricity_generated"])
    return combustion.emission_rate(flows["fuel"], fuel_factor, grid, electricity_factor)


def scale(incoming, outgoing):
    """Return the larger magnitude of the two flows, at least one, to normalise a residual."""
    return ops.maximum(ops.maximum(ops.abs(incoming), ops.abs(outgoing)), 1)


def _enthalpy(stream):
    """Return the enthalpy rate [W] of a stream above 0 K."""
    return heat_transfer.heat_rate(stream.heat_capacity_rate(), stream.T)


def _streams(ports):
    """Return the streams of ``ports``; the flue is what burning left, already counted as burned."""
    return [
        value for name, value in ports.items() if isinstance(value, Stream) and name != "flue_out"
    ]


def _internal_flux(result, measure):
    """Cancel streams actually passed between leaves in evaluation order, once per output."""
    available = {}
    internal = 0.0
    for leaf in result.leaves().values():
        for stream in _streams(leaf.inlets):
            if available.get(id(stream), 0):
                internal += measure(stream)
                available[id(stream)] -= 1
        for stream in _streams(leaf.outlets):
            available[id(stream)] = available.get(id(stream), 0) + 1
    return internal


def mass_balance(module, result):
    """Audit mass [kg/s], including explicit aquifer withdrawal/deposition boundaries."""
    if result.children:
        children = {
            path: mass_balance(module.get_submodule(path), child)
            for path, child in result.leaves().items()
        }
        incoming = sum(c["in"] for c in children.values())
        outgoing = sum(c["out"] for c in children.values())
        internal = _internal_flux(result, lambda stream: stream.m_dot)
        incoming -= internal
        outgoing -= internal
        residual = sum(c["residual"] for c in children.values())
    else:
        children = {}
        incoming, outgoing = leaf_mass(module, _call_ledger(result))
        residual = incoming - outgoing
    return {
        "in": incoming,
        "out": outgoing,
        "residual": residual,
        "relative_residual": diagnostics.performance_ratio(
            ops.abs(residual), scale(incoming, outgoing)
        ),
        "modules": children,
    }


def _is_edge(module):
    """Return whether ``module`` is at the plant's edge: what enters it left the plant."""
    return module.category in EDGE_CATEGORIES


def leaf_mass(module, ledger):
    """Return a leaf's mass in- and outflow, counting aquifers and edges as open boundaries."""
    incoming = sum(mass for mass, _ in ledger.inlets)
    outgoing = sum(mass for mass, _ in ledger.outlets)
    if _is_edge(module):
        return incoming + outgoing, incoming + outgoing
    if isinstance(module, ProductionReservoir):
        incoming += outgoing
    elif isinstance(module, InjectionReservoir):
        outgoing += incoming
    return incoming, outgoing + ledger.burned[0]


def energy_balance(module, result):
    """Return sensible enthalpy/energy fluxes [W] and an honest sum(in)-sum(out).

    Aquifers are open source/sink boundaries. Pressure, gravity and kinetic energy
    are not represented in this thermal model. `thermal_residual` audits modeled
    thermal transfers; `residual` ALSO includes unallocated pump electricity.
    A nonzero `unresolved_power` means full energy conservation is unverified.
    """
    flows = collect_flows(result)
    if result.children:
        totals = _composite_energy(module, result)
    else:
        totals = leaf_energy(module, _call_ledger(result))
        totals["heat_delivered"] = getattr(result.outputs, "duty", 0.0)
    incoming, outgoing, residual, unresolved = (
        totals[key] for key in ("in", "out", "residual", "unresolved_power")
    )
    normaliser = scale(incoming, outgoing)
    return flows | {
        "heat_delivered": totals["heat_delivered"],
        "losses": flows["heat_loss"],
        "in": incoming,
        "out": outgoing,
        "residual": residual,
        "relative_residual": diagnostics.performance_ratio(ops.abs(residual), normaliser),
        "unresolved_power": unresolved,
        "thermal_residual": residual - unresolved,
        "relative_thermal_residual": diagnostics.performance_ratio(
            ops.abs(residual - unresolved), normaliser
        ),
        "modules": totals["modules"],
    }


def _composite_energy(module, result):
    """Sum the leaf audits of a composite and cancel streams passed between its leaves."""
    children = {
        path: energy_balance(module.get_submodule(path), child)
        for path, child in result.leaves().items()
    }
    internal = _internal_flux(result, _enthalpy)
    return {
        "residual": sum(c["residual"] for c in children.values()),
        "unresolved_power": sum(c["unresolved_power"] for c in children.values()),
        "in": sum(c["in"] for c in children.values()) - internal,
        "out": sum(c["out"] for c in children.values()) - internal,
        "heat_delivered": getattr(result.outputs, "thermal_power", 0.0),
        "modules": children,
    }


def leaf_energy(module, ledger):
    """Audit one leaf; aquifers are open boundaries.

    NOTE(refactor): isothermal legacy pumps lack a thermodynamic work/loss model, so their
    electricity is reported as ``unresolved_power``. This term exposes missing bookkeeping; it is
    NOT a modeled heat-loss port.
    """
    flows = ledger.flows
    incoming = sum(enthalpy for _, enthalpy in ledger.inlets)
    outgoing = sum(enthalpy for _, enthalpy in ledger.outlets)
    if _is_edge(module):
        incoming = outgoing = incoming + outgoing
    elif isinstance(module, ProductionReservoir):
        incoming += outgoing
    elif isinstance(module, InjectionReservoir):
        outgoing += incoming
    incoming += sum(flows[key] for key in ENERGY_INPUTS)
    outgoing += sum(flows[key] for key in ENERGY_OUTPUTS) + ledger.burned[1]
    return {
        "residual": incoming - outgoing,
        "unresolved_power": _unresolved_power(module, ledger),
        "in": incoming,
        "out": outgoing,
        "heat_delivered": 0.0,
        "modules": {},
    }


def _unresolved_power(module, ledger):
    """Return what the audit cannot allocate [W].

    An isothermal pump does not allocate its electricity. ``GasMakeup`` mixes two gases and no
    fluid holds the mixture: ``fuel_out`` is valued at the heat capacity of the co-produced gas,
    so the sensible heat of the purchased gas changes by the difference.
    """
    if isinstance(module, (ESP, InjectionPump, LineShaftPump)):
        return ledger.flows["electricity"]
    if isinstance(module, GasMakeup):
        incoming = sum(enthalpy for _, enthalpy in ledger.inlets)
        return incoming - sum(enthalpy for _, enthalpy in ledger.outlets)
    return 0.0


def flow_work(module, ledger):
    """Return the pressure energy [W] a centrifugal pump gives, which the audit does not value."""
    return ledger.flow_work if isinstance(module, CentrifugalPump) else 0.0


def _is_boundary(module):
    """Return whether the ports of ``module`` bound the plant: an edge module or an aquifer."""
    return _is_edge(module) or isinstance(module, (ProductionReservoir, InjectionReservoir))


def _add_port(totals, side, port, name, read):
    """Add what port ``name`` carries to ``side`` of the ``totals``."""
    if not port.carries_stream:
        totals[f"energy_{side}"] += read(name)
        return
    totals[f"mass_{side}"] += read(f"{name}.mass_flow")
    totals[f"energy_{side}"] += read(f"{name}.enthalpy_flow") + read(f"{name}.chemical_flow")


def _add_boundary(totals, module, read):
    """Add the ports of a boundary module: what it gives enters the plant, what it takes leaves."""
    for name, port in module._outlets.items():
        _add_port(totals, "in", port, name, read)
    for name, port in module._inlets.items():
        _add_port(totals, "out", port, name, read)


def _add_root_ports(totals, plant, ends, read):
    """Add the plant ports of a building block run alone, read at the leaf ports they reach."""
    for side, section in (("in", "inlets"), ("out", "outlets")):
        for path, port in ends[section]:
            declared = getattr(plant.get_submodule(path), f"_{section}")[port]
            _add_port(totals, side, declared, port, partial(read, path))


def _add_burning(totals, ledger, read):
    """Add what burning takes: combustion air is not modelled, so a flue is not the gas burned."""
    mass, enthalpy = ledger.burned
    totals["mass_out"] += mass - read("flue_out.mass_flow")
    totals["energy_out"] += enthalpy - read("flue_out.enthalpy_flow")


def plant_totals(plant, ends, read):
    """Return what crosses the plant's edge over a run, in columns of ``read(path, field)``.

    ``mass_in``, ``mass_out`` [kg/s], ``energy_in``, ``energy_out`` [W] are the ports of the grids
    and environment modules, with the aquifers (a reservoir is the one open boundary that is
    not an edge module) and the plant ports of a building block run alone; gas counts with its
    chemical power. ``energy_out`` also holds the change of stored energy. ``unresolved`` [W] is
    what the audit does not value: the electricity of the isothermal pumps and flow work.
    ``ends`` gives the leaf ends ``(path, port)`` of the plant's ``inlets`` and ``outlets``.
    """
    totals = dict.fromkeys(("mass_in", "mass_out", "energy_in", "energy_out", "unresolved"), 0.0)
    leaves = [(path, module) for path, module in plant.named_modules() if module.is_leaf]
    for path, module in leaves:
        ledger = column_ledger(module, partial(read, path))
        totals["energy_out"] += ledger.flows["heat_accumulation"]
        totals["unresolved"] += _unresolved_power(module, ledger) + flow_work(module, ledger)
        _add_burning(totals, ledger, partial(read, path))
        if _is_boundary(module):
            _add_boundary(totals, module, partial(read, path))
    _add_root_ports(totals, plant, ends, read)
    return totals
