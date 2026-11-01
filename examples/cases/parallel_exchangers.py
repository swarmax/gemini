"""Doublet with three parallel heat exchangers and nodal-solved production and injection.

The port of the upstream GEMINI simulator's ``parallel_hex_plant`` example: an 18-stage ESP at
550 m in a deviated well is solved for its rate at the measured 10 bar wellhead pressure, the
brine passes three exchangers in 50/30/20 shares, and the injection pump is set to the wellhead
pressure the injector needs. Well, reservoir, ESP and exchanger data are the upstream example's.

Upstream fitted the injectivity index, 2.3 m3/h/bar, to 44.47 bar at 125.1 m3/h with a traversal
that adds the injector's friction instead of subtracting it. With the correct sign that index needs
54.86 bar, so the case recalibrates it from the same point and runs with both indices.

Shows ``gm.plants.example("ParallelExchangerPlant")``, which holds a ``NodalDoublet``,
``get``, a direct plant call, ``gm.modules.collect_flows`` and ``gm.evaluate.plant_balance``.

Run with ``python examples/cases/parallel_exchangers.py``.
"""

import gemini as gm

SECONDARY = gm.Stream(
    flow={"value": 125.1, "unit": "m3/h"},
    T={"value": 20, "unit": "degC"},
    p={"value": 3, "unit": "bar"},
    fluid=gm.Fluid(kind="water"),
)
FITTED_INJECTION = gm.Stream(
    flow={"value": 125.1, "unit": "m3/h"},
    T={"value": 70, "unit": "degC"},
    p={"value": 44.47, "unit": "bar"},
)
"""Injector wellhead point of the upstream fit; the temperature does not enter the traversal."""

INPUTS = {
    "doublet.esp.frequency": {"value": 60, "unit": "Hz"},
    "doublet.wellhead_pressure": {"value": 10, "unit": "bar"},
    "primary_splitters.0.split_fraction": 0.5,
    "primary_splitters.1.split_fraction": 0.6,
    "secondary_splitters.0.split_fraction": 0.5,
    "secondary_splitters.1.split_fraction": 0.6,
}


def command(plant, inputs):
    """Set each control or boundary, named by its path, on its module."""
    for path, value in inputs.items():
        declaration = plant.get(path)
        setattr(declaration.owner, declaration.name, value)


def recalibrated_injectivity(doublet):
    """Return the injectivity index [m3/s/Pa] that reproduces ``FITTED_INJECTION``."""
    bottom = doublet.injector(wellhead_in=FITTED_INJECTION).outlets.bottom_out
    flow = abs(bottom.m_dot) / doublet.sink.fluid.properties(bottom.p, bottom.T).rho_l
    return doublet.sink.injectivity_from_measurements(flow, bottom.p)


def print_injection(label, index, result):
    """Print the injection pressure and the pump power of one injectivity index."""
    outputs = result.children["doublet.injection_pump"].outputs
    print(
        f"Injectivity {label:<12}     {gm.units.convert(index, 'm3/s/Pa', 'm3/h/bar'):.4f} "
        f"m³/h/bar: injection {outputs.get('discharge_pressure', unit='bar'):.2f} bar, "
        f"pump {outputs.get('power', unit='kW'):.1f} kW"
    )


def print_exchangers(result):
    """Print the duty and the secondary outlet of each exchanger, and their sum."""
    duties = []
    for index in range(3):
        outputs = result.children[f"heat_exchangers.{index}"].outputs
        duties.append(outputs.get("duty", unit="kW"))
        print(
            f"Exchanger {index + 1}:                 {duties[-1]:.1f} kW, "
            f"secondary out {outputs.get('cold_out_T', unit='degC'):.2f} °C"
        )
    print(f"Total duty:                  {sum(duties):.1f} kW")


def main():
    """Run the plant with the upstream and the recalibrated injectivity and print the second."""
    plant = gm.plants.example("ParallelExchangerPlant")
    command(plant, INPUTS)
    upstream_index = plant.doublet.sink.injectivity_index
    upstream = plant(return_in=SECONDARY)
    injectivity = recalibrated_injectivity(plant.doublet)
    plant.doublet.sink.set_params("", {"injectivity_index": injectivity})
    result = plant(return_in=SECONDARY)
    rate = result.children["doublet.riser"].outlets.wellhead_out.m_dot
    flow = gm.units.convert(rate / 1000, "m3/s", "m3/h")
    outlet = gm.units.convert(result.outlets.supply_out.T, "K", "degC")
    electricity = gm.modules.collect_flows(result)["electricity"]
    print("Assumption: 80 °C reservoir; upstream fixes the wellhead temperature at 77 °C")
    print(f"Primary flow (nodal solve):  {flow:.2f} m³/h")
    print_injection("upstream", upstream_index, upstream)
    print_injection("recalibrated", injectivity, result)
    print_exchangers(result)
    print(f"Secondary outlet:            {outlet:.2f} °C")
    print(f"Electricity (ESP and pump):  {electricity / 1e6:.4f} MW")
    print(f"Mass residual:               {gm.modules.mass_balance(plant, result)['residual']} kg/s")
    closed = all(check["passed"] for check in gm.evaluate.plant_balance(plant, None, result))
    print(f"Plant balance closes:        {closed}")


if __name__ == "__main__":
    main()
