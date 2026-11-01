"""The closed lists of the case: equipment kinds with their cost basis, and gas species."""

EQUIPMENT_KINDS = {
    "drilling": ("money_per_length", "per metre of well"),
    "production_pump": ("money_per_power", "per W of shaft power at the nominal flow"),
    "injection_pump": ("money_per_power", "per W of shaft power at the nominal flow"),
    "circulation_pump": ("money_per_power", "per W of shaft power at the nominal flow"),
    "heat_pump": ("money_per_power", "per W of capacity"),
    "boiler": ("money_per_power", "per W of capacity"),
    "electric_boiler": ("money_per_power", "per W of capacity"),
    "chp": ("money_per_power", "per W of electric capacity"),
    "absorption_chiller": ("money_per_power", "per W of capacity"),
    "adsorption_chiller": ("money_per_power", "per W of capacity"),
    "compression_chiller": ("money_per_power", "per W of capacity"),
    "heat_exchanger": ("money_per_conductance", "per W/K of conductance"),
    "cooler": ("money_per_power", "per W of capacity"),
    "pipe": ("money_per_length", "per metre"),
    "thermal_storage": ("money_per_volume", "per m3"),
    "ice_storage": ("money_per_volume", "per m3"),
    "degasser": ("money", "fixed amount"),
    "flare": ("money", "fixed amount"),
    "gas_makeup": ("money", "fixed amount"),
}
"""Every equipment kind: ``{kind: (quantity of its capex factor, cost basis)}``.

The keys of ``assumptions.finance.capex`` and ``assumptions.finance.opex.fixed``. A module that is
equipment declares one of these kinds."""

GAS_SPECIES = ("CH4", "CO2", "N2", "H2S")
"""The species of ``environment.fluid.gas``, and of the keys of ``assumptions.emissions``."""
