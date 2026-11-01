"""Annotated physical quantities: validation bounds and machine-readable SI dimensions."""

from typing import Annotated, Any

from pydantic import Field

from gemini import units


def quantity(name: str, unit: str, **bounds) -> Any:
    """Return Pydantic metadata describing a physical quantity and its bounds."""
    units.define_quantity(name, unit)
    extra = {"quantity": name, "unit": unit}
    return Field(json_schema_extra=extra, **bounds)


Pressure = Annotated[float, quantity("pressure", "Pa", ge=0)]
PressureDifference = Annotated[float, quantity("pressure_difference", "Pa")]
Temperature = Annotated[float, quantity("temperature", "K", gt=0)]
TemperatureDifference = Annotated[float, quantity("temperature_difference", "K")]
MassFlow = Annotated[float, quantity("mass_flow", "kg/s")]
VolumeFlow = Annotated[float, quantity("volume_flow", "m3/s")]
Power = Annotated[float, quantity("power", "W")]
Electricity = Annotated[float, quantity("electricity", "W")]
Fuel = Annotated[float, quantity("fuel", "W")]
HeatAccumulation = Annotated[float, quantity("heat_accumulation", "W")]
Duty = Annotated[float, quantity("duty", "W")]
HydraulicPower = Annotated[float, quantity("hydraulic_power", "W")]
Energy = Annotated[float, quantity("energy", "J")]
Length = Annotated[float, quantity("length", "m", ge=0)]
Elevation = Annotated[float, quantity("elevation", "m")]
Speed = Annotated[float, quantity("speed", "m/s")]
Mass = Annotated[float, quantity("mass", "kg", ge=0)]
Area = Annotated[float, quantity("area", "m2", ge=0)]
Volume = Annotated[float, quantity("volume", "m3", ge=0)]
Angle = Annotated[float, quantity("angle", "rad")]
Density = Annotated[float, quantity("density", "kg/m3", gt=0)]
MassConcentration = Annotated[float, quantity("mass_concentration", "kg/m3", ge=0)]
Viscosity = Annotated[float, quantity("viscosity", "Pa.s", gt=0)]
SpecificHeat = Annotated[float, quantity("specific_heat", "J/kg/K", gt=0)]
SpecificEnthalpy = Annotated[float, quantity("specific_enthalpy", "J/kg")]
HeatCapacity = Annotated[float, quantity("heat_capacity", "J/K", gt=0)]
VolumetricHeatCapacity = Annotated[float, quantity("volumetric_heat_capacity", "J/m3/K", gt=0)]
ThermalDiffusivity = Annotated[float, quantity("thermal_diffusivity", "m2/s", gt=0)]
LinearPower = Annotated[float, quantity("linear_power", "W/m")]
ThermalConductivity = Annotated[float, quantity("thermal_conductivity", "W/m/K", gt=0)]
LinearThermalResistance = Annotated[float, quantity("linear_thermal_resistance", "m.K/W", gt=0)]
TemperatureGradient = Annotated[float, quantity("temperature_gradient", "K/m")]
HeatTransferCoefficient = Annotated[float, quantity("heat_transfer_coefficient", "W/m2/K", ge=0)]
ThermalConductance = Annotated[float, quantity("thermal_conductance", "W/K", ge=0)]
Permeability = Annotated[float, quantity("permeability", "m2", gt=0)]
ProductivityIndex = Annotated[float, quantity("productivity_index", "m3/s/Pa", gt=0)]
FlowCoefficient = Annotated[float, quantity("flow_coefficient", "m3/s/Pa^0.5", ge=0)]
Frequency = Annotated[float, quantity("frequency", "Hz", gt=0)]
Duration = Annotated[float, quantity("duration", "s", ge=0)]
Fraction = Annotated[float, quantity("fraction", "-", ge=0, le=1)]
Efficiency = Annotated[float, quantity("efficiency", "-", gt=0, le=1)]
Ratio = Annotated[float, quantity("ratio", "-", ge=0)]
Dimensionless = Annotated[float, quantity("dimensionless", "-")]
GasLiquidRatio = Annotated[float, quantity("gas_liquid_ratio", "-", ge=0)]
CorrosionRate = Annotated[float, quantity("corrosion_rate", "m/s", ge=0)]
Money = Annotated[float, quantity("money", "currency")]
AnnualMoney = Annotated[float, quantity("annual_money", "currency/yr")]
MoneyPerEnergy = Annotated[float, quantity("money_per_energy", "currency/J")]
MoneyRate = Annotated[float, quantity("money_rate", "currency/s")]
MoneyPerMass = Annotated[float, quantity("money_per_mass", "currency/kg", ge=0)]
MoneyPerPower = Annotated[float, quantity("money_per_power", "currency/W", ge=0)]
MoneyPerLength = Annotated[float, quantity("money_per_length", "currency/m", ge=0)]
MoneyPerConductance = Annotated[float, quantity("money_per_conductance", "currency/(W/K)", ge=0)]
MoneyPerVolume = Annotated[float, quantity("money_per_volume", "currency/m3", ge=0)]
MassPerEnergy = Annotated[float, quantity("mass_per_energy", "kg/J", ge=0)]
AnnualEnergy = Annotated[float, quantity("annual_energy", "J/yr", ge=0)]
AnnualRate = Annotated[float, quantity("annual_rate", "1/yr", ge=0)]
Count = Annotated[int, quantity("count", "-", gt=0)]
