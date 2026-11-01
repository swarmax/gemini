# Hackathon 2026 sample case

Sample of the SPE Europe Energy GeoHackathon 2026; the demand profiles are for the year 2027.

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
| Free gas at the pump intake | At most 18.75 % of the volume while running | Sourced below, not an organiser limit |
| Pump intake pressure | At least 5 bar while running | Assumption, no verified source; not an organiser limit |
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
10 degC; prices chemical 3 EUR/kg, waste disposal 0.2 EUR/kg,
heat and cold revenue 60 EUR/MWh; discount rate 0.05, lifetime 25 yr, `heat_cost_share` 0.8;
electricity 300 g CO2/kWh; capex of the production and injection pump 0.5 EUR/W, absorption and
adsorption chiller and compression chiller 0.3 EUR/W, heat exchanger 0.5 EUR/(W/K), cooler
0.1 EUR/W, pipe 500 EUR/m, flare 100000 EUR, gas makeup 50000 EUR; fixed opex per kind of 0.5 to
2 %/yr of its capex (heat exchanger 1, drilling 1) except the three kinds cited below.

### Uncertainty of the example

Six values carry an `uncertainty` next to their value in `case.json`. The ranges are assumptions of
the example, not from a source, chosen wide around the cited or placeholder value; `gm.study.sample` draws
them and `gm.study.sensitivity` runs each at its ends. A normal run, `size` and `minimize` use only the value.

| Value | Value in the case | Distribution (assumption) |
| --- | --- | --- |
| `opex.electricity` | 105.75 EUR/MWh | uniform 80 to 140 EUR/MWh |
| `opex.gas` | 39.92 EUR/MWh | triangular 25 to 70 EUR/MWh, mode 39.92 |
| `opex.co2` | 57.03 EUR/t | triangular 30 to 110 EUR/t, mode 57.03 |
| `environment.reservoir.permeability` | 200 mD | triangular 100 to 400 mD, mode 200 |
| `environment.ground.gradient` | 30 K/km | normal, std 2 K/km, cut to 25 to 35 K/km |
| `finance.discount_rate` | 0.05 | normal, std 0.01, cut to 0.02 to 0.08 |

Cited, price year 2015, currency EUR. Conversions to 2015 use the euro-area HICP annual average
index, all items (Eurostat `prc_hicp_aind`, `INX_A_AVG`, EA, 2015 = 100: 2015 100.00, 2020 105.06,
2025 128.75, update of 2026-02-06). The catalogue below is Danish Energy Agency, Technology Data for
Generation of Electricity and District Heating, version 0019, August 2026, with the Excel data sheets
of the same version (https://ens.dk/media/8614/download and https://ens.dk/media/8615/download, opened
2026-11-01). The fixed opex is the sheet's fixed O&M [EUR/MW/yr] over its nominal investment.

| Key | Value | Source and figure as stated |
| --- | --- | --- |
| `capex.heat_pump` | 0.73786 EUR/W | DEA data sheet "40 Comp. hp, waste heat 10 MW" (heat pump, waste heat, electricity, large, district heating): nominal investment (total) 0.95 MEUR/MW_h in the 2025 column, cost data in 2025 EURO; 0.95 / 1.2875 = 0.73786 EUR2015/W. Replaces 0.67 |
| `opex.fixed.heat_pump` | 0.2239 %/yr | Same sheet, fixed O&M (total) 2126.745 EUR/MW_h/y over 0.95 MEUR/MW_h. Replaces 2 |
| `capex.boiler` | 0.06073 EUR/W | DEA data sheet "44 Natural Gas DH Only" (gas boiler, medium): nominal investment (total), 2020 column, 0.0638024 MEUR/MW_h, cost data in 2020 EURO (Intro sheet); 0.0638024 / 1.0506 = 0.06073 EUR2015/W. Replaces 0.06 |
| `opex.fixed.boiler` | 3.25 %/yr | Same sheet, 2020 column, fixed O&M 2073.58 EUR/MW_h/y over 0.0638024 MEUR/MW_h. Replaces 1.5 |
| `capex.chp` | 0.96155 EUR/W electric | DEA data sheet "06 Gas engines, natural gas" (engine, back pressure, natural gas, small; 1 to 10 MW_e): nominal investment (total), 2020 column, 1.01020 MEUR/MW_e, cost data in 2020 EURO; 1.01020 / 1.0506 = 0.96155 EUR2015/W. Replaces 0.95 |
| `opex.fixed.chp` | 1.0263 %/yr | Same sheet, 2020 column, fixed O&M 10367.88 EUR/MW_e/y over 1.01020 MEUR/MW_e. Replaces 2 |
| `emissions.CH4.gwp` | 29.8 | IPCC AR6 WG1 chapter 7 table 7.15 (Forster et al. 2021), fossil methane, 100 years. Seen as quoted in Munoz, Schmidt and Weidema (2024), "The indirect global warming potential of methane oxidation in the IPCC's sixth assessment report", Environmental Research Letters 19(12), 121002, https://doi.org/10.1088/1748-9326/ad8edd: "the GWP100 for fossil and biogenic methane became 29.8 and 27.0 kg CO2-eq kg-1 methane, respectively (table 7.15 in Forster et al 2021)". The IPCC chapter itself could not be opened (HTTP 403) |
| `lifetime` 25 yr | kept | DEA data sheets above state a technical lifetime of 25 years for the large heat pump and the gas boiler (and the geothermal sheet 45.3); that is a technology lifetime, not a project appraisal period, so the value stays an assumption that agrees with it |
| `opex.electricity` | 105.75 EUR/MWh | Eurostat `nrg_pc_205`, electricity prices for non-household consumers, EU average (`EU27_2020`), band IE (20 000 to 69 999 MWh/yr), excluding VAT and other recoverable taxes (`X_VAT`), 2025-S1 0.1381 and 2025-S2 0.1342 EUR/kWh, mean 0.13615 EUR/kWh = 136.15 EUR/MWh (EUR 2025); 136.15 / 1.2875 = 105.75 EUR2015/MWh. API data of 2026-10-19. Band IE is chosen for a heat pump load of tens of GWh/yr. Replaces 100. The case names no country, so the EU average is used |
| `opex.gas` | 39.92 EUR/MWh | Eurostat `nrg_pc_203`, natural gas prices for non-household consumers, EU average (`EU27_2020`), band I4 (100 000 to 999 999 GJ/yr), `X_VAT`, 2025-S1 0.0545 and 2025-S2 0.0483 EUR/kWh, mean 0.0514 = 51.4 EUR/MWh (EUR 2025); 51.4 / 1.2875 = 39.92 EUR2015/MWh. Eurostat states the price per kWh of gross calorific value; the case does not state which heating value its fuel energy uses, so the value is exact only for a gross-value convention. Replaces 40 |
| `opex.co2` | 57.03 EUR/t | Instrat Foundation (Wojciech Przedlacki), "EU ETS 2025 summary and the beginning of 2026 auctions", 8 January 2026, https://energy.instrat.pl/en/eu-ets-2025-summary/: "The average CO2 allowance price in 2025 amounted to EUR 73.43 per tCO2 (volume-weighted average)", the 213 primary-market auctions of 2025; 73.43 / 1.2875 = 57.03 EUR2015/t. A secondary source, not the Commission or the EEA (their pages could not be opened). Replaces 80 |
| `capex.drilling` | 1239.13 EUR/m | SDE+ 2013 reference case, 2300 m doublet, 5.7 MEUR net drilling (Mijnlieff et al. 2013, EGC, slide 26), over two wells of 2300 m, taken into 2015 without escalation. Not re-opened in this check: placeholder, no verified source |
| `capex.degasser` | 1.0 MEUR | Same note: reserve for separation of hydrocarbons per doublet. Not re-opened: placeholder, no verified source |

The previous values 0.06, 0.95 and 0.67 EUR/W were cited to the April 2020 catalogue in 2015 prices; that
version was not re-opened for this check, and version 0019 (2020 and 2025 prices) is the source now.

Placeholder, no verified source (value unchanged): `capex.compression_chiller`, `absorption_chiller`
and `adsorption_chiller` 0.3 EUR/W (the DEA el and DH catalogue has no chiller or district cooling sheet; two searches found no
catalogue or peer-reviewed figure that was opened and read); `capex.production_pump` and `injection_pump` 0.5 EUR/W; `capex.heat_exchanger`
0.5 EUR/(W/K); `capex.cooler` 0.1 EUR/W; `capex.pipe` 500 EUR/m; `capex.flare`; `capex.gas_makeup`;
`capex.drilling` and `degasser` (above; DEA sheets 45.1 to 45.3 give only the whole plant, e.g. 1.9 MEUR/MW_h for 2000 m
(sheet 45.1.b) and 1.75 MEUR/MW_h (sheet 45.3), cost data in 2025 EURO, per MW of heat of the plant including heat pump; the sheets do not split wells, degasser, pumps or
exchangers, so they do not match a price per m of well or per kind); fixed opex of drilling, degasser, chillers, pumps, heat
exchanger, flare, gas makeup, cooler and pipe; `opex.chemical`, `waste_disposal` (not searched);
`revenue.heat` and `cold`; `discount_rate` 0.05 (the DEA catalogue guideline discounts reinvestments
at 4 % real, a different quantity; the European Commission Better Regulation Toolbox tool 64 text could not be opened);
`allocation.heat_cost_share`; `emissions.CO2.electricity` 300 g/kWh
(the EEA indicator page is an interactive chart that could not be read; the Umweltbundesamt page "Entwicklung der spezifischen
Kohlendioxid-Emissionen des deutschen Strommix in den Jahren 1990-2017", Climate Change 11/2018, states 528 g/kWh for 2015,
direct emissions, without the trade balance, but that is the 2015 grid and not the 2027 one the case describes, so it is not used).

The previous 100, 40 and 80 were not sourced. The energy prices are the latest real prices (2025) deflated to the 2015 price year,
the same convention as the capex above.

The compression chiller factor is a 0.3 EUR/W placeholder, not the heat pump row. `capex.injection_pump`
prices the `InjectionPump` of a plant per W of shaft power at its `nominal_flow` and `nominal_head`
(or the power curve at `nominal_flow`). The five plant dicts with an injection pump state those two design
values: `nominal_flow` 600 m3/h, the two doublets of 300 m3/h that the one plant-level pump serves, and
`nominal_head` 15.74 bar. They are the rule of `gm.study.size` (the flow of the doublets the pump serves,
and the pressure that `solve_injection_pressure` finds for the injection well at that flow, less the 10 bar
of the production wellhead as best suction, floored at zero) applied to the stored doublets and this case,
rounded to four digits. They are data of the plants, not a default of the package; the size of a plant with
other doublets rates its pump again. On `HeatingHeatPumpCoolingPlant` the pump is 0.187 MEUR of the
33.0 MEUR capex (0.57 %).

## Pump intake limits

`case.json` adds two constraints on the ESP intake of a running doublet, which the organisers did not state.

- Maximum free gas, 0.1875 of the volume at the intake. Source: Baker Hughes, Ace Plus gas handler pumps,
  <https://www.bakerhughes.com/production/artificial-lift/electrical-submersible-pump-systems/pumps/ace-plus-gas-handler-pumps>:
  "Performance tests indicate that Ace Plus gas handler pumps can process up to 75% free gas without locking"
  and "Standard pump stages can handle only one-fourth of this amount of free gas before locking." The limit is
  75 % / 4 = 18.75 %, the manufacturer's figure for standard stages; the page was opened on 2026-11-01. A stricter
  rule of thumb of 10 % for a standard pump (Takacs, Electrical Submersible Pumps Manual, 2009, as quoted by a design
  manual site, not opened at the book) is not used.
- Minimum intake pressure, 5 bar: assumption, no verified source. The published rule found (intake pressure above the
  bubble point of the produced fluid) needs the PVT of the fluid, which the case does not give.
- Intake values of the stored plants over the first 32 days of the case (one run, 300 m3/h per doublet): lowest pressure
  7.7 bar, largest gas share 12.1 %, so neither limit rejects a stored design. The 10 % rule of thumb would.
- The limits do reject searched designs. Without them `HeatingFullCoolingPlant` searches to 3 doublets at 3319 m with an
  intake of 2.0 bar and 35.7 % free gas, and `HeatingPlant` to 2 doublets at 3275 m with 3.0 bar and 27.2 %: both break
  both limits, so the sourced gas limit alone rejects them. With the limits they search to 1 doublet at 2456 m (5.4 bar,
  16.5 %, LCTS 55.59 EUR/MWh instead of 40.29) and 2 doublets at 3234 m (6.7 bar, 14.4 %, 29.83 instead of 29.45), and the
  lowest LCTS among the designs that deliver heat and cold is now `HeatingHeatPumpCoolingPlant`, 40.34 EUR/MWh.

## Values the plants state that a module no longer defaults

A module declares no design value: each plant dict of this folder states the values below, with the value the package used as a default before, so no result changed. Where no source is given the value is an assumption of this sample, not data of the organisers or of a machine. `dN` is `d0`, `d1`, ... one per doublet.

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
| `absorption_chiller.thermal_cop`, `chiller.thermal_cop` | 0.7 | cited: Herold, Radermacher and Klein (2016), Absorption Chillers and Heat Pumps |
| `absorption_chiller.minimum_driving_temperature`, `chiller.minimum_driving_temperature` | 353.15 K | assumption (a GEMINI operating limit of a LiBr chiller) |
| `adsorption_chiller.thermal_cop` | 0.55 | cited: Wang and Oliveira (2006), Prog. Energy Combust. Sci. 32 |
| `adsorption_chiller.minimum_driving_temperature`, `adsorption_chiller.maximum_driving_temperature` | 328.15 K, 363.15 K | assumption (a GEMINI operating range of a silica-gel machine) |
