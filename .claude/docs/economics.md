# Economics, KPIs, checks and well analysis

The packages `gemini.evaluate`, `gemini.analysis` and `gemini.study` sit above the run folders
(`engine`, `run`, `modules`, `plants`, ...), which import none of them. They read a plant, a
`gm.Case` and a finished run through the public API only. Every `gm.evaluate` function takes
`(plant, case, results, ...)`, and its return is a `Value` or a check in the
[return shapes](api.md#return-shapes): in Python a `gm.units.Quantity` in SI that also holds a
`reason` and its `parts`, and `to_plain` gives the plain JSON (no NumPy types, `NaN` and infinity
are `null`). A value the inputs cannot give is never a guess. Every name is real.

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

Every cost function returns a `Value`, a `gm.units.Quantity` in SI with the parts of its result in
`.parts`, each a value or a text; `to_plain` gives the JSON, the parts as more keys. `unit` is
`currency` (a label for the case's currency, `finance.currency`; nothing converts between
currencies), `currency/yr`, `currency/J`, `yr` or `kg`; `result.to("EUR/MWh")` converts. `A` is the
annuity factor, the sum over the lifetime years of `1 / (1 + discount_rate) ** t`, in years. Every
function takes `on_error="raise"`: a value the inputs cannot give raises `ValidationError`, code
`no_value`, or `missing_assumption`, naming its path in the case (`assumptions.finance.capex.heat_pump`),
for an assumption nobody gave. With `on_error="record"` nothing is raised and `value` is `None` with a
`reason`. Prices, rates and factors are those of `case.assumptions`; gemini holds none of its own.

| Name | Returns |
|---|---|
| `gm.evaluate.capex(plant, case)` | the sum of the capex of the equipment, per module in `parts["modules"]`, with the `price_year` of the case |
| `opex(plant, case, results)` | the fixed opex of each kind of equipment (`parts["fixed_by_kind"]`), plus the yearly bill of grid electricity, purchased gas, waste and chemicals at `opex.*` (a profile price is integrated step by step; co-produced gas costs nothing), plus the CO2 emitted at `opex.co2` when the case gives it; `components` lists the parts. There is no variable opex |
| `lcoh(plant, case, results, discount_rate=None, lifetime=None)` | `(capex + opex A) / (useful heat A)` in currency/J |
| `lcoc(...)` (as `lcoh`) | the same with the useful cold |
| `annualised_cost(plant, case, results, discount_rate=None, lifetime=None)` | `capex / A + opex` in currency/yr, with `capex`, `opex`, `annuity_factor`, `discount_rate`, `lifetime_years` |
| `lcts(...)` (as `lcoh`) | levelised cost of thermal supply: `annualised_cost / (heat + cold)` in currency/J; it needs no `heat_cost_share` |
| `co2(plant, case, results)` | kg of CO2-equivalent over the window, step by step: the leaf `co2_emission`, `methane_emission` times `emissions.CH4.gwp`, grid electricity times `emissions.CO2.electricity`; a factor is asked for only when its source is non-zero |
| `npv(plant, case, results, discount_rate=None, lifetime=None)` | `-capex + (revenue - opex) A`, with the `revenue` prices of the case |
| `payback(plant, case, results)` | `capex / (revenue - opex)` in `yr`, undiscounted |

`discount_rate` and `lifetime` are those of `case.assumptions.finance` unless given; `lifetime` is in
years. There is no `Cost` type and no `total_cost`: a module that is equipment is a subclass of the
mixin `Equipment` (`gemini/modules/_utils/cost.py`), sets `equipment_kind` to one of the kinds of
`gm.case.Capex` and defines `capex(finance)`, the factor of its kind times its own size
(`gemini.physics.costs.scaled(factor, size)`); `fixed_opex(finance)` is the share
`opex.fixed[kind]` times that capex. A composite adds only its own part. A factor or a share that
the case lacks for a kind the plant uses raises `missing_assumption` naming
`assumptions.finance.capex.<kind>` or `assumptions.finance.opex.fixed.<kind>`; nothing is
estimated. A plant with no equipment has no value.

The kinds, with the size the factor multiplies:

| Kind | Modules | Size |
| --- | --- | --- |
| `drilling` | the wells of a `Doublet` (its production well by segment, the injection well by path: twice the depth together) | m of well |
| `production_pump` | `Doublet` | shaft power at `nominal_flow` [W] |
| `circulation_pump` | `CirculationPump`, `CentrifugalPump` | shaft power [W] |
| `heat_pump`, `compression_chiller` | `HeatPump` (a kind by its `mode`) | `capacity` [W] |
| `boiler`, `electric_boiler` | `Boiler`, `ElectricBoiler` | capacity [W] |
| `chp` | `CHP` | `electric_capacity` [W] |
| `absorption_chiller`, `adsorption_chiller` | `AbsorptionUnit`, `AdsorptionChiller` | capacity [W] |
| `heat_exchanger`, `cooler` | `HeatExchanger`; `Cooler` | conductance [W/K]; capacity [W] |
| `pipe`, `thermal_storage` | `Pipe`; `ThermalStorage` | length [m]; volume [m3] |
| `degasser`, `flare`, `gas_makeup` | `Degasser`, `Flare`, `GasMakeup` | a fixed amount |
| `injection_pump` | `InjectionPump` | shaft power at `nominal_flow` (and `nominal_head` without curves) [W] |
| `ice_storage` | none | no module has a size for it |

Known limits. `InjectionPump` without `nominal_flow` raises `missing_value` on `capex`; `size` sets it.
`IceStorage` (its size in m3
needs the water density, which is not a parameter), `ESP` and `LineShaftPump` (an ESP is paid
inside the `Doublet`), `AquiferStorage`, `BoreholeField`, `DownholeHeatExchanger`, `ORC`,
`FlashTurbine`, `Separator`, `GasCompressor`, `PressurizationTank`, `Filter`, `Desander`, `Blowdown`
and `InhibitorDosing` have no kind either, so a plant that contains them is cheaper in the model
than in life. Grids, environment modules, mixers, splitters, valves and controllers are not
equipment.

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

### The values of the assumptions

gemini gives no value to any of these: each is a field of `case.assumptions` (see
[data.md](data.md#the-case)) that the user states, and a call that needs an absent one raises
`missing_assumption`. The sample case `inputs/examples/hackathon_2026/case.json` states them, in
price year 2015 and with the currency label EUR. Where a value is cited, the source is:

| Field | Value in the sample | Source |
|---|---|---|
| `capex.drilling` | 5.7e6 / (2 x 2300) = 1239.13 EUR/m | SDE+ 2013 reference case, 5.7 MEUR net drilling for a doublet at 2300 m, over two wells of 2300 m (Mijnlieff et al. 2013, EGC, Geothermal energy and support schemes in the Netherlands, slide 26). A 2013 figure, not escalated |
| `capex.degasser` | 1.0e6 EUR | same slide: reserve for separation of hydrocarbons per doublet, a 2013 figure, not escalated |
| `capex.heat_pump` | 0.67 EUR/W | Danish Energy Agency, Technology Data for Energy Plants, April 2020, ch. 40, compression heat pump, excess heat, 10 MW, 2020 in 2015 prices |
| `capex.boiler` | 0.06 EUR/W | same catalogue, ch. 44, district heating boiler, natural gas, 2020 |
| `capex.chp` | 0.95 EUR/W electric | same catalogue, ch. 06, spark ignition engine, natural gas, 1-10 MWe, 2020 |
| `emissions.CH4.gwp` | 29.8 | IPCC Sixth Assessment Report, WG I, ch. 7, table 7.15 (Forster et al. 2021): fossil methane over 100 years |

The other factors of the sample (`production_pump`, `injection_pump`, `compression_chiller`,
`absorption_chiller`, `adsorption_chiller`, `heat_exchanger`, `flare`, `gas_makeup`, `cooler`,
`pipe`), the fixed opex shares, the prices, the discount rate, the lifetime and the CO2 intensity
of electricity are placeholders for the test: the organisers gave no source, and they are not a
recommendation. The shallow district sample states invented placeholders for every factor, as its README says; leave a factor out of a case file and the call that needs it raises `missing_assumption`.

Convert at the boundary: EUR/MWh divided by 3.6e9 is EUR/J, kg/GJ divided by 1e9 is kg/J.

## Totals and KPIs

`gm.evaluate.totals(plant, case, results)` returns `{name: value}` (each a `Value`, `{value, unit}` in JSON) of what crossed the
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
| `energy_balance(plant, case, results)` | the leaf columns named in `ENERGY_INPUTS` and `ENERGY_OUTPUTS` of `modules/_utils/balance.py`, except the signed `heat_accumulation`: finite or missing, not negative | smallest power [W], 1e-9 W |
| `plant_balance(plant, case, results)` | mass and energy in = out + losses + change of stored energy, per module (1e-9) and for the root (1e-6) | a list of checks, the worst relative residual of each |
| `mass_balance(plant, case, results)` | the leaf outputs whose unit in `results.units` is kg/s: finite or missing, not negative | smallest flow [kg/s], 1e-12 kg/s |
| `bounds(plant, case, results)` | every recorded output with a declared limit (`ge`, `gt`, `le`, `lt` of its `Declaration`) | number of values outside, 0 |
| `constraints(plant, case, results)` | every `gm.case.Constraint` of the case and the supply temperatures of the services, below | one check per matched module and constraint |
| `run_all(plant, case, results)` | the first three, `bounds` and `constraints` | `{passed, checks}` |

The limits of a run are the `constraints` of its `gm.Case`: each names a **role** and a
**quantity** of it, never a module path or a field (`gm.case.roles()` is the closed table):

```python
import gemini as gm

case = gm.Case.from_json("inputs/examples/hackathon_2026/case.json")
plant = gm.Plant.from_json("inputs/examples/hackathon_2026/plants/HeatingPlant.json")
results = gm.simulate(plant, case)
checks = gm.evaluate.constraints(plant, case, results)
print(case.constraints[0].on, case.constraints[0].quantity, checks[0]["name"])
```

The units of a role are found in the plant by module class and wiring, never by name: `doublet` is
every `Doublet`, `heat_pump` a `HeatPump` whose sink reaches a `HeatingGrid`, `chiller` a machine
whose cold output reaches a `CoolingGrid`, and so on. A constraint applies to each unit of its role
on its own.

`over` says how the run is read: `each` judges every step and reports the worst (`worst_step` gives
its time); `sum`, `mean`, `max` and `min` judge one figure of the run; `duration` judges the total
time of the steps that count, `min` and `max` then being durations, passing within half a step.
`when="running"` counts only the steps on which the module carried flow: the minimum flow holds
while a doublet runs. A bound is a `Quantity` or its dict; a value on the limit passes within a
relative 1e-9.

The role `plant` is the plant as a whole (`unit_path` `""`, and the check is named after the quantity alone):
`electricity_bought`, `gas_bought` and `heat_surplus` are powers, read from the same edge ports as
`gm.evaluate.totals` (the net import of the electricity grid, the gas out of the gas grid, the surplus
of the heating grid), and `co2` is the mass emitted in one step [kg] as `gm.evaluate.co2` counts it, so
`over: "sum"` is the mass of the run and needs `assumptions.emissions.CO2.electricity` when the run
buys electricity (`missing_assumption` otherwise). `heat_output` of a `heat_pump`, `boiler` or `chp` and
`cold_output` of a `chiller` are the enthalpy delivered, the difference of the flows of two ports (a
heat pump heating: sink out less sink in; cooling: source in less source out; absorption and adsorption:
chilled in less chilled out; boiler and `CHP`: fluid out less fluid in). `doublet` also has
`intake_pressure` and `intake_gas_fraction`, the outputs of its `ESP`. A `sum` of a power adds the step
values, with no integration; `when="running"` of the plant counts the steps on which any unit carried flow. The service requirement is checked as well: each `HeatingGrid` must receive water at
least at `demand.heating.supply_temperature` and each `CoolingGrid` at most at
`demand.cooling.supply_temperature`; a service without a supply temperature adds no check.

`gm.evaluate.constraints` returns one check `{name, role, unit_path, quantity, passed, value, limit,
worst_step}` per unit and constraint, `value` the worst value of the run (or the figure) and `limit` the
bound that was violated, else the nearest. A role with no unit in the plant gives one check with `passed` `None` and
`unit_path` `None`; a name that is not in `gm.case.roles()` raises `ValidationError`, code `unknown_name`,
with suggestions. A violated limit is an answer, and a run with no value of
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

## `gm.study`

`gm.modules.check` is described in [modules.md](modules.md#registry-categories-and-streams).

`gm.study.size(plant, case, backup)` returns a new plant with first sizes from the case, by gemini
physics only. `backup` is a design policy with no default (`missing_value` naming `backup` when
absent, `invalid_value` for another word): `"peak"` rates a boiler for the whole heating peak (and drive heat) with
the doublets off, so it carries the peak when a doublet is out; `"none"` rates it for the heat the
doublets cannot reach, the larger of the peak less the heat of the doublets at their limits and the
part of the peak the reservoir temperature cannot reach. The sizes: the number of doublets (the
smallest in `case.choices.doublets` whose heat at the flow limit and the brine cooling limit of the
case's constraints covers the heating peak, the largest with a note when none does); the nominal
flow of each doublet, which is the flow limit of the case, the largest flow it may run, so its
`share` in `gm.evaluate.capacities` is at most one; the capacity of each boiler (the policy above),
heat pump and chiller; and the rating of the injection pump (the total flow of the doublets it
serves and the head to inject at that flow less the wellhead pressure). A heat pump gets the part of
the peak the reservoir water cannot reach by itself, `peak (T_supply - T_reservoir) / (T_supply -
T_return)` shared by its units (the formula assumes an ideal exchanger), and none (listed with a
note) when the reservoir is hotter than the supply. A chiller gets the cooling peak shared, except
the chiller that closes the chilled-water series, which gets the whole peak: a sorption unit
delivers less than its rating when its characteristic map says so at the peak conditions (an
adsorption chiller 6 kW short at the peak, which the chillers in series pass on as 3 mK), and the
last chiller makes up the difference. A boiler is rated for the step where the heating demand and the drive heat of the
sorption chillers it feeds (their duty over `thermal_cop`, found from the wiring) peak together:
the whole of it for `"peak"`, and for `"none"` that less the heat of the doublets, at least its
lift share (the ideal-exchanger assumption may leave the supply short, which `broken` lists). The sized plant is then
simulated once on the case. The plant is not changed; the notes are `plant.sizing`: `{"sized":
[{path, value, reason}], "unchanged": [{path, reason}], "broken": [{unit_path, role, quantity,
value, limit, worst_step}], "simulation": str}`, where `broken` lists each constraint the sized
design breaks (empty when it meets them all) and `simulation` says `simulated` or `not simulated:
<code>: <reason>`. A plant class that takes no structural size `doublets` (see
`gm.plants.capabilities()`) keeps the doublets it has and says so in `unchanged`; a size the case
lacks the input for raises `missing_value` naming its path. A size that is not computed for a
module kind (`chp`, `heat_exchanger`) is left unchanged and listed.

`gm.study.minimize(plant, case, objective, variables=None, constraints=None, evaluations=100, *,
plan=None)` searches design values. Each trial copies the plant and the case, sets the variables,
plans the demand of the case on that design with `gm.schedule`, simulates and reads the metric, so
neither is changed. Without `variables` they are those of `case.choices`: `size.doublets` (a
discrete variable: the search runs once for each count, from the lowest to the highest, on a new
plant of that size, and the best trial of all counts wins) and `depth`; a list replaces them, so
restate these to keep searching them, and a capacity is searched only when listed. A name is a plant
`path.parameter`, a number of the case as `case.<path>` (the path of `case.json`, for example
`case.assumptions.finance.opex.electricity`), `size.doublets`, or `<role>.<parameter>` with a role
of `gm.case.roles()` (`heat_pump.capacity`, `chiller.capacity`, `doublet.nominal_flow`,
`doublet.depth`): it sets that parameter on every unit of the role, after the doublet count, so one
list serves plants of other paths and counts. `depth` on a plant with no depth of its own is the
depth of each doublet. A variable the plant cannot take, a role it lacks or `size.doublets` on a
plant whose dict has none, is not searched and is in the result's `fixed`
(`{name, value, reason}`); `invalid_design` is raised only when nothing is left to search. A `plan`
stays fixed over the trials and lets `case` be `None` for a building block; with neither the call
raises `missing_value`. `evaluations` is the largest number of simulations **for each doublet
count**; with three variables 15 gave 45 trials. The search is
`scipy.optimize.differential_evolution` from a Latin hypercube, seed fixed, with five candidates per
variable, so a smaller budget than one population raises `ValidationError`.

A trial is feasible when its run has no failed step, every constraint of the case passes
(`gm.evaluate.constraints`, the supply temperatures of the services included) and every limit of
the `constraints` argument (limits on *metrics*, `{metric, minimum, maximum}`, not the
`case.constraints` on roles) holds. A check with no value (no flow, a role the plant lacks) does
not fail a trial. A trial that does not run, such as a negative injection head at great depth, is
infeasible and the search goes on. The optimiser sees every feasible trial as better than every
infeasible one and the infeasible ones ordered by their relative violation. `history` holds every
trial with its `reason` (`None` when feasible; the first failed check, a dict, or a text) and
`parts["violation"]`. The result is `{best, feasible, fixed, history, evaluations}`; `best` is the
objective as a `Value` whose `parts["parameters"]` are `{name: Quantity}` and whose `["plant"]` is
the best feasible plant, or with none the least violating trial that ran, then `feasible` is
`False`. A trial costs about 1.5 times one `gm.simulate` of the same plant and case (0.15 s against
0.10 s on the year of the hackathon sample), see below.

`gm.study.sample(plant, case, distributions, metrics, count, seed=0, *, plan=None)` draws `normal`,
`uniform` and `triangular` values (a plant parameter or `case.<path>`, each field a `Quantity`) with
`numpy.random.default_rng(seed)`, one simulation each, and summarises each metric as `mean`, `p5`,
`p50`, `p95`, with `failed`, the number of draws left out. A run with failed steps is no valid
design: its metrics are `None` with a `reason` (the count of failed steps and the most frequent
failure group of `gm.evaluate.failures`), it stays out of the summary, and in `sensitivity` its
end and the effect are `None` with that reason. `minimize` calls such a trial infeasible with the
same reason, never the best, and `compare` calls a report with `failed_steps > 0` infeasible
(`failed_steps`). The evaluate cost functions still report what was delivered.
`gm.study.sensitivity(plant, case, parameters, metrics, *, plan=None)` runs each value at its `low`
and its `high` with the others as they are, and returns a list of `{parameter, metric, low, high,
at_low, at_high, effect}`, the largest effect first, with `to_frame(units=None)`: the metric columns
in the display unit of the metric, or the unit of `units`, and a `unit` column.

**What a trial costs.** A trial copies the plant once, sets its variables and the values of the case
on that copy (`applied_in_place` of `gemini/run/_utils/apply.py`), and the run and every metric read
that copy: `apply_case` returns a copy that already carries the same case object, so it copies
nothing again. The ESP depth and the pipe path of a well (`section_length`, `section_inclination`,
`section_diameter`, `section_roughness`, `esp_depth`) are numeric graph inputs, so one traced graph
serves every trial of a study (a different number of sections, or an ESP that is added or removed,
traces once more). `Results.to_frame()` of a finished run builds its table with the unit of each
column without touching the columns one by one.

**Parallel trials.** `with gm.runtime.settings(processes=4):` runs the independent trials of
`sample` and `sensitivity` in four worker processes, and the searches of `minimize` for the
different doublet counts (a search over one count is sequential: each candidate uses the
generation before it). The results are those of a serial run, in the same order. Workers start from
a `forkserver`, so a script needs the `if __name__ == "__main__":` guard; the first parallel call of
a process pays the import of gemini once (about a second and a half) and every worker traces its
own graphs, so a study of fewer than a dozen trials is faster serial.

A metric is a KPI or total of `gm.evaluate.totals` or one of `lcoh`, `lcoc`, `lcts`,
`annualised_cost`, `co2`; the economic ones read the assumptions of `case`, so they need a case with
the factors they use. `parameters` in `best`, `history` and `samples` are `Quantity` values in SI,
the input of the next `set_params`.

## Report and comparison

`gm.evaluate.capacities(plant, case, results)` returns `{path: {kind, capacity, peak, share}}` for
each module that is equipment and has a rating: the design capacity, the largest use of any step
and their ratio. `gm.evaluate.report(plant, case, results)` returns a `Report`, a `dict` with
`heat_delivered`, `cold_delivered`, `boiler_heat`, `electricity_bought`, `gas_bought` (J over the
run), `capacities`, `capex`, `opex`, `lcts`, `lcoh`, `lcoc`, `co2`, `constraints`, `passed` and
`failed_steps`; its costs are read with `on_error="record"`, so a cost the case cannot give is a
value `None` with a `reason` and many designs stay comparable. `report.to_dict()` is plain JSON in display units, the parts of each value too: the annualised cost and the opex components in MEUR/yr, an energy per year in MWh/yr, a mass in kt, a duration in days (the lifetime included); `units=` reaches the parts of the same SI unit (`co2="t"` shows the kg parts in t); the values inside the report stay SI.
`gm.evaluate.compare(reports, by)` ranks reports by the metrics `by` (a name, a list, or a
`{metric: "min" | "max"}` dict) and returns a `Comparison`, a list with one entry per report in the
order given (`index`, `values`, `ranks`, `pareto`, `feasible`, and `reasons` when not feasible) and
`to_frame(units=None)`. A report is feasible when no step failed, no constraint failed and every
service in its `services` (`report["services"]`) is delivered; feasible reports rank first, only
they can be on the front, and `reasons` are the failed items of `gm.evaluate.constraints` or
`{name, reason}`. `values` stay floats in SI; `to_frame` shows the metrics in display units, columns
`<metric> [<unit>]`. A report with no value of a metric ranks last for it and is never on the
front.
