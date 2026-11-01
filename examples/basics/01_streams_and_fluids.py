"""Build a stream and a fluid, with values given as unit strings.

Shows ``gm.Stream``, ``gm.Fluid``, ``gm.BRINE``, ``gm.WATER``, ``Stream.with_`` and ``gm.units``.

Run with ``python examples/basics/01_streams_and_fluids.py``.
"""

import gemini as gm


def main():
    """Print a stream, the same flow of another fluid and a few unit conversions."""
    brine = gm.Fluid(
        density={"value": 1068, "unit": "kg/m3"}, viscosity={"value": 0.4, "unit": "mPa*s"}
    )
    stream = gm.Stream(
        flow={"value": 150, "unit": "m3/h"},
        T={"value": 80, "unit": "degC"},
        p={"value": 20, "unit": "bar"},
        fluid=brine,
    )
    flow = gm.units.convert(stream.volumetric_flow(), "m3/s", "m3/h")
    print(f"Brine mass flow:     {stream.m_dot:.2f} kg/s")
    print(f"Brine volume flow:   {flow:.1f} m³/h")
    print(f"Temperature:         {gm.units.convert(stream.T, 'K', 'degC'):.1f} °C")
    print(f"Pressure:            {gm.units.convert(stream.p, 'Pa', 'bar'):.1f} bar")

    cooled = stream.with_(T=gm.units.convert(40, "degC", "K"))
    print(f"After cooling:       {gm.units.convert(cooled.T, 'K', 'degC'):.1f} °C")
    water = gm.Stream(
        flow={"value": 150, "unit": "m3/h"},
        T={"value": 80, "unit": "degC"},
        p={"value": 20, "unit": "bar"},
        fluid=gm.WATER,
    )
    print(f"Same volume, water:  {water.m_dot:.2f} kg/s")
    print(f"Default brine:       {gm.BRINE.properties(stream.p, stream.T).rho_l:.0f} kg/m3")

    quantity = gm.units.Quantity(150, "m3/h")
    print(f"A quantity in SI:    {quantity.si:.5f} m3/s")
    print(f"Is m3/h a flow?      {gm.units.fits('m3/h', 'volume_flow')}")


if __name__ == "__main__":
    main()
