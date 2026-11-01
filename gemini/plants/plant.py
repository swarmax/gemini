"""Plants: a ``Module`` that connects its children and whose forward runs them in that order."""

from gemini._utils import files
from gemini._utils.strings import join_path, snake_case
from gemini.errors import ValidationError
from gemini.modules._utils import design
from gemini.modules._utils.serialization import tree_params
from gemini.modules.container import ModuleList
from gemini.modules.declarations import Inlet, Outlet, Output
from gemini.modules.module import Module
from gemini.physics import energy
from gemini.plants._utils import circuits, inputs, listing, loops, outputs, reader, writer
from gemini.plants._utils.factory import make_module
from gemini.plants._utils.legacy.reader import from_folder as from_project_folder
from gemini.plants._utils.plan import STATE, PlanConstraint, compile_plan, is_group, port_ends
from gemini.plants._utils.ports import PortResolver
from gemini.plants._utils.run import Run


class Plant(PortResolver, Module):
    """Named modules and the connections between them: every composite is a ``Plant``.

    A plant class declares its children, ports and connections in ``__init__``, in the sections
    ``# Modules``, ``# Parameters``, ``# Inlets``, ``# Outlets``, ``# Connections``, ``# Outputs``,
    and never writes ``forward``; ``gm.Plant(name)`` builds one with ``add`` and ``connect``. A
    child assigned as an attribute is registered as ``add`` does. Every port of a child is
    connected or named as a plant port; a plant port exists only when named. ``name`` is the name
    given, by default the name of the class.

    A plant may override ``set_params`` to derive its children's values from design values. What
    such a call states explicitly is remembered and wins over what is derived, derived values are
    never stored, and the fluid of a plant passes to its children.
    """

    abstract = True

    purpose = None
    """What a plant class serves: ``heating``, ``cooling`` or ``both``; else a building block."""
    loop_tolerance = loops.TOLERANCE
    loop_passes = loops.MAX_PASSES

    def __init__(self, name=None):
        """Start an empty plant called ``name``."""
        if name is None:
            name = "plant" if type(self) is Plant else type(self).__name__
        object.__setattr__(self, "_name", name)
        super().__init__()
        self._size = {}
        self._inputs = {}
        self._connections = []
        self._constraints = []
        self._declared = set()
        self._derived_params = set()
        self._stated_child_params = set()
        self._listed = {"inlets": {}, "outlets": {}}
        self._output_entries = None
        self._stated = {}
        self._baselines = {}
        self._sections = {}
        self._plan = None
        self._planned_offers = ()

    @classmethod
    def _empty(cls, name):
        """Return an empty plant of no class: a plant dict with a structure states all of it."""
        plant = Plant.__new__(Plant)
        Plant.__init__(plant, name)
        return plant

    @property
    def name(self):
        """Return the name given to the plant."""
        return self._name

    @property
    def path(self):
        """Return the assigned tree path, or the snake case name of a standalone plant."""
        return self._path or snake_case(self._name)

    @property
    def _type_label(self):
        return self._name

    @property
    def fluid(self):
        """Return the fluid of the plant."""
        return self._fluid

    @fluid.setter
    def fluid(self, value):
        """Set the fluid of the plant and of every module below it, and derive again."""
        for module in self.modules():
            module._set_own_fluid(value)

    def _set_own_fluid(self, value):
        """Set the fluid of this plant alone and derive again."""
        super()._set_own_fluid(value)
        if self._derives_params():
            self.set_params("", {})

    def _derives_params(self):
        """Return whether this class overrides ``set_params`` to derive its children's values."""
        return type(self).set_params is not Plant.set_params

    def set_params(self, path, params, valid_from=None):
        """Store parameters as ``Module.set_params`` does and remember what the root was given."""
        if valid_from is None:
            names = {join_path(path, key): value for key, value in params.items()}
            kept = {key: value for key, value in names.items() if key not in self._derived_params}
            self._stated[""] = self._stated.get("", {}) | kept
        return super().set_params(path, params, valid_from)

    def set_inputs(self, values):
        """Set inputs of the plant by path and return it; ``to_dict`` stores them.

        ``values`` maps a path to a number in SI or a quantity, never a unit string: the
        dotted path of a control or boundary (``"heat_pump.temperature_setpoint"``), or
        ``port.field`` of a plant inlet (``"heating_return.T"``, the fields ``m_dot``, ``T``, ``p``
        and ``fluid``). One value that does not fit raises and changes nothing. A run overrides an
        input with a column of its name, and a value assigned on a module is not stored.
        """
        checked = inputs.checked(self, values)
        declared = self.inputs()
        self._set_inputs({path: item for path, item in checked.items() if path in declared})
        self._inputs |= inputs.as_stated(values, checked)
        return self

    def input_value(self, path):
        """Return the input at ``path`` in SI, or ``None`` when it has no value.

        The value of ``set_inputs`` wins; otherwise the value persisted on the module.
        """
        return inputs.value(self, path)

    def _root_inputs(self):
        """Return the plant inlet fields of ``set_inputs`` as ``{port: {field: value}}``."""
        return inputs.root_streams(self)

    def _own_values(self, params, valid_from=None):
        """Return the own parameters in force at ``valid_from`` with those of ``params``, in SI."""
        given = {name: value for name, value in params.items() if name in self._parameters}
        checked = {name: self._parameters[name].validate(value) for name, value in given.items()}
        return self._params_at(valid_from) | checked

    def _keep_derived(self, derived, params):
        """Return the ``derived`` child values that no explicit value replaces, and record them.

        A deriving ``set_params`` calls this with its derived values and the ``params`` of the
        call. A dotted name in ``params`` is an explicit child value, now and in later calls, and
        so is a child value assigned on the child. The names kept are the ones ``to_dict`` leaves
        out.
        """
        self._stated_child_params |= {name for name in params if "." in name}
        kept = {
            name: value
            for name, value in derived.items()
            if name not in self._stated_child_params and not self._is_overridden(name)
        }
        self._derived_params = (self._derived_params | kept.keys()) - self._stated_child_params
        return kept

    def _is_overridden(self, name):
        parameter = design.parameter(self, name)
        return parameter.name in parameter.owner._param_overrides

    def _add_module(self, name, module):
        """Register a child assigned as an attribute, as ``add`` does."""
        super()._add_module(name, module)
        self._note_child(name, module)

    def _note_child(self, key, module):
        """Record that nothing has been stated yet for ``module`` and what it starts from."""
        if key in self._baselines:
            return
        self._baselines[key] = {}
        if is_group(module):
            for name, child in module.named_children():
                self._note_child(join_path(key, name), child)
            return
        self._stated[key] = {}
        self._baselines[key] = tree_params(module)

    def add(self, type, name=None, params=None):
        """Add a module of registry name or class ``type`` and return it.

        ``params`` is one dict of design values, the dict ``set_params`` takes: numbers in SI
        or quantities, dotted names for a composite. ``name`` defaults to the snake case type,
        numbered when taken; a dotted name adds into a group such as ``filters.hot``.
        """
        module, type_name = make_module(type)
        key = self._free_name(name, type_name)
        baseline = tree_params(module)
        stated = dict(params or {})
        module.set_params("", stated)
        self._attach(key, module, stated, baseline)
        return module

    def _attach(self, key, module, stated, baseline):
        """Register ``module`` under the (possibly dotted) ``key`` with the params as stated."""
        parent_path, _, local = key.rpartition(".")
        parent = self.get_submodule(parent_path)
        if parent is not self and not is_group(parent):
            raise ValidationError(f"{key}: {parent_path!r} is not a group", path="name")
        if isinstance(parent, ModuleList):
            parent.append(module)
        else:
            parent._add_module(local, module)
        self._stated[key] = stated
        self._baselines[key] = baseline
        self._refresh()

    def _free_name(self, name, type_name):
        taken = {path for path, _ in self.named_modules()}
        if name is not None:
            if name in taken:
                raise ValidationError(f"add: name {name!r} is already taken", path="name")
            return name
        base = snake_case(type_name)
        candidates = [base] + [f"{base}_{number}" for number in range(2, len(taken) + 3)]
        return next(item for item in candidates if item not in taken)

    def connect(self, source, target, type=None):
        """Connect an outlet to an inlet; ``type="state"`` closes a loop through the last step.

        An end is a module, a port declaration or ``"path.port"``. A bare module path picks its
        only free port of a fitting kind; several fitting pairs raise ``ambiguous_port``.
        A bare word that names no module is a plant port: ``connect("return_in",
        "heat_exchanger.cold_in")`` names a plant inlet.
        """
        self._link(source, target, type, explicit=False)

    def _link(self, source, target, type, explicit):
        """Add one connection or name one plant port; ``explicit`` requires ``path.port`` ends."""
        if type not in (None, STATE):
            raise ValidationError(
                f"type = {type!r}; expected 'state' or null", path="type", code="invalid_value"
            )
        if self._is_port_name(source):
            return self._name_port("inlets", source, target, explicit)
        if self._is_port_name(target):
            return self._name_port("outlets", target, source, explicit)
        first = self._candidates(source, "source", explicit)
        second = self._candidates(target, "target", explicit)
        (path, port, _), (target_path, target_port, _) = self._choose(first, second)
        self._add_connection(path, port, target_path, target_port, type)

    def _add_connection(self, path, port, target_path, target_port, connection_type):
        item = {"source": join_path(path, port), "target": join_path(target_path, target_port)}
        if connection_type == STATE:
            item["type"] = STATE
        self._connections.append(item)
        self._refresh()

    def constrain(self, target, by, bounds, equals=None, at_least=None):
        """Let the engine find the free value ``by`` at which ``target`` reaches its value.

        ``target`` is a path of the plant: an output or a port field such as
        ``riser.wellhead_out.p``. ``equals`` is the path of the value it must reach, a parameter,
        boundary or output. ``by`` is the path of a control or boundary of a child, and
        ``bounds`` the path of a pair of values, or two numbers or paths. With ``at_least``
        instead of ``equals`` a target that reaches its value at the lower bound keeps that bound.
        """
        if (equals is None) == (at_least is None):
            raise ValidationError(
                f"constrain: equals = {equals!r}, at_least = {at_least!r}; expected exactly one",
                path="equals",
                code="invalid_value",
            )
        limits = bounds if isinstance(bounds, str) else tuple(bounds)
        value = at_least if equals is None else equals
        self._constraints.append(PlanConstraint(target, value, by, limits, equals is None))
        self._plan = None

    def _register_declaration(self, name, declaration):
        """Register a declaration; a port assigned by a plant class stays through ``_refresh``."""
        if isinstance(declaration, (Inlet, Outlet)):
            self._declared.add(name)
        if isinstance(declaration, Output) and declaration.formula is not None:
            self._output_entries = (self._output_entries or {}) | {
                name: outputs.entry_of(declaration.formula)
            }
            declaration = outputs.typed(self, name, declaration.formula)
        super()._register_declaration(name, declaration)

    def _refresh(self):
        self._plan = None
        for side, declare in (("inlets", Inlet), ("outlets", Outlet)):
            for name, ends in self._port_map(side).items():
                if name in self._declared:
                    continue
                path, port = port_ends(ends)[0]
                end = getattr(self.get_submodule(path), side)()[port]
                registry = getattr(self, f"_{side}")
                registry.pop(name, None)
                Module._register_declaration(self, name, declare(end.type, kind=end.kind))

    def target_of(self, source):
        """Return the ``"path.port"`` that the outlet ``source`` feeds, or ``None``.

        ``None`` is an outlet that leaves the plant or feeds no connection of this plant.
        """
        found = [item["target"] for item in self._connections if item["source"] == source]
        return found[0] if found else None

    def source_of(self, target):
        """Return the ``"path.port"`` that feeds the inlet ``target``, or ``None``.

        ``None`` is an inlet fed by a plant port, or by no connection of this plant.
        """
        found = [item["source"] for item in self._connections if item["target"] == target]
        return found[0] if found else None

    def feeds(self, source):
        """Return the paths of the modules the outlet ``source`` reaches, nearest first.

        The walk follows the circuit through each module, a mixer and a splitter included, and ends
        at a plant port or at a module the circuit does not pass, such as a grid. It is how to ask
        what a unit serves: ``gm.schedule`` reads a unit's role from it.
        """
        return circuits.feeds(self, source)

    def _connection_list(self):
        """Return the plant's connections as ``[{source, target, kind, type}]``.

        ``kind`` is the label of the labelled end, ``None`` when both ends take anything.
        """
        return listing.connection_list(self)

    def summary(self):
        """Return a text table of the modules: type, category, inbound connections, parameters."""
        return listing.summary(self)

    def to_dict(self, structure=False):
        """Return the plant dict.

        A plant of a class stores its class, its size and the values that were given, never its
        structure or a derived value. A plant built with ``add`` and ``connect``, or a class plant
        with ``structure=True``, stores its modules and connections, which is how an agent edits
        a plant: ``gm.Plant.from_dict`` reads either.
        """
        if type(self) is Plant or structure:
            return writer.structure_dict(self)
        fresh = type(self)(**self._size)
        if (
            fresh._connections != self._connections
            or fresh._children.keys() != self._children.keys()
        ):
            return writer.structure_dict(self)
        return writer.class_dict(self, fresh)

    def to_json(self, path):
        """Write the plant dict as JSON."""
        files.to_json(path, self.to_dict())

    @classmethod
    def from_json(cls, path):
        """Return the plant of the JSON file of a plant dict."""
        return cls.from_dict(files.from_json(path))

    @classmethod
    def from_legacy(cls, folder):
        """Return the plant of the old GEMINI project in ``folder``.

        The folder holds what the old application saved: ``diagram.json`` (the nodes and links),
        one ``<node>_<id>.param`` file per diagram node with its properties, dated values and tag
        names, and any other file (the data CSV, ``well_trajectory.csv``, ``plant.conf``), which is
        read as-is and not converted.
        """
        return from_project_folder(folder)

    @classmethod
    def from_dict(cls, data):
        """Build any plant, of a class or without one, from a plant dict.

        One ``ValidationError`` lists every problem.
        """
        return reader.from_dict(cls, data)

    def validate(self, on_error="raise"):
        """Check the plant's structure as ``gm.plants.validate`` does; the same ``on_error``."""
        data = self.to_dict(structure=True)
        return reader.check(Plant, data, on_error)

    def _compiled(self):
        """Return the plan; which outlets are offered depends on how the modules are set."""
        offers = tuple(module._offers() for module in self.modules())
        if self._plan is None or offers != self._planned_offers:
            self._plan, self._planned_offers = compile_plan(self), offers
        return self._plan

    def _iterates(self):
        """Return whether a call of this plant closes a loop or solves a constraint."""
        return self._compiled().iterates

    def _plant_value(self, values):
        """Return the value of a plant port: its one end, or the sum of what its ends carry."""
        return values[0] if len(values) == 1 else energy.total_power(values)

    def _plan_outlets(self, results):
        plan = self._compiled()
        for name, ends in plan.outlets.items():
            yield name, self._plant_value([results[path].outlets[port] for path, port in ends])
        for name, ends in plan.given.items():
            yield name, self._plant_value([results[path].inlets[port] for path, port in ends])

    def _compute_combinations(self, call):
        """Record the outputs this plant combines from the results of its children."""
        records = dict(self._recorded_calls(call.call_records))
        for name, output in self._outputs.items():
            if output.formula is None:
                continue
            key, *paths = output.formula
            values = [outputs.read(self, records, path) for path in paths]
            setattr(self, name, outputs.combine(key, values))

    @staticmethod
    def _recorded_calls(call_records, prefix=""):
        for path, result in call_records:
            full_path = join_path(prefix, path)
            yield full_path, result
            yield from Plant._recorded_calls(result.call_records, full_path)

    def forward(self, inlets):
        """Call the modules in connection order, close the loops and return the plant outlets."""
        run = Run(self, inlets)
        for item in self._compiled().items:
            run.execute(item)

        # Outlets
        outlets = dict(self._plan_outlets(run.results))
        return outlets
