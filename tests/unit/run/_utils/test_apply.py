"""The values of a case reach the modules of a plant by class, on a copy."""

import pytest

import gemini as gm
from gemini.run._utils.apply import apply_case
from gemini.units import Quantity
from tests.fixtures.errors import raises
from tests.fixtures.sample_cases import sample_case, template_dict


def sample_plant():
    """Return the sample design without any value of the case."""
    return gm.Plant.from_dict(template_dict("HeatingCoolingPlant"))


def with_environment(case, **sections):
    """Return ``case`` with parts of its environment replaced (SI values)."""
    parts = {name: getattr(case.environment, name) for name in ("ground", "reservoir", "fluid")}
    updated = {
        name: parts[name].model_copy(update=values) if name in parts else values
        for name, values in sections.items()
    }
    environment = case.environment.model_copy(update=updated)
    return case.model_copy(update={"environment": environment})


def test_the_plant_of_the_user_never_changes():
    """The values are set on a copy."""
    plant = sample_plant()
    before = plant.state_dict()
    applied = apply_case(plant, sample_case())
    assert plant.state_dict() == before and applied is not plant
    assert plant.d0.gradient is None and applied.d0.gradient == pytest.approx(0.03)


def test_the_ground_and_the_reservoir_reach_every_doublet_at_its_depth():
    """Temperature and pressure are the rules of the case at the depth of the doublet."""
    case = sample_case()
    plant = sample_plant()
    plant.set_params("", {"depth": Quantity(3000, "m")})
    applied = apply_case(plant, case)
    for doublet in (applied.d0, applied.d1):
        assert doublet.reservoir.temperature == pytest.approx(case.environment.temperature_at(3000))
        assert doublet.sink.pressure == pytest.approx(case.environment.pressure_at(3000))
        assert doublet.reservoir.permeability == case.environment.reservoir.permeability


def test_the_brine_of_the_case_is_the_fluid_of_every_doublet_module():
    """Density, viscosity and the dissolved gas of ``environment.fluid``."""
    applied = apply_case(sample_plant(), sample_case())
    fluid = applied.d1.well.fluid
    assert fluid.density == 1030.0 and fluid.gas_liquid_ratio == 0.8
    assert fluid.gas_composition == {"CH4": 0.8, "CO2": 0.2}


def test_the_same_plant_on_two_reservoirs_gives_two_production_temperatures():
    """Only the case differs."""
    plant = sample_plant()
    hot = apply_case(plant, with_environment(sample_case(), ground={"gradient": 0.04}))
    cold = apply_case(plant, sample_case())
    assert hot.d0.reservoir.temperature > cold.d0.reservoir.temperature


def test_a_given_reservoir_temperature_anchors_the_geotherm():
    """The measured temperature at the reference depth is shifted by the gradient."""
    case = with_environment(sample_case(), reservoir={"temperature": 350.0})
    applied = apply_case(sample_plant(), case)
    assert applied.d0.reservoir.temperature == pytest.approx(350.0)


def test_the_air_is_an_input_of_every_atmosphere_and_a_profile_waits_for_the_plan():
    """A constant is set on the copy; a profile is no input."""
    applied = apply_case(sample_plant(), sample_case())
    assert applied.input_value("atmosphere.temperature") == pytest.approx(283.15)
    assert sample_plant().input_value("atmosphere.temperature") is None


def test_the_return_and_the_required_supply_reach_the_consumers():
    """Heating asks a minimum supply, cooling a maximum; both return temperatures are set."""
    applied = apply_case(sample_plant(), sample_case())
    assert applied.heating_consumer.return_temperature == pytest.approx(333.15)
    assert applied.heating_consumer.minimum_supply_temperature == pytest.approx(373.15)
    assert applied.cooling_consumer.return_temperature == pytest.approx(298.15)
    assert applied.cooling_consumer.maximum_supply_temperature == pytest.approx(293.15)


def test_a_formation_outside_a_doublet_gets_the_ground():
    """``Formation`` takes the gradient and the surface temperature."""
    plant = gm.plants.NodalDoublet()
    applied = apply_case(plant, sample_case())
    assert applied.formation.geothermal_gradient == pytest.approx(0.03)
    assert applied.formation.surface_temperature == pytest.approx(285.15)


def test_a_value_the_plant_needs_and_the_case_lacks_is_named_by_its_path():
    """A plant without its environment raises ``missing_value`` naming the path in the case."""
    case = sample_case().model_copy(update={"environment": None})
    with raises(gm.errors.ValidationError, "missing_value") as caught:
        apply_case(sample_plant(), case)
    assert caught.value.path == "environment.fluid.density"
    case = with_environment(sample_case(), ground={"gradient": None})
    with raises(gm.errors.ValidationError, "missing_value") as caught:
        apply_case(sample_plant(), case)
    assert caught.value.path == "environment.ground.gradient"
