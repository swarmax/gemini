"""The plant catalogue: which plants exist and how to get one."""

from gemini._utils import paths, registry
from gemini._utils.files import from_json
from gemini._utils.strings import close_matches, did_you_mean, join_names
from gemini.errors import NotImplementedYet, ValidationError
from gemini.modules._utils.serialization import Report, from_sections
from gemini.plants._utils import reader
from gemini.plants.plant import Plant

PURPOSES = ("heating", "cooling", "both")
"""What a plant serves, the ``category`` of ``names``."""


def names(category=None):
    """Return the names of the plant classes, sorted; ``category`` is what they serve.

    ``heating``, ``cooling`` or ``both``: the plants that serve that, the other plants being
    building blocks.
    """
    found = registry.names("plants")
    if category is None:
        return found
    if category not in PURPOSES:
        raise ValidationError(
            f"plants.names: category = {category!r}; expected one of {join_names(PURPOSES)}"
            f"{did_you_mean(category, PURPOSES)}",
            path=str(category),
            suggestions=close_matches(category, PURPOSES),
            code="unknown_name",
        )
    return [name for name in found if registry.get(name).purpose == category]


def _check(function, name):
    valid = names()
    if name not in valid:
        raise ValidationError(
            f"plants.{function}: unknown plant {name!r}; valid: {join_names(valid)}"
            f"{did_you_mean(name, valid)}",
            path=name,
            suggestions=close_matches(name, valid),
            code="unknown_name",
        )


def get(name):
    """Return a new plant of class ``name`` whose parameters are not set.

    An unknown name, or the name of a module that is not a plant, raises ``ValidationError`` with
    close matches in ``suggestions``.
    """
    _check("get", name)
    return registry.get(name)()


def example(name):
    """Return a new plant ``name`` with real parameter values.

    The plant comes from its class; ``inputs/plants/<name>.json`` of a source checkout gives its
    ``size``, ``params`` and any ``fluids``, ``boundary``, ``bindings``, ``param_history`` and
    ``inputs``, under the keys of a plant dict. ``Doublet`` and ``DoubletHeatPlant`` carry the
    values of the measured doublet, and the other plants the values their unit tests use, the
    design parameters only: controls and boundaries are inputs of a run. A template plant has no
    values of its own, a design is its plant dict (``gm.Plant.from_dict``). A registered plant
    without a file raises ``NotImplementedYet`` naming it, and without ``inputs/`` this raises
    ``inputs_missing``.
    """
    _check("example", name)
    path = paths.plant_values(name)
    if not path.exists():
        raise NotImplementedYet(f"plants.example: {name!r} has no sourced parameter values yet")
    values = from_json(path)
    plant = registry.get(name)(**values.get("size", {}))
    plant.set_params("", values["params"])
    from_sections(plant, values, Report(strict=True))
    reader.set_sections(plant, values)
    plant._stated[""] = {}
    return plant.set_inputs(values.get("inputs", {}))


def validate(data, on_error="raise"):
    """Check a plant dict and return ``[]``, or raise one ``ValidationError`` with every problem.

    With ``on_error="record"`` nothing is raised and the problems are returned, each
    ``{path, code, message, suggestions}``: the list the error carries in ``problems``. ``path``
    points into the dict, for example ``connections[1].target``.
    """
    return reader.check(Plant, data, on_error)
