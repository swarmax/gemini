# Physics rules

`gemini/physics` holds the textbook formulas and everything more than one category reads; physics of
one category lives in `gemini/modules/<category>/_physics.py` (rule in
[conventions.md](conventions.md#module-rules)). Modules declare parameters and wire streams; they
call physics and write no correlation of their own. The public names are `gm.physics.<topic>`.
Unit conversions are not here: they are `gm.units` (`gemini/units/`, see below). The files cover
constants, fluid properties, geometry, hydraulics, heat transfer, pumps, chemistry, corrosion and
erosion, gas compression, refrigeration cycles, IAPWS-IF97 steam, ground heat transport,
psychrometrics, separation, combustion, thermal storage, PID control, power cycles, grid
electricity, energy conversion and health diagnostics. The equipment catalogue
([equipment.md](equipment.md)) lists the functions each module calls. The sections after the file
list state the rules, then each subject (the original GEMINI correlations first).

## What each file holds

One heading per file of `gemini/physics/` and per moved `_physics.py` part, one line per public function with its arguments and
what it computes. Public default constants (`DEFAULT_*` and similar) are not listed. Every
function carries `@ops.physics` except those named under "Functions without `@ops.physics`".

### `constants.py`

Physical constants retained from the original GEMINI correlations. It holds constants and no
functions.

### Units (`gemini/units/conversions.py`)

These are the functions of `gm.units`, not of `gm.physics`: unit conversions at package and
correlation boundaries; historical factors retained.

- `si_unit(unit)`: SI unit that `unit` converts to, or `None` for an unknown unit.
- `si_conversion(unit, quantity)`: `(scale, offset)` with `to_si(value) == float(value) * scale +
  offset`.
- `to_si(value, unit, quantity)`: convert a bound scalar to SI; volume flow remains [m3/s] until
  density is known.
- `array_to_si(values, unit, quantity)`: convert an array-like of `unit` values to SI, element for
  element as `to_si` does.
- `value_in_si(value, expected_unit, path, quantity)`: convert a `Quantity` or its dict to a
  declaration's SI unit; text for a field with a unit raises `invalid_value`, a unit of another
  dimension `invalid_unit`, and a plain number passes as SI.
- `Unit`: the `str` enum of the unit table, one member per unit (`Unit.M3_PER_H == "m3/h"`).
- `Quantity(value, unit)`: a number or array with its `Unit`; `.si`, `.to(unit, quantity=None)`,
  `to_dict()`, `from_dict(d)`; equality compares SI values.
- `convert(value, from_unit, to_unit, quantity)`: convert a scalar between units of the same
  dimension through SI.
- `define_quantity(name, unit)`: record that the quantity `name` is stored in the SI unit `unit`.
- `names(quantity)`: sorted unit names, or those of one quantity such as `"pressure"`.
- `fits(unit, quantity)`: whether `unit` is a known unit of the named `quantity` (`"pressure"`,
  `"power"`).
- `bar_to_pa(x)`: convert [bar] to [Pa]: `x * 1e5`.
- `pa_to_bar(x)`: convert [Pa] to [bar]: `x / 1e5`.
- `c_to_k(x)`: convert [degC] to [K]: `x + 273.15`.
- `k_to_c(x)`: convert [K] to [degC]: `x - 273.15`.
- `m3h_to_m3s(x)`: convert [m3/h] to [m3/s]: `x / 3600`.
- `m3s_to_m3h(x)`: convert [m3/s] to [m3/h]: `x * 3600`.
- `md_to_m2(x)`: convert [mD] to [m2]: `x * 9.869233e-16`.
- `m2_to_md(x)`: convert [m2] to [mD]: `x / 9.869233e-16`.
- `m3s_to_bbl_per_day(x)`: convert [m3/s] to [bbl/day]: `x * 543439.650564`.
- `bbl_per_day_to_m3s(x)`: convert [bbl/day] to [m3/s]: `x / 543439.650564`.
- `ft_head_to_pa(x)`: convert [ft head] to [Pa]: `x * 2988.30167`.
- `pa_to_ft_head(x)`: convert [Pa] to [ft head]: `x / 2988.30167`.
- `bhp_to_w(x)`: convert [bhp] to [W]: `x * 745.7`.
- `w_to_bhp(x)`: convert [W] to [bhp]: `x / 745.7`.
- `m_to_ft(x)`: convert [m] to [ft]: `x / 0.3048`.
- `ft_to_m(x)`: convert [ft] to [m]: `x * 0.3048`.
- `kgm3_to_lbmft3(x)`: convert [kg/m3] to [lbm/ft3]: `x / 16.01846`.
- `lbmft3_to_kgm3(x)`: convert [lbm/ft3] to [kg/m3]: `x * 16.01846`.
- `pas_to_cp(x)`: convert [Pa s] to [cP]: `x / 1e-3`.
- `cp_to_pas(x)`: convert [cP] to [Pa s]: `x * 1e-3`.
- `inch_to_m(x)`: convert [inch] to [m]: `x * 0.0254`.
- `m_to_inch(x)`: convert [m] to [inch]: `x / 0.0254`.
- `m_to_mm(x)`: convert [m] to [mm]: `x * 1000`.
- `mm_to_m(x)`: convert [mm] to [m]: `x / 1000`.
- `m3s_to_m3day(x)`: convert [m3/s] to [m3/day]: `x * 86400`.
- `m3day_to_m3s(x)`: convert [m3/day] to [m3/s]: `x / 86400`.
- `index_to_si(x)`: convert [m3/h/bar] to [m3/s/Pa]: `x / 3600 / 1e5`.
- `index_from_si(x)`: convert [m3/s/Pa] to [m3/h/bar]: `x * 3600 * 1e5`.
- `c_to_f(x)`: convert [degC] to [degF]: `x * 1.8 + 32`.
- `bar_to_psi(x)`: convert [bar] to [psi]: `x * 14.503774`.
- `pa_to_gpa(x)`: convert [Pa] to [GPa]: `x / 1e9`.
- `gpa_to_pa(x)`: convert [GPa] to [Pa]: `x * 1e9`.
- `rad_to_deg(x)`: convert [rad] to [deg]: `x * 180 / pi`.
- `deg_to_rad(x)`: convert [deg] to [rad]: `x * pi / 180`.
- `m2_to_mm2(x)`: convert [m2] to [mm2]: `x * 1e6`.
- `ms_to_mm_year(x)`: convert penetration speed [m/s] to [mm/year]: `x * 1000 * 31557600`.
- `mol_l_bar_to_mol_m3_pa(x)`: convert Henry solubility constant [mol/l/bar] to [mol/m3/Pa]:
  `x * 0.01`.
- `kgh_to_kgs(x)`: alias of `m3h_to_m3s`; converts [kg/h] to [kg/s]: `x / 3600`.
- `nm_to_dyne_cm(x)`: alias of `pas_to_cp`; converts [N/m] to [dyne/cm]: `x / 1e-3`.
- `dyne_cm_to_nm(x)`: alias of `cp_to_pas`; converts [dyne/cm] to [N/m]: `x * 1e-3`.

### `fluid.py`

Constant fluid properties inherited from GEMINI's PVTConstantSTP model.

- `mixture_density(liquid_density, gas_density, gas_mass_fraction)`: homogeneous mixture density
  [kg/m3] of a gas mass fraction [-].
- `volume_flow(mass_flow, density)`: volume flow [m3/s] of a mass flow at a density, `q = m / rho`.
- `liquid_volume_flow(mass_flow, gas_mass_fraction, liquid_density)`: liquid volume flow [m3/s] of a
  mixture, `q_l = m (1 - x) / rho_l`.
- `heat_capacity_rate(mass_flow, heat_capacity)`: heat capacity rate [W/K] of a stream, `C = m cp`.

### `gas.py`

A gas from its composition, a mapping of species to mole fraction (`SPECIES`: `CH4`, `C2H6`, `C3H8`,
`CO2`, `N2`, with molar mass, lower heating value and burning carbon atoms).

- `molar_mass(composition)` [kg/mol]; `mass_fraction(composition, species)` [-].
- `ideal_gas_density(pressure, temperature, mass_per_mole)` [kg/m3], `normal_density(composition)` at
  `NORMAL_TEMPERATURE` and `NORMAL_PRESSURE`.
- `lower_heating_value(composition)` [J/kg]; `combustion_co2(composition)`: kg of CO2 formed per kg of
  gas, without the CO2 the gas carries.
- `gas_mass_fraction(ratio, density_normal, liquid_density)` and its inverse `gas_liquid_ratio`.
- `GRID_COMPOSITION`: a published grid analysis, the default of `GasGrid` and `GasMakeup`.

### `geometry.py`

Pure in-memory pipe geometry calculations.

- `circle_area(diameter)`: area [m2] of a circle, `A = pi * d**2 / 4`.
- `lateral_area(diameter, length)`: lateral area [m2] of a cylinder, `A = pi d L`.
- `mean_velocity(mass_flow, density, diameter)`: mean velocity [m/s] of a flow through a circular
  section, `m / rho / A`.
- `build_path(trajectory_table, tally_table)`: build a path from SI trajectory and optional SI tally
  intervals.

### `hydraulics.py`

Pipe hydraulics: Darcy–Weisbach with Swamee–Jain, Beggs–Brill, path marching, radial inflow.

- `reynolds_number(velocity, density, diameter, viscosity)`: Reynolds number [-] of a flow in a
  pipe, `Re = u rho D / mu`.
- `darcy_weisbach_dp(velocity, rho, inclination, mu, diameter, roughness, length)`: signed friction
  and gravity pressure drops [Pa] of one pipe interval.
- `pipe_friction_drop(velocity, rho, mu, diameter, roughness, length)`: friction pressure drop [Pa]
  of a liquid in a straight pipe, any regime.
- `pipe_conductance(heat_transfer_coefficient, diameter, length)`: conductance `UA` [W/K] of a pipe
  wall, `U pi D L`.
- `valve_flow_coefficient(rated, opening, rangeability, equal_percentage)`: effective flow
  coefficient of a control valve at an opening.
- `affine_correction(pressure, slope, offset)`: a pressure with the affine calibration correction,
  `a p + b`.
- `productivity_pressure(reservoir_pressure, flow, productivity)`: bottomhole pressure [Pa] of a
  producer on a linear IPR, `p - q / PI`.
- `injectivity_pressure(reservoir_pressure, flow, injectivity)`: bottomhole pressure [Pa] of an
  injector on a linear law, `p + q / II`.
- `productivity_index(flow, reservoir_pressure, bottomhole_pressure)`: productivity index [m3/s/Pa]
  of one measurement, `q / (p_res - p_bh)`.
- `injectivity_index(flow, reservoir_pressure, bottomhole_pressure)`: injectivity index [m3/s/Pa] of
  one measurement, `q / (p_bh - p_res)`.
- `beggs_brill_dp(us_g, us_l, rho_g, rho_l, inclination, mu_g, mu_l, sigma, diameter, roughness,
  length)`: two-phase friction and gravity pressure drops [Pa] of one pipe interval.
- `quadratic_pressure_drop(reference_drop, flow, reference_flow)`: pressure drop [Pa] of a fixed
  resistance: `dp_ref * (q / q_ref)^2`.
- `valve_pressure_drop(mass_flow, density, flow_coefficient)`: liquid pressure drop [Pa] of a valve:
  `dp = (rho / rho_0) (q / Kv)^2`.
- `hydrostatic_dp(rho, height, inclination_sine)`: hydrostatic pressure difference [Pa] of a fluid
  column, `dp = rho g h s`.
- `pipe_path_profile(path, stream, fluid, direction, heat_transfer_coefficient, ambient_temperature,
  correlation, correlation_2p)`: march the pressure and temperature of a stream along a pipe path.
- `radial_pressure_drops(volume_flow, viscosity, permeability, thickness, drainage_radius,
  wellbore_radius, skin)`: radial Darcy and skin pressure drops [Pa] of an inflow to a well (Akin
  2019).
- `corrosion_profile(path, stream, fluid, direction, heat_transfer_coefficient, ambient_temperature,
  chemistry, model)`: CO2 corrosion rate [mm/year] of each section along the hydraulic profile.
- `erosion_check(path, stream, fluid)`: compare section velocities with the API erosional velocity
  limit.

The doublet design adds `radial_index` (the inverse of `radial_pressure_drops`),
`hydrostatic_pressure`, `pump_setting_depth` and `design_pump_head` to `hydraulics.py`,
`geotherm_temperature`, `SURFACE_TEMPERATURE`, `GEOTHERMAL_GRADIENT` and `DOUBLET_WELL_SPACING` to `ground.py`, `vertical_path` to `geometry.py` and
`constant_head_curves` to `pumps.py`.

### `heat_transfer.py`

Pipe heat loss and standard heat-exchanger effectiveness relations.

- `pipe_temperature_change(inlet_temperature, heat_transfer_coefficient, area, liquid_mass_flow,
  gas_mass_flow, liquid_heat_capacity, gas_heat_capacity, ambient_temperature)`: legacy explicit
  heat-loss increment [K] using SI inputs.
- `lmtd(dt1, dt2)`: logarithmic mean temperature difference; reject a temperature cross.
- `ntu(ua, c_min)`: number of transfer units.
- `effectiveness_counterflow(transfer_units, c_ratio)`: counterflow heat-exchanger effectiveness.
- `effectiveness_parallel(transfer_units, c_ratio)`: parallel-flow heat-exchanger effectiveness.
- `logarithmic_mean(first, second)`: logarithmic mean of two positive values, without guards.
- `signed_parts(value)`: positive part and the negative part of a signed value.
- `heat_rate(capacity_rate, temperature_difference)`: sensible heat rate of a stream.
- `setpoint_duty(capacity_rate, temperature_gap)`: heat needed to close a temperature gap; zero when
  there is no gap.
- `temperature_change(duty, capacity_rate)`: temperature change of a stream that receives a duty;
  zero when stopped.
- `effectiveness_outlet_temperature(inlet_temperature, effectiveness, reference_temperature)`:
  outlet temperature of a stream from the effectiveness definition.
- `ambient_effectiveness(conductance, capacity_rate)`: effectiveness of a stream exchanging heat
  with a constant temperature.
- `relaxation_factor(conductance, duration, heat_capacity)`: decay factor of a lumped body relaxing
  towards its surroundings.
- `exponential_relaxation(start, equilibrium, factor)`: value after an exponential approach to an
  equilibrium.
- `mixed_temperature(first_rate, first_temperature, second_rate, second_temperature)`: adiabatic
  mixing temperature of two streams of the same fluid.
- `sensible_latent_loads(available, sensible_demand, latent_demand, is_dry)`: sensible and latent
  loads a cooling circuit takes up, sensible served first.
- `fan_power(duty, specific_fan_power)`: fan electricity of a cooler that is proportional to its
  duty.
- `mean_temperature(first, second)`: arithmetic mean of two temperatures.
- `exchanger_balance(hot_inlet, cold_inlet, hot_rate, cold_rate, conductance, counterflow)`:
  effectiveness-NTU balance of a two-stream heat exchanger.
- `terminal_differences(hot_in, hot_out, cold_in, cold_out, counterflow)`: two terminal temperature
  differences of a two-stream exchanger.
- `apparent_conductance(arrangement, hot_in_T, hot_out_T, cold_in_T, cold_out_T, m_dot_hot,
  m_dot_cold, cp_hot, cp_cold)`: `(UA, code, hot duty, cold duty, LMTD)` from measured temperatures
  and flows.

### `ground.py`

Ground and aquifer heat transport: doublet breakthrough, conduction shapes, Ramey profiles.

- `aquifer_volumetric_heat_capacity(porosity, fluid_heat_capacity, rock_heat_capacity)`: bulk
  volumetric heat capacity [J/m3/K] of a saturated aquifer.
- `doublet_breakthrough_volume(well_spacing, thickness, aquifer_heat_capacity,
  fluid_heat_capacity)`: injected volume [m3] at which the cold front reaches the producer.
- `doublet_cold_fraction(volume_ratio)`: share [-] of the produced flow that arrives at the
  injection temperature.
- `cylinder_store_conductance(conductivity, diffusivity, volume, height, period)`: period-mean
  conduction conductance [W/K] of a cylindrical heat store.
- `vertical_cylinder_conductance(conductivity, length, diameter)`: steady conductance [W/K] of a
  vertical cylinder below an isothermal surface.
- `steady_flux_resistance(conductivity, borehole_radius, cell_radius)`: ground resistance [m K/W]
  between a borehole wall and its cell's mean.
- `ramey_time_function(time, diffusivity, radius)`: Ramey's dimensionless transient conduction
  function f(t) [-].
- `ramey_fluid_temperature(inlet_temperature, top_temperature, gradient, length,
  relaxation_length)`: temperature [K] of a fluid after flowing `length` down a geothermal gradient.
- `injected_volume(volume_flow, duration)`: liquid volume that flows through a well during a step.
- `doublet_temperature_drop(injected, breakthrough, reservoir_temperature, injection_temperature)`:
  drop of the produced temperature of a doublet after thermal breakthrough.
- `doublet_breakthrough_time(breakthrough, volume_flow)`: time for a doublet's thermal front to
  reach the producer; `None` at no flow.
- `store_conductance(volume, conductivity, porosity, water_volumetric_heat_capacity,
  rock_heat_capacity, height, period)`: conduction conductance [W/K] of an aquifer store of injected
  water volume.
- `mix_store(volume, change, added_volume, added_change)`: a fully mixed store after water is
  injected into it.
- `store_relaxation(change, volume, conductance, duration, water_volumetric_heat_capacity)`: a
  store's temperature change after conduction towards the aquifer temperature.
- `stored_heat(water_volumetric_heat_capacity, volume, change)`: excess heat of a water volume at a
  temperature change.
- `aquifer_stored_energy(water_volumetric_heat_capacity, warm_volume, warm_change, cold_volume,
  cold_change)`: net excess heat of the warm and the cold store of a well pair.
- `thermal_recovery(recovered_heat, charged_heat)`: thermal recovery efficiency of a store; `None`
  until heat has been charged.
- `borehole_loop_conductance(capacity_rate, count, depth, radius, spacing, conductivity,
  borehole_resistance)`: inlet-to-ground conductance of the loops of a borehole field.
- `borehole_field_surroundings_conductance(count, spacing, depth, conductivity)`: conductance [W/K]
  between a borehole field volume and the undisturbed ground.
- `borehole_field_capacity(volumetric_heat_capacity, count, spacing, depth)`: heat capacity [J/K] of
  the lumped ground volume of a borehole field.
- `borehole_field_temperature_change(change, exchange, surroundings, inlet_temperature,
  undisturbed_temperature, duration, capacity)`: ground temperature change of a borehole field after
  one step.
- `ramey_rock_resistance(time, diffusivity, borehole_radius, conductivity)`: transient rock
  resistance [m K/W] of a well at an operating time.
- `ramey_relaxation_length(capacity_rate, borehole_resistance, rock_resistance)`: Ramey's relaxation
  length of the circuit fluid.

### `doublet.py`

- `design(values, density, viscosity, skins, pressure=None)`: the child values of a doublet that
  its design values give, by dotted name; a group of values that is not complete derives nothing.

### `pumps.py`

Pump relations: the TNO R11363 power polynomial, affinity-law curves, efficiencies. `head`,
`esp_efficiency`, `pump_efficiency` and `line_shaft_friction_power` live in
`modules/pumps/_physics.py`; `power` and `constant_head_curves` stay here because the doublet design
reads them too.

- `head(volume_flow, frequency, stages, coefficients)`: pressure rise [Pa] from flow [m3/s],
  frequency [Hz], stages and ft coefficients.
- `power(volume_flow, frequency, stages, coefficients)`: power [W] from flow [m3/s], frequency [Hz],
  stages and bhp coefficients.
- `speed_ratio(frequency, rated_frequency)`: speed ratio of a variable-speed pump.
- `centrifugal_head(flow, speed, coefficients)`: pressure rise of a centrifugal pump from its
  quadratic curve and the speed.
- `best_efficiency_ratio(flow, speed, best_efficiency_flow)`: flow relative to the speed-scaled
  best-efficiency flow.
- `parabolic_efficiency(best_efficiency, load)`: hydraulic efficiency of the parabola through the
  origin.
- `hydraulic_power(flow, head)`: power given to the liquid by a pump.
- `pump_efficiency(flow, head, power)`: SI efficiency of a pump from a measured or modelled power;
  zero when stopped.
- `esp_efficiency(flow, head, power)`: retained US-basis ESP efficiency; zero for a stopped pump.
- `is_in_operating_window(flow, minimum_flow, maximum_flow, speed)`: whether a flow lies inside the
  speed-scaled operating window of a pump.
- `line_shaft_friction_power(friction_loss, depth, speed)`: mechanical friction power of a line
  shaft.

### `modules/pumps/_physics.py`: compression

Ideal-gas adiabatic compression with an isentropic efficiency and intercooled stages.

- `isentropic_outlet_temperature(inlet_temperature, pressure_ratio, heat_capacity_ratio)`: ideal-gas
  isentropic outlet temperature [K] of one compression stage.
- `stage_outlet_temperature(inlet_temperature, pressure_ratio, heat_capacity_ratio,
  isentropic_efficiency)`: adiabatic outlet temperature [K] of one stage with an isentropic
  efficiency.
- `stage_pressure_ratio(pressure_ratio, stages)`: pressure ratio of each of several equal stages.
- `overall_pressure_ratio(discharge_pressure, suction_pressure)`: overall pressure ratio of a
  compressor.
- `specific_compression_work(inlet_temperature, pressure_ratio, heat_capacity_ratio, specific_heat,
  isentropic_efficiency, stages)`: shaft work per kg of gas [J/kg] of an intercooled multistage
  compressor.
- `shaft_power(mass_flow, specific_work)`: shaft power of a compressor.
- `heat_rejected(electricity, shaft_power, stages)`: heat an intercooled electric compressor rejects
  to its surroundings.

### `refrigeration.py`

Heat pump and chiller relations: Carnot and Lorenz COPs, part load. The sorption functions listed
here (`characteristic_*`, `sorption_*`) live in `modules/cooling/_physics.py`.

- `carnot_cop_heating(sink_temperature, source_temperature, minimum_lift)`: Carnot heating COP of a
  heat pump.
- `carnot_cop_cooling(sink_temperature, source_temperature, minimum_lift)`: Carnot cooling COP
  (energy efficiency ratio) of a chiller.
- `log_mean_temperature(inlet_temperature, outlet_temperature)`: logarithmic mean (thermodynamic
  mean) temperature of a sensible glide.
- `lorenz_cop_heating(sink_inlet, sink_outlet, source_inlet, source_outlet, minimum_lift)`: Lorenz
  (gliding-temperature) heating COP of a heat pump.
- `characteristic_temperature_difference(generator_temperature, rejection_temperature,
  evaporator_temperature, rejection_coefficient, evaporator_coefficient)`: characteristic
  temperature difference of a sorption machine.
- `characteristic_evaporator_duty(driving_difference, minimum_driving_difference, slope,
  sensitivity)`: evaporator duty [W] of a sorption machine from its characteristic equation.
- `characteristic_sensitivity(generator_rate, rejection_rate, evaporator_rate, generator_ratio,
  rejection_ratio, rejection_coefficient, evaporator_coefficient)`: how much the mean-temperature
  ddt falls per watt of evaporator duty [K/W].
- `sorption_evaporator_capacity(generator_temperature, rejection_temperature,
  evaporator_temperature, generator_rate, rejection_rate, evaporator_rate, slope,
  minimum_driving_difference, rejection_coefficient, evaporator_coefficient, thermal_cop,
  auxiliary_power_ratio)`: largest evaporator duty [W] a sorption chiller delivers at these inlets.
- `sorption_rejection_ratio(thermal_cop, auxiliary_power_ratio)`: heat-rejection duty of a sorption
  machine per unit evaporator duty.
- `sorption_delivered_duty(requested, available, capacity, useful_ratio)`: evaporator duty a
  sorption machine delivers and whether it falls short.
- `coefficient_of_performance(useful_duty, input_duty)`: coefficient of performance of a machine.
- `sorption_duties(evaporator_duty, thermal_cop, auxiliary_power_ratio)`: generator duty, auxiliary
  electricity and rejected heat of a sorption machine.
- `part_load_duty(requested, capacity, minimum_part_load)`: duty [W] a capacity-limited machine with
  a minimum part load delivers.
- `carnot_fraction_cop_heating(efficiency, minimum_lift, sink_inlet, sink_outlet, source_inlet,
  source_outlet)`: heating COP as a fraction of the Carnot COP at the outlet temperatures.
- `carnot_fraction_cop_cooling(efficiency, minimum_lift, sink_inlet, sink_outlet, source_inlet,
  source_outlet)`: cooling COP as a fraction of the Carnot COP at the outlet temperatures.
- `lorenz_fraction_cop_heating(efficiency, minimum_lift, sink_inlet, sink_outlet, source_inlet,
  source_outlet)`: heating COP as a fraction of the Lorenz COP at the circuit glides.
- `heating_evaporator_duty(condenser_duty, cop)`: evaporator duty of a heat pump from its condenser
  duty and heating COP.
- `cooling_condenser_duty(evaporator_duty, cop)`: condenser duty of a chiller from its evaporator
  duty and cooling COP.
- `carnot_heating_source_outlet(source_inlet, temperature_change, sink_outlet, efficiency,
  minimum_lift)`: source outlet temperature that closes the balance of a Carnot-fraction pump.
- `heating_cop_minimum_source(sink_outlet, efficiency)`: source temperature below which a
  Carnot-fraction heating COP is at most 1.
- `carnot_cooling_sink_outlet(sink_inlet, temperature_change, source_outlet, efficiency,
  minimum_lift)`: sink outlet temperature that closes the balance of a Carnot-fraction chiller.
- `cooling_minimum_sink_rate(duty, efficiency, source_outlet)`: sink capacity rate [W/K] a
  Carnot-fraction chiller needs to reject its duty.
- `lorenz_source_surplus(source_outlet, source_rate, source_inlet, sink_inlet, sink_outlet, duty,
  efficiency, minimum_lift)`: evaporator balance surplus [W] of a Lorenz-fraction pump at a source
  outlet.
- `source_limit_shortfall(cop_function, useful_duty, sink_inlet, sink_rate, source_inlet,
  source_limit, available, efficiency, minimum_lift)`: evaporator demand minus the available source
  heat [W] at a heating duty.

### `modules/power/_physics.py`: steam

Saturated water and steam properties from IAPWS-IF97 and wet steam expansion.

- `saturation_pressure(temperature)`: saturation pressure [Pa] of water at a temperature [K].
- `saturation_temperature(pressure)`: saturation temperature [K] of water at a pressure [Pa].
- `liquid_enthalpy(pressure, temperature)`: specific enthalpy [J/kg] of liquid water in IF97 region
  1.
- `liquid_entropy(pressure, temperature)`: specific entropy [J/kg/K] of liquid water in IF97 region
  1.
- `vapour_enthalpy(pressure, temperature)`: specific enthalpy [J/kg] of steam in IF97 region 2.
- `vapour_entropy(pressure, temperature)`: specific entropy [J/kg/K] of steam in IF97 region 2.
- `b23_pressure(temperature)`: region 2/3 boundary pressure [Pa] (IF97 eq. 5, 623.15 K to 863.15 K).
- `saturation_properties(pressure)`: saturated liquid and vapour enthalpy and entropy at a pressure
  [Pa].
- `flash_fraction(enthalpy, pressure)`: steam mass fraction [-] after isenthalpic flashing to a
  pressure [Pa].
- `flash_state(mass_flow, inlet_temperature, inlet_pressure, flash_pressure)`: single-flash split of
  a liquid into saturated steam and brine.
- `turbine_balance(mass_flow, inlet_enthalpy, outlet_enthalpy, condensate_enthalpy,
  generator_efficiency)`: enthalpy balance of a condensing turbine, generator and condenser.
- `baumann_expansion(inlet_pressure, outlet_pressure, dry_efficiency, baumann_factor)`: expansion of
  dry saturated steam into the wet region with the Baumann rule.

### `psychrometrics.py`

Moist-air psychrometrics: saturation pressure, dew point, humidity ratio and wet bulb.

- `saturation_pressure(temperature)`: saturation pressure of water vapour [Pa] over ice or liquid
  water.
- `dew_point(temperature, relative_humidity)`: dew-point temperature [K] of moist air.
- `evaporation_rate(duty, latent_heat)`: water evaporated when a duty is rejected as latent heat.
- `humidity_ratio(temperature, relative_humidity, pressure)`: humidity ratio [kg water vapour per kg
  dry air] of moist air.
- `wet_bulb_temperature(temperature, relative_humidity)`: psychrometric wet-bulb temperature [K] at
  standard sea-level pressure.

### `chemistry.py`

Henry-law CO2 partition model retained from GEMINI water-analysis workflows.

- `henry_constant(temperature)`: temperature-dependent Henry solubility constant.
- `co2_solubility_liquid(co2_fraction, temperature, pressure)`: evaluate dissolved CO2 using Henry's
  law.
- `co2_solubility_gas(co2_fraction, gas_water_ratio, gas_density, gas_molecular_weight)`: evaluate
  CO2 contained in the gas per unit water volume.
- `co2_partial_pressure(co2_fraction, gas_pressure, gas_water_ratio, gas_density,
  gas_molecular_weight, temperature_sample, temperature_system)`: CO2 partial pressure [Pa] from SI
  sample and system conditions.

### `corrosion.py`

CO2 corrosion correlations (NORSOK M-506, de Waard–Lotz 1991/1995) and wall-loss helpers.

- `co2_corrosion_rate(model, fitted, temperature, pressure, water_flow_rate, water_density,
  water_viscosity, diameter, roughness, co2_fraction, co2_partial_pressure, bicarb_concentration,
  ionic_strength, coefficients)`: CO2 wall penetration rate [mm/year] of the NORSOK, DLM or DLD
  correlation.
- `wall_loss(rates_mm_per_year, durations_s)`: cumulative radial wall loss [mm] of
  piecewise-constant corrosion rates.
- `remaining_wall_thickness(outer_radius, inner_radius, loss)`: remaining wall thickness [m], `t =
  r_o - (r_i + loss)`.
- `time_to_minimum_wall(thickness, minimum, rate)`: time [s] to a minimum wall thickness, `t = (w -
  w_min) / rate`.

### `erosion.py`

Erosion correlations: DNV RP O501, OKA, E/CRC Tulsa and API RP 14E.

- `erosion_rate(model, flow_rate, rho_fluid, diameter, alpha, material, hardness, particle_material,
  particle_diameter, rho_pipe, shape_factor)`: erosion rate [mm/year] of the DNV, OKA or E/CRC Tulsa
  correlation.
- `api_erosional_velocity(rho_fluid)`: API erosional velocity limit [m/s], `u_e = C / sqrt(rho)`.
- `api_velocity_comparison(actual, limit)`: compare actual and limiting flow velocities.

### `separation.py`

Flow splitting, shared by piping and treatment, and `FILTER_CLOGGING_BAR`, which the legacy bridge
reads. `degasser_split`, `cyclone_sand`, `dosing_flows` and the other filter and degasser defaults
live in `modules/treatment/_physics.py`.

- `split_flow(mass_flow, fraction)`: remainder and the branch of a mass flow split, `(m - f m, f
  m)`.
- `degasser_split(mass_flow, gas_mass_fraction, efficiency)`: liquid flow, the separated gas flow
  and the gas fraction left in the liquid.
- `cyclone_sand(efficiency, sand_concentration, liquid_flow)`: sand removal rate and the residual
  sand concentration of a cyclone.
- `dosing_flows(dose, mass_flow, product_concentration)`: product and the active mass flow of a
  chemical dosing.

### `combustion.py`

Fuel-fired heat and power: fuel input of a boiler or engine, flare emissions.

- `willans_fuel_input(load, electric_capacity, electric_efficiency, no_load_fraction)`: fuel power
  of an engine on its Willans line; zero when the engine is off.
- `engine_energy_flows(fuel, load, electric_capacity, thermal_efficiency)`: recoverable engine heat
  and the electric output of a combined heat and power unit.
- `flare_emissions(gas_flow, co2_fraction, methane_fraction, combustion_efficiency, heating_value)`:
  CO2 and methane emissions and the fuel power of a flared gas.
- `released_heat(gas_flow, heating_value, combustion_efficiency)`: heat a flare releases.

### `modules/storage/_physics.py`

Thermal storage: mixed water tanks, coil conductance and the phase segments of an ice store.

- `circuit_conductance(effectiveness, capacity_rate)`: conductance of a circuit exchanging heat with
  a store at uniform temperature.
- `tank_capacity(volumetric_heat_capacity, volume)`: heat capacity of a tank of liquid.
- `tank_service_report(hot, capacity, temperature, reference_temperature, charge_heat,
  discharge_heat)`: stored energy and the two circuit duties of a tank, signed by its service.
- `tank_relaxation(temperature, capacity, duration, charge_conductance, charge_temperature,
  discharge_conductance, discharge_temperature, loss_conductance, ambient_temperature)`: temperature
  of a fully mixed tank after a step with constant inlets.
- `ice_stored_cold(water_mass, latent_heat, fraction)`: latent cold stored in an ice store.
- `ice_advance(fraction, temperature, duration, inlet_temperature, conductance, water_mass,
  latent_heat, freezing_temperature, water_specific_heat, ice_specific_heat)`: frozen fraction and
  the temperature of an ice store after a step.
- `ice_step(fraction, temperature, duration, inlet_temperature, conductance, water_mass,
  latent_heat, freezing_temperature, water_specific_heat, ice_specific_heat)`: advances an ice store
  through one phase segment.

### `modules/control/_physics.py`

Discrete PID control: the error, the ideal-form command and the clamped integral.

- `pid_error(setpoint, measurement, reverse)`: control error in the sense of the controller
  direction.
- `pid_derivative(gain, derivative_time, error_change, previous_step)`: derivative term of the ideal
  PID form.
- `pid_command(gain, error, integral, derivative)`: unclamped command of the ideal PID form.
- `pid_integral_increment(gain, duration, integral_time, error)`: increase of the integral term over
  one step.
- `anti_windup_increment(increment, unclamped, minimum_output, maximum_output)`: integral increment,
  zero while the output is clamped and driven further out.

### `modules/power/_physics.py`: power cycles

Binary organic Rankine cycle plant relations: Lorenz efficiency, capacity cap, energy balance.

- `lorenz_efficiency(hot_temperature, cold_temperature, condensing_temperature)`: reversible
  efficiency of a sensible heat glide rejected at a temperature.
- `cycle_design(brine_temperature, brine_mass_flow, brine_heat_capacity, ambient_temperature,
  condenser_approach, pinch, minimum_outlet_temperature, carnot_fraction, capacity)`: design point
  of an air-cooled binary cycle fed by brine.
- `plant_balance(heat_input, cycle_efficiency, parasitic_fraction)`: energy balance of a binary
  plant from its heat input.

### `electricity.py`

Electricity exchange of a plant with a grid connection of limited capacity.

- `net_exchange(consumption, generation, import_limit, export_limit, import_price, export_price)`:
  import and export of a plant through a limited grid connection.

### `dispatch.py`

The energy balance of `gm.schedule` at each step, on arrays over the steps: `doublet_flow(heat_need,
heat_per_flow, minimum_flow, maximum_flow)`, `loaded_by_cost(demand, capacities, costs)`, what each
source takes when the cheapest loads first, `marginal_cost(price, efficiency, co2_price,
emission_factor)`, `methane_emission_factor()`, `heat_pump_cop(heating, carnot_fraction, minimum_lift,
sink_outlet, source_outlet)`, `temperature_after(start, end, share)`, `circuit_flow(heat,
specific_heat, temperature_difference)` and `flow_share(first, second)`.

### `energy.py`

Energy conversion through an efficiency, shared by pumps, compressors, motors and burners.

- `input_power(useful_power, efficiency)`: power a converter draws for a useful power, `P_in = P_out
  / eta`.

### `diagnostics.py`

Health-scoring relations shared by the modules: drift, bounded score, margin, limit test.

- `relative_drift(measured, predicted)`: relative deviation of a measurement from its prediction.
- `bounded_score(ratio)`: a ratio clipped to [0, 1], a health score.
- `remaining_margin(ratio)`: margin left before a ratio reaches one.
- `below_limit(ratio, threshold)`: whether a ratio fell by more than the threshold.
- `performance_ratio(measured, reference)`: a measured performance over its reference value,
  `measured / reference` [-].

## Rules

- Use plain typed functions and SI inputs/outputs; small structured return models are allowed.
- Every function runs on floats, arrays and traced values. Public functions carry `@ops.physics`
  (exceptions: see "Functions without `@ops.physics`"):
  it gives scalars NumPy types, so plain `/` and `**` are silent in an eager call as they are on
  arrays and in a graph. A value-dependent `if` is `ops.where`, a `raise` is `ops.check` with the
  same class and message, and `math.*` is an op (see [native-engine.md](native-engine.md)). A check
  guards all results of its function and `where` drops the error of the unselected branch, so a
  function has one version: `where(stopped, 0.0, ntu(rate))` works. An out-of-domain number in a
  correlation with no check gives NaN. A failed tuple cannot be unpacked, so a physics function
  returning a tuple is read by index when its check can fail. Where a module reports its own error
  class the function takes `error` and `context` (`ramey_time_function`, `steady_flux_resistance`,
  `vertical_cylinder_conductance`). A direct call on arrays raises a failing check at once, for the
  first failing row; rows crossing a `where` around a check need a graph (`run_function`).
- State dimensions, reference formulas and assumptions in docstrings.
- Keep correlation-specific US or laboratory bases explicit at the formula boundary.
- `gemini.units._UNITS` is the single table of public data units (SI unit, scale, offset). A declared
  difference quantity converts by scale only, so `{"value": 5, "unit": "degC"}` as a temperature difference is 5 K.
- Do not perform database I/O, logging or mutate global state during calculations.
- `Fluid` definitions in `gemini.types.fluid` own immutable overrides and cache their
  `FluidProperties` snapshot; physics must not import types at runtime (`hydraulics` imports
  `Stream` and `Fluid` for type checking only).
- Do not hide undefined diagnostics as valid numbers. The receiving aquifer's unconfigured
  drainage radius leaves radial estimates unavailable while its pressure-flow model works.
- Inputs outside a correlation's domain raise `gm.errors.PhysicsError` instead of dividing
  by zero or returning NaN: zero flow or CO2 pressure where a correlation divides by them or
  takes their logarithm, a negative flow that gives a complex corrosion or erosion rate, NORSOK
  underflow near 360 °C, and a zero liquid superficial velocity in Beggs–Brill. Unsupported
  model names raise `ValidationError` and missing chemistry raises
  `PhysicsError`.
- The Beggs–Brill flow-regime map follows Beggs and Brill as revised by Brill and Beggs, with
  boundaries at no-slip holdup λ = 0.01 and λ = 0.4. A no-slip holdup of exactly 0.4 takes the
  upper range (intermittent for L3 < Fr <= L4, distributed for Fr > L4); it formerly matched no
  regime and divided by zero. Two-phase reverse flow uses the mirrored friction of forward flow.
- Preserve original numerical cases in `tests/fixtures/golden_values.json`, checked by
  `tests/unit/test_golden.py` and the physics unit tests. Intentional changes require a
  `NOTE(refactor):` sentence in the docstring and measured or physical evidence; see
  [refactor-notes.md](refactor-notes.md).

## Fluid properties

`fluid.py` holds the constant-property snapshot `FluidProperties` and `types/fluid.py` the
immutable `Fluid` that selects it (the inherited GEMINI `PVTConstantSTP` model, property model
`constant_stp`). Pressure and temperature do not change any property: `Fluid.properties(p, T)`
returns one cached snapshot per complete `Fluid` value.

- Defaults (water near standard conditions): `rho_l` = 1000 kg/m3, `rho_g` = 1.976 kg/m3,
  `gmf` = 0, `mu_l` = 0.001 Pa s, `mu_g` = 21.29e-6 Pa s, `cp_l` = 4217.4 J/kg/K, `cp_g` =
  819 J/kg/K, `k_l` = 1.6 W/m/K, `k_g` = 0.0147 W/m/K, `sigma` = 0.0728 N/m.
- `density` = `1 / (gmf / rho_g + (1 - gmf) / rho_l)` [kg/m3], the homogeneous mixture density
  from the gas mass fraction `gmf`; `fluid.mixture_density(liquid_density, gas_density,
  gas_mass_fraction)` is the same formula for floats, arrays and traced values.
- `kind` is `brine` (default), `water`, `glycol_water`, `steam` or `gas`. `glycol_water` replaces the
  liquid values by DOWFROST HD, 30 % propylene glycol by volume at 40 degC: `rho_l` = 1029.85,
  `cp_l` = 3841, `k_l` = 0.4622, `mu_l` = 0.0016295 (SI). `density`, `viscosity`,
  `specific_heat` and `thermal_conductivity` override the four values after that: those of the
  liquid, and those of the gas of a `gas` fluid, whose `rho_l` and `rho_g` otherwise are its density
  at normal conditions. Its density at a stream's `p` and `T` is `Fluid.density_at`, ideal-gas.
- `gas_liquid_ratio` `R` with `gas_composition` gives `gmf = R rho_n / (rho_l + R rho_n)`.
- `corrosion_inputs(p, T)` = `co2_partial_pressure = w_CO2 rho_l / M_CO2 / henry_constant(T)`
  [Pa] and `ionic_strength = salinity rho_l` [kg/m3], with `M_CO2` = 0.04401 kg/mol: the
  dissolved CO2 mass fraction becomes a concentration and the Henry law (Chemistry) is inverted;
  `T` may be an array or a traced value.

Salinity, CO2 and free gas are mass fractions; glycol is a volume fraction. Brine density and
viscosity are not inferred from salinity: supply the overrides. A `steam` fluid carries the
liquid-water snapshot, not vapour properties (use `modules/power/_physics.py`). Mass fractions summing above one,
a glycol fraction on another kind, or a glycol fraction other than 0.3 raise a pydantic
`ValueError`, not `PhysicsError`. `FluidProperties` and `Stream` are frozen slots dataclasses:
invalid physical values (a non-positive property, a gas mass fraction outside [0, 1), a
non-finite flow, `T <= 0`, `p < 0`) raise `PhysicsError`; on arrays and traced values the same
limits are `gemini.ops.check` calls.

## Hydraulics

`hydraulics.py` marches pressure and temperature along a `PipePath` of `PipeSection`s (length
[m], inclination [rad], inner diameter [m], roughness [m]). Inclination is measured from
horizontal, positive when descending in surface-to-bottom order. Friction and gravity drops are
signed so that the pressure rises by both when flowing down and falls by both when flowing up.

- `darcy_weisbach_dp(u, rho, theta, mu, D, K, L)` = friction `f rho L / D |u| u / 2` and
  gravity `rho g L sin(theta)` [Pa], the gravity term being `hydrostatic_dp(rho, L, sin(theta))`.
  `Re = hydraulics.reynolds_number(|u|, rho, D, mu)` = `|u| rho D / mu` and `f` is the Swamee and
  Jain (1976) friction factor `0.25 / log10(K / (3.7 D) + 5.74 / Re^0.9)^2`; `g` = 9.81 m/s2.
  Zero velocity gives zero friction.
- `beggs_brill_dp(us_g, us_l, ...)`: two-phase friction and gravity drops (Beggs and Brill 1973,
  as in Shoham 2006, p. 59). The regime and holdup use the US basis (ft/s, lbm/ft3, dyne/cm,
  ft, `g` = 32.17405 ft/s2). With no-slip holdup `lambda = us_l / (us_g + us_l)`, liquid
  velocity number `N_Lv = 1.938 us_l (rho_l / sigma)^0.25` and `Fr = u_m^2 / (g D)`, the
  boundaries are `L1 = 316 lambda^0.302`, `L2 = 0.0009252 lambda^-2.4684`, `L3 = 0.10
  lambda^-1.4516` and `L4 = 0.5 lambda^-6.738`.
- Horizontal holdup `a lambda^b / Fr^c` with `(a, b, c)` = (0.98, 0.4846, 0.0868) segregated,
  (0.845, 0.5351, 0.0173) intermittent, (1.065, 0.5824, 0.0609) distributed; inclined holdup
  `H_l = H_0 psi` with `psi = 1 + C (sin 1.8 theta - 0.333 sin^3 1.8 theta)` and `C = max(0,
  (1 - lambda) ln(d lambda^e N_Lv^f Fr^h))`. Downhill flow uses (4.7, -0.3692, 0.1244, -0.5056)
  in every regime; uphill segregated (0.011, -3.768, 3.539, -1.614), uphill intermittent (2.96,
  0.305, -0.4473, 0.0978), uphill distributed `psi = 1`. The transition regime blends the
  segregated and intermittent holdups with `A = (L3 - Fr) / (L3 - L2)`; `H_l` is clamped to
  [0, 1].
- Friction: `y = lambda / H_l^2`, `s = ln(2.2 y - 1.2)` for `1 < y < 1.2`, otherwise `s = ln y /
  (-0.0523 + 3.182 ln y - 0.8725 (ln y)^2 + 0.01853 (ln y)^4)`; the multiplier is `exp(s)`. The
  no-slip mixture `rho_m`, `mu_m` give `Re = u_m rho_m D / mu_m`, `f_n = (-0.8685 ln((1.964
  ln Re - 3.8215) / Re + K / (3.71 D)))^-2`, friction `0.5 rho_m u_m |u_m| f_n exp(s) L / D`
  and gravity `(H_l rho_l + (1 - H_l) rho_g) g L sin(theta)` [Pa]. The SI terms use inputs
  converted to the US basis and back, which changes the last bits and is kept for the goldens.
- `pipe_path_profile(path, stream, fluid, direction, heat_transfer_coefficient,
  ambient_temperature)` takes each section from `Fluid.properties`: `Q = fluid.volume_flow(m_dot,
  density)`, the velocities `geometry.mean_velocity(m, rho, D)` = `m / rho / A` with `A =
  pi D^2 / 4`, `us_l` from `(1 - gmf) m` and `rho_l`, and Darcy-Weisbach when the gas mass
  fraction is zero, otherwise Beggs-Brill with `us_g = mean_velocity(m_g, rho_g, D)` and `rho_g` the density of the gas at the section's `p` and `T` (`Fluid.gas_density_at`). Pressures are floored at 0.001
  Pa. `direction` is `up` or `down`; zero flow gives zero drops (gravity too). The marched outlet
  is uncorrected; the affine correction `p = a p_out + b` is `hydraulics.affine_correction`,
  applied by the `Well` module.
- `geometry.build_path(trajectory, tally)` makes one section per trajectory interval:
  `sin(theta) = delta_TVD / delta_MD`, rounded to 0.01 degree as in WIMS, with the diameter and
  roughness of the interval's end point, split at tally joints (a tally interval covering the
  piece midpoint overrides them). Example roughness 2e-5 is metres.

The two-phase choice is the structural test `fluid.gas_mass_fraction == 0`, equal to the former
test on the gas mass flow, so a liquid-only fluid never evaluates Beggs-Brill; zero flow is a
`where`. The regime is an integer code, because `where` selects numbers.

Beggs-Brill needs a nonzero liquid and mixture velocity and a positive holdup after clamping,
and a point inside the regime map; otherwise `PhysicsError`. `build_path` raises it for
fewer than two points, nonincreasing MD or `|delta TVD| > delta MD`; unsupported correlation
names or a direction other than `up` or `down` raise `ValidationError`.

## Reservoir inflow

The reservoir modules (`modules/subsurface/reservoir.py`) combine a linear inflow relation with
the radial Darcy terms of `hydraulics.py` (Akin 2019); volume flow `Q` is at reservoir
conditions, `Q = m_dot / rho_l`.

- Production: `p_bh = p_res - Q / PI` [Pa], `PI` the productivity index [m3/s/Pa].
- Injection: `p_bh = p_res + Q / II` [Pa], `II` the injectivity index [m3/s/Pa] and `Q` the
  absolute volume flow of the arriving stream.
- `hydraulics.productivity_index(Q, p_res, p_bh)` = `Q / (p_res - p_bh)` and
  `hydraulics.injectivity_index` = `Q / (p_bh - p_res)`. The reservoir methods
  `productivity_from_measurements` and `injectivity_from_measurements` call them and raise
  `PhysicsError` for equal pressures, a check the physics functions do not make; the
  functions then return infinity. `productivity_pressure` and `injectivity_pressure` are the two
  inflow relations above.
- `gm.analysis.estimate_reservoir_pressure(flows, bottomhole_pressures)` (not in `physics`) fits
  `p_bh / Q = p_res (1 / Q) + b` by least squares: the
  slope is the reservoir pressure and the second return value is the R-squared of the fit.
- `radial_pressure_drops(Q, mu, k, h, r_e, r_w, S)` = flow drop `Q mu ln(r_e / r_w) / (2 pi k
  h)` and skin drop `Q mu S / (2 pi k h)` [Pa]; the radial bottomhole pressure is `p_res +
  flow drop + skin drop`.
- `hydrostatic_dp(rho, height, inclination_sine=1.0)` = `rho g height s` [Pa] with `g` = 9.81
  m/s2; the reservoir reports it for `rho_l` and the top depth, the pipe and the path functions
  pass `s = sin(theta)`.

A nonpositive `k`, `h`, `r_e` or `r_w` raises `PhysicsError`;
`estimate_reservoir_pressure` needs at
least two finite, nonzero, varying samples (`PhysicsError`). Both indices default to
`None` and a missing one raises `ValidationError`. The linear relations take the viscosity
and density only through the flow; `mu_l` and `rho_l` come from the reservoir fluid.

## Pumps

`pumps.py` holds the TNO R11363 (2022) polynomial curves of an electrical submersible pump on
the historical US basis, used by `ESP`. The coefficients are ascending powers `c_i` of the flow
`q` in bbl/day, fitted at the catalogue frequency `ESP_REFERENCE_FREQUENCY` = 60 Hz, one pump
stage:

- `head(Q, f, N, c)` = `N (f / 60)^2 sum(c_i q^i) * 2988.30167` [Pa]; the coefficients give ft
  of head and `2988.30167` Pa/ft converts it.
- `power(Q, f, N, c)` = `N (f / 60)^3 sum(c_i q^i) * 745.7` [W]; the coefficients give bhp and
  `745.7` W/bhp converts it.
- `q = Q * 543439.650564` bbl/day for a flow `Q` in m3/s. Head follows the square and power the
  cube of the frequency ratio (affinity laws).
- `esp_efficiency(Q, H, P)` = `(q / 135773) (H / P) (745.7 / 2988.30167)` [-], a fraction, and
  0 when `P < ESP_MIN_EFFICIENCY_POWER` = 0.1 W.
- Every constant of `constants.py` (`G`, `G_FT`, `CO2_MOLAR_MASS`, `MIN_PATH_PRESSURE`,
  `ESP_REFERENCE_FREQUENCY`, `ESP_EFFICIENCY_FLOW_FACTOR`, `VALVE_REFERENCE_DENSITY`) and the
  pump thresholds `ESP_MIN_EFFICIENCY_POWER` and `LINE_SHAFT_MIN_EFFICIENCY_POWER` of `pumps.py`
  are `gemini.ops.Constant` objects: plain floats in arithmetic and comparisons on concrete
  values (bit for bit, float32 promotion included) and named graph inputs when traced. A
  `Constant` is not a `float`: use `float(constant)` or `.value` where a float is needed, and
  `ops.maximum`/`ops.minimum` instead of `max`/`min` (the builtins would return the object).
  The ESP module's validity check and the branch of `esp_efficiency` are `ops.check` and
  `ops.where`, so the same code is traced (see [native-engine.md](native-engine.md)). The
  efficiency branch divides with `ops.truediv(head, power)` because `where` evaluates both
  branches and the power curve may be zero: `/` on two Python floats would raise before
  `where` is reached.

The polynomials are only valid inside the flow range of the manufacturer curve; the functions
do not check it and raise nothing. Any number of coefficients is accepted.

### Centrifugal pump

`pumps.py` also holds the SI curves of `CentrifugalPump`: a quadratic head curve with a parabolic
efficiency, scaled by the speed ratio.

- `speed_ratio(f, f_rated)` = `s = f / f_rated` [-]; the speed follows the supply frequency of an
  induction motor.
- `centrifugal_head(Q, s, c)` = `c0 s^2 + c1 s Q + c2 Q^2` [Pa] for the rated-speed curve `H = c0 +
  c1 Q + c2 Q^2` (three coefficients in Pa, Pa s/m3, Pa s2/m6); the affinity laws `Q ~ s`,
  `H ~ s^2`, valid for speed ratios of about 0.5 to 1.1 (Karassik et al., Pump Handbook, 4th ed.,
  chapter 2).
- `best_efficiency_ratio(Q, s, Q_bep)` = `x = Q / (s Q_bep)` [-], one at the best-efficiency
  point; the best-efficiency flow scales with speed.
- `parabolic_efficiency(eta_bep, x)` = `eta_bep x (2 - x)` [-] (Ulanicki, Kahler and Coulbeck
  2008); the 2 is the shape of the parabola, zero slope at `x = 1`.
- `hydraulic_power(Q, H)` = `Q H` [W], the power given to the liquid.
- `is_in_operating_window(Q, Q_min, Q_max, s)` = `s Q_min <= Q <= s Q_max`; `ESP` uses the same
  function.

### Line shaft pump

`LineShaftPump` uses the ESP polynomials `head` and `power` and adds a shaft term and an SI
efficiency.

- `line_shaft_friction_power(k, L, s)` = `k L s` [W]: the friction per shaft length `k` [W/m] at
  catalogue speed grows in proportion to speed (constant bearing friction torque; the form of
  the ANSI/HI 2.3 tables).
- `pump_efficiency(Q, H, P)` = `Q H / P` [-], 0 when `P < LINE_SHAFT_MIN_EFFICIENCY_POWER` = 0.1 W.
  It is not bitwise the expression of `esp_efficiency`, which keeps the US-basis factors.

## Chemistry

`chemistry.py` holds the Henry-law CO2 partition of GEMINI water-analysis workflows, which
supplies the CO2 partial pressure for the corrosion correlations. Temperatures are in K,
pressures in Pa and concentrations in mol/m3. Every function is written with `gemini.ops`, so it
runs on floats, arrays and traced values with the same results:

- `henry_constant(T)` = `0.01 * 0.0385 exp(2400 (1 / T - 1 / 293.15))` [mol/m3/Pa]: 0.0385
  mol/l/bar at 293.15 K, the factor 0.01 converting to SI.
- `co2_solubility_liquid(x, T, p)` = `x K_H(T) p` [mol/m3], the dissolved CO2 of a gas of mole
  fraction `x` at pressure `p`.
- `co2_solubility_gas(x, GWR, rho_gas, M_gas)` = `x GWR rho_gas / M_gas` [mol/m3] for a standard
  gas-water volume ratio `GWR`, standard gas density [kg/m3] and molar mass [kg/mol].
- `co2_partial_pressure(...)` = `(C_liquid(T_sample, p_gas) + C_gas) / K_H(T_system)` [Pa]: the
  CO2 of the sample, dissolved and in gas, is repartitioned by Henry's law at the system
  temperature.

The functions apply no range checks; a nonpositive temperature is outside the model.

## Corrosion

`corrosion.py` holds the NORSOK M-506 and de Waard-Lotz CO2 corrosion correlations, DLM (Milliams
1991) and DLD (Dugstad 1995), through the SI boundary `co2_corrosion_rate(model, ...)` with
`model` `NORSOK`, `DLM` or `DLD`. Inside, the correlations keep their published basis (degC,
bar, NORSOK water flow in m3/day, viscosity in cP, bicarbonate in mg/l, ionic strength in g/l).
Rates are in mm/year, the explicit literature-unit exception of the package.

- Fugacity: `f = 10^(p (0.0031 - 1.4 / T)) p_CO2` [bar] with `p` the total pressure, capped at
  250 bar, and `T` in K. `p_CO2` is `co2_partial_pressure` [Pa], else `co2_fraction * p`.
- Scale factor `F = min(10^(2400 / T - e log10 f - 6.7), 1)` for `T >= 2400 / (6.7 + 0.6 log10 f)`,
  otherwise 1, with `e` = 0.6 (DLM) or 0.44 (DLD).
- DLM = `10^(5.8 - 1710 / T + 0.67 log10 f) F` [mm/year]; it ignores the flow.
- DLD = `F / (1 / CR_r + 1 / CR_m)` with `CR_r = 10^(4.93 - 1119 / T + 0.58 log10 f)` and
  `CR_m = 2.45 u^0.8 / D^0.2 f`, `u` the velocity from the flow and the diameter.
- NORSOK = `A K_t f^0.62 (tau / 19)^(0.146 + 0.0324 log10 f) f(pH)`. `K_t` interpolates
  linearly in degC over 5, 15, 20, 40, 60, 80, 90, 120, 150 with 0.42, 1.59, 4.762, 8.927,
  10.695, 9.949, 6.250, 7.770, 5.203 and takes the end values outside. The wall shear stress
  is `tau = rho f_w u^2 / 2` with `f_w = 0.001375 (1 + (20000 K / D + 10^6 mu / (u D rho))^0.33)`
  (`mu` in Pa s, `K` roughness).
- `pH` solves the carbonate charge balance for `[H+]` by Newton's method (start 10^-3.5, or
  10^-2.9 above 20 bar CO2; tolerance 1e-6 relative; at most 100 steps and then the last
  iterate without a warning), with equilibrium constants that depend on degF, psi and mol/l
  (bicarbonate molar mass 61.2 g/mol, NaCl 58.44 g/mol); the pH is rounded to 0.01. A
  nonpositive root gives pH 99.99. The solve is `ops.newton`; on arrays each row stops by the
  same rule and returns the same iterate as the scalar loop (SciPy's array `newton` stops on an
  absolute tolerance after the step and moves a pH across a rounding boundary, so it is not
  used). A failing iteration gives NaN, which reads as the nonpositive root.
- `f(pH)` has piecewise formulas only at the exactly tabulated temperatures 5, 15, 20, 40, 60,
  80, 90, 120 and 150 degC and for pH 3.5 to 6.5; elsewhere it is 7, so the rate jumps between
  40.000 and 40.001 degC. The 5 degC first segment keeps `2.0676 + 0.2309 pH` where the other
  temperatures use `- 0.2309`. Both are retained numerical decisions of the goldens.
- Defaults: `water_density` 1000 kg/m3, `water_viscosity` 0.001 Pa s, `diameter` 0.1 m,
  `roughness` 5e-5 m, `bicarb_concentration` 0.268 kg/m3, `ionic_strength` 71 kg/m3. With
  `fitted=True` the constants (`A`, `B`, `C`, `D`; NORSOK only `A`, the rate scale) can be
  replaced through `coefficients`.
- Wall loss: `wall_loss(rates, durations)` = `cumsum(rate * dt / year)` [mm] with a 365.25-day
  year; `remaining_wall_thickness(r_o, r_i, loss)` = `r_o - (r_i + loss)`; and
  `time_to_minimum_wall(t, t_min, rate)` = `(t - t_min) / rate` [s], 0 at or below the minimum,
  infinity for a nonpositive or nonfinite rate and NaN for missing values.

A CO2 partial pressure of zero, a zero flow for NORSOK and DLD, a negative flow (complex rate)
and equilibrium-constant underflow near 360 degC raise `PhysicsError`; neither
`co2_fraction` nor `co2_partial_pressure` raises `PhysicsError`; another model name
raises `ValidationError`.

## Erosion

`erosion.py` holds the DNV RP O501, Oka (2005) and E/CRC Tulsa solid-particle erosion rates and
the API RP 14E velocity limit. `erosion_rate(model, ...)` is the SI boundary (flow in m3/s,
angle in rad, hardness in Pa, particle diameter in m) and returns mm/year, the explicit
literature-unit exception of the package. Inside, the flow is in m3/h, the angle in degrees and
radians as each formula needs, the hardness in GPa and the Oka particle diameter in mm.

- Shared terms: the particle mass flow equals the total fluid mass flow (no solids fraction),
  `m_p = Q rho_f`; the velocity is `U = m_p / (rho_f A)`, `A = pi D^2 / 4`, and the impacted
  area is `A_t = A / sin(alpha)`.
- DNV = `Y m_p K U^n F(alpha) / (rho_pipe A_t)` with `Y = 1000 * 365.25 * 86400` mm/year per
  m/s and `F` the seventh-order polynomial of `alpha` [rad] `alpha (9.37 + alpha (-42.295 +
  alpha (110.864 + alpha (-175.804 + alpha (170.137 + alpha (-98.398 + alpha (31.211 - 4.17
  alpha)))))))`. `(K, n, rho_pipe)` is (2e-9, 2.6, 7800) for `steel`, (0.3e-9, 3.6, 1800) for
  `grp/epoxy` and (0.6e-9, 3.6, 1800) for `grp/vinyl ester` (case-insensitive).
- Oka = `year m_p / A_t E` with `A_t` in mm2 and `E = K Hv^k1 (U / U_ref)^k2(Hv) (d_p / d_ref)^k3`
  [mm3/kg], `Hv` in GPa and `d_p` in mm. For `SIO2`, `SIC`, `GLASS`: `U_ref` = 104, 99, 100 m/s;
  `d_ref` = 326, 326, 200; `k1` = -0.12, -0.05, -0.16; `k2` = `2.3 Hv^0.038`, `3 Hv^0.085`,
  2.1; `k3` = 0.19; `K` = 65, 45, 27.
- Tulsa = `Y E_r m_p / (rho_pipe A_t)` with `E_r = 2.17e-7 H_b^-0.59 F_s U^2.41 F(alpha)`,
  `F(alpha) = 5.4 alpha - 10.11 alpha^2 + 10.93 alpha^3 - 6.33 alpha^4 + 1.42 alpha^5` and the
  Brinell hardness `H_b = 0.95057 Hv / 0.009807 - 0.03743` from the Vickers hardness in GPa.
- Defaults: `alpha` = pi/2, `material` `steel`, `hardness` 1e9 Pa, `particle_material` `SIO2`,
  `particle_diameter` 0.0001 m, `rho_pipe` 7800 kg/m3, `shape_factor` 0.5.
- `api_erosional_velocity(rho)` = `0.3048 / sqrt(0.0283 / 0.454) * 125 / sqrt(rho)` [m/s], the
  API RP 14E criterion with `C` = 125 and its imperial conversions;
  `api_velocity_comparison(u, limit)` returns the ratio `u / limit`, the margin `limit - u` and
  the flag `u > limit`.

Model names are case-insensitive (`DNV`, `DNVGL`, `OKA`, `TULSA`, `E/CRC Tulsa`, `ECRC`); `API`
is a velocity limit, not a rate. Unknown names, DNV materials (titanium is rejected) and Oka
particle materials raise `ValidationError`. A zero impact angle, a negative flow (complex
rate) and a nonpositive density or API limit raise `PhysicsError`.

## Compression

`modules/pumps/_physics.py` holds ideal-gas adiabatic compression (GPSA Engineering Data Book, 14th ed.
2017, Section 13; compressibility factor Z = 1, constant `k = cp/cv`), used by `GasCompressor`:

- `isentropic_outlet_temperature(T_1, r, k)` = `T_1 r^((k-1)/k)` [K];
- `stage_outlet_temperature(T_1, r, k, eta_s)` = `T_1 + (T_2s - T_1) / eta_s` [K]: every loss
  of an adiabatic stage heats the gas;
- `specific_compression_work(T_1, r, k, cp, eta_s, stages)` = `N cp (T_2 - T_1)` [J/kg] for `N`
  equal stages at ratio `r^(1/N)` with intercooling to `T_1`, the minimum-work split.

A pressure ratio below one (expansion) or non-finite, a nonpositive or non-finite inlet
temperature, `k <= 1`, an efficiency outside (0, 1], a nonpositive `cp` or fewer than one stage
raise `PhysicsError`. Valid for near-ideal gases and stage ratios up to about 4.

## Refrigeration

`refrigeration.py` and `modules/cooling/_physics.py` hold the heat pump, chiller and sorption-machine relations of `HeatPump`,
`AbsorptionUnit` and `AdsorptionChiller`. Inputs and outputs are SI (K, W, W/K); NaN and
out-of-domain inputs raise `PhysicsError`.

- `carnot_cop_heating(sink, source, minimum_lift=0)` = `T_sink / max(T_sink - T_source,
  minimum_lift)` and `carnot_cop_cooling(...)` = `T_source / max(...)`. Nonpositive
  temperatures and a nonpositive floored lift are rejected; for one lift, heating COP = cooling
  COP + 1.
- `log_mean_temperature(T_in, T_out)` = `(T_in - T_out) / ln(T_in / T_out)` (`T_in` when equal),
  the thermodynamic mean temperature of a sensible glide.
- `lorenz_cop_heating(sink_in, sink_out, source_in, source_out, minimum_lift=0)` = `T_h /
  max(T_h - T_s, minimum_lift)` with the log-mean sink and source temperatures (Lorenz 1894); it
  equals the Carnot COP when both glides vanish.
- `characteristic_temperature_difference(t_G, t_AC, t_E, a, r)` = `t_G - a t_AC + r t_E`,
  evaluated in degC from kelvin inputs: the published fits (Hellmann, Schweigler and Ziegler
  1999; Kuehn and Ziegler 2005) use Celsius, and the two bases agree only in the ideal Duehring
  form `1 - a + r = 0`.
- `characteristic_sensitivity(C_G, C_AC, C_E, Q_G/Q_E, Q_AC/Q_E, a, r)` = `k`, the drop of the
  mean-temperature ddt per watt of evaporator duty; `inf` when a circuit is stopped.
- `characteristic_evaporator_duty(ddt_in, ddt_min, s, k)` = `max(0, s (ddt_in - ddt_min) / (1 +
  s k))`, the closed-form solution of `Q_E = s (ddt_mean - ddt_min)`.
- `sorption_evaporator_capacity(...)` combines the three for a machine with a constant thermal
  COP and an auxiliary-electricity ratio: the largest evaporator duty at the circuit inlets.
- `part_load_duty(requested, capacity, minimum_part_load)` = `min(requested, capacity)`, or 0
  below `minimum_part_load * capacity`: the machine is off for the step rather than cycling
  (EN 14825 describes the cycling alternative with a degradation coefficient).

## Steam

`modules/power/_physics.py` holds the exact IAPWS-IF97 equations for water and steam in SI units (Pa, K, J/kg,
J/kg/K), not fits, used by `Separator` and `FlashTurbine`:

- `saturation_pressure(T)` (eq. 30, 273.15 K to 647.096 K) and `saturation_temperature(p)`
  (eq. 31, 611.213 Pa to 22.064 MPa);
- `liquid_enthalpy(p, T)`, `liquid_entropy(p, T)`: region 1 (273.15 K to 623.15 K,
  `p_sat(T) <= p <= 100 MPa`);
- `vapour_enthalpy(p, T)`, `vapour_entropy(p, T)`: region 2 (`0 < p <= p_sat(T)` up to
  623.15 K, `p <= b23_pressure(T)` up to 863.15 K, `p <= 100 MPa` up to 1073.15 K);
- `saturation_properties(p)` returns a frozen `SaturationProperties` (`pressure`,
  `temperature`, `liquid_enthalpy`, `vapour_enthalpy`, `liquid_entropy`, `vapour_entropy`,
  and the properties `evaporation_enthalpy` and `evaporation_entropy`) for 611.213 Pa to
  16.529 MPa; region 3 is not implemented, so saturated states above 623.15 K raise;
- `flash_fraction(h, p)` = `(h - h_f) / h_fg`, zero when subcooled; an enthalpy at or above
  saturated vapour raises;
- `baumann_expansion(p_in, p_out, eta_dry, a)`: dry saturated steam expanded into the wet
  region with the Baumann rule `eta = eta_dry (1 - a (1 - x_mean))`, solved in closed form and
  returned as a frozen `Expansion`; a dry exhaust raises.

`steam.saturation_pressure` (IF97 region 4, over liquid water up to the critical point) and
`psychrometrics.saturation_pressure` (Hyland and Wexler over ice and water) are two models, not one
function in two places. Each is the standard of its field and they differ by up to about 3e-4
relative. Use the steam one with the steam tables and the psychrometric one with moist air.

The unit tests reproduce the IF97 verification tables 5, 15, 35 and 36 to a relative 1e-8 and
the IF97 steam tables at 0.1 MPa and 1 MPa. States on the saturation line pass the region checks
within a relative pressure tolerance of 1e-9. Properties are those of pure water; salts and
non-condensable gases are not represented. Sources: IAPWS-R7-97(2012); Wagner et al. (2000),
J. Eng. Gas Turbines Power 122, 150-182; DiPippo (2016), Geothermal Power Plants, 4th ed.

## Ground

`ground.py` holds ground and aquifer heat transport for the subsurface equipment. Out-of-domain
inputs (nonpositive sizes or properties, NaN, a negative volume ratio, a cell radius not above
the borehole radius, `ln(4L/D) < 1`, Ramey below `alpha t / r^2 = 25`) raise
`PhysicsError`; modules convert geometry and time errors into `ValidationError`.

- `aquifer_volumetric_heat_capacity(phi, (rho c)_w, (rho c)_r)` = `phi (rho c)_w + (1 - phi)
  (rho c)_r`, assuming local thermal equilibrium (Bear 1972).
- `doublet_breakthrough_volume(L, H, (rho c)_a, (rho c)_w)` = `pi L^2 H (rho c)_a / (3 (rho
  c)_w)` (Gringarten and Sauty 1975), without confining-bed conduction or regional flow.
- `doublet_cold_fraction(V / V_B)`: the share `theta / pi` of the produced flow already swept by
  cold water, where theta solves `3 (sin theta - theta cos theta) / sin^3 theta = V / V_B`
  (dipole streamline travel times, checked against integrated streamlines); a Taylor series
  below 0.1 rad avoids cancellation. It is 0 up to breakthrough and 1/2 at `V = 3 V_B`. The
  angle is an `ops.brentq` solve (`xtol` 1e-14), and the early returns are `ops.where`.
- `cylinder_store_conductance(k, alpha, V, H, t_p)` = `2 k A / sqrt(pi alpha t_p)` over the
  envelope of a cylinder of volume V and height H: period-mean semi-infinite conduction
  (Carslaw and Jaeger 1959), valid while `sqrt(alpha t_p)` is small against the store.
- `vertical_cylinder_conductance(k, L, D)` = `2 pi k L / ln(4L/D)` (Incropera, table 4.1), for
  `L >> D`.
- `steady_flux_resistance(k, r_b, r_e)`: the exact uniform-sink annulus resistance, which
  reduces to `(ln(r_e/r_b) - 3/4) / (2 pi k)` (Hellstrom 1991) and is reached after about
  `r_e^2 / (4 alpha)`.
- `ramey_time_function(t, alpha, r)` = `ln(2 sqrt(alpha t) / r) - gamma / 2`, the line-source
  long-time asymptote (Ramey 1962), within about 1 % of `E1(r^2 / (4 alpha t)) / 2` for
  `alpha t / r^2 >= MIN_RAMEY_FOURIER = 25`, a `Constant`. Its keyword-only `error` and `context`
  let `DownholeHeatExchanger` report an early time as `ValidationError`: a `try` around a
  physics call cannot work in a trace.
- `ramey_fluid_temperature(T_in, T_top, G, z, A)`: Ramey's exact steady profile in a linear
  gradient with the relaxation length `A = m_dot cp R_total`.

The aquifer store, borehole field and doublet-state functions of the file list
(`store_conductance`, `mix_store`, `store_relaxation`, `borehole_loop_conductance`,
`borehole_field_temperature_change`, `ramey_rock_resistance`, ...) are lumped balances of the
modules that use them. The positive and negative parts of a signed duty are
`heat_transfer.signed_parts`.

## Psychrometrics

`psychrometrics.py` holds moist-air relations in SI (K, fraction, Pa) for an ideal mixture of
dry air and water vapour without the enhancement factor, used by `CoolingGrid`:

- `saturation_pressure(T)`: Hyland and Wexler (1983), ASHRAE Handbook - Fundamentals (2017),
  chapter 1, equations 5 (over ice, -100 to 0 degC) and 6 (over water, 0 to 200 degC); within
  3e-4 relative of the ASHRAE table. Outside 173.15 K to 473.15 K or NaN raises.
- `dew_point(T, relative_humidity)`: inverts `saturation_pressure` with Brent's method (to
  1e-9 K), so the two are consistent by construction; below 0 degC it is the frost point.
  Relative humidity must be in (0, 1]; a dew point below -100 degC raises. The inversion is an
  `ops.brentq` solve; on arrays it repeats Brent's method step for step (the result carries up
  to 1.4e-12 relative of the `xtol` error, so a different root finder would differ by more than
  the `1e-12` tolerance of the array path). The input checks work on arrays.
- `humidity_ratio(T, relative_humidity, p)` = `0.621945 p_w / (p - p_w)` (ASHRAE equations 20
  and 22); saturated values are about 0.4 % below the ASHRAE `W_s` column. `p <= p_w` raises.
- `wet_bulb_temperature(T, relative_humidity)`: Stull (2011), J. Appl. Meteor. Climatol. 50,
  2267-2269, fitted at 101.325 kPa; valid for -20 to 50 degC and relative humidity 0.05 to 0.99
  (error -1 to +0.65 K); inputs outside raise.

`psychrometrics.saturation_pressure` is not `steam.saturation_pressure`; see Steam.

```python
from gemini.physics import psychrometrics

assert round(psychrometrics.saturation_pressure(293.15), 1) == 2338.8
assert round(psychrometrics.dew_point(297.15, 0.5) - 273.15, 2) == 12.95
assert round(psychrometrics.humidity_ratio(293.15, 0.5, 101325), 6) == 0.007262
```

## Separation

`separation.py` and `modules/treatment/_physics.py` hold the lumped splits of the treatment and piping modules (`Splitter`,
`Blowdown`, `Degasser`, `Desander`, `InhibitorDosing`). No relation has a residence time, a level
or a size distribution.

- `split_flow(m, f)` = `(m - f m, f m)` [kg/s]: an ideal tee or bleed with a commanded share and no
  pressure loss; the parts sum to the feed up to rounding. A reverse flow scales both parts.
- `degasser_split(m, x, eta)`: gas `eta x m`, liquid `m - eta x m` and the gas fraction left in
  the liquid `(1 - eta) x / (1 - eta x)`; the free gas is conserved and dissolved gas stays in the
  liquid (no Henry's law).
- `cyclone_sand(eta, c, Q_l)`: removal rate `eta c Q_l` [kg/s] and residual concentration `(1 -
  eta) c` [kg/m3], `Q_l = fluid.liquid_volume_flow(...)`. The grade-efficiency curve is one constant
  efficiency (Svarovsky 2000), so the cut size does not follow the flow.
- `dosing_flows(dose, m, w)`: product `dose m` and active substance `w dose m` [kg/s]; the dosed
  mass is not added to the stream (Gallup 2009).
- Defaults of the filter and the degasser are `FILTER_NOMINAL_DROP` = 1600 Pa,
  `FILTER_NOMINAL_MASS_FLOW` = 149 / 3600 * 1068 kg/s, `FILTER_CLOGGING_BAR` = 0.5 and
  `DEFAULT_DEGASSER_DROP` = 14900 Pa.

## Combustion

`combustion.py` holds the fuel side of `CHP`, `Boiler` and `Flare`. Boiler fuel is
`energy.input_power`.

- `willans_fuel_input(L, P_el, eta_el, f0)` = `F_full (f0 + (1 - f0) L)` [W] with `F_full = P_el /
  eta_el` on the lower heating value, and 0 at `L = 0`: fuel at constant speed is close to linear
  in load (Heywood 1988).
- `engine_energy_flows(F, L, P_el, eta_th)` = `(eta_th F, L P_el)` [W]: recoverable heat and
  electric output; the rest of the fuel is the heat loss.
- `flare_emissions(m, x_CO2, x_CH4, eta_c, H)`: with `m_b = eta_c x_CH4 m` the CO2 emission is
  `x_CO2 m + m_b M_CO2 / M_CH4`, the methane emission `x_CH4 m - m_b` [kg/s] and the fuel
  `m_b H` [W]. `eta_c` = 0 is a vent. Defaults: `FLARE_EFFICIENCY` = 0.98, `METHANE_HEATING_VALUE` =
  50e6 J/kg.

- `released_heat(m, H, eta_c)` = `m H eta_c` [W]: the heat a flare gives to `loss_out`.

## Storage

`modules/storage/_physics.py` holds lumped stores at one uniform temperature, used by `ThermalStorage` and
`IceStorage`.

- `circuit_conductance(e, C)` = `G = e C` [W/K]: a circuit exchanging heat with a store at uniform
  temperature takes `G (T_in - T)` (effectiveness-NTU, Incropera et al.).
- `tank_capacity(rho cp, V)` = `rho cp V` [J/K].
- `tank_relaxation(...)`: the fully mixed tank `C dT/dt = G_c (T_c - T) + G_d (T_d - T) - UA (T -
  T_amb)` solved exactly for constant inlets, `T_eq + (T - T_eq) exp(-b dt / C)` with `b = G_c +
  G_d + UA` (Duffie and Beckman 2013, section 8.3); unchanged for `b = 0`.
- `tank_service_report(hot, C, T, T_ref, Q_c, Q_d)` = `(E, Q_charge, Q_discharge)` with `E = C (T -
  T_ref)` for a hot tank; every sign flips for a chilled tank.
- `ice_stored_cold(M, L, x)` = `M L x` [J], the latent cold of frozen fraction `x`.
- `ice_advance(...)` returns the frozen fraction and temperature after a step, integrated exactly
  and piecewise for a constant inlet: the latent segment has the constant duty `G (T_in - T_f)`
  and `x` changes linearly; a sensible segment relaxes with the time constant `M c / G` and stops
  at the freezing temperature. `ice_step` is one segment, and at most `MAX_SEGMENTS` = 3
  segments run per step.
- Defaults: `DEFAULT_LATENT_HEAT` = 333550 J/kg, `DEFAULT_FREEZING_TEMPERATURE` = 273.15 K,
  `DEFAULT_WATER_HEAT_CAPACITY` = 4219.9 and `DEFAULT_ICE_HEAT_CAPACITY` = 2096.8 J/kg/K,
  `DEFAULT_TANK_TEMPERATURE` = 293.15 K.

## Control

`modules/control/_physics.py` holds the ideal (ISA) PID form of `PIDController`, discretised as in Astrom and
Hagglund (2006, chapter 3): explicit rectangular integral, backward-difference derivative on the
error, and anti-windup by clamping (conditional integration).

- `pid_error(setpoint, y, reverse)` = `setpoint - y` for reverse action, `y - setpoint` for direct
  action.
- `pid_derivative(K, Td, de, h_prev)` = `K Td de / h_prev`, unfiltered, exact for a uniform clock.
- `pid_command(K, e, I, D)` = `K e + I + D`, before the output limits.
- `pid_integral_increment(K, h, Ti, e)` = `K h e / Ti`, in command units.
- `anti_windup_increment(inc, u, u_min, u_max)` = 0 when `u >= u_max` and `inc > 0`, or `u <= u_min`
  and `inc < 0`, otherwise `inc`.

## Power cycles

`modules/power/_physics.py` also holds the binary organic Rankine cycle of `ORC`. The reversible work of a heat
source cooled from `T_in` to `T_out` and rejected at the condensing temperature is the Lorenz
(triangular-cycle) work, and the plant delivers a fraction of it (DiPippo 2007, 2016, chapter 8).

- `lorenz_efficiency(T_a, T_b, T_c)` = `1 - T_c ln(T_a / T_b) / (T_a - T_b)` [-], that is `1 - T_c /
  T_lm`. It is not written with `refrigeration.log_mean_temperature`: that function checks its
  arguments and returns the inlet for equal temperatures, this one keeps the retained
  floating-point order.
- `cycle_design(...)`: `T_c = T_amb + approach`, `T_out = max(T_min, T_c + pinch)`, the cycle
  efficiency `carnot_fraction` times the Lorenz efficiency between `T_in - pinch` and `T_out -
  pinch`, and the uncapped gross power `eta m cp (T_in - T_out)`. Above `capacity` the processed
  share of the brine is `capacity / uncapped power` and `is_capped` is true. Efficiency, share and
  flag are zero when `T_in <= T_out`. Part-load degradation is not modelled.
- `plant_balance(Q, eta, f)`: gross power `eta Q`, parasitic power `f` times gross, net
  `gross - parasitic`, condenser duty `Q - gross`, heat loss condenser duty plus parasitic power
  (the parasitic power ends as heat in the air); `thermal_efficiency` is net over `Q`, `None`
  without heat input.

## Electricity

`electricity.py` holds net metering at one connection point with one tariff per direction, for
`ElectricityGrid`, without reactive power, losses or demand charges.

- `net_exchange(C, G, import_limit, export_limit, import_price, export_price)` returns `net_import`
  `min(max(0, C - G), limit)` and `net_export` `min(max(0, G - C), limit)` [W], the parts above the
  limits as `unserved_consumption` and `curtailed_generation`, and `cost_rate = import price *
  net_import - export price * net_export` [currency/s], negative for a revenue. A limit of `None`
  means unlimited; whether a limit exists is a configuration, so it is a Python test.

## Energy

`energy.py` has one relation, the efficiency of a steady converter: `input_power(P_out, eta)` =
`P_out / eta` [W], the shaft power, electricity or fuel a pump, compressor, motor or burner draws
for a useful power at the operating point its efficiency belongs to.

## Diagnostics

`diagnostics.py` holds the health scoring that every module uses against a prediction. These are
plain ratio formulas and conventions without a published source, in one place so that all
modules score alike.

- `relative_drift(measured, predicted)` = `(measured - predicted) / max(|predicted|, DRIFT_FLOOR)`,
  finite for a zero prediction; `DRIFT_FLOOR` = 1e-12.
- `bounded_score(r)` = `min(1, max(0, r))`: one is healthy, zero is failed.
- `remaining_margin(r)` = `max(0, 1 - r)`.
- `below_limit(r, threshold)` = `r < 1 - threshold`, the alarm of a decline or fouling test.
- `performance_ratio(measured, reference)` = `measured / reference`, valid for a nonzero reference.
- Default thresholds: `DEFAULT_DRIFT_THRESHOLD` = 0.10, `DEFAULT_DECLINE_THRESHOLD` = 0.15,
  `DEFAULT_FOULING_THRESHOLD` = 0.15.

## Units

`gemini/units/conversions.py` converts at the package and correlation boundaries.

- Each conversion factor is declared once as a named module constant (`PA_PER_BAR`,
  `M_PER_FOOT`, `SECONDS_PER_HOUR`, `PA_PER_FOOT_HEAD`, `W_PER_BHP`, ...). The table `_UNITS` and
  the `*_to_*` converters both read that constant.
- A converter whose body equals that of another quantity's converter is an alias of it:
  `kgh_to_kgs = m3h_to_m3s`, `nm_to_dyne_cm = pas_to_cp`, `dyne_cm_to_nm = cp_to_pas`.
- A converter is valid for any finite number and does no range check. NIST SP 811 (2008) gives
  the exact definitions (bar, inch, foot, psi, hour, degree Celsius); the millidarcy, barrel per
  day, foot of head, brake horsepower, lbm/ft3 and psi factors are retained numbers of the
  original GEMINI, kept bit for bit.
- `to_si`, `convert`, `value_in_si`, `si_unit`, `names`, `fits` and the unit sets of
  `Profile` and `Stream` all read `_UNITS`; `define_quantity` records the SI unit of each named
  quantity.

## Functions without `@ops.physics`

- `fluid.mixture_density`, `volume_flow`, `liquid_volume_flow` and `heat_capacity_rate`: `Stream`
  and `FluidProperties` call them on every eager step, the decorator would make those calls about
  3.5 times slower, and they divide only by validated positive properties, so they need no eager
  scope.
- `gemini/units/conversions.py`: the converters sit on the hot path of every binding and plain operators work on
  every backend, so the registry wrapper would only add cost.
