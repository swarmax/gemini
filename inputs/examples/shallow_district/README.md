# Shallow district sample case

A second sample case, unlike the first: an hourly demand of three winter weeks on one shallow,
colder doublet, a 65 degC network and other limits. Every value is invented for testing and none is
measured data. Only `examples/` and `tests/` read this folder, and nothing under `gemini/` knows it.

`examples/quickstart.py` and `examples/plant.py` run it through the general functions
`gm.Case.from_json`, `gm.Plant.from_json`, `gm.simulate` and `gm.evaluate`.

| File | Holds |
| --- | --- |
| `demand.csv` | 504 hourly rows from 2026-01-12: `timestamp`, `heat_kw`, `cool_kw`, a daily cycle with a morning peak, lower at night and at the weekend; written once from a formula |
| `case.json` | The case: time, site, brine, demand (kW), choices (1 to 2 doublets, 1000 to 1800 m), constraints and assumptions |
| `plant.json` | A plant dict of class `HeatingHeatPumpCoolingPlant` on one doublet: design values only |

## Values

| Value | Setting |
| --- | --- |
| Depth, geotherm | 1300 m, 36 K/km from 9 degC: about 56 degC, so a heat pump is needed for 65 degC |
| Reservoir pressure | 120 barg, near hydrostatic at this depth |
| Thickness, permeability | 60 m, 450 mD |
| Brine | 1012 kg/m3, 0.55 mPa.s, GLR 0.15 Nm3/m3, 92 % CH4 and 8 % CO2 |
| Heating supply, return | 65 degC, 38 degC |
| Cooling supply, return | 16 degC, 22 degC |
| Air | 6 degC |
| Constraints | 35 to 180 m3/h while running, brine cooling at most 22 K, at most 450 h running of 504, pump efficiency 0.6 to 0.68, pump intake pressure at least 5 bar and free gas at most 18.75 % of the intake volume while running, volume balance within 1e-5 m3/s |
| Plant | Well 0.216 m, 130 m3/h, 8 bar wellhead, exchanger 250 kW/K, heat pump 1.6 MW with Carnot fraction 0.5 ("close to 50 percent of the Carnot value", H. U. Frutschi, ABB Review 5/1996, pp. 33-34), boiler 3.5 MW at 0.92, compression chiller 0.4 MW, cooler 1 MW |

## Assumptions and prices

Every value here is an invented placeholder of the example, none a market price. Electricity 120 and gas 55 EUR/MWh, no revenue, discount rate 0.04, lifetime 30 yr, `heat_cost_share` 0.8, electricity 360 g CO2/kWh.
Capex: the cited factors of the hackathon README (drilling, heat pump, boiler, CHP, degasser,
compression chiller 0.73786 EUR/W, the heat pump row) and, for the heat pump, boiler and CHP, the cited fixed opex shares (0.2239, 3.25 and 1.0263 %/yr) and invented ones for the pumps (0.5 EUR/W), exchanger
(0.5 EUR/(W/K)), cooler (0.1 EUR/W), pipe (500 EUR/m), flare and gas makeup; other fixed opex 1.5 %/yr
(drilling 1 %/yr).

The injection pump of `plant.json` states its two design values, `nominal_flow` 130 m3/h (its one doublet)
and `nominal_head` 14.13 bar. They come from the rule of `gm.study.size` (the flow of the doublets the
pump serves, and the pressure that the injection well needs at that flow less the 8 bar of the production
wellhead as best suction, floored at zero) applied to the stored doublet and this case. They are data of
the plant, not a default of the package.

## Pump intake limits

The `intake_pressure` and `intake_gas_fraction` constraints limit the ESP intake of a running doublet.

- Maximum free gas, 0.1875 of the volume at the intake. Source: Baker Hughes, Ace Plus gas handler pumps,
  <https://www.bakerhughes.com/production/artificial-lift/electrical-submersible-pump-systems/pumps/ace-plus-gas-handler-pumps>:
  "Performance tests indicate that Ace Plus gas handler pumps can process up to 75% free gas without locking"
  and "Standard pump stages can handle only one-fourth of this amount of free gas before locking." The limit is
  75 % / 4 = 18.75 %, the manufacturer's figure for standard stages; the page was opened on 2026-11-01.
- Minimum intake pressure, 5 bar: assumption, no verified source. The published rule found (intake pressure above the
  bubble point of the produced fluid) needs the PVT of the fluid, which the case does not give.
- Intake values of the stored plant over the case (one run): pressure 14.7 to 121 bar and gas share 0.15 to
  1.2 %, so neither limit rejects it.
