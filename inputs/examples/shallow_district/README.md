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

## Values the plants state that a module no longer defaults

A module declares no design value: each plant dict of this folder states the values below, with the value the package used as a default before, so no result changed. Where no source is given the value is an assumption of this sample, not data of the measurements or of a machine. `dN` is `d0`, `d1`, ... one per doublet.

| Name | Value | Status |
| --- | --- | --- |
| `heating_supply_pipe.roughness`, `heating_return_pipe.roughness` (and the cooling pipes) | 4.5e-5 m | cited: new commercial steel, Moody (1944), Trans. ASME 66 |
| `dN.drainage_radius` | 1000 m | assumption (the lower end of 1 to 2 km Dutch doublet spacing, Willems 2016) |
| `dN.roughness` | 4.5e-5 m | cited: new commercial steel, Moody (1944), Trans. ASME 66 (wall of the vertical wells, was inside the derivation) |
| `dN.esp.correction_factors` | [1, 0] | assumption (no calibration) |
| `dN.reservoir.skin`, `dN.sink.skin` | 0 | assumption |
| `dN.well|riser|injector.friction_correlation` | darcy_weisbach | assumption (model choice) |
| `dN.well|riser|injector.two_phase_friction_correlation` | BeggsBrill | assumption (model choice) |
| `dN.well|riser|injector.correction_factors` | [1, 0] | assumption (no calibration) |
| `dN.well|riser|injector.heat_transfer_coefficient` | 10 W/m2/K | assumption (the value of the original GEMINI well model) |
| `degasser.nominal_pressure_drop` | 14900 Pa | assumption (0.149 bar of the original GEMINI example) |
| `filters.hot|cold.nominal_pressure_drop` | 1600 Pa | assumption (0.016 bar of the original GEMINI example) |
| `filters.hot|cold.nominal_mass_flow` | 44.2033 kg/s | assumption (149 m3/h of brine at 1068 kg/m3) |
| `filters.hot|cold.clogging_pressure_drop` | 50000 Pa | assumption (0.5 bar, the limit of an old project) |
| `heat_exchanger.arrangement` | counterflow | assumption |
| `heat_exchanger.fouling_threshold`, `dN.reservoir.decline_threshold`, `dN.sink.decline_threshold` | 0.15 | assumption (alarm threshold) |
| `gas_grid.composition` | CH4 0.82495, C2H6 0.03955, C3H8 0.01275, CO2 0.01191, N2 0.11084 (mole fractions) | assumption (a measured grid gas of the original GEMINI example) |
| `flare.combustion_efficiency` | 0.98 | cited: US EPA AP-42, section 13.5 |
| `heat_pump.cop_model`, `compression_chiller.cop_model` | carnot | assumption (model choice) |
| `heat_pump.carnot_fraction`, `compression_chiller.carnot_fraction` | 0.5 | cited: H. U. Frutschi, ABB Review 5/1996 |
| `heat_pump.lorenz_fraction`, `compression_chiller.lorenz_fraction` | 0.5 | assumption (no source for a Lorenz value of its own) |
| `heat_pump.minimum_temperature_lift`, `compression_chiller.minimum_temperature_lift` | 10 K | cited: lowest lift of the machines summarised by Arpagaus et al. (2018) |
