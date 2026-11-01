"""Compare one simulated day at three ESP frequencies.

Shows ``gm.engine.Clock.days``, ``gm.types.Profile.constant``, ``gm.Dataset.from_profiles``,
``gm.simulate`` and
``gm.evaluate.plant_balance``. Below about 52 Hz this pump cannot lift the produced brine to the
surface and every step fails with a negative pressure, so the sweep starts at 55 Hz.

Run with ``python examples/recipes/sweep_esp_frequency.py``.
"""

import gemini as gm

FREQUENCIES = tuple(gm.units.Quantity(hertz, "Hz") for hertz in (55, 60, 65))
DAY = gm.engine.Clock.days(2027, 1, 1, days=1)


def inputs(frequency):
    """Return a day of constant production at one pump frequency."""
    profiles = {
        "doublet.reservoir.production_rate": gm.types.Profile.constant(150, unit="m3/h", clock=DAY),
        "doublet.esp.frequency": gm.types.Profile.constant(
            frequency.value, unit=frequency.unit, clock=DAY
        ),
        "injection_pump.pressure_setpoint": gm.types.Profile.constant(51.5, unit="bar", clock=DAY),
    }
    return gm.Dataset.from_profiles(profiles)


def main():
    """Simulate each frequency and print the energy of each module that has one."""
    plant = gm.plants.example("DoubletHeatPlant")
    for frequency in FREQUENCIES:
        results = gm.simulate(plant, plan=inputs(frequency), clock=DAY)
        closed = all(check["passed"] for check in gm.evaluate.plant_balance(plant, None, results))
        label = f"{frequency.value:g} {frequency.unit}"
        print(f"{label}: {len(results.errors())} failed rows, balance closes: {closed}")
        for (module, port), row in results.to_frame(table="energy").iterrows():
            if row["energy_MWh"] > 0:
                print(f"  {module + ' ' + port:<26} {row['energy_MWh']:8.3f} MWh")


if __name__ == "__main__":
    main()
