# Glossary

One name per concept for every parameter, output and port of a module. Names are full words. The
`Stream` fields `m_dot`, `T` and `p` keep their symbols; they are part of the frozen `Stream` type
and appear in a name only as `<port>_T`, the output of a port's temperature, by the rule of
[conventions.md](conventions.md#naming). The physics functions take their own argument names and
are not covered here.

`tests/unit/modules/test_glossary.py` checks every name of every registered module against the two
lists below: no name is retired, and every word of a name is in the vocabulary. A new word goes
into the vocabulary in the commit that first uses it, only if it is a full word for a new concept.

## Concepts

| Concept | Name | Not |
| --- | --- | --- |
| number of stages of a machine | `stage_count` | a count written as `no_` or `number_of_` |
| list of curve coefficients | `head_coefficients`, `power_coefficients` | `coeff` |
| lower or upper bound | `minimum_<quantity>`, `maximum_<quantity>` | `min_`, `max_`, a suffix `_min` |
| fall in pressure | `<place>_pressure_drop` | `dp` |
| value at the design point | `nominal_<quantity>`, `<side>_nominal_<quantity>` | a suffix `_nominal` |
| mass flow as a parameter or output | `<what>_mass_flow` | `m_dot` |
| overall conductance UA | `thermal_conductance`; to the ambient `heat_loss_conductance` | `ua` |
| overall coefficient U per area | `heat_transfer_coefficient` | `u_value`, `coeff` |
| share of an ideal cycle | `carnot_fraction`, `lorenz_fraction` | `carnot_efficiency`, `fraction_of_carnot` |
| flow at the best-efficiency point | `best_efficiency_flow`, `best_efficiency_ratio` | `bep` |
| boolean | `is_<state>`: `is_capped`, `is_in_operating_window` | a bare `capped` |
| required supply temperature of a service | `minimum_supply_temperature` (`HeatingGrid`), `maximum_supply_temperature` (`CoolingGrid`); set from `demand.<service>.supply_temperature` of the case | `required_`, `target_` |
| return temperature of a service | `return_temperature`; set from `demand.<service>.return_temperature` of the case | |
| a value the case sets, not the plant dict | declared `Parameter(..., case="<path>")` | |
| temperature at a port | `<port>_T`: `fluid_out_T`, `hot_out_T`, `production_out_T` | |
| temperature elsewhere | `<place>_temperature`: `ground_temperature`, `approach_temperature` | `_T` |
| number of transfer units | `transfer_units` | `ntu` |
| logarithmic mean difference | `log_mean_temperature_difference` | `lmtd` |
| heat per kg and kelvin | `<what>_specific_heat` | `heat_capacity` for a per-kg value |
| heat per m3 and kelvin | `<what>_volumetric_heat_capacity` | |
| thickness of a water-bearing layer | `aquifer_thickness` | a bare `thickness` |
| bulk material around a well | `ground_conductivity`, `ground_diffusivity`, `ground_...` | |
| solid matrix of a porous layer | `rock_volumetric_heat_capacity` | |
| depth of a borehole | `borehole_depth` | a bare `depth` |
| design of a doublet from its depth | `depth`, `thickness`, `gradient`, on `Doublet` and, `depth` alone, on the plants of `DoubletsPlant` | |

Four short forms stay because the full word would be longer and no clearer in this field: `T` (see
above), `co2`, `cop` (coefficient of performance) and `esp` (electrical submersible pump).

## Port roles

Every port is `<role>_in` or `<role>_out` ([conventions.md](conventions.md#naming)). The roles are
`hot`, `cold`, `source`, `sink`, `generator`, `chilled`, `cooling`, `charge`, `discharge`, `supply`,
`return`, `gas`, `liquid`, `fuel`, `power`, `loss`, `air`, `waste`, `chemical`, `wellhead`, `bottom`,
`sandface`, `production`, `injection`, `fluid`, `branch<N>`, `grid`, `excess`, `heat`, `flue` and `wet_air`.

## Retired names

| Retired | Current |
| --- | --- |
| `approach_T` | `approach_temperature` |
| `bep_flow` | `best_efficiency_flow` |
| `bep_ratio` | `best_efficiency_ratio` |
| `building_return_T` | `building_return_temperature` |
| `building_supply_T` | `building_supply_temperature` |
| `capped` | `is_capped` |
| `carnot_efficiency` | `carnot_fraction` |
| `clogging_dp` | `clogging_pressure_drop` |
| `correction_factor` | `correction_factors` |
| `dp` | `nominal_pressure_drop` |
| `dp_cold` | `cold_pressure_drop` |
| `dp_cold_nominal` | `cold_nominal_pressure_drop` |
| `dp_friction` | `friction_pressure_drop` |
| `dp_gravity` | `gravity_pressure_drop` |
| `dp_hot` | `hot_pressure_drop` |
| `dp_hot_nominal` | `hot_nominal_pressure_drop` |
| `dp_nominal` | `nominal_pressure_drop` |
| `flow_dp` | `flow_pressure_drop` |
| `fluid_mean_T` | `fluid_mean_temperature` |
| `fraction_of_carnot` | `carnot_fraction` |
| `friction_correlation_2p` | `two_phase_friction_correlation` |
| `ground_T` | `ground_temperature` |
| `head_coeff` | `head_coefficients` |
| `heat_loss_coefficient` | `heat_loss_conductance` |
| `heat_transfer_coeff` | `heat_transfer_coefficient` |
| `hydrostatic_dp` | `hydrostatic_pressure_drop` |
| `ice_heat_capacity` | `ice_specific_heat` |
| `in_operating_window` | `is_in_operating_window` |
| `lmtd` | `log_mean_temperature_difference` |
| `lorenz_efficiency` | `lorenz_fraction` |
| `m_dot_cold_nominal` | `cold_nominal_mass_flow` |
| `m_dot_hot_nominal` | `hot_nominal_mass_flow` |
| `m_dot_nominal` | `nominal_mass_flow` |
| `max_flow` | `maximum_flow` |
| `min_flow` | `minimum_flow` |
| `no_stages` | `stage_count` |
| `ntu` | `transfer_units` |
| `output_max` | `maximum_output` |
| `output_min` | `minimum_output` |
| `p_out` | `outlet_pressure` |
| `power_coeff` | `power_coefficients` |
| `production_T` | `production_out_T` |
| `rock_conductivity` | `ground_conductivity` |
| `rock_diffusivity` | `ground_diffusivity` |
| `skin_dp` | `skin_pressure_drop` |
| `u_value` | `heat_transfer_coefficient` |
| `ua` | `thermal_conductance` |
| `water_heat_capacity` | `water_specific_heat` |

## Vocabulary

```text
absorbed absorber accumulation active adsorber air ambient approach aquifer arrangement auxiliary
baumann best blowdown borehole bottom bottomhole branch1 branch2 breakthrough brine building bulb burned capacity
capped carnot change characteristic charge charged chemical chilled clogging co2 coefficient coefficients
cold combustion command composition concentration condenser condensing conductance conductivity consumption
cooler cooling cop coproduced correction correlation cost count curtailed decline demand density depth
derivative dew diameter difference diffusivity direction discharge dose drainage drawdown drift
driving drop dumped duty effective effectiveness efficiency electric electricity elevation
emission empty energy error esp evaporation evaporator excess exhaust export extraction factor factors
fan feed first flow flue fluid fouling fraction freezing frequency friction fuel full gain gas
generated generation generator geothermal gradient gravity grid gross ground groundwater head heat
heating hot humidity hydraulic hydrostatic ice imbalance import in index indoor injected
injection injectivity inclination inlet inner input integral is isentropic latent length lift limit limited
liquid load log loop lorenz loss margin mass maximum mean measurement methane minimum mixed mode
model motor net network no nominal opening operating or out outlet output overpressure parasitic
part path period permeability phase pinch pipe point porosity power pressure previous price
product production productivity proportional pump pumping purchased quality radial radius rangeability rate rated rates
ratio recovered recovery reference rejection relative removal residual resistance retained
return rise rock role roughness running sand sandface saturated saturation second secondary section segment
sensible separation service setpoint setting shaft sink skin slope soil source spacing specific
split stage steam step storage stored suction supplied supply surface surplus tank temperature thermal
thickness threshold time top transfer tubing two type undisturbed units unmet unserved useful
value valve velocity vented viscosity volume volumetric warm waste water well wellbore wellhead wet
window
```

## Case and cost terms

Not names of module declarations, so not in the list above; the one meaning of each word elsewhere:

| Term | Meaning |
| --- | --- |
| case | `gm.Case`: everything a plant is asked to do and the world around it, in the sections `time`, `environment`, `demand`, `choices`, `constraints`, `assumptions` |
| role | a kind of unit found in a plant by class and wiring (`doublet`, `heat_pump`, `boiler`, `chp`, `chiller`, `heat_exchanger`, `heating_supply`, `cooling_supply`); `gm.case.roles()` |
| quantity of a role | what a constraint limits on every unit of the role (`production_flow`, `brine_cooling`, `cop`, ...) |
| equipment kind | the key of `capex` and `opex.fixed` in the case (`drilling`, `heat_pump`, `boiler`, ...); a module that is equipment declares `equipment_kind` |
| capex factor | the unit cost of a kind in the case, times the size of the equipment |
| problem | only the shape `{path, code, message, suggestions}` of an error or a failed row; never an input |
