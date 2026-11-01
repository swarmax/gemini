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
| Constraints | 35 to 180 m3/h while running, brine cooling at most 22 K, at most 450 h running of 504, pump efficiency 0.6 to 0.68, volume balance within 1e-5 m3/s |
| Plant | Well 0.216 m, 130 m3/h, 8 bar wellhead, exchanger 250 kW/K, heat pump 1.6 MW with Carnot fraction 0.5 ("close to 50 percent of the Carnot value", H. U. Frutschi, ABB Review 5/1996, pp. 33-34), boiler 3.5 MW at 0.92, compression chiller 0.4 MW, cooler 1 MW |

## Assumptions and prices

Every value here is an invented placeholder of the example, none a market price. Electricity 120 and gas 55 EUR/MWh, no revenue, discount rate 0.04, lifetime 30 yr, `heat_cost_share` 0.8, electricity 360 g CO2/kWh.
Capex: the cited factors of the hackathon README (drilling, heat pump, boiler, CHP, degasser,
compression chiller 0.67 EUR/W) and invented ones for the pumps (0.5 EUR/W), exchanger
(0.5 EUR/(W/K)), cooler (0.1 EUR/W), pipe (500 EUR/m), flare and gas makeup; fixed opex 1.5 %/yr
(drilling 1 %/yr).
