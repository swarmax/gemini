"""Doublet with a nodal-solved production rate and a boiler and CHP on the secondary network.

The port of the upstream GEMINI simulator's ``doublet_plant`` example. The producer is solved for
its rate at a 3 bar wellhead pressure and the injector for the pump head it needs: its 3100 m
column already over-delivers, so the injection pump draws nothing. 140 m3/h of 20 degC water is
split in two: one half is heated by the exchanger and topped up by a gas boiler, the other by a
gas-engine CHP. Well, reservoir and ESP data are the upstream example's. The boiler and CHP design
values are this case's own, because upstream drives both by a gas flow.

Shows ``gm.plants.example("BoilerChpPlant")``, which holds a ``NodalDoublet``, ``get``,
``gm.modules.collect_flows``, ``gm.modules.emissions`` and ``gm.evaluate.plant_balance``.

Run with ``python examples/cases/boiler_chp.py``.
"""

import gemini as gm

SECONDARY = gm.Stream(
    flow={"value": 140, "unit": "m3/h"},
    T={"value": 20, "unit": "degC"},
    p={"value": 3, "unit": "bar"},
    fluid=gm.Fluid(kind="water"),
)
GAS_FACTOR = 56.6 / 1e9
"""CO2 emitted per joule of natural gas [kg/J]: 56.6 kg/GJ, the upstream factor."""

GRID_FACTOR = 0.3 / gm.units.convert(1, "kWh", "J")
"""CO2 emitted per joule of grid electricity [kg/J]: 0.3 kg/kWh, the upstream factor."""

INPUTS = {
    "doublet.esp.frequency": {"value": 65, "unit": "Hz"},
    "doublet.wellhead_pressure": {"value": 3, "unit": "bar"},
    "splitter.split_fraction": 0.5,
    "boiler.temperature_setpoint": {"value": 70, "unit": "degC"},
    "chp.load_fraction": 1.0,
    "air.temperature": {"value": 10, "unit": "degC"},
}


def command(plant, inputs):
    """Set each control or boundary, named by its path, on its module."""
    for path, value in inputs.items():
        declaration = plant.get(path)
        setattr(declaration.owner, declaration.name, value)


def main():
    """Run the plant once and print its energy flows and emissions."""
    plant = gm.plants.example("BoilerChpPlant")
    command(plant, INPUTS)
    result = plant(return_in=SECONDARY)
    flows = gm.modules.collect_flows(result)
    rate = result.children["doublet.riser"].outlets.wellhead_out.m_dot
    flow = gm.units.convert(rate / 1000, "m3/s", "m3/h")
    duty = result.children["heat_exchanger"].outputs.get("duty", unit="MW")
    outlet = gm.units.convert(result.outlets.supply_out.T, "K", "degC")
    injection_pump = result.children["doublet.injection_pump"].outputs.power
    emitted = gm.modules.emissions(result, GAS_FACTOR, GRID_FACTOR) * 86400
    print("Assumptions: 3 MW boiler at 80 %, 400 kW CHP, 56.6 kg CO2/GJ, 0.3 kg CO2/kWh")
    print(f"Primary flow (nodal solve):  {flow:.2f} m³/h")
    print(f"Exchanger duty:              {duty:.3f} MW")
    print(f"Secondary outlet:            {outlet:.2f} °C")
    print(f"Gas burnt:                   {flows['fuel'] / 1e6:.3f} MW")
    print(f"CHP electricity:             {flows['electricity_generated'] / 1e6:.3f} MW")
    print(f"Electricity used:            {flows['electricity'] / 1e6:.3f} MW")
    print(f"Injection pump:              {injection_pump:.1f} W (no pump needed)")
    print(f"CO2 emissions:               {emitted:.0f} kg/day")
    closed = all(check["passed"] for check in gm.evaluate.plant_balance(plant, None, result))
    print(f"Plant balance closes:        {closed}")


if __name__ == "__main__":
    main()
