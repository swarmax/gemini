"""Call one module and read its outlets, outputs and port quantities.

Shows calling ``gm.modules.ESP``, ``ModuleResult`` (``outputs``, ``outlets``, ``inlets``),
``Stream.quantities``, ``describe``, ``gm.modules.no_outputs`` and ``gm.runtime.settings``.

Run with ``python examples/basics/02_modules.py``.
"""

import gemini as gm

STREAM = gm.Stream(
    flow={"value": 150, "unit": "m3/h"},
    T={"value": 80, "unit": "degC"},
    p={"value": 20, "unit": "bar"},
)


def configured_esp():
    """Return a standalone ESP with the pump design of the doublet heat plant."""
    design = gm.plants.example("DoubletHeatPlant").doublet.esp
    values = {name: parameter.value for name, parameter in design.named_parameters()}
    return gm.modules.ESP().set_params("", values)


def print_call(esp):
    """Call the pump at 50 Hz and print its outputs, outlets and port quantities."""
    result = esp(fluid_in=STREAM, frequency={"value": 50, "unit": "Hz"})
    outlet = result.outlets.fluid_out
    quantities = outlet.quantities()
    print(f"Head:              {result.outputs.get('head', unit='bar'):.2f} bar")
    print(f"Outlet pressure:   {gm.units.convert(outlet.p, 'Pa', 'bar'):.2f} bar")
    print(f"Power drawn:       {result.inlets.power_in / 1e3:.1f} kW")
    print(
        f"Outlet volume:     {gm.units.convert(quantities['volume_flow'], 'm3/s', 'm3/h'):.1f} m³/h"
    )
    print(f"Outlet enthalpy:   {quantities['enthalpy_flow'] / 1e6:.2f} MW")


def print_description(esp):
    """Print what the module declares."""
    described = esp.describe()
    print(f"Inlets:            {', '.join(described['inlets'])}")
    print(f"Controls:          {', '.join(described['controls'])}")
    print(f"Frequency unit:    {described['controls']['frequency']['unit']}")
    print(f"Outputs:           {', '.join(described['outputs'])}")
    print(f"Shipped modules:   {len(gm.modules.names())}")


def main():
    """Call the pump, read its declarations and run it without outputs and in float32."""
    esp = configured_esp()
    print_call(esp)
    print_description(esp)
    with gm.modules.no_outputs():
        fast = esp(fluid_in=STREAM, frequency={"value": 50, "unit": "Hz"})
    print(f"Without outputs:   {len(fast.outputs)} outputs")
    with gm.runtime.settings(precision="float32"):
        legacy = esp(fluid_in=STREAM, frequency={"value": 50, "unit": "Hz"})
    print(f"Head in float32:   {legacy.outputs.get('head', unit='bar'):.2f} bar")


if __name__ == "__main__":
    main()
