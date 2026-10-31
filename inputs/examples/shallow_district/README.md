# Shallow district sample problem

A second sample problem, unlike the first: an hourly demand of three winter weeks on one shallow,
colder doublet, a 65 °C network and other limits. Every value is invented for testing and none is
measured data. Only `examples/` and `tests/` read this folder, and nothing under `gemini/` knows it.

`examples/cases/shallow_district.py` runs it through the same general functions as any problem:
`gm.Problem.from_json`, `gm.Plant.from_json`, `gm.schedule` and `gm.simulate`.

| File | Holds |
| --- | --- |
| `demand.csv` | 504 hourly rows from 2026-01-12: `timestamp`, `heat_kw`, `cool_kw`, a daily cycle with a morning peak, lower at night and at the weekend; written once from a formula |
| `problem.json` | The problem: the demand (`demand.csv`, in kW), the site, the constraints and the assumptions with prices; `gm.Problem.from_json` |
| `plant.json` | A plant dict of class `HeatingHeatPumpCoolingPlant` on one doublet: design values only |

## Values

| Value | Setting | Why |
| --- | --- | --- |
| Depth | 1300 m | A shallow doublet |
| Geotherm | 36 K/km from 9 °C | Gives about 56 °C, so a heat pump is needed for 65 °C |
| Reservoir and sink pressure | 120 barg | Near hydrostatic at this depth |
| Thickness, permeability | 60 m, 450 mD | A thin, good sand |
| Well diameter | 0.216 m | A smaller well |
| Brine | 1012 kg/m³, 0.55 mPa·s | A low-salinity brine |
| Gas-liquid ratio | 0.15 Nm³/m³, 92 % CH4, 8 % CO2 | Little gas |
| Nominal flow, wellhead pressure | 130 m³/h, 8 bar | Sized for the peak |
| Pump efficiency | 0.65, both pumps | |
| Injection pressure | 36 bar | Lower values gave a negative head |
| Heat exchanger | 250 kW/K | Small network |
| Heat pump | 1.6 MW, source not below 27 °C, Carnot fraction 0.5 | Lifts to the supply; "close to 50 percent of the Carnot value", H. U. Frutschi, ABB Review 5/1996, pp. 33-34 |
| Boiler | 3.5 MW, efficiency 0.92 | Covers the peak |
| Heating supply, return | 65 °C, 38 °C at 5 bar | A low-temperature network |
| Compression chiller | 0.4 MW, supply 16 °C, return 22 °C at 3 bar, Carnot fraction 0.5 | Heat-free cooling; the same source |
| Cooler | 1 MW, 6 K approach, 18 °C, 60 kg/s | Rejects the chiller heat |
| Air | 6 °C | A cold season |
| Pipes | 400 m, 0.2 m inside diameter | |

## Site

`problem.json` holds the ground: `d*.gradient` 36 K/km, `d*.surface_temperature` 9 degC,
`d*.thickness` 60 m, `d*.permeability` 450 mD, `d*.reservoir.pressure` and `d*.sink.pressure`
120 barg. The brine (`fluids`) is not a plant parameter, so it stays in `plant.json`.

## Constraints

| Path | Value |
| --- | --- |
| `d*.reservoir.liquid_flow`, while running | 35 to 180 m3/h |
| `d*.brine_cooling` | at most 22 K |
| `d*.reservoir.liquid_flow`, total time running | at most 450 h of 504: its 54 outage steps are the lowest-demand hours |
| `d*.pump_efficiency` | 0.6 to 0.68 |
| `d*.volume_imbalance` | within 1e-5 m3/s |
| `heating_consumer.supply_in.temperature` | at least 65 degC |
| `cooling_consumer.supply_in.temperature` | at most 16 degC |

## Assumptions and prices

Like every value of this folder, the assumptions are invented for testing; none is a market price
and none comes from gemini code or from a source. `gm.schedule` needs the electricity and gas
prices, so they are stated.

| Value | Setting | Source |
| --- | --- | --- |
| `prices.electricity` | 120 EUR/MWh | invented |
| `prices.gas` | 55 EUR/MWh | invented |
| `discount_rate`, `lifetime_years` | 0.04, 30 years | invented |
| `electricity_emission_factor` | 360 g CO2/kWh | invented |
