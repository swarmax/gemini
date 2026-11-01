"""The plant dict, format 2: the sections every plant shares, read and written.

Beside ``format`` and what says which plant it is, a plant dict holds, keyed by dotted path from
the root (``""`` is the root), ``fluids``, ``boundary``, ``bindings`` and ``param_history``. A
stated value stays as written while it still equals the current one.
"""

from contextlib import contextmanager
from functools import partial

from pydantic import ValidationError as PydanticError
from pydantic_core import to_jsonable_python

from gemini import runtime
from gemini._utils.jsonable import to_plain
from gemini._utils.strings import close_matches, did_you_mean, join_path
from gemini.errors import GeminiError, ValidationError
from gemini.modules._utils import design
from gemini.types.bindings import DatedParams
from gemini.types.fluid import Fluid
from gemini.types.shapes import problem

FORMAT = 2
SECTIONS = ("fluids", "boundary", "bindings", "param_history")


class Report:
    """Collect the problems of reading a data, or raise the first one when ``strict``."""

    def __init__(self, strict=False):
        """Start without problems."""
        self.strict = strict
        self.items = []
        self.broken = set()

    def skips(self, text):
        """Return whether ``text`` names a module that failed to build, whose problem is known."""
        return any(text == path or text.startswith(path + ".") for path in self.broken)

    @contextmanager
    def guard(self, path):
        """Turn a ``GeminiError`` raised inside the block into a problem at ``path``."""
        try:
            yield
        except GeminiError as error:
            if self.strict:
                raise
            self.items.append(located(path, error))


def located(path, error):
    """Return the problem of an error raised at data ``path``."""
    inner = getattr(error, "path", None)
    full = f"{path}.{inner}" if path and inner else path or inner or ""
    return problem(full, error.code, error, error.suggestions)


def format_error(data):
    """Return the ``ValidationError`` for data that is not format 2, else ``None``."""
    if not isinstance(data, dict):
        return ValidationError(
            f"plant dict = {type(data).__name__}; expected a mapping", code="invalid_format"
        )
    if data.get("format") == FORMAT:
        return None
    if "version" in data:
        return ValidationError(
            f"plant dict version = {data['version']!r}; expected format {FORMAT}",
            code="old_format",
            path="version",
        )
    return ValidationError(
        f"plant dict format = {data.get('format')!r}; expected {FORMAT}",
        path="format",
        code="invalid_format",
    )


def plain_value(value):
    """Return a parameter value as plain JSON."""
    return to_plain(to_jsonable_python(value))


def tree_params(module):
    """Return every initialized parameter of the tree as ``{dotted path: plain value}``."""
    return {
        path: plain_value(parameter.value)
        for path, parameter in module.named_parameters()
        if parameter.initialized
    }


def keep_stated(stated, current, parse):
    """Return ``stated`` while it parses to ``current``, else ``None``."""
    try:
        return stated if stated is not None and parse(stated) == current else None
    except (PydanticError, ValueError, TypeError, GeminiError):
        return None


def _fluids(root, stated, baselines):
    default = runtime.get_default_fluid()
    result = {}
    for path, module in root.named_modules():
        current = module._fluid
        kept = keep_stated(stated.get(path), current, Fluid.model_validate)
        if kept is not None:
            result[path] = kept
        elif path in stated or current != baselines.get(path, default):
            result[path] = current.model_dump(mode="json")
    return result


def _boundary(root):
    return {
        path: to_plain(module.boundary) for path, module in root.named_modules() if module.boundary
    }


def _bindings(root, stated):
    """Return the flat bindings of each path: stated while they still say the same."""
    modules = dict(root.named_modules())
    result = {}
    for path, current in root.bindings.items():
        target = modules.get(path)
        kept = keep_stated(stated.get(path), current, partial(design.sectioned, target))
        result[path] = kept if kept is not None else design.flat(target, current)
    return result


def _dated_params(entries):
    return [DatedParams.model_validate(item) for item in entries]


def _own_history(path, module, derived):
    """Return the dated entries of ``module`` without the values a deriving module computed.

    A module whose entries then all say the same has no history of its own: the deriving module
    writes the history and rebuilds these dates when it is read. ``None`` then.
    """
    names = {name for name in module._parameters if join_path(path, name) in derived}
    entries = [item.model_dump(mode="json") for item in module._param_history]
    for entry in entries:
        entry["params"] = {key: value for key, value in entry["params"].items() if key not in names}
    same = all(entry["params"] == entries[0]["params"] for entry in entries)
    return None if names and same else entries


def _history(root, stated):
    derived = design.derived_names(root)
    result = {}
    for path, module in root.named_modules():
        current = module._param_history
        if len(current) == 1 and current[0].valid_from is None:
            continue
        kept = keep_stated(stated.get(path), current, _dated_params)
        written = kept if kept is not None else _own_history(path, module, derived)
        if written is not None:
            result[path] = written
    return to_plain(result)


def to_sections(root, stated=None, baselines=None):
    """Return the ``fluids``, ``boundary``, ``bindings`` and ``param_history`` of a tree.

    ``stated`` holds the sections of the data the tree was read from and ``baselines`` the
    fluid each path had when it was created; empty sections other than ``bindings`` and
    ``param_history`` are left out.
    """
    stated = stated or {}
    sections = {
        "fluids": _fluids(root, stated.get("fluids", {}), baselines or {}),
        "boundary": _boundary(root),
        "bindings": _bindings(root, stated.get("bindings", {})),
        "param_history": _history(root, stated.get("param_history", {})),
    }
    return {
        key: value
        for key, value in sections.items()
        if value or key in ("bindings", "param_history")
    }


def _module_at(root, path):
    modules = dict(root.named_modules())
    if path not in modules:
        raise ValidationError(
            f"{root.path}: unknown module path {path!r}{did_you_mean(path, modules)}",
            suggestions=close_matches(path, modules),
            code="unknown_name",
        )
    return modules[path]


def _from_fluid(module, value, alone):
    """Set the fluid of ``module``; ``alone`` keeps it from passing to the children."""
    try:
        if alone:
            module._set_own_fluid(value)
        else:
            module.fluid = value
    except PydanticError as error:
        raise ValidationError(f"fluid: {error}", code="invalid_value") from error


def _from_boundary(module, value):
    if not isinstance(value, dict):
        raise ValidationError("boundary: expected a mapping", code="invalid_format")
    module.boundary = dict(value)


def _from_history(module, entries):
    if not isinstance(entries, list):
        raise ValidationError("param_history: expected a list", code="invalid_format")
    snapshots = []
    for index, item in enumerate(entries):
        try:
            snapshot = DatedParams.model_validate(item)
        except PydanticError as error:
            raise ValidationError(f"[{index}]: {error}", path=f"[{index}]") from error
        for name, value in snapshot.params.items():
            design.parameter(module, name).validate(value)
        snapshots.append(snapshot)
    module._param_history = snapshots
    if module._derives_params():
        for snapshot in snapshots:
            module.set_params("", snapshot.params, snapshot.valid_from)


def _from_order(section, entries):
    """Return the items of a section; the history of a child before its deriving parent's."""
    if section == "param_history":
        return sorted(entries.items(), key=lambda item: item[0].count("."), reverse=True)
    return entries.items()


def _names_below(entries, path):
    """Return whether a section names a module below ``path``: it then speaks for each itself."""
    prefix = f"{path}." if path else ""
    return any(name != path and name.startswith(prefix) for name in entries)


def from_sections(root, data, report):
    """Apply the sections of ``data`` to the tree, adding each problem to ``report``."""
    fluids = data.get("fluids", {})
    readers = {
        "fluids": lambda path, value: _from_fluid(
            _module_at(root, path), value, _names_below(fluids, path)
        ),
        "boundary": lambda path, value: _from_boundary(_module_at(root, path), value),
        "param_history": lambda path, value: _from_history(_module_at(root, path), value),
        "bindings": lambda path, value: design.set_bindings(root, path, value),
    }
    for section, read in readers.items():
        for path, value in _from_order(section, data.get(section, {})):
            if report.skips(path):
                continue
            with report.guard(f"{section}.{path}"):
                read(path, value)


def from_params(root, params, report, prefix="params"):
    """Set flat dotted ``params`` on the tree as undated design values.

    All in one call, so that values which need each other, a depth and its geotherm, may come in
    any order. If that fails, one by one, so that each problem is reported at its own name.
    """
    try:
        root.set_params("", params)
        return
    except GeminiError:
        pass
    for name, value in params.items():
        with report.guard(f"{prefix}.{name}"):
            root.set_params("", {name: value})


def tree_dict(module):
    """Return the parameters and sections of a module tree that is no plant, for a checkpoint."""
    derived = design.derived_names(module)
    params = {name: value for name, value in tree_params(module).items() if name not in derived}
    return {"format": FORMAT, "params": params} | to_sections(module)


def tree_from_dict(cls, data):
    """Build ``cls()`` and fill it from ``tree_dict``; raise on the first problem."""
    error = format_error(data)
    if error is not None:
        raise error
    report = Report(strict=True)
    root = cls()
    from_params(root, data.get("params", {}), report)
    from_sections(root, data, report)
    return root
