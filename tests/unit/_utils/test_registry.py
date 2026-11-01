"""One registry of module and plant types."""

import importlib.util
import inspect
from pathlib import Path

import pytest

import gemini as gm
from gemini._utils import registry
from gemini.errors import ValidationError
from gemini.modules.module import Module
from tests.fixtures.errors import raises


def test_every_registered_type_has_a_listed_category():
    """A name per module, a category from the fixed list."""
    assert "ESP" in gm.modules.names("pumps") and "ESP" not in gm.modules.names("heating")
    for name in gm.modules.names():
        assert registry.category(name) in gm.modules.categories()


def test_every_registered_type_has_the_category_of_its_folder():
    """A category is the folder of the class."""
    for name in gm.modules.names():
        item = gm.modules.get(name)
        cls = item if isinstance(item, type) else type(item)
        folder = Path(inspect.getfile(cls)).parent.name
        assert registry.category(name) == folder, name


def test_the_folders_are_the_categories_and_none_is_empty():
    """Every category has its folder and at least one module, and no folder is left over."""
    package = Path(registry.__file__).parents[1] / "modules"
    folders = {path.parent.name for path in package.glob("[!_]*/__init__.py")}
    assert folders | {"plants"} == set(gm.modules.categories())
    assert all(gm.modules.names(category) for category in gm.modules.categories())


def _subclasses(cls):
    for item in cls.__subclasses__():
        yield item
        yield from _subclasses(item)


def test_no_shipped_class_states_a_category():
    """The folder is the only source, so a class and its folder can never disagree."""
    shipped = [item for item in _subclasses(Module) if item.__module__.startswith("gemini.")]
    assert gm.modules.ESP in shipped
    assert [item for item in shipped if "category" in vars(item)] == []


@pytest.mark.parametrize(
    "name,category",
    [
        ("PIDController", "control"),
        ("FlashTurbine", "power"),
        ("ORC", "power"),
        ("Separator", "power"),
        ("AquiferStorage", "storage"),
        ("ProductionWell", "wells"),
        ("Cooler", "exchangers"),
        ("ElectricityGrid", "grids"),
        ("GasMakeup", "piping"),
        ("CHP", "heating"),
        ("AdsorptionChiller", "cooling"),
        ("Doublet", "plants"),
        ("ATESPlant", "plants"),
    ],
)
def test_the_category_of_a_module(name, category):
    """The modules that used to sit under a neighbouring category, and the plants."""
    assert registry.category(name) == category


def test_every_shipped_equipment_class_is_registered():
    """Nothing exported by ``gm.modules`` is missing from the catalogue."""
    exported = [getattr(gm.modules, name) for name in gm.modules.__all__]
    classes = [item for item in exported if isinstance(item, type) and issubclass(item, Module)]
    missing = [
        item.__name__
        for item in classes
        if item.category is not None and item.__name__ not in gm.modules.names()
    ]
    assert missing == []


def test_get_returns_the_class():
    """A module name gives its class."""
    assert gm.modules.get("ESP") is gm.modules.ESP


def test_an_unknown_name_suggests_close_ones():
    """The error carries the close names as data, for tool results."""
    with raises(ValidationError, "unknown_name", match="did you mean 'Boiler'") as caught:
        gm.modules.get("Boilr")
    assert caught.value.to_dict()["suggestions"] == ["Boiler"]


def test_an_unknown_category_is_refused():
    """Only the fixed categories exist."""
    with pytest.raises(ValidationError, match="expected one of"):
        gm.modules.names("pump")


def test_a_class_needs_a_listed_category():
    """A module without a category cannot join the catalogue."""

    class NoCategory(Module):
        """Module without a category."""

    with pytest.raises(ValidationError, match="NoCategory.category"):
        registry.register(NoCategory)


def test_a_class_from_outside_states_its_own_category():
    """A subclass of a shipped class has no folder, so it does not inherit one."""

    class Mine(gm.modules.ESP):
        """Subclass that states nothing."""

    assert Mine.category is None and Mine().category is None
    with pytest.raises(ValidationError, match="Mine.category"):
        registry.register(Mine)


def test_a_taken_name_is_refused(monkeypatch):
    """Two classes never share a name; the same class registers twice without harm."""
    monkeypatch.setattr(registry, "_entries", dict(registry._entries))
    with raises(ValidationError, "duplicate_name", match="takes the name 'ESP'"):

        class ESP(Module):
            """Second class of a taken name."""

            category = "pumps"

    registry.register(gm.modules.ESP)
    assert gm.modules.get("ESP") is gm.modules.ESP


def test_an_abstract_class_is_left_out_and_its_subclass_joins(monkeypatch):
    """``abstract`` speaks for the class that says it, never for a subclass."""
    monkeypatch.setattr(registry, "_entries", dict(registry._entries))

    class Base(Module):
        """A base class of a family."""

        category = "pumps"
        abstract = True

    class Member(Base):
        """A member of the family."""

    assert "Base" not in gm.modules.names() and "Member" in gm.modules.names("pumps")


def test_a_plant_is_a_class_in_the_registry():
    """A plant class joins the registry as any module does."""
    assert "Doublet" in gm.modules.names("plants")
    assert gm.modules.get("Doublet") is gm.plants.Doublet


def test_importing_a_file_registers_the_classes_that_state_a_category(monkeypatch, tmp_path):
    """A class joins the catalogue by being defined; a plant dict can then name it."""
    monkeypatch.setattr(registry, "_entries", dict(registry._entries))
    file = tmp_path / "user_module.py"
    file.write_text(
        "from tests.fixtures.booster_module import Booster\n\n\n"
        "class Lifter(Booster):\n"
        '    """A booster from outside."""\n\n'
        '    category = "pumps"\n'
    )
    spec = importlib.util.spec_from_file_location("user_module", file)
    spec.loader.exec_module(importlib.util.module_from_spec(spec))
    assert "Lifter" in gm.modules.names("pumps")
    result = gm.call(
        "Lifter",
        {},
        {
            "fluid_in": {
                "m_dot": gm.units.Quantity(10, "kg/s"),
                "T": gm.units.Quantity(300, "K"),
                "p": gm.units.Quantity(2e5, "Pa"),
            }
        },
        {},
    )
    assert result["outlets"]["fluid_out"]["p"]["value"] == pytest.approx(3e5)


def test_public_register_and_load_file_are_gone():
    """A class registers itself."""
    assert not hasattr(gm.modules, "register") and not hasattr(gm.modules, "load_file")
