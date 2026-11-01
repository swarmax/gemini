"""Step a small district energy plant: a heating network and an ATES-cooled cooling network.

A geothermal supply feeds a heating network with two building substations. In parallel an aquifer
thermal energy storage (ATES) plant runs in its charge (summer) mode: cold groundwater chills the
water of a cooling network that serves one building, and the warmed groundwater is stored in the
warm well. The return of the cooling network is fed back to the ATES plant at the next step. Each
hourly step is checked for energy closure: the sensible-enthalpy audit closes except for the pumps'
flow work.

Shows ``gm.plants.example("DistrictEnergyPlant")``, ``get``, ``Module.step``,
``gm.modules.energy_balance``, ``gm.modules.collect_flows`` and ``gm.evaluate.plant_balance``.

Run with ``python examples/cases/district_heating_cooling.py``.
"""

import gemini as gm

HOUR = gm.units.convert(1, "h", "s")
GEOTHERMAL_SUPPLY = gm.Stream(
    flow={"value": 18, "unit": "t/h"},
    T={"value": 75, "unit": "degC"},
    p={"value": 6, "unit": "bar"},
)
FIRST_COOLING_RETURN = gm.Stream(
    flow={"value": 36, "unit": "t/h"},
    T={"value": 17, "unit": "degC"},
    p={"value": 3, "unit": "bar"},
)
AIR = {"value": 10, "unit": "degC"}
COOLING_BUILDING = {
    "consumer.sensible_cooling_demand": {"value": 150, "unit": "kW"},
    "consumer.latent_cooling_demand": {"value": 0, "unit": "kW"},
    "consumer.indoor_temperature": {"value": 24, "unit": "degC"},
    "consumer.indoor_relative_humidity": 0.5,
    "valve.opening": 0.9,
}
INPUTS = {
    "heating.pump.frequency": {"value": 50, "unit": "Hz"},
    "heating.splitters.0.split_fraction": 0.5,
    "heating.substations.0.valve.opening": 0.9,
    "heating.substations.1.valve.opening": 0.9,
    "heating.substations.0.consumer.heat_demand": {"value": 150, "unit": "kW"},
    "heating.substations.1.consumer.heat_demand": {"value": 100, "unit": "kW"},
    "cooling.pump.frequency": {"value": 50, "unit": "Hz"},
    "ates.storage.groundwater_flow": {"value": 36, "unit": "t/h"},
    "ates.storage.mode": "charge",
    "ates.source_valve.split_fraction": 0.0,
    "ates.load_valve.split_fraction": 0.0,
    "ates.pump.frequency": {"value": 50, "unit": "Hz"},
    "ates.heat_pump.temperature_setpoint": {"value": 40, "unit": "degC"},
    "air.temperature": AIR,
} | {f"cooling.substations.0.{name}": value for name, value in COOLING_BUILDING.items()}


def command(plant, inputs):
    """Set each control or boundary, named by its path, on its module."""
    for path, value in inputs.items():
        declaration = plant.get(path)
        setattr(declaration.owner, declaration.name, value)


def consumer_heat(plant, result, module_class):
    """Return the heat [W] the water gives up in the leaves of ``module_class``, by their ports."""
    consumers = [
        leaf
        for path, leaf in result.leaves().items()
        if isinstance(plant.get_submodule(path), module_class)
    ]
    return sum(
        leaf.inlets.supply_in.quantities()["enthalpy_flow"]
        - leaf.outlets.return_out.quantities()["enthalpy_flow"]
        for leaf in consumers
    )


def closes(plant, result):
    """Tell whether the audit residual is the pumps' flow work and the plant balance closes."""
    audit = gm.modules.energy_balance(plant, result)
    leaves = result.leaves().values()
    flow_work = sum(leaf.outputs.get("hydraulic_power", 0.0) for leaf in leaves)
    balanced = all(check["passed"] for check in gm.evaluate.plant_balance(plant, None, result))
    return balanced and abs(audit["residual"] - flow_work) <= 1e-9 * audit["in"]


def main():
    """Step the plant for six hours and print one line per step."""
    plant = gm.plants.example("DistrictEnergyPlant")
    command(plant, INPUTS)
    state, cooling_return = None, FIRST_COOLING_RETURN
    air = gm.modules.Atmosphere.ambient_air(AIR)
    print("Assumptions: 10 °C air, an 11 °C aquifer, 150 and 100 kW of heat, 150 kW of cold")
    print("hour  heat kW  cold kW  electricity kW  stored MWh  chilled °C  closes")
    for hour in range(6):
        inlets = {"hot_in": GEOTHERMAL_SUPPLY, "cold_in": cooling_return, "air_in": air}
        state, result = plant.step(state, HOUR, inlets)
        flows = gm.modules.collect_flows(result)
        heat = consumer_heat(plant, result, gm.modules.HeatingGrid)
        cold = flows["heat_absorbed"] - consumer_heat(plant, result, gm.modules.CoolingGrid)
        storage = result.children["ates"].children["storage"]
        stored = gm.units.convert(storage.outputs.stored_energy, "J", "kWh") / 1000
        chilled = gm.units.convert(result.children["ates"].outlets.supply_out.T, "K", "degC")
        print(
            f"{hour:4d} {heat / 1e3:8.1f} {cold / 1e3:8.1f} {flows['electricity'] / 1e3:15.2f} "
            f"{stored:11.3f} {chilled:11.2f}  {closes(plant, result)}"
        )
        cooling_return = result.outlets.cold_out


if __name__ == "__main__":
    main()
