"""A doublet designed from its depth: the child values its design gives."""

from gemini import ops
from gemini.physics import geometry, ground, hydraulics, pumps

COLUMN = ("depth", "gradient", "surface_temperature")
"""The design values of the water column and the geotherm."""

FLOW_PATH = ("permeability", "thickness", "well_diameter")
"""The design values of the wells and the reservoir flow."""

PUMP = ("nominal_flow", "pump_efficiency", "nominal_wellhead_pressure")
"""The design values of the pump."""

RESERVOIRS = ("reservoir", "sink")
"""The children of a doublet that are reservoirs."""

WELLS = ("well", "riser", "injector")
"""The children of a doublet that are wells."""


def _given(values, names):
    return all(values[name] is not None for name in names)


@ops.physics
def design(values, density, viscosity, skins, pressure=None):
    """Return the child values of a doublet that its design ``values`` give, by dotted name.

    A group of values that is not complete derives nothing: the column needs ``COLUMN``, the flow
    paths ``FLOW_PATH`` as well and the pump ``PUMP`` as well. ``skins`` are the skin factors of
    ``RESERVOIRS`` and ``pressure`` [Pa] a reservoir pressure stated by hand, which the pump is
    then sized against instead of the hydrostatic one.
    """
    if not _given(values, COLUMN):
        return {}
    derived = _column(values, density)
    if not _given(values, FLOW_PATH):
        return derived
    derived |= _flow_paths(values, viscosity, skins)
    if not _given(values, PUMP):
        return derived
    reservoir = derived["reservoir.pressure"] if pressure is None else pressure
    return derived | _pump(values, density, viscosity, reservoir, derived)


def _column(values, density):
    """Return the values that follow from the depth, the geotherm and the fluid density."""
    depth, gradient, surface = values["depth"], values["gradient"], values["surface_temperature"]
    temperature = ground.geotherm_temperature(surface, gradient, depth)
    mean = ground.geotherm_temperature(surface, gradient, depth / 2)
    derived = {f"{well}.soil_temperature": mean for well in WELLS}
    derived["formation.geothermal_gradient"] = gradient
    derived["formation.surface_temperature"] = surface
    for name in RESERVOIRS:
        derived[f"{name}.temperature"] = temperature
        derived[f"{name}.pressure"] = hydraulics.hydrostatic_pressure(density, depth)
    return derived


def _flow_paths(values, viscosity, skins):
    """Return the values that follow from the permeability, thickness and well diameter."""
    radius = values["well_diameter"] / 2
    path = geometry.section_values(
        geometry.vertical_path(
            values["depth"], values["well_diameter"], hydraulics.COMMERCIAL_STEEL_ROUGHNESS
        )
    )
    derived = {f"{well}.{name}": value for well in WELLS for name, value in path.items()}
    for name in RESERVOIRS:
        derived[f"{name}.permeability"] = values["permeability"]
        derived[f"{name}.aquifer_thickness"] = values["thickness"]
        derived[f"{name}.top_depth"] = values["depth"] - values["thickness"] / 2
        derived[f"{name}.drainage_radius"] = values["drainage_radius"]
        derived[f"{name}.wellbore_radius"] = radius
    index = {
        name: hydraulics.radial_index(
            viscosity,
            values["permeability"],
            values["thickness"],
            values["drainage_radius"],
            radius,
            skins[name],
        )
        for name in RESERVOIRS
    }
    derived["reservoir.productivity_index"] = index["reservoir"]
    derived["sink.injectivity_index"] = index["sink"]
    return derived


def _pump(values, density, viscosity, pressure, derived):
    """Return the pump setting depth and the curves of a pump sized at the nominal flow."""
    flow, wellhead = values["nominal_flow"], values["nominal_wellhead_pressure"]
    drawdown = hydraulics.productivity_pressure(0.0, -flow, derived["reservoir.productivity_index"])
    setting = hydraulics.pump_setting_depth(values["depth"], pressure, drawdown, wellhead, density)
    head = hydraulics.design_pump_head(
        wellhead,
        pressure,
        drawdown,
        density,
        viscosity,
        values["depth"],
        values["well_diameter"],
        hydraulics.COMMERCIAL_STEEL_ROUGHNESS,
        flow,
    )
    head_curve, power_curve = pumps.constant_head_curves(head, values["pump_efficiency"])
    return {
        "esp.stage_count": 1,
        "esp.head_coefficients": head_curve,
        "esp.power_coefficients": power_curve,
        "esp.setting_depth": setting,
        "well.esp_depth": setting,
        "well.segment": "below_esp",
        "riser.esp_depth": setting,
        "riser.segment": "above_esp",
    }
