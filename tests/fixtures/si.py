"""Wrap SI numbers into quantities through the public API, for tests that hold values in SI.

A public boundary takes a ``gm.units.Quantity`` for every value with a dimension. A test that
builds its values in a dict, or computes them, passes them here and gets the dict the boundary
takes, each value in the SI unit of its declaration, so the numbers are unchanged.
"""

from gemini.errors import ValidationError
from gemini.types import bare
from gemini.units import Quantity

STREAM = {"m_dot": "kg/s", "T": "K", "p": "Pa", "flow": "m3/s"}
FLUID = {
    "density": "kg/m3",
    "viscosity": "Pa.s",
    "specific_heat": "J/kg/K",
    "thermal_conductivity": "W/m/K",
}


def _wrapped(value, unit):
    return Quantity(value, unit) if unit not in (None, "-") and bare.is_bare(value) else value


def params(module, values, path=""):
    """Return ``values`` of the parameters of ``module`` at ``path``, bare numbers as quantities."""
    declared = dict(module.get_submodule(path).named_parameters())
    unknown = [name for name in values if name not in declared]
    if unknown:
        raise ValidationError(f"si.params: unknown parameter {unknown[0]!r}", code="unknown_name")
    return {name: _wrapped(value, declared[name].unit) for name, value in values.items()}


def inputs(plant, values):
    """Return ``values`` of the inputs of ``plant`` with each bare number a quantity."""
    declared = plant.inputs()
    return {
        name: _wrapped(value, declared[name].unit if name in declared else None)
        for name, value in values.items()
    }


def stream(**fields):
    """Return the keyword fields of a ``Stream`` with each bare number a quantity."""
    return {name: _wrapped(value, STREAM.get(name)) for name, value in fields.items()}


def fluid(**fields):
    """Return the keyword fields of a ``Fluid`` with each bare number a quantity."""
    return {name: _wrapped(value, FLUID.get(name)) for name, value in fields.items()}


def set_params(module, path, values, valid_from=None):
    """Call ``module.set_params`` with ``values`` wrapped as ``params`` does; return the module."""
    return module.set_params(path, params(module, values, path), valid_from)


def add(plant, type, name=None, values=None):
    """Call ``plant.add`` with ``values`` wrapped as ``params`` does for a module of ``type``."""
    from gemini.plants._utils.factory import make_module

    probe, _ = make_module(type)
    return plant.add(type, name, params(probe, values or {}))
