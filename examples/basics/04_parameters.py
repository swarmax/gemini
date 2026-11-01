"""Change parameters by date, set controls and boundaries and bind data columns.

Shows ``set_params`` with ``valid_from``, ``params_at``, ``param_history``, attribute assignment,
``bindable`` and ``set_bindings``.

Run with ``python examples/basics/04_parameters.py``.
"""

import gemini as gm


def dated_design(plant):
    """Give the pump 14 stages from 2025 on and read the design of each date."""
    plant.set_params("doublet.esp", {"stage_count": 14}, valid_from="2025-01-01")
    for date in ("2024-06-01", "2025-06-01"):
        print(f"Stages on {date}:  {plant.params_at('doublet.esp', time=date)['stage_count']}")
    print(f"Dated entries:         {len(plant.param_history('doublet.esp'))}")


def inputs(plant):
    """List the controls and persist one command; a boundary is set in the same way."""
    print(f"Controls:              {', '.join(sorted(plant.controls()))}")
    print(f"Boundaries:            {len(plant.boundaries())}")
    plant.doublet.esp.frequency = {"value": 50, "unit": "Hz"}
    print(f"Pump frequency:        {plant.doublet.esp.frequency:.0f} Hz")
    substation = gm.plants.example("HeatingSubstation")
    substation.consumer.heat_demand = {"value": 150, "unit": "kW"}
    print(f"Heat demand boundary:  {substation.consumer.heat_demand / 1e3:.0f} kW")


def bindings(plant):
    """Name the data columns of the pump's frequency and suction pressure."""
    bindable = plant.bindable("doublet.esp")
    print(f"Bindable controls:     {', '.join(bindable['controls'])}")
    print(f"Bindable inlet fields: {', '.join(bindable['inlets']['fluid_in'])}")
    plant.set_bindings(
        "doublet.esp", {"frequency": "esp_hz", "fluid_in.p": {"column": "p_in", "unit": "bar"}}
    )
    print(f"Bound names:           {', '.join(sorted(plant.to_dict()['bindings']['doublet.esp']))}")


def main():
    """Show the parameters, inputs and bindings of the doublet heat plant."""
    plant = gm.plants.example("DoubletHeatPlant")
    print(f"Parameters:            {len(list(plant.named_parameters()))}")
    print(f"Root inputs:           {len(plant.inputs(recurse=False))}")
    dated_design(plant)
    inputs(plant)
    bindings(plant)


if __name__ == "__main__":
    main()
