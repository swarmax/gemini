# Hackathon 2027 sample case

One sample case of gemini: only `examples/` and `tests/` read this folder, and nothing under
`gemini/` knows it. The inputs of the GEMINI agentic geothermal design hackathon, as the organisers released them on
2026-10-29. The requirements document is dated 28 October 2026. These files are unchanged:
`GEMINI_Heating_Demand_Daily_2027.csv`, `GEMINI_Cooling_Demand_Daily_2027.csv` and
`GEMINI_Hackathon_Challenge_Requirements.pdf`.

The profiles are synthetic: 365 daily-average power values, 1 January to 31 December 2027.

| Profile | Peak | Peak date | Year |
| --- | --- | --- | --- |
| Heating | 30.0 MWth | 2027-01-28 | 111.67 GWh/yr |
| Cooling | 10.0 MWcool | 2027-07-19 | 23.74 GWh/yr |

## Reservoir

| Parameter | Value |
| --- | --- |
| Midpoint depth | 2,500 m TVD |
| Gross thickness | 100 m |
| Geothermal gradient | 30 °C/km |
| Reference surface temperature | 12 °C |
| Reservoir pressure | 250 bar(g) |
| Permeability | 200 mD |

For another well depth the organisers allow hydrostatic pressure for the reservoir pressure and the
gradient for the reservoir temperature.

## Brine and associated gas

| Parameter | Value |
| --- | --- |
| Brine density | 1,030 kg/m³, constant |
| Dynamic viscosity | 0.40 mPa·s, constant |
| Gas-liquid ratio | 0.8 Nm³ gas per m³ produced liquid |
| Methane in the produced gas | 80 mol% |
| Carbon dioxide in the produced gas | 20 mol% |
| Fluid composition | Fixed baseline; variable PVT optional |

A normal cubic metre is at 0 °C and 1.01325 bar(a). The ratio is the gas that can be liberated at
standard conditions.

## Limits

| Constraint | Value | Status |
| --- | --- | --- |
| Geothermal doublets | 1 to 3 | Design variable |
| Maximum production flow | 300 m³/h per doublet | Hard cap |
| Minimum stable flow while active | 50 m³/h per doublet | Hard cap |
| Maximum brine cooling | 40 °C, producer to injector | Hard cap |
| Pump hydraulic efficiency | 70% | Simplified |
| Production and injection volume | Equal liquid volumes, same reservoir | Required |
| Annual operation of a doublet | 330 daily steps | Daily power and energy balance |
| Heating supply temperature | 100 °C | Fixed |
| Cooling supply temperature | 20 °C | Fixed |

## Heat pump performance

Every heat pump and compression chiller states `carnot_fraction` 0.5 in its plant dict, which the
cost dispatch and the run read: "close to 50 percent of the Carnot value", H. U. Frutschi, ABB
Review 5/1996, pp. 33-34. It is a general figure and no data of these machines.

## Files added for the examples

The organiser files stay as released. The others hold the requirements above, and the assumptions
they leave open, in the shapes of gemini.

| File | Holds | Read by |
| --- | --- | --- |
| `demand.csv` | The two organiser demand files joined on `date`: `heating_demand_MWth` and `cooling_demand_MWcool`, values unchanged | `case.json` |
| `case.json` | The one case: time, site, brine, demand, the choices (1 to 3 doublets, 2000 to 3500 m), the constraints (with the 330 day operating duration) and the assumptions | every example, `gm.Case.from_json` |
| `plants/<Class>.json` | One plant dict per candidate: `HeatingPlant`, `HeatingAbsorptionCoolingPlant`, `HeatingHeatPumpCoolingPlant`, `HeatingFullCoolingPlant`, `HeatingCoolingPlant`, and `HackathonPlant` (structure form: desander, inhibitor dosing, one absorption chiller); design values only, no site | `examples/hackathon.py`, tests |

Sizes of equipment and the injection pressure are design values of the plants. The return
temperatures, the air temperature and every price are assumptions of the case.

## Given by the organisers, in `case.json`

| Section | Values |
| --- | --- |
| `environment` | Gradient 30 K/km, surface 12 degC, 2500 m, 100 m, 200 mD, 250 barg; brine 1030 kg/m3, 0.4 mPa.s, GLR 0.8, 80 % CH4 and 20 % CO2 |
| `demand` | The two profiles; supply 100 degC heating and 20 degC cooling |
| `choices` | 1 to 3 doublets; the depth range 2000 to 3500 m is an assumption of the example |
| `constraints` | 50 to 300 m3/h while running, brine cooling at most 40 K, at most 330 d running, pump efficiency 0.7, equal liquid volumes (within 1e-6 m3/s) |

## Assumptions of the example

Every value of this section is a placeholder of the example, from no source and none given by the organisers: return temperatures 60 degC (heating) and 25 degC (cooling), air
10 degC; prices electricity 100 and gas 40 EUR/MWh, chemical 3 EUR/kg, waste disposal 0.2 EUR/kg,
heat and cold revenue 60 EUR/MWh; discount rate 0.05, lifetime 25 yr, `heat_cost_share` 0.8;
electricity 300 g CO2/kWh; CO2 price 80 EUR/t (`opex.co2`); capex of the production and injection pump 0.5 EUR/W, absorption and
adsorption chiller and compression chiller 0.3 EUR/W, heat exchanger 0.5 EUR/(W/K), cooler
0.1 EUR/W, pipe 500 EUR/m, flare 100000 EUR, gas makeup 50000 EUR; fixed opex per kind of 0.5 to
2 %/yr of its capex (heat pump 2, boiler 1.5, heat exchanger 1, drilling 1).

Cited, price year 2015, currency EUR:

| Key | Value | Source |
| --- | --- | --- |
| `capex.drilling` | 1239.13 EUR/m | SDE+ 2013 reference case, 2300 m doublet, 5.7 MEUR net drilling (Mijnlieff et al. 2013, EGC, slide 26), over two wells of 2300 m, taken into 2015 without escalation |
| `capex.degasser` | 1.0 MEUR | Same note: reserve for separation of hydrocarbons per doublet |
| `capex.heat_pump` | 0.67 EUR/W | Danish Energy Agency, Technology Data for Energy Plants, April 2020, chapter 40, compression heat pump, excess heat, 10 MW, 2015 prices |
| `capex.boiler` | 0.06 EUR/W | DEA Technology Data, chapter 44, district heating boiler, natural gas, 2015 prices |
| `capex.chp` | 0.95 EUR/W electric | DEA Technology Data, chapter 06, spark ignition engine, natural gas, 1-10 MWe, 2015 prices |
| `emissions.CH4.gwp` | 29.8 | IPCC AR6 WG1 chapter 7 table 7.15 (Forster et al. 2021), fossil methane, 100 years |

The compression chiller factor is a 0.3 EUR/W placeholder, not the heat pump row. `capex.injection_pump` is in the case as the design has it, but no module is priced by it yet (the injection pump has no design head), so it is not used.
