# Hackathon 2027 sample problem

One sample problem of gemini: only `examples/` and `tests/` read this folder, and nothing under
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

These are not the organisers' files: they hold the requirements above, and the assumptions the
requirements leave open, in the shapes of gemini. The two organiser CSVs stay as released.

| File | Holds | Read by |
| --- | --- | --- |
| `demand.csv` | The two organiser demand files joined on `date`: `heating_demand_MWth` and `cooling_demand_MWcool`, values unchanged | both problems |
| `problem.json` | The problem of `plant.json`: the demand, the site, the constraints (with the 330 day operating duration) and the assumptions with prices; `gm.Problem.from_json` | `examples/cases/challenge_year.py` |
| `problem_with_treatment.json` | The problem of the treatment design: the same demand and prices, no duration constraint (no outages), the heating supply as its only supply limit | `examples/cases/hackathon.py` |
| `plant.json` | A plant dict of class `HeatingCoolingPlant` on two doublets: design values only | `examples/cases/challenge_year.py` |
| `plant_with_treatment.json` | A plant dict in the structure form: two doublets, desander, inhibitor dosing, one absorption chiller; design values only | `examples/cases/hackathon.py` |
| `templates/<Class>.json` | Plant dicts of the other template plants on these requirements, design values only | tests |

Sizes of equipment, return temperatures, the air and the injection pressure are assumptions of the
examples, which print them.

## Site in `problem.json`

The values of the ground and of the fluid's place are the `site`, applied to a plant with
`problem.apply_site(plant)`; the plant keeps the design values (`depth`, `well_diameter`,
`nominal_flow`, `pump_efficiency`, `nominal_wellhead_pressure` and the surface equipment).

| Key | Value |
| --- | --- |
| `d*.gradient` | 30 K/km |
| `d*.surface_temperature` | 12 degC |
| `d*.thickness` | 100 m |
| `d*.permeability` | 200 mD |
| `d*.reservoir.pressure`, `d*.sink.pressure` | 250 barg (`problem.json` only: the treatment design takes the hydrostatic pressure of its depth) |

The brine and its gas (`fluids`) are not a plant parameter, so they stay in the plant dict.

## Constraints in `problem.json`

| Path | Bound | Source |
| --- | --- | --- |
| `d*.reservoir.liquid_flow`, while running | 50 to 300 m3/h | stable minimum and hard cap |
| `d*.reservoir.liquid_flow`, total time running | at most 330 d | annual operation of a doublet |
| `d*.brine_cooling` | at most 40 K | maximum brine cooling |
| `d*.pump_efficiency` | 0.7 | pump efficiency |
| `d*.volume_imbalance` | within 1e-6 m3/s | equal liquid volumes |
| `heating_consumer.supply_in.temperature` | at least 100 degC | heating supply |
| `cooling_consumer.supply_in.temperature` | at most 20 degC | cooling supply |

`problem_with_treatment.json` has the flow, brine cooling and `heat_users.supply_in.temperature`
limits only. The pump efficiency and the volume balance are not limits of that design, and the
duration constraint is left out: it is planned without outages.

## Assumptions and prices

The assumptions are placeholders of the examples. Their source is an `assumptions.json` written
for the examples, now the `assumptions` key of both problem files: none comes from gemini code and
none from the organisers, whose requirements give no price, rate or lifetime.

| Value | Setting | Source |
| --- | --- | --- |
| `prices.electricity` | 100 EUR/MWh | placeholder of the examples |
| `prices.gas` | 40 EUR/MWh | placeholder of the examples |
| `prices.heat`, `prices.cold` | 60 EUR/MWh | placeholder of the examples |
| `prices.waste_disposal` | 0.2 EUR/kg | placeholder of the examples |
| `prices.chemical` | 3 EUR/kg | placeholder of the examples |
| `discount_rate`, `lifetime_years` | 0.05, 25 years | placeholder of the examples |
| `electricity_emission_factor` | 300 g CO2/kWh | placeholder of the examples |
| `pump_cost`, `chiller_cost`, `exchanger_cost`, `flare_cost`, `makeup_cost` | as in the file | placeholder of the examples |
