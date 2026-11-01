"""Equipment modules: declarations and children registered in ``__init__``, called with inlets.

A module registers what ``__init__`` assigns: ``Parameter``, ``Inlet``, ``Control``, ``Boundary``,
``State``, ``Output`` and ``Outlet`` declarations go to ordered registries and ``Module`` values
become children with dotted paths. Calling a module validates the inlets, applies controls and
boundaries, runs the forward pre-hooks, ``forward``, which assigns the outputs of a leaf, the
composite output formulas and the forward hooks, then returns a ``ModuleResult``.

The values of one call (resolved controls and boundaries, recorded outputs and the results of
child calls) live in a ``_Call`` record held in the ``_current_call`` context variable while the
call runs; it is the only per-call state. During ``Module.step`` every call record also carries
the ``_Step`` record with the time step and the state trees. ``no_outputs()`` is the only other
context setting.
"""

import importlib
import inspect
from collections.abc import Mapping
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass, field
from functools import partial
from itertools import repeat

import numpy as np
from pydantic_core import to_jsonable_python

from gemini import ops, runtime, units
from gemini._utils.context import ContextSetting
from gemini._utils.hooks import RemovableHandle, has_signature
from gemini._utils.mappings import get_nested, set_nested
from gemini._utils.registry import register
from gemini._utils.strings import (
    close_matches,
    did_you_mean,
    first_paragraph,
    join_names,
    join_path,
    snake_case,
    split_path,
)
from gemini.errors import DefinitionError, PhysicsError, ValidationError
from gemini.errors.lookup import UnknownMember
from gemini.modules._utils import description, design
from gemini.modules.declarations import (
    UNSET,
    Boundary,
    Control,
    Declaration,
    Inlet,
    Outlet,
    Output,
    Parameter,
    State,
)
from gemini.ops import kernels
from gemini.types.bindings import DatedParams
from gemini.types.flows import Stream
from gemini.types.fluid import Fluid
from gemini.types.ports import Ports
from gemini.types.results import ModuleResult

_current_call = ContextVar("module_call", default=None)
_outputs_enabled = ContextVar("module_outputs_enabled", default=True)
_in_trial = ContextVar("module_in_trial", default=False)
_FIELD_DISPLAY_UNITS = {"Pa": "bar", "K": "°C", "m3/s": "m3/h", "W": "kW"}
_REGISTRIES = (
    (Parameter, "_parameters"),
    (Inlet, "_inlets"),
    (Control, "_controls"),
    (Boundary, "_boundaries"),
    (State, "_states"),
    (Output, "_outputs"),
    (Outlet, "_outlets"),
)


def _describe_unknown_member(name, module):
    """Name the module path and the closest child, declaration or port for a missing attribute.

    Reads only the instance dictionary, so it also works before ``super().__init__()``.
    """
    registries = module.__dict__
    candidates = list(registries.get("_children", ()))
    for _, registry in _REGISTRIES:
        candidates.extend(registries.get(registry, ()))
    path = registries.get("_path") or module.name
    return f"{path}: unknown member {name!r}{did_you_mean(name, candidates)}"


def no_outputs():
    """Skip output computation and hooks within a nestable context or decorator."""
    return ContextSetting(_outputs_enabled, lambda current: False)


def outputs_enabled():
    """Return whether the current context records computed outputs."""
    return _outputs_enabled.get()


def class_path(cls):
    """Return the ``module:qualname`` path that plant files and checkpoints store for a class.

    Together with ``import_class`` this is the only import-by-string in GEMINI: a saved plant or
    checkpoint must name the handwritten plant class that rebuilds its module tree.
    """
    return f"{cls.__module__}:{cls.__qualname__}"


def import_class(path):
    """Import the ``Module`` subclass named by a ``class_path`` string."""
    module_name, qualname = path.split(":", 1)
    value = importlib.import_module(module_name)
    for part in qualname.split("."):
        value = getattr(value, part)
    if not isinstance(value, type) or not issubclass(value, Module):
        raise ValidationError(f"Serialized class {path!r} is not a Module", code="invalid_format")
    return value


@dataclass
class _Step:
    """Time step and state trees of one ``Module.step`` in progress.

    ``states`` holds the states at the start of the step and ``next_states`` the states at its
    end, both nested by child name below the stepped module ``root``. ``next_states`` starts as a
    copy of ``states``, so a stateful module that is not called keeps its state.
    """

    root: "Module"
    dt: float
    states: dict
    next_states: dict
    advanced: set = field(default_factory=set)

    def start(self, keys):
        """Return the start-of-step states of the module at ``keys``, or an empty mapping."""
        return deepcopy(get_nested(self.states, keys, None) or {})

    def advance(self, keys, values):
        """Record the end-of-step states of the module at ``keys``; each module advances once."""
        if keys in self.advanced:
            path = ".".join(keys) or self.root.path
            raise ValidationError(
                f"{path}: stateful module called more than once in one step", code="invalid_design"
            )
        self.advanced.add(keys)
        if not keys:
            self.next_states = values
            return
        set_nested(self.next_states, keys, values)


class _ScalarParameters(dict):
    """Parameter values of an eager call as the scope gives them, wrapped on first read."""

    def __init__(self, module):
        """Read parameters of ``module``."""
        super().__init__()
        self._module = module

    def __missing__(self, name):
        """Return the stored value of parameter ``name`` wrapped, and keep it for this call."""
        value = self[name] = ops.scope.wrap(self._module._parameter_value(name))
        return value


def _holds_array(value):
    """Return whether a port value holds an array over rows; a 0-d array is a scalar."""
    if isinstance(value, list):
        return any(_holds_array(item) for item in value)
    if isinstance(value, Stream):
        return any(_holds_array(item) for item in (value.m_dot, value.T, value.p))
    return isinstance(value, np.ndarray) and bool(value.ndim)


def _has_arrays(inlets, inputs):
    """Return whether a call holds arrays over rows, which leaves its scope unwrapped.

    A 0-d array is a scalar: ops give one under a forced NumPy backend.
    """
    return any(_holds_array(value) for value in (*inlets.values(), *inputs.values()))


def _numpy_value(value):
    """Return a port value for the eager scope: a stream's fields or a power as ``np.float64``."""
    if isinstance(value, list):
        return [_numpy_value(item) for item in value]
    return value._numpy() if isinstance(value, Stream) else ops.scope.wrap(value)


def _numpy_ports(inlets):
    """Return ``inlets`` with stream fields and powers as ``np.float64`` for the eager scope."""
    return Ports._trusted(
        {name: _numpy_value(value) for name, value in inlets.items()}, inlets._path
    )


def _read(call, value):
    """Return a recorded output as the call's physics sees it: wrapped in a wrapping call."""
    if not call.wrapping:
        return value
    return np.float64(value) if type(value) is float else ops.scope.wrap(value)


def _restored(returned, scoped, inlets):
    """Return the outlets of ``forward`` with a passed-through scoped inlet restored."""
    if scoped is inlets or not isinstance(returned, dict):
        return returned
    originals = {id(scoped[name]): inlets[name] for name in inlets}
    return {name: originals.get(id(value), value) for name, value in returned.items()}


def _scalar_output(declaration, value):
    """Return an output of a forced backend: a 0-d NaN is the ``None`` of ``X | None``."""
    is_scalar_array = isinstance(value, np.ndarray) and not value.ndim
    if is_scalar_array and declaration.accepts_none() and value != value:
        return None
    return value


def _row_output(declaration, item):
    """Return one row of an array output: a NaN is the ``None`` of ``X | None``."""
    if isinstance(item, float) and item != item and declaration.accepts_none():
        return None
    return item


def _is_column(item):
    """Return whether ``item`` is an array of rows."""
    return isinstance(item, np.ndarray) and item.ndim > 0


def _output_rows(value):
    """Return the rows of an array output (a column's values once) or of a list holding arrays.

    A call that made one row returns ``None``.
    """
    if not isinstance(value, list):
        if not _is_column(value):
            return None
        rows = value.tolist()
        return list(dict.fromkeys(rows)) if value.ndim == 1 else rows
    if not any(_is_column(item) for item in value):
        return None
    columns = [item.tolist() if _is_column(item) else repeat(item) for item in value]
    return [list(row) for row in zip(*columns)]


def _plain_outlet(value):
    """Return an outlet value with plain scalars; a ``Failed`` field raises its error."""
    if isinstance(value, list):
        return [_plain_outlet(item) for item in value]
    return value._plain() if isinstance(value, Stream) else ops.scope.plain(value)


@dataclass
class _Call:
    """Values of one module call in progress.

    ``outputs`` holds what ``forward`` assigned, so it can read an output back. ``recording`` is
    false when outputs are disabled: the values are not validated and the result drops them.
    ``call_records`` collects the results of every child call made during this call, in call
    order. ``parent`` is the enclosing call.
    ``states`` holds the module's own state values and ``step`` the running ``_Step``, if any.
    A traced call (a call of the compiler) sets ``parameters`` to the traced parameter values
    that replace the stored ones, and records outputs without validating them. ``trace`` is the
    running trace of the compiler: a call made while it is set is recorded through
    ``trace.child`` instead of being evaluated. ``wrapping`` marks an eager call whose
    physics gets NumPy scalars (``gemini.ops.scope``).
    """

    module: "Module"
    inputs: dict
    outputs: dict
    parent: "_Call | None"
    recording: bool = True
    states: dict | None = None
    step: _Step | None = None
    call_records: list = field(default_factory=list)
    parameters: dict | None = None
    trace: object | None = None
    wrapping: bool = False
    drawn: dict = field(default_factory=dict)

    def kept_outputs(self):
        """Return the outputs the result of this call holds."""
        return self.outputs if self.recording or _in_trial.get() else {}

    def owned_by(self, module):
        """Return the innermost call of ``module`` in this chain, or ``None``."""
        call = self
        while call is not None and call.module is not module:
            call = call.parent
        return call


def _active_call(module):
    """Return the running call of ``module``, or ``None`` outside its calls."""
    current = _current_call.get()
    return current.owned_by(module) if current is not None else None


class _FolderCategory:
    """The ``category`` of a class: the folder of the package that holds its file.

    ``gemini/modules/pumps/esp.py`` gives ``pumps`` and ``gemini/plants/doublet.py`` gives
    ``plants``, so a shipped class never declares it. A class from outside has no such folder and
    is ``None`` until it assigns ``category`` itself, which replaces this descriptor; a subclass of
    a shipped class states its own too.
    """

    def __get__(self, instance, owner):
        """Return the folder of ``owner``, or ``None`` for a file outside the folders."""
        if owner.__module__.startswith("gemini.plants."):
            return "plants"
        if not owner.__module__.startswith(f"{__package__}."):
            return None
        folder, _, file = owner.__module__.removeprefix(f"{__package__}.").partition(".")
        return folder if file and not folder.startswith("_") else None


class Module:
    """Base class discovering declarations and child modules assigned in ``__init__``.

    Subclasses call ``super().__init__()`` first, then assign declarations and children in the
    documented section order. ``name`` is the snake_case class name; ``path`` is the dotted
    position in the tree, or the name for a standalone module; ``category`` is the folder of the
    class.
    """

    repr_fields = ()
    offer_inlets = ()
    _derived_params = frozenset()
    category = _FolderCategory()
    abstract = True

    def __init_subclass__(cls, **kwargs):
        """Register a class that has a category, unless its own body says ``abstract = True``."""
        super().__init_subclass__(**kwargs)
        if cls.category is not None and not cls.__dict__.get("abstract", False):
            register(cls)

    def __init__(self):
        """Create the ordered registries and the run-owned metadata."""
        for _, registry in _REGISTRIES:
            object.__setattr__(self, registry, {})
        object.__setattr__(self, "_children", {})
        object.__setattr__(self, "_pre_hooks", {})
        object.__setattr__(self, "_hooks", {})
        object.__setattr__(self, "_input_values", {})
        object.__setattr__(self, "_path", "")
        object.__setattr__(self, "_parent", None)
        object.__setattr__(self, "_fluid", runtime.get_default_fluid())
        object.__setattr__(self, "bindings", {})
        object.__setattr__(self, "boundary", {})
        object.__setattr__(self, "_param_history", [DatedParams(params={})])
        object.__setattr__(self, "_param_overrides", {})

    @property
    def name(self):
        """Return the snake_case class name, for example ``heat_exchanger``."""
        return snake_case(type(self).__name__)

    @property
    def _type_label(self):
        """Return the name ``repr`` shows for this module."""
        return type(self).__name__

    @property
    def path(self):
        """Return the assigned tree path or standalone derived name."""
        return self._path or self.name

    @property
    def stateful(self):
        """Whether the module declares states that ``step`` advances."""
        return bool(self._states)

    @property
    def fluid(self):
        """Return the fluid this module's streams carry."""
        return self._fluid

    @fluid.setter
    def fluid(self, value):
        """Set and validate the module fluid; ``state_dict`` saves it.

        Assignment is an author-level tool, so a mapping holds SI numbers, as ``state_dict`` saves.
        """
        self._set_own_fluid(value)

    def _set_own_fluid(self, value):
        """Set the fluid of this module alone."""
        object.__setattr__(self, "_fluid", Fluid._of(value))

    def __setattr__(self, name, value):
        """Register declarations and children, or assign declared values.

        Assigning a declared value, ``esp.frequency = 50``, is an author-level tool and stays SI:
        a number is in the SI unit of the declaration. Users set values with ``set_params``,
        ``set_inputs`` or a control of a call, which take quantities.
        """
        if name.startswith("_"):
            object.__setattr__(self, name, value)
            return
        if "_parameters" not in self.__dict__:
            if isinstance(value, (Declaration, Module)):
                raise DefinitionError(
                    f"{type(self).__name__}.__init__ must call super().__init__() before "
                    f"assigning {name!r}"
                )
            object.__setattr__(self, name, value)
            return
        if isinstance(value, Declaration):
            self._register_declaration(name, value)
        elif isinstance(value, Module):
            self._add_module(name, value)
        else:
            self._assign_value(name, value)

    def _register_declaration(self, name, declaration):
        existing = self._declarations().get(name)
        if existing is not None and existing is not declaration:
            raise DefinitionError(f"{self.path}.{name}: declaration is already registered")
        registry = next(
            getattr(self, registry)
            for kind, registry in _REGISTRIES
            if isinstance(declaration, kind)
        )
        registry[name] = declaration.bind(self, name)
        if isinstance(declaration, Parameter) and declaration.initialized:
            initial = self._param_history[0].params
            initial[name] = to_jsonable_python(deepcopy(declaration.value))

    def _descendant_path(self, module):
        """Return the dotted path of ``module`` below this one, or ``None`` outside the tree."""
        return next((path for path, item in self.named_modules() if item is module), None)

    def _assign_value(self, name, value):
        if name in self._parameters:
            self._parameters[name].owner._set_parameter(name, value)
            return
        inputs = self._controls | self._boundaries
        if name in inputs:
            self._set_input(name, inputs[name].validate(value))
            return
        if name in self._outputs:
            self._record_output(name, value)
            return
        if name in self._states:
            raise DefinitionError(f"{self.path}.{name}: a state changes only in _advance_states")
        if name in self._declarations():
            raise DefinitionError(f"{self.path}.{name}: cannot replace a declaration")
        self._children.pop(name, None)
        object.__setattr__(self, name, value)

    def _set_input(self, name, value):
        call = _active_call(self)
        target = call.inputs if call is not None else self._input_values
        target[name] = value

    def _record_output(self, name, value):
        call = _active_call(self)
        if call is None:
            raise DefinitionError(f"{self.path}.{name}: outputs may only be assigned in forward")
        if call.trace is not None or not call.recording:
            call.outputs[name] = value
            return
        declaration = self._outputs[name]
        rows = _output_rows(value)
        if rows is not None:
            for item in rows:
                declaration.validate(_row_output(declaration, item))
            call.outputs[name] = value
            return
        call.outputs[name] = declaration.validate(_scalar_output(declaration, value))

    def _add_module(self, name, module):
        """Register an immediate child and reject ambiguous names or ownership cycles."""
        if not isinstance(module, Module):
            raise DefinitionError(f"{self.path}.{name}: child must be a Module")
        if not name or "." in name or name.startswith("_"):
            raise DefinitionError(f"{self.path}: invalid child name {name!r}")
        if name in self._declarations():
            raise DefinitionError(f"{self.path}: child name {name!r} conflicts with a declaration")
        if hasattr(type(self), name):
            raise DefinitionError(f"{self.path}: child name {name!r} shadows a module attribute")
        if any(item is self for item in module.modules()):
            raise DefinitionError(f"{self.path}.{name}: module ownership cannot contain a cycle")
        self._children[name] = module
        object.__setattr__(self, name, module)
        object.__setattr__(module, "_parent", self)
        module._set_path(join_path(self._path, name))

    def _set_path(self, path):
        object.__setattr__(self, "_path", path)
        for declaration in self._declarations().values():
            declaration.bind(self, declaration.name)
        for name, child in self.named_children():
            child._set_path(join_path(path, name))

    def _declarations(self):
        result = {}
        for _, registry in _REGISTRIES:
            result.update(getattr(self, registry))
        return result

    def __getattr__(self, name):
        """Resolve parameter values, current input and output values and port declarations.

        Called only for names that are not ordinary attributes. Controls and boundaries resolve
        to the value of the running call, then the persisted value, then the declared default.
        States resolve to the value at the start of the running step, else the initial state.
        Outputs resolve to the value recorded in the running call, otherwise to their
        declaration, as do inlets and outlets.
        """
        registries = self.__dict__
        if name in registries.get("_parameters", {}):
            call = _active_call(self)
            if call is not None and call.parameters is not None:
                return call.parameters[name]
            return self._parameter_value(name)
        if name in registries.get("_controls", {}) or name in registries.get("_boundaries", {}):
            return self._input_value(name)
        if name in registries.get("_states", {}):
            call = _active_call(self)
            if call is not None and call.states is not None:
                return call.states[name]
            return self._initial_states()[name]
        if name in registries.get("_outputs", {}):
            call = _active_call(self)
            if call is not None and name in call.outputs:
                return _read(call, call.outputs[name])
            return self._outputs[name]
        for registry in ("_inlets", "_outlets"):
            if name in registries.get(registry, {}):
                return registries[registry][name]
        raise UnknownMember(name, self, _describe_unknown_member)

    def _parameter_value(self, name):
        parameter = self._parameters[name]
        if not parameter.initialized:
            root = self._root()
            raise root._missing_error(root._missing_paths())
        return parameter.value

    def _input_value(self, name):
        call = _active_call(self)
        if call is not None and name in call.inputs:
            return call.inputs[name]
        if name in self._input_values:
            return self._input_values[name]
        declaration = (self._controls | self._boundaries)[name]
        if declaration.default is not UNSET:
            return declaration.default_value()
        raise ValidationError(
            f"{declaration.path}: {declaration.section} {name!r} has no value "
            f"[{declaration.unit or '-'}]",
            code="missing_value",
        )

    def named_children(self):
        """Iterate immediate children in insertion order."""
        yield from self._children.items()

    def children(self):
        """Iterate immediate child modules."""
        yield from self._children.values()

    def named_modules(self, prefix=""):
        """Walk self and descendants once using dotted paths."""
        seen = set()

        def walk(module, path):
            if id(module) in seen:
                return
            seen.add(id(module))
            yield path, module
            for name, child in module.named_children():
                yield from walk(child, join_path(path, name))

        yield from walk(self, prefix)

    def modules(self):
        """Walk self and all unique descendants."""
        for _, module in self.named_modules():
            yield module

    def get_submodule(self, path):
        """Resolve a dotted descendant path; the empty path denotes self."""
        module = self._find_submodule(path)
        if module is None:
            raise ValidationError(
                f"{self.path}: unknown module path {path!r}"
                f"{did_you_mean(path, dict(self.named_modules()))}",
                code="unknown_name",
            )
        return module

    def _find_submodule(self, path):
        """Return the descendant at a dotted path, or ``None`` when there is none."""
        module = self
        for part in path.split(".") if path else ():
            module = module._children.get(part)
            if module is None:
                return None
        return module

    @property
    def is_leaf(self):
        """Whether this module owns no child modules."""
        return not self._children

    def _named(self, registry_name, recurse):
        for path, module in self.named_modules() if recurse else [("", self)]:
            for name, declaration in getattr(module, registry_name).items():
                yield join_path(path, name), declaration

    def _section(self, registry_name, recurse):
        return dict(self._named(registry_name, recurse))

    def parameters(self, recurse=True):
        """Iterate parameter declarations of this module and, by default, its descendants."""
        for _, parameter in self._named("_parameters", recurse):
            yield parameter

    def named_parameters(self, recurse=True):
        """Iterate ``(dotted path, parameter)`` pairs relative to this module."""
        yield from self._named("_parameters", recurse)

    def controls(self, recurse=True):
        """Return controllable input declarations by dotted path relative to this module."""
        return self._section("_controls", recurse)

    def boundaries(self, recurse=True):
        """Return external boundary declarations by dotted path relative to this module."""
        return self._section("_boundaries", recurse)

    def inputs(self, recurse=True):
        """Return controls followed by boundaries, by dotted path relative to this module."""
        return self.controls(recurse) | self.boundaries(recurse)

    def states(self, recurse=True):
        """Return state declarations by dotted path relative to this module."""
        return self._section("_states", recurse)

    def outputs(self, recurse=True):
        """Return computed output declarations by dotted path relative to this module."""
        return self._section("_outputs", recurse)

    def soft_sensors(self, recurse=True):
        """Return outputs marked as inferred measurements, by dotted path."""
        return {name: value for name, value in self.outputs(recurse).items() if value.soft_sensor}

    def inlets(self):
        """Return this module's own inlet declarations; a child's ports are internal wiring."""
        return dict(self._inlets)

    def outlets(self):
        """Return this module's own outlet declarations; a child's ports are internal wiring."""
        return dict(self._outlets)

    def get(self, path):
        """Return the declaration at a dotted path, whatever its kind."""
        module_path, name = split_path(path)
        declarations = self.get_submodule(module_path)._declarations()
        if name not in declarations:
            raise ValidationError(
                f"{self.path}: unknown name {path!r}; valid: {join_names(declarations)}"
                f"{did_you_mean(name, declarations)}",
                suggestions=close_matches(name, declarations),
                code="unknown_name",
            )
        return declarations[name]

    def _set_inputs(self, mapping):
        """Persist validated controls and boundaries addressed by relative dotted path."""
        declarations = self.inputs()
        pending = []
        for path, value in mapping.items():
            if path not in declarations:
                raise ValidationError(
                    f"{self.path}: unknown control/boundary path {path!r}; valid: "
                    f"{join_names(declarations)}{did_you_mean(path, declarations)}",
                    code="unknown_name",
                )
            declaration = declarations[path]
            pending.append((declaration.owner, declaration.name, declaration.validate(value)))
        for owner, name, value in pending:
            owner._input_values[name] = value
        return self

    def _missing_design(self):
        """Return the names of what this module's design lacks; a class with such a rule says."""
        return []

    def _missing_designs(self):
        """Return the dotted paths of what the designs of this module tree lack."""
        return [
            join_path(path, name)
            for path, module in self.named_modules()
            for name in module._missing_design()
        ]

    def _check_design(self):
        """Raise ``missing_value`` for each design value the tree lacks, before a run starts."""
        missing = self._missing_designs()
        if missing:
            raise self._missing_error(missing)

    def _missing_error(self, paths):
        """Return the one ``missing_value`` error that lists every path with its meaning."""
        items = [
            description.missing_item(description.missing_entry(path, self.get(path)))
            for path in paths
        ]
        listed = "; ".join(f"{item['path']}: {item['message']}" for item in items)
        return ValidationError(
            f"{self.path}: uninitialized parameters: {listed}",
            path=items[0]["path"],
            code="missing_value",
            problems=items,
        )

    def _root(self):
        """Return the module at the top of the tree this module belongs to."""
        module = self
        while module._parent is not None:
            module = module._parent
        return module

    def _missing_paths(self):
        """Return the dotted paths of what the tree lacks: design values, then parameters."""
        uninitialized = [name for name, value in self.named_parameters() if not value.initialized]
        return list(dict.fromkeys(self._missing_designs() + uninitialized))

    def missing_parameters(self):
        """Return what the tree still needs, as JSON: one entry per unset parameter.

        Each entry has ``path`` (dotted, from this module), ``type``, ``quantity``, ``unit`` (SI),
        ``units`` (every unit a value may be given in), ``minimum``, ``maximum``, ``enum`` and
        ``description`` (the physical meaning). Design values a module still waits for come
        first. An empty list means the tree can run.
        """
        return [description.missing_entry(path, self.get(path)) for path in self._missing_paths()]

    def _prepare(self):
        """Reject uninitialized parameters, before any call."""
        missing = self._missing_paths()
        if missing:
            raise self._missing_error(missing)

    @property
    def is_initialized(self):
        """Whether every parameter in this module tree has a value."""
        return not self._missing_paths()

    def _override_params(self, values):
        """Set parameters by local or dotted path as overrides, which win over every date."""
        for name, value in values.items():
            declaration = self.get(name)
            declaration.owner._set_parameter(declaration.name, value)
        return self

    def _set_parameter(self, name, value):
        """Set one own parameter as an explicit override; a deriving module derives from it."""
        if self._derives_params():
            self._set_si_params("", {name: value})
            return
        self._parameters[name].set(value)

    def _derives_params(self):
        """Return whether this module derives its children's values; only a plant may."""
        return False

    def describe(self):
        """Return the plain description of this module: see ``modules.md``."""
        return description.describe(self)

    def parameter_schema(self):
        """Return the JSON Schema of the parameters of this module."""
        return description.parameter_schema(self)

    def validate_params(self, params, on_error="raise"):
        """Check ``params`` without changing the module: ``[]``, or every problem.

        The values are those ``set_params`` takes, so a bare number for a value with a dimension
        is an ``invalid_value`` problem.
        """
        return description.validate_params(self, params, on_error)

    def _params_at(self, at):
        """Return the complete validated parameter mapping active at an instant.

        ``at=None`` selects the latest snapshot. Explicit overrides win over every snapshot.
        """
        selected = design.snapshot_at(self, at)
        values = selected.params | self._param_overrides
        return {name: self._parameters[name].validate(value) for name, value in values.items()}

    def _root_inputs(self):
        """Return the stated fields of the root inlets; only a plant states them."""
        return {}

    def _has_input_value(self, name):
        """Return whether control or boundary ``name`` has a persisted value."""
        return name in self._input_values

    def _apply_params_at(self, at):
        """Apply dated parameter snapshots recursively while retaining explicit overrides."""
        for module in self.modules():
            for name, value in module._params_at(at).items():
                module._parameters[name].set(value, explicit=False)

    def forward(self, inlets):
        """Move inlet fluids to declared outlets; subclasses implement this."""
        raise NotImplementedError(f"{type(self).__name__} has no forward method")

    def _offer(self, inlets):
        """Return the ``offered`` outlets; a module that declares one overrides this.

        It runs before the other modules and reads only controls, boundaries, parameters and
        the inlets named in ``offer_inlets``.
        """
        raise NotImplementedError(f"{type(self).__name__} offers nothing")

    def _offered(self, inlets=None):
        """Return the values of the ``offered`` outlets, for a plant to pass on before they run."""
        self._prepare()
        parent = _current_call.get()
        ports = Ports(inlets or {}, path=self.path)
        if parent is not None and parent.trace is not None:
            return parent.trace.offer(self, ports, parent)
        with ops.scope.Scope(self._scalar_mode(), _has_arrays(ports, {})) as scope:
            step = parent.step if parent is not None else None
            call = self._eager_call(self._resolve_inputs({}), parent, step, scope.wrapping)
            token = _current_call.set(call)
            try:
                offered = self._offer(_numpy_ports(ports) if scope.wrapping else ports)
            finally:
                _current_call.reset(token)
        return {name: _plain_outlet(value) for name, value in offered.items()}

    def __call__(self, *args, **kwargs):
        """Apply controls and boundaries, run hooks and ``forward``, and validate outlets."""
        parent = _current_call.get()
        return self._run(args, kwargs, parent.step if parent is not None else None)

    def _run(self, args, kwargs, step):
        """Evaluate one call; inside a step a stateful module also advances its states."""
        self._prepare()
        inlets, supplied = self._split_call_args(args, kwargs)
        parent = _current_call.get()
        if parent is not None and parent.trace is not None:
            return parent.trace.child(self, inlets, supplied, parent)
        inputs = self._resolve_inputs(supplied)
        with ops.scope.Scope(self._scalar_mode(), _has_arrays(inlets, inputs)) as scope:
            call = self._eager_call(inputs, parent, step, scope.wrapping)
            token = _current_call.set(call)
            try:
                scoped = _numpy_ports(inlets) if scope.wrapping else inlets
                outlets = self._evaluate(inlets, scoped, call)
                if step is not None and self._states:
                    values = self._next_states(scoped, outlets, step.dt)
                    step.advance(self._step_keys(step), values)
            finally:
                _current_call.reset(token)
        result = ModuleResult.of(
            self,
            call.kept_outputs(),
            outlets,
            self._settled_inlets(inlets, call),
            ops.scope.plain(dict(call.inputs)),
            call.call_records,
        )
        if parent is not None:
            parent.call_records.append((self._relative_path(parent.module), result))
        return result

    def _eager_call(self, inputs, parent, step, wrapping):
        """Return the call record of an eager call; ``wrapping`` gives physics NumPy scalars.

        Wrapped controls, boundaries, states and (read on demand) parameters are what ``forward``
        sees, so a plain operator on them is silent like the ops; results hold plain values.
        """
        states = self._call_states(step)
        if wrapping:
            inputs = {name: ops.scope.wrap(value) for name, value in inputs.items()}
            states = None if states is None else ops.scope.wrap(states)
        return _Call(
            module=self,
            inputs=inputs,
            outputs={},
            recording=outputs_enabled(),
            parent=parent,
            states=states,
            step=step,
            parameters=_ScalarParameters(self) if wrapping else None,
            wrapping=wrapping,
        )

    def _scalar_mode(self):
        """Return ``WRAP`` to give physics NumPy scalars in an eager call, else ``PLAIN``.

        NOTE(refactor): the ESP overrides it for float32 precision, whose arithmetic an
        ``np.float64`` scalar would change; no other module does.
        """
        return kernels.WRAP

    def _evaluate(self, inlets, scoped, call):
        """Run pre-hooks, ``forward``, the formula outputs and forward hooks of one call.

        Hooks see the plain ``inlets``; ``forward`` sees ``scoped``.
        """
        for hook in tuple(self._pre_hooks.values()):
            hook(self, inlets)
        returned = self.forward(scoped)
        self._check_outlet_names(returned)
        given = {name: returned[name] for name in self._given_outlets()}
        taken = {name: scoped[name] for name in self._drawn_outlets() if name in scoped}
        if call.trace is None:
            outlets = self._check_outlets(_restored(given, scoped, inlets), taken)
            call.drawn = self._checked_drawn(returned)
        else:
            outlets = Ports({name: (given | taken)[name] for name in self._outlets}, path=self.path)
            call.drawn = {name: returned[name] for name in self._drawn_inlets()}
        if call.recording:
            self._output_step(inlets, outlets, call)
        return outlets

    def _settled_inlets(self, inlets, call):
        """Return the declared inlets of a call, each drawn one with the value the module drew."""
        values = {
            name: call.drawn[name] if name in call.drawn else inlets[name] for name in self._inlets
        }
        return Ports._trusted(values, self.path)

    def _given_outlets(self):
        """Return the outlets ``forward`` returns: all but those whose takers decide the flow."""
        return [name for name, port in self._outlets.items() if not port.drawn]

    def _drawn_outlets(self):
        """Return the outlets that receive what their takers drew."""
        return [name for name, port in self._outlets.items() if port.drawn]

    def _drawn_inlets(self):
        """Return the inlets whose value ``forward`` returns."""
        return [name for name, port in self._inlets.items() if port.drawn]

    def _fed_inlets(self):
        """Return the single stream inlets a caller supplies, in declaration order."""
        return {
            name: port for name, port in self._inlets.items() if not port.gives and not port.many
        }

    def _checked_drawn(self, returned):
        """Return what ``forward`` drew through its drawn inlets, validated."""
        return {
            name: self._inlets[name].validate(_plain_outlet(returned[name]))
            for name in self._drawn_inlets()
        }

    def _output_step(self, inlets, outlets, call):
        """Finish the outputs after ``forward``, the one sequence of an eager and a traced call.

        Forward hooks see the plain ``inlets``, in a trace through ``call.trace`` which tells
        whether they write an output.
        """
        self._compute_combinations(call)
        for hook in tuple(self._hooks.values()):
            if call.trace is None:
                hook(self, inlets, outlets)
            else:
                call.trace.hook(self, hook, inlets, outlets, call)
        self._check_outputs(call.outputs)

    def _relative_path(self, owner):
        prefix = owner._path + "." if owner._path else ""
        return self._path.removeprefix(prefix) or self.name

    def _split_call_args(self, args, kwargs):
        """Return validated inlet ``Ports`` and the supplied control/boundary keywords."""
        inlet_names = list(self._fed_inlets())
        ports = inlet_names + list(self._optional_ports())
        valid_names = ports + list(self._controls) + list(self._boundaries)
        self._check_keywords(kwargs, valid_names)
        if len(args) == 1 and isinstance(args[0], Mapping):
            inlet_values = self._mapping_inlets(args[0], kwargs)
        else:
            inlet_values = self._positional_inlets(args, kwargs)
        missing = [name for name in inlet_names if name not in inlet_values]
        if missing:
            raise ValidationError(
                f"{self.path}: missing required inlet(s) {', '.join(missing)}; "
                f"valid names: {join_names(inlet_names)}",
                code="invalid_call",
            )
        inlets = self._validated_ports(
            "inlet",
            self._call_ports(),
            self._with_optional_ports(inlet_values),
            partial(ValidationError, code="invalid_call"),
        )
        inputs = {
            name: kwargs[name] for name in self._controls | self._boundaries if name in kwargs
        }
        return inlets, inputs

    def _optional_ports(self):
        """Return the ports a call may leave out: ``many`` inlets and drawn outlets, by name."""
        many = {name: port for name, port in self._inlets.items() if port.many}
        return many | {name: self._outlets[name] for name in self._drawn_outlets()}

    def _call_ports(self):
        """Return every port a call holds a value for: fed inlets, then the optional ports."""
        return self._fed_inlets() | self._optional_ports()

    def _empty_ports(self, values=None):
        """Return what the optional ports hold when nothing is taken: no list items, the offer.

        ``values`` are the ports of the call, which the offer may read.
        """
        optional = self._optional_ports()
        empty = {name: [] for name, port in optional.items() if port.many}
        if len(empty) == len(optional):
            return empty
        fed = {name: (values or {})[name] for name in self.offer_inlets}
        return empty | {
            name: value for name, value in self._offered(fed).items() if name in optional
        }

    def _with_optional_ports(self, values):
        """Return ``values`` with the optional ports the call left out."""
        if all(name in values for name in self._optional_ports()):
            return values
        return self._empty_ports(values) | dict(values)

    def _check_keywords(self, kwargs, valid_names):
        unknown = [name for name in kwargs if name not in valid_names]
        if unknown:
            name = unknown[0]
            raise ValidationError(
                f"{self.path}: unexpected keyword {name!r}; valid names: {join_names(valid_names)}"
                f"{did_you_mean(name, valid_names)}",
                code="invalid_call",
            )

    def _mapping_inlets(self, mapping, kwargs):
        ports = self._call_ports()
        valid = join_names(ports)
        mixed = [name for name in ports if name in kwargs]
        if mixed:
            raise ValidationError(
                f"{self.path}: cannot mix inlet mapping with inlet keyword {mixed[0]!r}; "
                f"valid names: {valid}",
                code="invalid_call",
            )
        unknown = [name for name in mapping if name not in ports]
        if unknown:
            name = unknown[0]
            raise ValidationError(
                f"{self.path}: unknown inlet {name!r}; valid names: {valid}"
                f"{did_you_mean(name, ports)}",
                code="invalid_call",
            )
        return mapping

    def _positional_inlets(self, args, kwargs):
        inlet_names = list(self._fed_inlets())
        valid = join_names(inlet_names)
        if len(args) > len(inlet_names):
            raise ValidationError(
                f"{self.path}: expected at most {len(inlet_names)} positional inlet arguments, "
                f"got {len(args)}; valid names: {valid}",
                code="invalid_call",
            )
        values = dict(zip(inlet_names, args))
        duplicate = values.keys() & kwargs.keys()
        if duplicate:
            raise ValidationError(
                f"{self.path}: multiple values for inlet {next(iter(duplicate))!r}; "
                f"valid names: {valid}",
                code="invalid_call",
            )
        ports = self._call_ports()
        values.update({name: kwargs[name] for name in ports if name in kwargs})
        return values

    def _validated_ports(self, kind, declarations, values, error, prepare=lambda value: value):
        """Return the ``Ports`` of ``values`` validated by ``declarations``, else raise ``error``.

        ``kind`` is ``"inlet"`` or ``"outlet"`` in the message; ``prepare`` is applied to each value
        before it is validated.
        """
        validated = []
        for name, declaration in declarations.items():
            value = prepare(values[name])
            try:
                validated.append((name, declaration.validate(value)))
            except (TypeError, ValueError, PhysicsError) as exc:
                raise error(
                    f"{self.path}: invalid {kind} {name!r}; "
                    f"valid names: {join_names(declarations)}: {exc}"
                ) from exc
        return Ports(validated, path=self.path)

    def _check_outlet_names(self, returned):
        """Reject a ``forward`` result that is not a dict of what the module gives."""
        if not isinstance(returned, dict):
            raise DefinitionError(f"{self.path}: forward must return an outlet dict")
        expected = [*self._given_outlets(), *self._drawn_inlets()]
        missing = set(expected) - returned.keys()
        extra = returned.keys() - set(expected)
        if missing or extra:
            raise DefinitionError(
                f"{self.path}: outlet names missing={sorted(missing)}, extra={sorted(extra)}; "
                f"valid names: {join_names(expected)}"
            )

    def _check_outlets(self, given, taken):
        """Return the outlet ``Ports``: what ``forward`` gave and what its takers took."""
        return self._validated_ports(
            "outlet", self._outlets, given | taken, DefinitionError, _plain_outlet
        )

    def _resolve_inputs(self, supplied):
        """Return validated controls and boundaries: supplied, persisted, then default values."""
        return {
            name: (
                declaration.validate(supplied[name])
                if name in supplied
                else self._input_value(name)
            )
            for name, declaration in (self._controls | self._boundaries).items()
        }

    def _compute_combinations(self, call):
        """Record the outputs a plant combines from its children; a leaf has none."""

    def _check_outputs(self, recorded):
        missing = sorted(self._outputs.keys() - recorded.keys())
        if missing:
            raise DefinitionError(f"{self.path}: outputs left unassigned: {missing}")

    def initial_state(self):
        """Return the initial states, nested by child name; ``None`` when nothing is stateful."""
        if self._states:
            return self._initial_states()
        states = {
            name: child_state
            for name, child in self.named_children()
            if (child_state := child.initial_state()) is not None
        }
        return states or None

    def step(self, state, dt, inlets):
        """Advance every declared state over ``dt`` seconds; return ``(next_state, result)``.

        ``state`` is the tree ``initial_state`` returns, or ``None`` for the initial states. The
        call runs as ``self(inlets)``; each stateful module called during it starts from its
        entry in ``state`` and records its end-of-step entry. A descendant that is stateful
        without declaring states steps itself, so a composite cannot step it and refuses.
        """
        if dt <= 0:
            raise ValidationError(
                f"{self.path}: dt = {dt} s; expected a positive step", code="invalid_design"
            )
        explicit = [
            path
            for path, module in self.named_modules()
            if path and module.stateful and not module._states
        ]
        if explicit:
            raise ValidationError(
                f"{self.path}: stateful descendants {', '.join(explicit)} need a step method "
                "on this composite that steps them",
                code="invalid_design",
            )
        start = state if state is not None else self.initial_state() or {}
        step = _Step(root=self, dt=dt, states=start, next_states=deepcopy(start))
        result = self._run((inlets,), {}, step)
        return step.next_states or None, result

    def _trial(self, *args, **kwargs):
        """Return the result of one call that no running call records, outputs not validated.

        A plant that closes a loop or solves a constraint evaluates trial passes with it, then
        calls each module once with the converged inlets, so its outputs and balances see only
        that call. Pre-hooks run and forward hooks do not. A stateful module would evaluate at its
        initial states, so it is refused.
        """
        if self.stateful:
            raise ValidationError(
                f"{self.path}: stateful = True; expected a stateless module for a trial call",
                code="invalid_design",
            )
        token, trial = _current_call.set(None), _in_trial.set(True)
        try:
            with no_outputs():
                return self(*args, **kwargs)
        finally:
            _in_trial.reset(trial)
            _current_call.reset(token)

    def _offers(self):
        """Return whether the ``offered`` outlets exist as this module is set; some may not."""
        return True

    def _loop_start(self, port, entering):
        """Return the first guess [K] of the temperature on outlet ``port`` of a closed loop.

        ``entering`` lists the streams that reach this module from outside the loop. A module that
        can guess overrides this; the plan then prefers to tear that outlet.
        """
        return None

    def _loop_limits(self, inlets):
        """Return the ``(lower, upper)`` temperatures [K] a loop through this module must keep.

        ``inlets`` are the inlets that come from outside the loop. ``None`` is no limit.
        """
        return None, None

    def _iterates(self):
        """Return whether a call of this module closes a loop or solves a constraint."""
        return False

    def _initial_states(self):
        """Return the validated initial value of every declared state."""
        return {name: self._initial_state(name, state) for name, state in self._states.items()}

    def _initial_state(self, name, state):
        """Return the initial value of one state: its reference default, else its parameter."""
        if state.default is not UNSET:
            return state.default_value()
        return state.validate(self._parameter_value(f"initial_{name}"))

    def _call_states(self, step):
        """Return the state values one call starts from, or ``None`` without declared states."""
        if not self._states:
            return None
        if step is None:
            return self._initial_states()
        supplied = step.start(self._step_keys(step))
        unknown = sorted(supplied.keys() - self._states.keys())
        if unknown:
            raise ValidationError(
                f"{self.path}: unknown state {unknown[0]!r}; valid: {join_names(self._states)}"
                f"{did_you_mean(unknown[0], self._states)}",
                code="unknown_name",
            )
        return self._initial_states() | {
            name: self._states[name].validate(value) for name, value in supplied.items()
        }

    def _step_keys(self, step):
        """Return the child names that lead from the stepped module to this module."""
        if self is step.root:
            return ()
        prefix = step.root._path + "." if step.root._path else ""
        return tuple(self._path.removeprefix(prefix).split("."))

    def _next_states(self, inlets, outlets, dt):
        """Validate the end-of-step states that ``_advance_states`` returns."""
        values = self._advance_states(inlets, outlets, dt)
        if not isinstance(values, Mapping) or values.keys() != self._states.keys():
            raise ValidationError(
                f"{self.path}: _advance_states returned {sorted(values or ())}; expected "
                f"{join_names(self._states)}",
                code="invalid_design",
            )
        return {name: self._states[name].validate(value) for name, value in values.items()}

    def _advance_states(self, inlets, outlets, dt):
        """Return the end-of-step value of every declared state; stateful leaves override it."""
        raise NotImplementedError(f"{type(self).__name__} declares states without _advance_states")

    def register_forward_pre_hook(self, fn):
        """Call ``fn(module, inlets)`` before each forward evaluation."""
        self._check_hook_signature(fn, ("module", "inlets"), "forward pre-hook")
        return RemovableHandle(self._pre_hooks, fn)

    def register_forward_hook(self, fn):
        """Call ``fn(module, inlets, outlets)`` after output computation."""
        self._check_hook_signature(fn, ("module", "inlets", "outlets"), "forward hook")
        return RemovableHandle(self._hooks, fn)

    def _check_hook_signature(self, fn, expected, kind):
        if not has_signature(fn, expected):
            actual = tuple(inspect.signature(fn).parameters)
            raise DefinitionError(
                f"{self.path}: {kind} signature must be ({', '.join(expected)}); "
                f"got ({', '.join(actual)})"
            )

    def health(self, result, measured):
        """Compare one call's ``ModuleResult`` with measured outputs; ``None`` means not assessed.

        Equipment with a diagnostic model overrides this; the engine calls it after each replayed
        twin with the bound measurements of that tick.
        """
        return None

    def state_dict(self):
        """Return JSON-safe parameter and fluid snapshots for the complete tree."""
        return {
            path: {
                "type": snake_case(module.name),
                "params": {
                    name: to_jsonable_python(parameter.value)
                    for name, parameter in module._parameters.items()
                    if parameter.initialized
                },
                "fluid": module._fluid.model_dump(mode="json"),
            }
            for path, module in self.named_modules()
        }

    def set_state_dict(self, state, strict=True):
        """Validate snapshots before applying any of them.

        With ``strict`` the snapshot paths must equal the tree's module paths; otherwise only the
        modules named in ``state`` are filled and unknown paths are rejected.
        """
        modules = dict(self.named_modules())
        missing, unexpected = modules.keys() - state.keys(), state.keys() - modules.keys()
        if unexpected or (strict and missing):
            raise ValidationError(
                f"{self.path}: state paths differ; missing={missing}, unexpected={unexpected}",
                code="invalid_format",
            )
        pending = []
        for path, entry in state.items():
            module = modules[path]
            values = {
                name: module.get(name).validate(value) for name, value in entry["params"].items()
            }
            pending.append((module, values, Fluid._of(entry["fluid"])))
        for module, values, fluid in pending:
            for name, value in values.items():
                module._parameters[name].set(value, explicit=False)
            object.__setattr__(module, "_fluid", fluid)
        return self

    def set_params(self, path, params, valid_from=None):
        """Store validated parameters of the module at ``path`` as a dated snapshot.

        The snapshot is the values in force at ``valid_from`` merged with ``params``; without a
        date the undated base entry and the current values change. Names may be dotted. A value
        with a dimension is a ``gm.units.Quantity`` or its ``{"value", "unit"}`` dict, converted
        to SI after its unit is checked against the declared quantity; a bare number for it
        raises ``ValidationError`` (``invalid_value``) naming the path, the quantity and the
        accepted units, zero included. A parameter without a dimension takes a plain number.
        Returns the module.

        This is the public door. It converts and hands over to ``_set_si_params``, the one
        private method that stores SI values: the engine, ``study``, ``size`` and the case
        call that one.
        """
        return self._set_si_params(path, design.in_si(self, path, params), valid_from)

    def _set_si_params(self, path, params, valid_from=None):
        """Store the SI values ``params`` of the module at ``path``; ``set_params`` calls this.

        Every route that sets parameters comes here. A plant class that derives its children's
        values overrides this method, not ``set_params`` (see ``modules.md``); a value for it, at
        any depth, reaches that override.
        """
        return design.set_params(self, path, params, valid_from)

    def params_at(self, path, time=None):
        """Return the parameter values of the module at ``path`` in force at ``time``."""
        return design.params_at(self, path, time)

    def param_history(self, path):
        """Return the dated parameter snapshots of the module at ``path``."""
        return design.param_history(self, path)

    def bindable(self, path):
        """Return what can be bound at ``path``, by section."""
        return design.bindable(self, path)

    def set_bindings(self, path, bindings):
        """Replace the bindings of the module at ``path``; units are checked. Returns the module."""
        return design.set_bindings(self, path, bindings)

    def _extra_repr(self):
        """Display up to four initialized scalar parameters."""
        parts = []
        for name in self.repr_fields or tuple(self._parameters):
            parameter = self._parameters.get(name)
            if parameter is None or not parameter.initialized:
                continue
            value = parameter.value
            if isinstance(value, (dict, list, tuple)) or value is None:
                continue
            parts.append(f"{name}={_display(value, parameter.unit or '', parameter.quantity)}")
            if len(parts) == 4:
                break
        return ", ".join(parts)

    def __repr__(self):
        """Render a compact recursive module tree."""
        extra = self._extra_repr()
        if not self._children:
            return f"{self._type_label}({extra})"
        rows = [f"{self._type_label}({extra}"]
        for name, child in self.named_children():
            rows.append("  (" + name + "): " + repr(child).replace("\n", "\n  "))
        return "\n".join(rows + [")"])

    @classmethod
    def help(cls):
        """Return the class description and its declarations for interactive use."""
        lines = [first_paragraph(inspect.getdoc(cls) or cls.__name__)]
        module = cls()
        for title, registry in (
            ("Parameters", module._parameters),
            ("Inlets", module._inlets),
            ("Controls", module._controls),
            ("Boundaries", module._boundaries),
            ("States", module._states),
            ("Outputs", module._outputs),
            ("Outlets", module._outlets),
        ):
            if registry:
                lines.append(f"\n{title}:")
                lines.extend(f"  {name}: {_describe(value)}" for name, value in registry.items())
        return "\n".join(lines)


def _display(value, unit, quantity):
    """Format one parameter value with its unit, in field units when the runtime asks for them."""
    if runtime.get_display_units() == "field" and unit in _FIELD_DISPLAY_UNITS:
        target = _FIELD_DISPLAY_UNITS[unit]
        value, unit = units.convert(value, unit, target, quantity), target
    shown = f"{value:.5g}" if isinstance(value, float) else str(value)
    return shown + (f" {unit}" if unit and unit != "-" else "")


def _describe(declaration):
    """Return the unit, default and flags of one declaration for ``Module.help``."""
    details = [declaration.unit] if declaration.unit else []
    if isinstance(declaration, Parameter) and declaration.default is not UNSET:
        details.append(f"default={declaration.default!r}")
    if isinstance(declaration, Parameter) and declaration.calibratable:
        details.append("calibratable")
    if isinstance(declaration, Output) and declaration.soft_sensor:
        details.append("soft sensor")
    return ", ".join(details)
