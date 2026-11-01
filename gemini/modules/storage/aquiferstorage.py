"""Aquifer thermal energy storage (ATES) well pair with a warm and a cold store."""

from typing import Literal

from gemini import ops
from gemini.errors import PhysicsError, ValidationError
from gemini.modules._utils.flow import require_forward
from gemini.modules.declarations import Control, Inlet, Outlet, Output, Parameter, State
from gemini.modules.module import Module
from gemini.physics import energy, fluid, ground, heat_transfer
from gemini.types import (
    Dimensionless,
    Duration,
    Energy,
    Fraction,
    HeatAccumulation,
    Length,
    MassFlow,
    Power,
    Pressure,
    Stream,
    Temperature,
    TemperatureDifference,
    ThermalConductivity,
    Volume,
    VolumetricHeatCapacity,
)

STORES = ("warm", "cold")
"""The two stores of the well pair, in state order."""

SOURCE_AND_TARGET = {"charge": ("cold", "warm"), "discharge": ("warm", "cold")}
"""Store produced from and store injected into, per flowing ``mode``."""


class AquiferStorage(Module):
    """Balanced ATES well pair storing heat in a warm and cold in a cold aquifer store.

    ``mode`` ``"charge"`` produces from the cold well and injects ``injection_in`` into the
    warm well (summer: heat from cooling is stored); ``"discharge"`` produces from the warm
    well and injects into the cold well (winter: stored heat is recovered); ``"idle"`` moves no
    water and requires zero flow. The doublet is balanced: ``production_out`` carries the
    injected mass flow, pressure and fluid at the temperature of the store it is produced from
    (the aquifer temperature in idle mode); well hydraulics belong to well modules.

    Each store is fully mixed and described by its injected water volume V [m3] and its
    temperature change theta = T - T_aq [K] relative to ``aquifer_temperature``; an empty
    store produces native groundwater at the aquifer temperature. Its excess heat is
    E = (rho c)_w V theta, with (rho c)_w from the circuit fluid, and it occupies the thermal
    volume V (rho c)_w / (rho c)_a with (rho c)_a = phi (rho c)_w + (1 - phi) (rho c)_r, a
    cylinder of height ``aquifer_thickness`` H and thermal radius R. Losses to the
    surroundings are transient conduction through the whole envelope A = 2 pi R (R + H),
    averaged over the ``storage_period`` t_p: UA = 2 k A / sqrt(pi alpha t_p) with
    alpha = k / (rho c)_a (``ground.cylinder_store_conductance``, Carslaw and Jaeger 1959), so
    each store relaxes towards the aquifer temperature with the time constant
    (rho c)_w V / UA and the losses scale with the area-to-volume ratio, as observed for ATES
    (Bloemendal and Hartog 2018, Geothermics 71, 306-319). A store above the aquifer
    temperature reports its loss as ``loss_out``, one below it its gain as
    ``loss_out`` (negative). The ``storage_period`` is the charge or discharge season of seasonal
    ATES, about half a year, and the plant states it.

    Each step first applies the injected volume Q dt (mixing) and the withdrawn volume
    (temperature unchanged; the store volume stops at zero, after which native water is
    produced), then the exact exponential conduction decay over ``dt`` at the end-of-step
    volume. The decay is exact for an idle store; with flow the operator splitting is first
    order in ``dt``. When a store empties within one step, the step's production temperature
    is still the start-of-step store temperature.

    ``stored_energy`` is the net excess heat of both stores (the cold store counts negative).
    ``recovery_efficiency`` is the warm store's thermal recovery, heat produced over heat
    injected, both relative to the aquifer temperature (the definition of Bloemendal and
    Hartog 2018); it is ``None`` until positive heat has been charged.

    Assumptions: no regional groundwater flow, dispersion or buoyancy; no thermal
    interaction between the wells; a sharp, fully mixed store instead of a thermal fringe
    (late-season production temperatures are therefore too high and early ones too low); a
    fully penetrating screen over H; and a conduction boundary layer sqrt(alpha t_p) thin
    against R and H. Dispersion and fringe losses are not resolved, so
    ``ground_conductivity`` is calibratable as an effective value. Valid for low-temperature
    ATES (stores below about 30 degC, so buoyancy flow is weak).
    ``heat_accumulation`` is the rate of change of the stored heat at the start of the step: the
    sensible enthalpy flow of ``injection_in`` minus that of ``production_out`` (``m_dot cp T``
    per stream, the basis of ``energy_balance``) minus the net conduction loss. It is the signed
    storage outflow of ``energy_balance``, so the well pair is first-law closed per call.

    The production temperature does not depend on the injected stream, so a plant that closes
    the groundwater loop through this module (production, pump, heat exchanger, injection) needs
    no iteration: with ``groundwater_flow`` and ``groundwater_pressure`` set, ``production_out`` is
    offered before the other modules run, and the module is called once with the returned
    groundwater, which it produces again at ``groundwater_pressure``.

    NOTE(refactor): written with ops, but a graph break while the graph has no ``scan``: the
    store volumes, temperature changes and heat totals are states.
    """

    def __init__(self):
        """Declare aquifer data, the operating mode and the two store states."""
        super().__init__()

        # Parameters
        self.aquifer_temperature = Parameter(
            Temperature, description="Undisturbed temperature of the aquifer"
        )
        self.aquifer_thickness = Parameter(
            Length, gt=0, description="Thickness of the storage aquifer"
        )
        self.porosity = Parameter(
            Fraction, gt=0, lt=1, description="Pore volume as a fraction of the aquifer rock volume"
        )
        self.rock_volumetric_heat_capacity = Parameter(
            VolumetricHeatCapacity, description="Volumetric heat capacity of the saturated rock"
        )
        self.ground_conductivity = Parameter(
            ThermalConductivity, calibratable=True, description="Thermal conductivity of the ground"
        )
        self.storage_period = Parameter(
            Duration,
            gt=0,
            description="Duration of one charge or discharge period of the store",
        )
        self.groundwater_pressure = Parameter(
            Pressure | None,
            default=None,
            gt=0,
            description="Pressure of the groundwater; empty when not given",
        )

        # Inlets
        self.injection_in = Inlet(Stream, kind="brine")

        # Controls
        self.mode = Control(
            Literal["charge", "discharge", "idle"],
            description="Operating mode: charge, discharge or idle",
        )
        self.groundwater_flow = Control(
            MassFlow | None,
            default=None,
            ge=0,
            description="Natural groundwater flow through the store; empty means none",
        )

        # States
        self.warm_volume = State(Volume, default=0)
        self.warm_temperature_change = State(TemperatureDifference, default=0)
        self.cold_volume = State(Volume, default=0)
        self.cold_temperature_change = State(TemperatureDifference, default=0)
        self.charged_heat = State(Energy, default=0)
        self.recovered_heat = State(Energy, default=0)

        # Outputs
        self.stored_energy = Output(
            Energy, description="Heat held in the store relative to its reference"
        )
        self.recovery_efficiency = Output(
            Dimensionless | None, description="Share of the stored heat recovered"
        )
        self.warm_temperature = Output(Temperature, description="Temperature of the warm store")
        self.cold_temperature = Output(Temperature, description="Temperature of the cold store")
        self.heat_accumulation = Output(
            HeatAccumulation,
            description="Rate at which the store gains heat (negative when it loses)",
        )

        # Outlets
        self.production_out = Outlet(Stream, kind="brine", offered=True)
        self.loss_out = Outlet(Power, kind="heat")

    def forward(self, inlets):
        """Produce the injected mass flow from the source store of the current mode."""

        # Outlets
        injection_in = inlets.injection_in
        self._volume_flow(injection_in)
        production_out = injection_in.with_(T=self.production_temperature())
        if self.groundwater_pressure is not None:
            production_out = production_out.with_(p=self.groundwater_pressure)

        losses = self._store_losses(injection_in)
        loss_out = energy.total_power(losses)

        # Outputs
        water = self._fluid_heat_capacity(injection_in)
        self.stored_energy = ground.aquifer_stored_energy(
            water,
            self.warm_volume,
            self.warm_temperature_change,
            self.cold_volume,
            self.cold_temperature_change,
        )
        self.recovery_efficiency = ground.thermal_recovery(self.recovered_heat, self.charged_heat)
        self.warm_temperature = self.aquifer_temperature + self.warm_temperature_change
        self.cold_temperature = self.aquifer_temperature + self.cold_temperature_change
        self.heat_accumulation = (
            heat_transfer.heat_rate(injection_in.heat_capacity_rate(), injection_in.T)
            - heat_transfer.heat_rate(production_out.heat_capacity_rate(), production_out.T)
            - sum(losses)
        )

        outlets = dict(production_out=production_out, loss_out=loss_out)
        return outlets

    def _offer(self, inlets):
        """Offer the produced groundwater of a loop through the well pair."""
        if self.groundwater_pressure is None or self.groundwater_flow is None:
            raise ValidationError(
                f"{self.path}: groundwater_pressure and groundwater_flow are needed to offer "
                "production_out; expected both on a loop through the well pair",
                code="invalid_design",
            )
        offered = Stream._si(
            m_dot=self.groundwater_flow,
            T=self.production_temperature(),
            p=self.groundwater_pressure,
            fluid=self.fluid,
        )
        return {"production_out": offered}

    def _store_losses(self, injection):
        """Return the conduction loss [W] of each store to the aquifer around it."""
        water = self._fluid_heat_capacity(injection)
        return [
            heat_transfer.heat_rate(
                ground.store_conductance(
                    volume,
                    self.ground_conductivity,
                    self.porosity,
                    water,
                    self.rock_volumetric_heat_capacity,
                    self.aquifer_thickness,
                    self.storage_period,
                ),
                change,
            )
            for volume, change in map(self._store, STORES)
        ]

    def _advance_states(self, inlets, outlets, dt):
        injection = inlets.injection_in
        volume = ground.injected_volume(self._volume_flow(injection), dt)
        injected_change = injection.T - self.aquifer_temperature
        water = self._fluid_heat_capacity(injection)
        states = {}
        for store in STORES:
            store_volume, change = self._moved_store(store, volume, injected_change)
            conductance = ground.store_conductance(
                store_volume,
                self.ground_conductivity,
                self.porosity,
                water,
                self.rock_volumetric_heat_capacity,
                self.aquifer_thickness,
                self.storage_period,
            )
            states[f"{store}_volume"] = store_volume
            states[f"{store}_temperature_change"] = ground.store_relaxation(
                change, store_volume, conductance, dt, water
            )
        charged = self.charged_heat
        if self.mode == "charge":
            charged = charged + ground.stored_heat(water, volume, injected_change)
        states["charged_heat"] = charged
        recovered = self.recovered_heat
        if self.mode == "discharge":
            recovered = recovered + ground.stored_heat(water, volume, self.warm_temperature_change)
        states["recovered_heat"] = recovered
        return states

    def production_temperature(self):
        """Return the temperature [K] that ``production_out`` has in the running step."""
        source, _ = self._source_and_target()
        if source is None:
            return self.aquifer_temperature
        return self.aquifer_temperature + self._store(source)[1]

    def _moved_store(self, store, volume, injected_change):
        """Return a store's volume [m3] and temperature change [K] after this step's flow."""
        store_volume, change = self._store(store)
        source, target = self._source_and_target()
        if store == target:
            return ground.mix_store(store_volume, change, volume, injected_change)
        if store == source:
            return ops.maximum(store_volume - volume, 0.0), change
        return store_volume, change

    def _source_and_target(self):
        """Return the stores the running mode takes water from and puts it into, else ``None``."""
        return SOURCE_AND_TARGET.get(self.mode, (None, None))

    def _store(self, store):
        """Return a store's volume [m3] and temperature change [K] at the start of the step."""
        if store == "warm":
            return self.warm_volume, self.warm_temperature_change
        return self.cold_volume, self.cold_temperature_change

    @staticmethod
    def _fluid_heat_capacity(stream):
        """Return the volumetric heat capacity (rho c)_w [J/m3/K] of the circuit liquid."""
        properties = stream.fluid.properties(stream.p, stream.T)
        return properties.liquid_volumetric_heat_capacity

    def _volume_flow(self, injection):
        """Return the injected liquid volume flow [m3/s] after checking it against the mode."""
        require_forward(self.path, "injection_in.m_dot", injection.m_dot)
        if self.mode == "idle":
            ops.check(
                injection.m_dot == 0,
                PhysicsError,
                "{path}: injection_in.m_dot = {m_dot} kg/s in idle mode; expected 0",
                path=self.path,
                m_dot=injection.m_dot,
            )
        density = injection.fluid.properties(injection.p, injection.T).rho_l
        return fluid.volume_flow(injection.m_dot, density)
