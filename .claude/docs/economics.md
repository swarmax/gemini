# Economics, KPIs, checks and well analysis

The packages `gemini.evaluate`, `gemini.analysis` and `gemini.optim` sit above the run folders
(`engine`, `run`, `modules`, `plants`, ...), which import none of them. They read a plant, a
`gm.Problem` and a finished run through the public API only, every `gm.evaluate` function takes
`(plant, problem, results, ...)`, and and every return is plain JSON (`to_plain`: no NumPy types, `NaN` and infinity are `null`) in the
[return shapes](api.md#return-shapes). A value the inputs cannot give is never a guess. Each name is
`real` or raises `NotImplementedYet` with its final signature and a full docstring.

## What a run gives

`Results` stores the leaf columns (`path.field`, the outputs and the port quantities), not the
composite outputs. Everything below is read from the edge modules:

- Heat delivered is what the water loses across the `HeatingGrid` leaves and cold delivered what
  it gains across the `CoolingGrid` leaves (`evaluate/_utils/series.py`: `delivered_heat`,
  `delivered_cold`). **Useful** heat and cold are that less the `surplus` of the grid, so at most the
  demand (`useful_heat`, `useful_cold`). `gm.evaluate.totals` gives all three; every KPI and levelised
  cost reads the useful energy: a heat nobody needed costs money and earns nothing.
- Electricity bought and sold are `net_import` and `net_export` of the `ElectricityGrid`, gas
  bought is `gas_out.chemical_flow` of the `GasGrid`, waste `waste_in.mass_flow` of the `WasteGrid`
  and chemicals `chemical_out.mass_flow` of the `ChemicalGrid` (`edge_total`). `gm.evaluate.totals`
  gives them, with the emissions and the losses.
- CO2 comes from one place: `Atmosphere` computes `co2_emission` and `methane_emission` [kg/s] from
  the gas that reaches `gas_in`.
- A tick with no value (a skipped or failed row) adds no energy and is left out of ratios and peaks.
- The window of a run is the sum of its tick durations. Annual figures scale the window to one year
  (`SECONDS_PER_YEAR`, 365.25 days): the run is taken as representative of a year.

A plant without a consumer leaf, such as the doublet heat plant, delivers no heat in these terms, so
its heat and cold KPIs and levelised costs are `null` with that reason.

## Costs

Every function returns a `Value`, a `gm.units.Quantity` in SI with the parts of its result in
`.parts`, each a value or a text; `to_plain` gives the JSON, the parts as more keys. `unit` is
`currency` (a label for the case's currency, nothing converts between currencies), `currency/yr`,
`currency/J`, `yr` or `kg`; `result.to("EUR/MWh")` converts. `A` is the annuity factor, the
sum over the lifetime years of `1 / (1 + discount_rate) ** t`, in years. Every function takes
`on_error="raise"`: a value the inputs cannot give raises `ValidationError`, code `no_value`, or
`missing_assumption`, naming it, for an assumption nobody gave. With `on_error="record"` nothing is
raised and `value` is `None` with a `reason`. The prices, rates and cost factors are those of
`problem.assumptions` (`gm.Assumptions`).

| Name | Returns |
|---|---|
| `gm.Assumptions` | frozen object of the problem; see the table of sources below |
| `gm.evaluate.capex(plant, problem)` | `total_cost(plant)`: investment in the currency of the declared costs, with `price_year` and `source` |
| `opex(plant, problem, results)` | fixed + variable cost per year + yearly bill of grid electricity, purchased gas, waste and chemicals at `prices` (a profile price is integrated step by step; co-produced gas costs nothing) + the CO2 emitted at `co2_price` when given; `components` lists the parts |
| `lcoh(plant, problem, results, discount_rate=None, lifetime=None)` | `(capex + opex A) / (useful heat A)` in currency/J, `A` the annuity factor |
| `lcoc(...)` (as `lcoh`) | the same with the useful cold |
| `annualised_cost(plant, problem, results, discount_rate=None, lifetime=None)` | `capex / A + opex` in currency/year, with `capex`, `opex`, `annuity_factor`, `discount_rate`, `lifetime_years` |
| `lcts(...)` (as `lcoh`) | levelised cost of thermal supply, the team's design metric: `annualised_cost / (heat + cold)` in currency/J, heat and cold delivered per year, with `annualised_cost`, `heat`, `cold`; it needs no `heat_cost_share` |
| `co2(plant, problem, results)` | kg of CO2-equivalent over the window: the leaf `co2_emission`, `methane_emission` times `methane_gwp`, grid electricity times `electricity_emission_factor` |
| `npv(plant, problem, results, discount_rate=None, lifetime=None)` | `-capex + (revenue - opex) A` |
| `payback(plant, problem, results)` | `capex / (revenue - opex)` in years, undiscounted |

`Cost` and `total_cost` (`types/cost.py`) are the one cost implementation. Every equipment module
that has a cost declares `capex(assumptions)`, which returns a `Cost` from its own design values and
a cost factor of `Assumptions` through `scaled_cost(assumptions, factor, size)`; a composite adds only
its own part. A factor without a value raises `ValidationError`, code `missing_assumption`, under
`"record"` `{value: null, reason}`. A plant with no declaring module has no value, with the reason "no
module declares a cost". Costs in different currencies or price years raise `ValidationError`;
assumptions in another currency than the costs raise `ValidationError`.

| Module | `capex` |
| --- | --- |
| `Doublet` with a design | `drilling_cost` times twice the depth, plus `pump_cost` times the shaft power at `nominal_flow`; without a design, none |
| `HeatPump`, `Boiler`, `AbsorptionUnit` | `heat_pump_cost`, `boiler_cost`, `chiller_cost` times `capacity` |
| `CHP` | `chp_cost` times `electric_capacity` |
| `HeatExchanger` | `exchanger_cost` times `thermal_conductance` |
| `Degasser`, `Flare`, `GasMakeup` | `degasser_cost`, `flare_cost`, `makeup_cost`, fixed items |

`lcoh` charges the whole plant cost to the heat. A plant that also delivers cold has no value ("the
split of its cost is not defined") unless `heat_cost_share` gives the part charged to heat; `lcoc`
gets the rest. `lcts` needs no share: with a `heat_cost_share` of 1, `lcts` is `lcoh` times its
energy over `heat + cold`. It has no value when the run delivers neither. `lcoh` and `lcoc` keep the
one expression `(capex + opex A) / (energy A)`: `annualised_cost` and they share `lifetime_cost`
(`capex + opex A`) and not the division, which would move the last bits of their numbers. Levelised
cost, `npv` and `payback` assume constant yearly energy and cost over the
lifetime, with no degradation, tax, replacement or residual value.

Missing user inputs raise `ValidationError` with code `missing_assumption` and the path
`assumptions.<name>`: a discount rate or lifetime given nowhere, an electricity or gas price for an
energy the run buys, a heat or cold price for a product it delivers, an electricity emission factor
for grid electricity drawn. A price is asked for only when its energy is non-zero.

### Sources of the `Assumptions` defaults

| Field | Unit | Default | Source |
|---|---|---|---|
| `currency` | text | `"EUR"` | label only, the default of `Cost`; not a price |
| `methane_gwp` | - | 29.8 | IPCC Sixth Assessment Report, Working Group I, ch. 7, table 7.15 (Forster et al. 2021): fossil methane over 100 years |
| `discount_rate` | per year | None | depends on the project; the user gives it |
| `lifetime_years` | years | None | depends on the equipment; the user gives it |
| `prices["electricity"]`, `prices["gas"]`, `prices["heat"]`, `prices["cold"]` | currency/J | None | depends on country, year and contract; a `Quantity` such as `{"value": 100, "unit": "EUR/MWh"}`, or a profile on the demand index (an array value) |
| `prices["waste_disposal"]`, `prices["chemical"]` | currency/kg | None | depends on the contract |
| `co2_price` | currency/kg | None | a choice of the assessment; a `Quantity` (`{"value": 80, "unit": "EUR/t"}`) |
| `heat_cost_share` | - | None | a choice of the assessment |
| `electricity_emission_factor` | kg/J | None | depends on the grid and the year; a `Quantity` such as `{"value": 300, "unit": "g/kWh"}` |

### Sources of the cost factors

All are in `cost_price_year` = 2015, the prices of the Danish catalogue; `Assumptions` has the
citation of each in `COST_SOURCES`, and `capex` returns it in `source`.

| Field | Unit | Default | Source |
|---|---|---|---|
| `drilling_cost` | currency/m of well | 1239.13 | SDE+ 2013 reference case, 5.7 MEUR net drilling for a doublet at 2300 m, over 2 x 2300 m (Mijnlieff et al. 2013, EGC, slide 26). Per doublet by the table's own sum: 6.2 MWth at 1527 EUR/kWth is 9.5 MEUR. A 2013 figure, not escalated. The 3000 m case gives 1833 EUR/m: use it for deep designs |
| `degasser_cost` | currency | 1 000 000 | SDE+ 2013 reference case, reserve for separation of hydrocarbons per doublet (same slide), a 2013 figure, not escalated |
| `heat_pump_cost` | currency/W | 0.67 | Danish Energy Agency, Technology Data for Energy Plants, April 2020, ch. 40, compression heat pump, excess heat, 10 MW, 2020 |
| `boiler_cost` | currency/W | 0.06 | same catalogue, ch. 44, district heating boiler, natural gas, 2020 |
| `chp_cost` | currency/W electric | 0.95 | same catalogue, ch. 06, spark ignition engine, natural gas, 1-10 MWe, 2020 |
| `pump_cost`, `chiller_cost`, `exchanger_cost`, `flare_cost`, `makeup_cost` | | None | no source found; using one raises `missing_assumption` |

Convert at the boundary: EUR/MWh divided by 3.6e9 is EUR/J, kg/GJ divided by 1e9 is kg/J.

## Totals and KPIs

`gm.evaluate.totals(plant, problem, results)` returns `{name: {value, unit}}` of what crossed the
plant's edge (`heat_delivered`, `heat_useful`, `heat_surplus`, `cold_delivered`, `cold_useful`,
`cold_surplus`, `electricity_bought`, `electricity_sold`, `gas_bought`, `losses`, `co2_emitted`,
`methane_emitted`, `waste`, `chemicals`) and of the KPIs below; one the run cannot give is `null`
with a `reason`. There is no separate KPI call. With E(x) the sum over ticks of x times the tick
duration:

| Name | Unit | Definition |
|---|---|---|
| `heating_coverage` | - | E(useful heat) / E(useful heat + `unmet_demand`) over the `HeatingGrid` leaves |
| `cooling_coverage` | - | E(useful cold) / E(useful cold + `unmet_sensible` + `unmet_latent`) over the `CoolingGrid` leaves |
| `cop` | - | E(useful heat) / E(`ElectricityGrid.power_out`); cooling not counted |
| `peak_heat` | W | largest tick sum of useful heat (delivered power, not the demand peak) |
| `peak_cold` | W | largest tick sum of useful cold |

## Checks and constraints

Each check returns the check `{name, passed, value, limit}`, `value` and `limit` being values; a
violated limit is `passed: false`, never an error (`passed` is `None`, with a `reason` in `value`,
when the results hold nothing the check can judge). Because `Results` has no streams, the enthalpy and mass
closure of `modules/_utils/balance.py` (sum in minus sum out per call) cannot be recomputed from
it, and the checks audit what the columns hold:

| Check | Covers | `value`, `limit` |
|---|---|---|
| `energy_balance(plant, problem, results)` | the leaf columns named in `ENERGY_INPUTS` and `ENERGY_OUTPUTS` of `modules/_utils/balance.py`, except the signed `heat_accumulation`: finite or missing, not negative | smallest power [W], 1e-9 W |
| `plant_balance(plant, problem, results)` | mass and energy in = out + losses + change of stored energy, per module (1e-9) and for the root (1e-6) | a list of checks, the worst relative residual of each |
| `mass_balance(plant, problem, results)` | the leaf outputs whose unit in `results.units` is kg/s: finite or missing, not negative | smallest flow [kg/s], 1e-12 kg/s |
| `bounds(plant, problem, results)` | every recorded output with a declared limit (`ge`, `gt`, `le`, `lt` of its `Declaration`) | number of values outside, 0 |
| `constraints(plant, problem, results)` | every `gm.Constraint` of the problem, below | one check per matched module and constraint |
| `run_all(plant, problem, results)` | the first three, `bounds` and `constraints` | `{passed, checks}` |

The limits of a run are the `constraints` of its `gm.Problem`, built without a plant:

```python
problem = gm.Problem(
    demand,
    constraints=[
        gm.Constraint("d*.reservoir.liquid_flow", min={"value": 50, "unit": "m3/h"}, max={"value": 300, "unit": "m3/h"}, when="running"),
        gm.Constraint("d*.brine_cooling", max={"value": 40, "unit": "K"}),
        gm.Constraint("heat_users.supply_in_T", min={"value": 100, "unit": "degC"}),
        gm.Constraint("d*.reservoir.liquid_flow", max={"value": 330, "unit": "d"}, over="duration", when="running"),
    ],
)
checks = gm.evaluate.constraints(plant, problem, results)
```

A path is `<module path>.<field>`, `*` stays within one name (`d*.power` is not `d0.esp.power`). It
names a result field or a parameter. `over` says how the run is read: `each` judges every step and
reports the worst (`worst_step` gives its time); `sum`, `mean`, `max` and `min` judge one figure of
the run; `duration` judges the total time of the steps that count, `min` and `max` then being
durations, passing within half a step. `when="running"` counts only the steps on which the module
carried flow: the minimum flow holds while a doublet runs. A parameter takes `over="each"` and is
judged once against its value with the site of the problem applied, or at each date inside the run
when it changes. `d*.volume_imbalance` is the produced less the injected liquid volume flow of a
doublet. A bound is a `Quantity` or its dict, a plain number only for a field without a unit; a value on the limit passes within a
relative 1e-9.

`gm.evaluate.constraints` returns one check `{name, passed, value, limit, path, worst_step}` per
matched module and constraint, `value` the worst value of the run (or the figure) and `limit` the
bound that was violated, else the nearest. A path that matches nothing raises `ValidationError`,
code `unknown_name`, with suggestions. A violated limit is an answer, and a run with no value of
the field, every row having failed, gives `passed: null` with the reason `no_value`. `Results`
holds leaf columns, so an output of a composite is read through the paths its combination names:
`Doublet` declares `brine_cooling`
(`Output.difference("riser.wellhead_out.T", "injector.wellhead_in.T")`), and the liquid volume flow of
a doublet is `reservoir.liquid_flow` of its reservoir. `gm.schedule` enforces some forms of the same
constraints and lists the others in `plan.attrs["check_only"]`, see
[engine.md](engine.md#schedule); `constraints` judges them all.

A real closure check needs the engine to record each call's residual (`balance.energy_balance`)
as a result column; that is a change to the engine, not to this package.

## `gm.analysis`

`gm.analysis.calibrate` and `CalibrationResult` fit parameters through replay; the other names:

| Name | Status | Notes |
|---|---|---|
| `nodal(plant, well, conditions)` | real | IPR, VLP and operating point from `gemini/analysis/solves.py`, for production and injection wells; the plant is not changed |
| `pump_curve(plant, pump, measured=None)` | real | the polynomial head curve of the pump at 60 Hz (the private `_head_curve` of `gemini/analysis/wells.py`), theoretical head of measured points, `gm.analysis.fit_head_correction` |
| `corrosion_forecast(model, until)` | real | `co2_corrosion_rate`, `wall_loss`, `time_to_minimum_wall` |
| `injectivity(data, well)` | `NotImplementedYet` | Hall analysis not built |
| `calibrate_pump(plant, pump, measured)` | `NotImplementedYet` | no module applies the `correction_factors` of `ESP` (only the legacy import and export read it); it will run `gm.analysis.calibrate` |
| `calibrate_corrosion(logs)` | `NotImplementedYet` | no fit of the correlation constants to logs exists |
| `erosion(plant, well)` | `NotImplementedYet` | a plant holds neither flow nor solids content, and the retained model has no solids fraction |

`nodal` takes `conditions` as one dict or a list of dicts (a what-if): `wellhead_pressure` [Pa],
`rates` as the `[low, high]` bracket [kg/s] and `frequency` [Hz] for an ESP; quantities such as
`{"value": 3, "unit": "bar"}` are accepted. A case whose bracket leaves the well model's domain raises `PhysicsError`; with `on_error="record"`
the case carries the problem in `error` and the other cases still run. The VLP is the wellhead pressure the well, ESP and riser
deliver at each rate; the operating point is where it falls to the wellhead pressure asked for.

`well` naming an injection well, or its aquifer, solves the injection side (`doublet.injector`: the
path of a doublet itself is its production chain). A case has `rates`, `temperature` at the wellhead
and either `rate` or `wellhead_pressure`. `ipr` is the sandface pressure the aquifer needs, `vlp` the
wellhead pressure that delivers it, and the operating point the pressure of the rate or the rate of
the pressure. A rate the column of brine injects alone has no pressure to give: `null` on `vlp`, and a
`null` value with a reason in `operating_point`.

`pump_curve` head is a pressure difference in Pa; the head of a fluid column in metres is
`head / (density g)`. The correction is `theoretical = slope * measured + offset` (offset in Pa).

## `gm.optim`

`gm.modules.check` is described in [modules.md](modules.md#registry-categories-and-streams).

`gm.optim.minimize(plant, problem, variables, objective, constraints=None, evaluations=100, *,
plan=None)` searches design values. Each trial copies the plant, sets the variables with
`set_params`, plans the demand of the problem on that design with `gm.schedule`, simulates and reads
the metric, so the plant is not changed. A `plan` stays fixed over the trials and lets `problem` be
`None` for a building block; with neither the call raises `missing_value`. A trial reads a
finished run in about 0.15 s; simulating the year takes 0.3 s on a plant without a loop and 6 to 9 s
on one with the drive-water loop of a heat-driven chiller, which runs row by row. The search is
`scipy.optimize.differential_evolution` from a Latin hypercube, seed fixed,
with five candidates per variable: the population times the generations is the number of
simulations, so `evaluations` is a hard limit and a smaller budget than one population raises
`ValidationError`. A trial that fails, has no value or breaks a constraint is in `history` with its
`reason` and is never `best`. `gm.optim.sample(plant, problem, distributions, metrics, count, seed=0,
*, plan=None)` draws `normal`, `uniform` and `triangular` parameters with
`numpy.random.default_rng(seed)`, one simulation each, and summarises each metric as `mean`, `p5`,
`p50`, `p95`; a draw whose run failed has its `reason` and stays out of the summary.
`gm.optim.size` and `gm.optim.sensitivity` have their final signature and raise `NotImplementedYet`.

A metric is a KPI or total of `gm.evaluate.totals` or one of `lcoh`, `lcoc`, `lcts`,
`annualised_cost`, `co2`; the economic ones read the assumptions of `problem`, so they need a
problem. The constraints of the problem that `gm.schedule` enforces (the flow range and the brine
cooling per doublet) are required for a demand, as for `gm.schedule`. `parameters` in `best`,
`history` and `samples` are numbers in SI, the input of the next `set_params`.
