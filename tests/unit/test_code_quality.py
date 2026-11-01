"""The code-quality bar of ``.claude/docs/conventions.md`` cannot silently drop.

McCabe complexity is checked here with the limit of ``max-complexity`` in ``pyproject.toml``,
the one flake8 enforces.
"""

import ast
import functools
import io
import re
import subprocess
import tokenize
import tomllib
from collections import Counter

import pytest
from mccabe import PathGraphingAstVisitor

import gemini as gm
from gemini._utils import paths
from gemini._utils.files import from_json
from gemini.modules._utils.serialization import SECTIONS
from gemini.plants.plant import Plant
from tests.fixtures import ROOT

PYTHON_FOLDERS = ("gemini", "examples", "tests", "scripts")
SECTION_HEADERS = {
    "# Modules",
    "# Parameters",
    "# Inlets",
    "# Controls",
    "# Boundaries",
    "# States",
    "# Outputs",
    "# Outlets",
    "# Connections",
    "# Constraints",
}
TOOL_DIRECTIVE = re.compile(
    r"# (noqa: [A-Z]+\d+(, [A-Z]+\d+)*|type: ignore\[[\w-]+\]|pragma: no cover)"
)
NESTING = (ast.If, ast.For, ast.While, ast.With, ast.Try, ast.AsyncFor, ast.AsyncWith, ast.Match)
MAX_NESTING = 3
MAX_LINES = 40
LONG_FUNCTIONS = {}
EARLY_EXITS = (ast.Return, ast.Raise, ast.Continue, ast.Break)
BUILTIN_ERRORS = {"ValueError", "TypeError", "KeyError", "RuntimeError"}
RAISED_CLASSES = {
    "ValidationError",
    "DefinitionError",
    "PhysicsError",
    "RunError",
    "Cancelled",
    "NotImplementedYet",
    "GeminiError",
    "TraceError",
    "UnknownKey",
    "UnknownPort",
    "UnknownMember",
    "AttributeError",
    "NotImplementedError",
    "KeyError",
    "TypeError",
    "ValueError",
    "RuntimeError",
}
"""What the package raises; the built-ins are for the exempt topics of ``gemini._utils``."""
VALIDATORS = {"model_validator", "field_validator"}
DATA_FOLDER = re.compile(r"""/ *["'](inputs|assets)\b|["'][^"'`\n]*\b(inputs|assets)/""")
BUILDS_NO_DATA_PATH = {
    "gemini/_utils/paths.py",
    "scripts/test_changed.py",
    "tests/unit/scripts/test_test_changed.py",
    "tests/unit/test_code_quality.py",
}
"""Files allowed to name the data folders; the first is the one that knows where they are."""
SAMPLE_PROBLEM = re.compile(r"hackathon|challenge|inputs/examples", re.IGNORECASE)
"""What no file of ``gemini/`` may name: it is a general package, and a problem is only an input."""
VALUE_KEYS = {"plant", "size", "params", "inputs", *SECTIONS}
FRAMEWORK = re.compile("py" + "tor" + "ch|\\b" + "tor" + "ch\\b", re.IGNORECASE)
FRAMEWORK_STEM = "tor" + "ch"
"""Lowercase text that every ``FRAMEWORK`` match contains, checked before the slower regex."""
MATH_OPS = {
    "exp",
    "expm1",
    "log",
    "log10",
    "log1p",
    "sqrt",
    "power",
    "pow",
    "sin",
    "cos",
    "tan",
    "atan",
}
ARITHMETIC = (ast.Pow, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod)
FORMULA_EXCEPTIONS = {
    "gemini/modules/exchangers/heatexchanger.py: np.any": "health decides on scalars and arrays; "
    "ops has no reduction to a Python bool",
    "gemini/modules/module.py: literal 4": "how many parameters repr shows, not physics",
    "gemini/modules/module.py: np.float64": "the eager scope wraps a recorded float, not maths",
    "gemini/modules/module.py: np.ndarray": "a type test of the array path, not maths",
    "gemini/modules/pumps/esp.py: np.asarray": "the float32 cast of the retained precision",
    "gemini/modules/pumps/esp.py: np.float32": "the float32 cast of the retained precision",
    "gemini/modules/_utils/serialization.py: literal 2": "the plant file format number",
}
"""``file: marker`` of what a module may keep, each with its reason; see ``formula_markers``."""
SAME_FORM = {
    (
        "chemistry.py::co2_solubility_gas",
        "control/_physics.py::pid_derivative",
        "hydraulics.py::reynolds_number",
    ): "a product over a divisor: dissolved CO2, a PID term and the Reynolds number",
    (
        "hydraulics.py::productivity_pressure",
        "pumps/_physics.py::heat_rejected",
    ): "a less b over c: "
    "compressor heat and a linear inflow relation",
    (
        "combustion.py::released_heat",
        "ground.py::stored_heat",
        "pumps/_physics.py::line_shaft_friction_power",
        "storage/_physics.py::ice_stored_cold",
    ): "a product of three: stored heat, shaft friction, latent cold and burned heat",
    (
        "dispatch.py::circuit_flow",
        "pumps.py::best_efficiency_ratio",
        "refrigeration.py::cooling_minimum_sink_rate",
    ): "a over a "
    "product: a pump load ratio and a heat pump's smallest sink capacity rate",
}
"""Physics functions with one normalised body that are different relations, each with its reason."""


def tracked_files():
    """Return the repository's tracked and new, not ignored, files."""
    listed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    return sorted(path for path in set(listed) if (ROOT / path).is_file())


def python_files():
    """Return every Python file in the checked folders."""
    return [
        path for path in tracked_files() if path.endswith(".py") and path.startswith(PYTHON_FOLDERS)
    ]


@functools.cache
def tree(path):
    """Return the syntax tree of one file, parsed once per process."""
    return ast.parse((ROOT / path).read_text())


@functools.cache
def functions(path):
    """Return every function definition of one file, parsed once per process."""
    return tuple(
        node
        for node in ast.walk(tree(path))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    )


def body_lines(function):
    """Return the number of lines of a function body, excluding its docstring."""
    body = function.body
    if ast.get_docstring(function) is not None:
        body = body[1:]
    return body[-1].end_lineno - body[0].lineno + 1 if body else 0


def nesting(node, depth=0):
    """Return the deepest block nesting inside a node; an ``elif`` chain counts once."""
    deepest = depth
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        is_elif = isinstance(node, ast.If) and node.orelse == [child] and isinstance(child, ast.If)
        nested = isinstance(child, NESTING) and not is_elif
        deepest = max(deepest, nesting(child, depth + 1 if nested else depth))
    return deepest


PYTHON_FILES = python_files()
EXAMPLE_IMPORTS = ("gemini.engine", "gemini.modules", "gemini.types")
EXAMPLE_FILES = [path for path in PYTHON_FILES if path.startswith("examples/")]
IMPORTS_EXAMPLES = re.compile(r"^\s*(from|import) examples\b", re.MULTILINE)
CORE_MODULE_FILES = (
    "__init__.py",
    "call.py",
    "check.py",
    "container.py",
    "declarations.py",
    "module.py",
)
PACKAGE_FILES = [
    path
    for path in PYTHON_FILES
    if path.startswith("gemini/") and not path.startswith("gemini/_utils/")
]


def test_a_leaf_has_no_children_and_every_composite_is_a_plant():
    """Only a ``Plant`` or a group holds modules: a class computes or connects, never both."""
    composites = {
        name
        for name in gm.modules.names()
        if not issubclass(gm.modules.get(name), Plant) and not gm.modules.get(name)().is_leaf
    }
    assert composites == set()


def test_no_plant_class_writes_forward():
    """``Plant.forward`` is written once."""
    written = [
        name
        for name in gm.modules.names()
        if issubclass(gm.modules.get(name), Plant) and "forward" in vars(gm.modules.get(name))
    ]
    assert written == []


def test_no_module_defines_compute_outputs():
    """A leaf computes once, in ``forward``: no class of ``gemini/modules/`` has a second step."""
    found = [
        f"{path.relative_to(ROOT)}:{node.name}"
        for path in (ROOT / "gemini" / "modules").rglob("*.py")
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.ClassDef)
        for item in node.body
        if isinstance(item, ast.FunctionDef) and item.name == "_compute_outputs"
    ]
    assert not found


@pytest.mark.parametrize("path", PYTHON_FILES)
def test_only_section_headers_and_tool_directives_are_comments(path):
    """Explanations live in docstrings, never in comments inside code."""
    found = []
    source = io.StringIO((ROOT / path).read_text())
    for token in tokenize.generate_tokens(source.readline):
        text = token.string.strip()
        is_allowed = text in SECTION_HEADERS or TOOL_DIRECTIVE.fullmatch(text)
        if token.type == tokenize.COMMENT and not is_allowed:
            found.append(f"{path}:{token.start[0]}: {text}")
    assert found == []


@pytest.mark.parametrize("path", PYTHON_FILES)
def test_functions_nest_at_most_three_blocks(path):
    """Guard clauses keep every function at most three blocks deep."""
    deep = [
        f"{path}:{function.lineno} {function.name} ({nesting(function)})"
        for function in functions(path)
        if nesting(function) > MAX_NESTING
    ]
    assert deep == []


@pytest.mark.parametrize("path", PYTHON_FILES)
def test_functions_are_short_or_documented_exceptions(path):
    """Functions stay within about 40 lines; each longer one is listed with its reason.

    The ``__init__`` of a module or plant class is exempt: it is one list of declarations.
    """
    long = {
        f"{path}::{function.name}"
        for function in functions(path)
        if body_lines(function) > MAX_LINES
        and not (
            path.startswith(("gemini/plants/", "gemini/modules/")) and function.name == "__init__"
        )
    }
    assert long == {name for name in LONG_FUNCTIONS if name.startswith(f"{path}::")}


def test_long_function_exceptions_exist():
    """Every listed long-function exception names an existing function."""
    listed_paths = {name.partition("::")[0] for name in LONG_FUNCTIONS}
    names = {
        f"{path}::{function.name}"
        for path in PYTHON_FILES
        if path in listed_paths
        for function in functions(path)
    }
    assert set(LONG_FUNCTIONS) <= names


@pytest.mark.parametrize("path", PYTHON_FILES)
def test_no_else_after_an_early_exit(path):
    """A block that ends in ``return``, ``raise``, ``continue`` or ``break`` has no ``else``."""
    found = [
        f"{path}:{node.lineno}"
        for node in ast.walk(ast.parse((ROOT / path).read_text()))
        if isinstance(node, ast.If) and node.orelse and isinstance(node.body[-1], EARLY_EXITS)
    ]
    assert found == []


def raised_name(node):
    """Return the class name a ``raise`` statement raises, or None."""
    exception = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
    return exception.id if isinstance(exception, ast.Name) else None


def is_validator(function):
    """Tell whether a function is a validator, which must raise ``ValueError``."""
    return any(
        isinstance(decorator, ast.Call) and getattr(decorator.func, "id", None) in VALIDATORS
        for decorator in function.decorator_list
    )


@pytest.mark.parametrize("path", PACKAGE_FILES)
def test_package_code_raises_gemini_errors(path):
    """Deliberate errors use ``gm.errors``; ``gemini._utils`` topics and validators are exempt."""
    found = [
        f"{path}:{node.lineno} {raised_name(node)}"
        for function in functions(path)
        if not is_validator(function)
        for node in ast.walk(function)
        if isinstance(node, ast.Raise) and node.exc and raised_name(node) in BUILTIN_ERRORS
    ]
    assert found == []


@pytest.mark.parametrize("path", PACKAGE_FILES)
def test_package_code_raises_only_the_allowed_classes(path):
    """A raise names a public class of ``gm.errors``, a private lookup or a Python protocol error.

    ``TraceError`` is internal to ``gemini/compiler/graph/``; a former class has no way back in.
    """
    found = [
        f"{path}:{node.lineno} {raised_name(node)}"
        for function in functions(path)
        for node in ast.walk(function)
        if isinstance(node, ast.Raise) and node.exc and _named_class(raised_name(node))
        if raised_name(node) not in RAISED_CLASSES
    ]
    assert found == []
    if not str(path).startswith("gemini/compiler/graph/"):
        assert "TraceError" not in {raised_name(node) for node in _raises(path)}


def _raises(path):
    return [
        node
        for function in functions(path)
        for node in ast.walk(function)
        if isinstance(node, ast.Raise) and node.exc
    ]


def _named_class(name):
    return bool(name) and name[0].isupper()


def formula_markers(source):
    """Return the marks of a formula in a module's source, each once with its line."""
    found = {}
    for node in ast.walk(ast.parse(source)):
        marker = None
        if isinstance(node, ast.BinOp) and isinstance(node.op, ARITHMETIC):
            marker = type(node.op).__name__
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            owner, name = node.value.id, node.attr
            if owner in ("math", "np", "numpy") or (owner == "ops" and name in MATH_OPS):
                marker = f"{owner}.{name}"
        elif isinstance(node, ast.Constant) and type(node.value) in (int, float):
            marker = None if node.value in (0, 1) else f"literal {node.value}"
        if marker:
            found.setdefault(marker, node.lineno)
    return found


MODULE_FILES = [
    path
    for path in PACKAGE_FILES
    if path.startswith("gemini/modules/")
    and not path.endswith(("/_physics.py", "/declarations.py"))
]
PHYSICS_FILES = [
    path
    for path in PACKAGE_FILES
    if path.startswith("gemini/physics/") or path.endswith("/_physics.py")
]
CATEGORY_PHYSICS = [path for path in PHYSICS_FILES if path.startswith("gemini/modules/")]
PHYSICS_IMPORTS = ("gemini.errors", "gemini.ops", "gemini.physics", "gemini.types", "gemini.units")


@pytest.mark.parametrize("path", MODULE_FILES)
def test_modules_hold_no_formulas(path):
    """Physics lives in ``gemini/physics/`` or a ``_physics.py``: a module declares and wires."""
    markers = formula_markers((ROOT / path).read_text())
    found = {f"{path}: {marker}": line for marker, line in markers.items()}
    assert {name: line for name, line in found.items() if name not in FORMULA_EXCEPTIONS} == {}


def test_formula_exceptions_exist():
    """Every listed exception still names something the scan finds."""
    for name in FORMULA_EXCEPTIONS:
        path, _, marker = name.partition(": ")
        assert marker in formula_markers((ROOT / path).read_text())


class _Names(ast.NodeTransformer):
    """Replace argument and local names by their order of appearance."""

    def __init__(self):
        self.names = {}

    def visit_Name(self, node):
        """Rename a local or an argument; leave modules, functions and constants alone."""
        if isinstance(node.ctx, ast.Store) or node.id in self.names:
            node.id = self.names.setdefault(node.id, f"name{len(self.names)}")
        return node


def normalised_body(function):
    """Return the body of a function without docstring, annotations and its own names."""
    names = _Names()
    for argument in function.args.posonlyargs + function.args.args + function.args.kwonlyargs:
        names.names[argument.arg] = f"name{len(names.names)}"
    body = function.body[1:] if ast.get_docstring(function) else function.body
    return "".join(ast.dump(names.visit(statement)) for statement in body)


def is_one_operation(function):
    """Tell whether a body is one operator on two names: a definition, not a formula."""
    body = function.body[1:] if ast.get_docstring(function) else function.body
    value = body[0].value if len(body) == 1 and isinstance(body[0], ast.Return) else None
    operands = (getattr(value, "left", None), getattr(value, "right", None))
    return isinstance(value, ast.BinOp) and all(isinstance(item, ast.Name) for item in operands)


def physics_copies():
    """Return groups of public and private physics functions with one normalised body."""
    bodies = {}
    for path in PHYSICS_FILES:
        for function in ast.parse((ROOT / path).read_text()).body:
            if isinstance(function, ast.FunctionDef) and not is_one_operation(function):
                short = path.removeprefix("gemini/physics/").removeprefix("gemini/modules/")
                name = f"{short}::{function.name}"
                bodies.setdefault(normalised_body(function), []).append(name)
    return [tuple(sorted(names)) for names in bodies.values() if len(names) > 1]


def port_roles():
    """Return the port roles of the naming rule in ``.claude/docs/glossary.md``."""
    section = (ROOT / ".claude/docs/glossary.md").read_text().split("## Port roles")[1]
    return set(re.findall(r"`(\w+)`", section.split("## ")[0]))


@pytest.mark.parametrize("name", gm.modules.names())
def test_every_port_follows_the_naming_rule(name):
    """Every port is ``<role>_in`` or ``<role>_out``, the role from the glossary."""
    described = gm.modules.get(name)().describe()
    roles = port_roles()
    wrong = [
        port
        for port, suffix in [(port, "_in") for port in described["inlets"]]
        + [(port, "_out") for port in described["outlets"]]
        if not port.endswith(suffix)
        or re.sub(r"branch\d+", "branch", port.removesuffix(suffix)) not in roles | {"branch"}
    ]
    assert wrong == []


def gemini_imports(path):
    """Return the absolute ``gemini`` packages one file imports, ``gemini.ops`` for ``ops``."""
    found = set()
    for node in ast.walk(ast.parse((ROOT / path).read_text())):
        if isinstance(node, ast.ImportFrom) and node.module == "gemini":
            found |= {f"gemini.{alias.name}" for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and (node.module or "").startswith("gemini."):
            found.add(node.module)
    return found


@pytest.mark.parametrize("path", CATEGORY_PHYSICS)
def test_category_physics_imports_only_the_shared_layers(path):
    """A ``_physics.py`` reads the shared physics, never another category's ``_physics.py``."""
    outside = [
        name
        for name in gemini_imports(path)
        if not any(name == allowed or name.startswith(f"{allowed}.") for allowed in PHYSICS_IMPORTS)
    ]
    assert outside == []


@pytest.mark.parametrize("path", CATEGORY_PHYSICS)
def test_category_physics_serves_its_own_category(path):
    """A function a second category needs moves up into ``gemini/physics/``."""
    category = path.split("/")[2]
    users = [
        other
        for other in PACKAGE_FILES
        if f"gemini.modules.{category}" in (ROOT / other).read_text()
        and "_physics" in (ROOT / other).read_text()
        and not other.startswith((f"gemini/modules/{category}/", "gemini/modules/_utils/"))
    ]
    assert users == []


def test_no_two_physics_functions_share_a_body():
    """Every formula exists once; a copy with renamed arguments counts as a copy."""
    assert set(physics_copies()) == set(SAME_FORM)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("x = a * 2", {"Mult": 1, "literal 2": 1}),
        ("x = ops.exp(a)", {"ops.exp": 1}),
        ("x = ops.where(a, 0, 1)", {}),
        ("x = math.pi", {"math.pi": 1}),
        ("x = np.sum(a)", {"np.sum": 1}),
    ],
)
def test_formula_markers_find_a_formula(source, expected):
    """The scan sees arithmetic, maths calls and numbers other than 0 and 1."""
    assert formula_markers(source) == expected


def test_a_copy_with_other_argument_names_has_the_same_body():
    """The normalised body ignores docstrings and argument names, not the formula."""
    first, second, third = ast.parse(
        'def f(a, b):\n    """Doc."""\n    return a * b + 1\n'
        "def g(x, y):\n    return x * y + 1\n"
        "def h(x, y):\n    return x * y + 2\n"
    ).body
    assert normalised_body(first) == normalised_body(second) != normalised_body(third)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("def f():\n    if a:\n        for b in c:\n            pass\n", 2),
        ("def f():\n    if a:\n        pass\n    elif b:\n        pass\n", 1),
    ],
)
def test_nesting_counts_blocks_but_not_elif_chains(source, expected):
    """The nesting measure ignores ``elif`` chains."""
    assert nesting(ast.parse(source).body[0]) == expected


def imported_modules(path):
    """Return the dotted names one file imports."""
    found = set()
    for node in ast.walk(ast.parse((ROOT / path).read_text())):
        if isinstance(node, ast.Import):
            found |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            found.add(node.module or "")
    return found


@pytest.mark.parametrize("path", EXAMPLE_FILES)
def test_an_example_states_what_it_shows_and_how_to_run_it(path):
    """The module docstring comes first and has a ``Shows`` part and the command."""
    docstring = ast.get_docstring(ast.parse((ROOT / path).read_text()))
    assert docstring and "Shows " in docstring
    assert f"Run with ``python {path}``." in docstring


@pytest.mark.parametrize("path", EXAMPLE_FILES)
def test_an_example_ends_in_main_and_its_guard(path):
    """Every example has ``main()``, called from the ``__main__`` guard as its last statement."""
    last = ast.parse((ROOT / path).read_text()).body[-1]
    assert "main" in {function.name for function in functions(path)}
    assert isinstance(last, ast.If) and ast.unparse(last.test) == "__name__ == '__main__'"
    assert [ast.unparse(statement) for statement in last.body] == ["main()"]


@pytest.mark.parametrize("path", EXAMPLE_FILES)
def test_an_example_uses_the_public_api(path):
    """An example imports ``gemini`` and the public names of its folders, nothing internal."""
    internal = {
        name
        for name in imported_modules(path)
        if name.startswith("gemini.") and name not in EXAMPLE_IMPORTS
    }
    assert internal == set()


def test_examples_are_scripts_without_packages():
    """Nothing under ``examples/`` is a package, and it holds only scripts and its README."""
    files = [path for path in tracked_files() if path.startswith("examples/")]
    assert [path for path in files if path.endswith("__init__.py")] == []
    assert {path.rpartition(".")[2] for path in files} == {"py", "md"}


def test_nothing_imports_an_example():
    """No code imports from ``examples``: one test runs them, as subprocesses."""
    assert [
        path for path in PYTHON_FILES if IMPORTS_EXAMPLES.search((ROOT / path).read_text())
    ] == []


def test_only_the_paths_module_builds_a_path_to_the_data_folders():
    """Code reaches ``inputs/`` through ``gemini/_utils/paths.py``.

    An example is a standalone script on the public API, so it finds ``inputs/`` from ``__file__``.
    ``scripts/test_changed.py`` and its test match repository paths and build none.
    """
    code = [path for path in PYTHON_FILES if not path.startswith("examples/")]
    assert [
        path
        for path in code
        if path not in BUILDS_NO_DATA_PATH and DATA_FOLDER.search((ROOT / path).read_text())
    ] == []


def test_the_package_holds_no_data_files():
    """Every file of ``gemini/`` is Python: a plant is a class, its values are in ``inputs/``."""
    assert [
        path for path in tracked_files() if path.startswith("gemini/") and not path.endswith(".py")
    ] == []


def test_the_module_package_holds_only_its_core_classes_and_folders():
    """``gemini/modules/`` has the classes users subclass or build; the rest is in a folder."""
    top = [path for path in tracked_files() if re.fullmatch(r"gemini/modules/[^/]+", path)]
    assert sorted(top) == [f"gemini/modules/{name}" for name in CORE_MODULE_FILES]


def test_plants_holds_only_plant_classes():
    """Every public file of ``gemini/plants/`` defines a registered plant class."""
    files = [path for path in tracked_files() if re.fullmatch(r"gemini/plants/[^_/][^/]*", path)]
    assert "gemini/plants/plant.py" in files
    files.remove("gemini/plants/plant.py")
    for path in files:
        tree = ast.parse((ROOT / path).read_text())
        classes = {node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)}
        assert classes & set(gm.plants.names()), path


def test_a_file_of_example_values_has_only_the_allowed_keys_and_names_a_registered_plant():
    """``inputs/plants/`` holds the values of plants that exist, under the keys of a plant file."""
    files = sorted(paths.INPUTS.glob("plants/*.json"))
    assert files
    for path in files:
        values = from_json(path)
        assert set(values) <= VALUE_KEYS, path.name
        assert values["plant"] == path.stem and path.stem in gm.plants.names(), path.name
        assert isinstance(values["params"], dict), path.name


def test_the_package_knows_no_sample_problem():
    """Nothing under ``gemini/`` names the sample problems or the folder that holds them."""
    found = []
    for path in tracked_files():
        if path.startswith("gemini/"):
            text = (ROOT / path).read_text(encoding="utf-8")
            found += [path] if SAMPLE_PROBLEM.search(text) else []
    assert found == []


def test_the_repository_has_no_datasets_folder():
    """Data lives in ``inputs/``."""
    assert not (ROOT / "datasets").exists()
    assert [path for path in tracked_files() if path.startswith("datasets/")] == []


def test_no_framework_names_in_tracked_text_files():
    """Concepts are described directly, without naming the framework the design resembles.

    Only files containing ``FRAMEWORK_STEM`` are searched line by line: every match contains it,
    so the result is the same, and the case-insensitive regex over the 17 MB of example CSVs no
    longer pushes the test past the one-second budget on CI runners.
    """
    found = []
    for path in tracked_files():
        try:
            text = (ROOT / path).read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if FRAMEWORK_STEM not in text.lower():
            continue
        found.extend(
            f"{path}:{number}"
            for number, line in enumerate(text.splitlines(), 1)
            if FRAMEWORK.search(line)
        )
    assert found == []


RUN_FOLDERS = (
    "modules",
    "plants",
    "case",
    "physics",
    "ops",
    "runtime",
    "engine",
    "run",
    "types",
    "units",
    "errors",
    "_utils",
)
ABOVE_THE_RUN = ("compiler", "data", "study", "evaluate", "analysis")
REMOVED_FOLDERS = {"core", "base", "testing", "backends", "checks", "economics", "profiles"}
READ_WRITE_NAME = re.compile(r"^\s*(?:def|class) (_?(?:read|write|load|save|parse|dump)_\w*)", re.M)
"""What a reader or a writer is never called: ``from_<format>`` and ``to_<format>`` are the rule."""


IMPORTS = re.compile(
    r"^\s*from (gemini[\w.]*) import (\([^)]*\)|[^\n]*)|^\s*import (gemini[\w.]*)", re.M
)
"""An absolute import of ``gemini``: from what, which names, or the module it names."""


def every_import(path):
    """Return the absolute names one file imports, inside functions too, with each ``a.b`` name.

    A regular expression on the text: these guards read every file, so they stay within the budget.
    """
    found = set()
    for module, names, plain in IMPORTS.findall((ROOT / path).read_text()):
        found.add(module or plain)
        found |= {
            f"{module}.{name.split()[0]}"
            for name in names.strip("()\n ").split(",")
            if name.strip()
        }
    return found


def test_the_run_folders_import_nothing_above_the_run():
    """A run needs no compiler, no data readers and no evaluation."""
    wrong = {
        (path, name)
        for path in PACKAGE_FILES + [f for f in PYTHON_FILES if f.startswith("gemini/_utils/")]
        if path.split("/")[1] in RUN_FOLDERS
        for name in every_import(path)
        if name.startswith(tuple(f"gemini.{folder}" for folder in ABOVE_THE_RUN))
    }
    assert wrong == set()


CASE_NEVER_IMPORTS = (
    "gemini.run",
    "gemini.engine",
    "gemini.evaluate",
    "gemini.study",
    "gemini.compiler",
    "gemini.data",
    "gemini.analysis",
)


def test_the_case_imports_nothing_that_runs_or_judges():
    """The case sits above the plants and below the run: it reads no run, evaluation or study."""
    assert [
        (path, name)
        for path in PACKAGE_FILES
        if path.startswith("gemini/case/")
        for name in every_import(path)
        if name.startswith(CASE_NEVER_IMPORTS)
    ] == []


def test_the_case_has_no_default_but_absent():
    """A field of ``gm.case`` is required or ``None``; ``over`` and ``when`` are the two choices."""
    import gemini as gm
    from gemini.case._utils.section import Section

    allowed = {("Constraint", "over"): "each", ("Constraint", "when"): "always"}
    found = []
    for name in gm.case.__all__:
        cls = getattr(gm.case, name)
        if not (isinstance(cls, type) and issubclass(cls, Section)):
            continue
        for field, info in cls.model_fields.items():
            default = None if info.is_required() else info.default
            if default is not None and allowed.get((name, field)) != default:
                found.append(f"{name}.{field}")
    assert found == []


def _open_objects(node, path="case"):
    """Return the paths of the objects of a JSON Schema that accept unknown keys."""
    if isinstance(node, list):
        return [x for n, item in enumerate(node) for x in _open_objects(item, f"{path}[{n}]")]
    if not isinstance(node, dict):
        return []
    found = [path] if "properties" in node and node.get("additionalProperties") is not False else []
    return found + [x for key, item in node.items() for x in _open_objects(item, f"{path}.{key}")]


def test_the_case_schema_is_closed_at_every_level():
    """``additionalProperties`` is false in every object of the case schema."""
    assert _open_objects(gm.Case.schema()) == []


SHAPE_NAMES = {"problem", "problems", "_problems", "root_problems", "PROBLEM_SCHEMA"}
"""The names of the public return shape ``{path, code, message, suggestions}``, the one use.

The shape is in ``api.md`` and ``docs/schemas/problem.schema.json``: an error or a failed run row,
not an input. It keeps its name.
"""
OLD_INPUT_WORDS = re.compile(
    r"\bProblem\b|gm\.Problem|problem\.json|problem file|(?:sample|hackathon) problem|problem's"
)
"""What named the input that ``gm.Case`` replaced, in prose."""


def _identifiers(tree):
    """Return every name a module defines or uses: variables, attributes, arguments, definitions."""
    names = set()
    for node in ast.walk(tree):
        names |= {getattr(node, key, None) for key in ("id", "attr", "name", "arg")}
    return {name for name in names if isinstance(name, str)}


def test_no_problem_name_is_left_in_the_package():
    """The input is a case: no name or docstring of ``gemini/`` calls it a problem.

    The return shape ``problem`` is the one use of the word, and ``gemini/types/shapes.py`` names
    it in prose.
    """
    found = []
    for path in PACKAGE_FILES:
        text = (ROOT / path).read_text()
        if "roblem" not in text:
            continue
        names = _identifiers(ast.parse(text)) - SHAPE_NAMES
        found += [f"{path}: {name}" for name in names if "problem" in name.lower()]
        if path != "gemini/types/shapes.py":
            found += [f"{path}: {m.group()}" for m in OLD_INPUT_WORDS.finditer(text)]
    assert found == []


def test_modules_never_import_plants():
    """A plant is built from modules and a run from plants, never the other way round."""
    assert [
        (path, name)
        for path in PACKAGE_FILES
        if path.startswith("gemini/modules/")
        for name in every_import(path)
        if name.startswith(("gemini.plants", "gemini.run.")) or name == "gemini.run"
    ] == []


def test_no_folder_keeps_a_removed_name():
    """The layers have one name each."""
    folders = {
        part
        for path in tracked_files()
        if path.startswith("gemini/")
        for part in path.split("/")[:-1]
    }
    assert folders & REMOVED_FOLDERS == set()


def test_no_reader_or_writer_breaks_the_naming_rule():
    """Every reader is ``from_<format>`` and every writer ``to_<format>``."""
    assert [
        f"{path}::{name}"
        for path in PYTHON_FILES
        if path.startswith("gemini/")
        for name in READ_WRITE_NAME.findall((ROOT / path).read_text())
    ] == []


GEMINI_FILES = [path for path in PYTHON_FILES if path.startswith("gemini/")]
LEGACY_FOLDERS = ("gemini/plants/_utils/legacy/", "gemini/data/legacy/")
OLD_NAME = re.compile(r"legacy|compat|deprecated|^old_|_old($|_)|_v1|_v2", re.IGNORECASE)
"""What a kept old name, shape or call path is called."""
NAME_ALLOWANCE = {
    "from_legacy": "gm.Plant.from_legacy is the public reader of the old GEMINI project folder",
    "legacy_project": "paths.legacy_project is the sample folder of that reader",
}
"""Names with ``OLD_NAME`` outside the legacy folders, each with its reason."""
WRAPPER_ALLOWANCE = {
    "gemini/plants/plant.py::from_legacy": "the public name is api.md; the reader is its folder",
    "gemini/modules/module.py::fluid": "a property setter that calls the hook plants override",
}
"""Public functions that only call another gemini function, each with its reason."""
HOOKS = {"model_validator", "field_validator", "model_serializer", "field_serializer"}
"""Decorators that call a private function without a visible reference."""


@pytest.fixture(scope="module")
def package_trees():
    """Return the syntax tree of every Python file, parsed before the test is timed."""
    return {path: tree(path) for path in PYTHON_FILES}


def complex_functions(syntax, limit):
    """Return ``(name, line, complexity)`` of every function over ``limit``, as flake8 counts."""
    visitor = PathGraphingAstVisitor()
    visitor.preorder(syntax, visitor)
    return [
        (graph.entity, graph.lineno, graph.complexity())
        for graph in visitor.graphs.values()
        if graph.complexity() > limit
    ]


def identifiers(syntax):
    """Return ``(line, name)`` of every name a file defines or binds."""
    found = []
    for node in ast.walk(syntax):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            found.append((node.lineno, node.name))
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            found.append((node.lineno, node.id))
        elif isinstance(node, ast.arg):
            found.append((node.lineno, node.arg))
        elif isinstance(node, ast.alias):
            found.append((node.lineno, node.asname or ""))
    return found


def old_names(syntax):
    """Return the names of one file that say they keep something old."""
    return sorted({name for _, name in identifiers(syntax) if OLD_NAME.search(name)})


def callee(node, known):
    """Return the name of the gemini function a call reaches, or ``None``."""
    target = node.func
    if isinstance(target, ast.Name):
        return target.id if target.id in known and not target.id[0].isupper() else None
    if not isinstance(target, ast.Attribute):
        return None
    root = target.value
    if isinstance(root, ast.Name) and root.id in known | {"self", "cls"}:
        return target.attr
    is_super = isinstance(root, ast.Call) and getattr(root.func, "id", "") == "super"
    return target.attr if is_super else None


def forwarded(node):
    """Return the names a call passes on, or ``None`` where it passes anything else."""
    items = [*node.args, *(keyword.value for keyword in node.keywords)]
    items = [item.value if isinstance(item, ast.Starred) else item for item in items]
    names = [item.id if isinstance(item, ast.Name) else None for item in items]
    return None if None in names else sorted(names)


def own_parameters(function):
    """Return the parameter names of a function without ``self`` and ``cls``."""
    arguments = function.args
    names = [item.arg for item in arguments.posonlyargs + arguments.args + arguments.kwonlyargs]
    names += [item.arg for item in (arguments.vararg, arguments.kwarg) if item]
    return sorted(name for name in names if name not in ("self", "cls"))


def gemini_names(syntax):
    """Return the names a file imports from gemini and the functions it defines at its top."""
    known = {node.name for node in syntax.body if isinstance(node, ast.FunctionDef)}
    for node in ast.walk(syntax):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("gemini"):
            known |= {item.asname or item.name for item in node.names}
        elif isinstance(node, ast.Import):
            known |= {
                item.asname or item.name.split(".")[0]
                for item in node.names
                if item.name.startswith("gemini")
            }
    return known


def wrappers(syntax, path):
    """Return ``path::name`` of every public function that only forwards its arguments."""
    known = gemini_names(syntax)
    found = []
    for function in ast.walk(syntax):
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = function.body[1:] if ast.get_docstring(function) else function.body
        only = body[0] if len(body) == 1 else None
        call = only.value if isinstance(only, (ast.Return, ast.Expr)) else None
        if function.name.startswith("_") or not isinstance(call, ast.Call):
            continue
        if callee(call, known) and forwarded(call) == own_parameters(function):
            found.append(f"{path}::{function.name}")
    return found


def private_functions_unused(trees):
    """Return ``path::name`` of every private function that nothing in the package names."""
    references = Counter()
    for syntax in trees.values():
        for node in ast.walk(syntax):
            if isinstance(node, ast.Name):
                references[node.id] += 1
            elif isinstance(node, ast.Attribute):
                references[node.attr] += 1
            elif isinstance(node, ast.alias):
                references[node.name.split(".")[-1]] += 1
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                references[node.value] += 1
    return sorted(
        f"{path}::{node.name}"
        for path, syntax in trees.items()
        for node in ast.walk(syntax)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("_")
        and not node.name.startswith("__")
        and not references[node.name]
        and not hooked(node)
    )


def hooked(function):
    """Tell whether a decorator of a function is one that calls it without a reference."""
    names = {getattr(item, "id", getattr(item, "attr", "")) for item in function.decorator_list}
    names |= {getattr(getattr(item, "func", None), "id", "") for item in function.decorator_list}
    return bool(names & HOOKS)


def test_no_function_is_more_complex_than_the_flake8_limit(package_trees):
    """The limit of ``pyproject.toml`` holds in every file the lint covers, in the test run."""
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    limit = pyproject["tool"]["flake8"]["max-complexity"]
    paths = [path for path in PYTHON_FILES if path not in package_trees]
    trees = package_trees | {path: tree(path) for path in paths}
    assert {
        (path, *found)
        for path, syntax in trees.items()
        for found in complex_functions(syntax, limit)
    } == set()


def test_the_complexity_guard_counts_branches():
    """A function of eleven branches is over the limit of ten; one of three is not."""
    over = "def f(x):\n" + "".join(f"    if x == {n}:\n        return {n}\n" for n in range(11))
    assert complex_functions(ast.parse(over), 10) == [("f", 1, 12)]
    assert complex_functions(ast.parse("def g(x):\n    if x:\n        return 1\n"), 10) == []


def package_only(trees):
    """Return the trees of the files of ``gemini/``."""
    return {path: syntax for path, syntax in trees.items() if path.startswith("gemini/")}


def test_no_public_function_only_calls_another_with_its_arguments(package_trees):
    """A function that forwards its arguments is replaced by the one it calls, or is a hook."""
    trees = package_only(package_trees)
    found = [name for path, syntax in trees.items() for name in wrappers(syntax, path)]
    assert sorted(set(found) - set(WRAPPER_ALLOWANCE)) == []


def test_every_wrapper_allowance_is_still_a_wrapper(package_trees):
    """An allowance that no longer matches a wrapper is removed."""
    trees = package_only(package_trees)
    found = {name for path, syntax in trees.items() for name in wrappers(syntax, path)}
    assert set(WRAPPER_ALLOWANCE) <= found


def test_the_wrapper_guard_finds_a_forwarding_function():
    """Same arguments in any order are caught; another argument, a class or a builtin is not."""
    source = (
        "from gemini.units import convert\n"
        "def caught(value, unit):\n    return convert(unit, value=value)\n"
        "def method(self, a):\n    return self.other(a)\n"
        "def adds(value):\n    return convert(value, 1)\n"
        "def builds(value):\n    return Quantity(value)\n"
        "def sums(values):\n    return sum(values)\n"
        "def _private(value):\n    return convert(value)\n"
    )
    assert wrappers(ast.parse(source), "x.py") == ["x.py::caught", "x.py::method"]


def test_no_name_keeps_something_old_outside_the_legacy_folders(package_trees):
    """No ``legacy``, ``compat``, ``deprecated``, ``old_``, ``_old``, ``_v1``, ``_v2`` in a name."""
    found = [
        f"{path}: {name}"
        for path, syntax in package_only(package_trees).items()
        if not path.startswith(LEGACY_FOLDERS)
        for name in old_names(syntax)
        if name not in NAME_ALLOWANCE
    ]
    found += [
        path
        for path in tracked_files()
        if path.startswith("gemini/") and not path.startswith(LEGACY_FOLDERS)
        if OLD_NAME.search(path.removeprefix("gemini/"))
    ]
    assert found == []


def test_every_name_allowance_is_still_used(package_trees):
    """An allowed name that no file defines is removed from the allowance."""
    used = {name for syntax in package_only(package_trees).values() for name in old_names(syntax)}
    assert set(NAME_ALLOWANCE) <= used


def test_the_old_name_guard_finds_old_names_and_not_words_that_contain_them():
    """``old_value``, ``_compat`` and ``f_v2`` are caught; ``is_older`` and ``old`` are not."""
    caught = "def old_value(): pass\nclass Compat: pass\n_compat = 1\ndef f_v2(deprecated): pass\n"
    assert old_names(ast.parse(caught)) == ["Compat", "_compat", "deprecated", "f_v2", "old_value"]
    assert old_names(ast.parse("def is_older(folder, hold): pass\nold = 1\n")) == []


def test_no_private_function_is_unused(package_trees):
    """A private function that nothing in ``gemini/`` calls, passes or names is dead code."""
    assert private_functions_unused(package_only(package_trees)) == []


def test_the_unused_guard_finds_a_dead_function_and_not_a_used_or_hooked_one():
    """A name that is called, passed on, written as a string or decorated as a hook is used."""
    source = (
        "def _dead(): pass\n"
        "def _called(): pass\n"
        "def _passed(): pass\n"
        "def _named(): pass\n"
        "@model_validator(mode='after')\n"
        "def _hook(self): pass\n"
        "_called()\nrun(_passed)\ngetattr(x, '_named')\n"
    )
    assert private_functions_unused({"x.py": ast.parse(source)}) == ["x.py::_dead"]


DECLARATIONS = ("Parameter", "Control", "Boundary", "Output")


def declaration_calls(path):
    """Return the lines of the declarations in a file that give no ``description``."""
    tests = ast.walk(tree(path))
    named = {id(node.value) for node in tests if isinstance(node, ast.Attribute)}
    lines = []
    for node in ast.walk(tree(path)):
        if not isinstance(node, ast.Call) or id(node) in named:
            continue
        function = node.func
        name = function.id if isinstance(function, ast.Name) else None
        if isinstance(function, ast.Attribute) and isinstance(function.value, ast.Name):
            name = function.value.id
        if name in DECLARATIONS and not any(key.arg == "description" for key in node.keywords):
            lines.append(node.lineno)
    return lines


@pytest.mark.parametrize(
    "path",
    [
        path
        for path in python_files()
        if path.startswith(("gemini/modules/", "gemini/plants/"))
        and path != "gemini/modules/declarations.py"
    ],
)
def test_every_public_declaration_has_a_description(path):
    """A parameter, control, boundary or output says what it means, so an agent can fill it."""
    assert declaration_calls(path) == [], f"{path}: declaration without description="
