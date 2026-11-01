"""Run the development test profile: tests of what changed and of everything that imports it.

Usage::

    python scripts/test_changed.py                 # changes against HEAD plus the working tree
    python scripts/test_changed.py --base origin/main
    python scripts/test_changed.py --dry-run       # print the selection only
    python scripts/test_changed.py -- -x           # extra pytest arguments after --

Selection rules, applied to the changed files:

1. A changed test file runs itself; a changed ``conftest.py`` runs every test below it.
2. ``pyproject.toml``, ``tests/conftest.py`` or ``tests/xdist_plugin.py`` select every test.
3. Every Python module that imports a changed module, directly or transitively (importing
   ``a.b.c`` also imports the packages ``a`` and ``a.b``), is affected. Affected test files run,
   and every affected ``gemini/<path>/<name>.py`` runs its mirror
   ``tests/unit/<path>/test_<name>.py``. Imports made by ``conftest.py`` files are not followed,
   otherwise every change would select the whole suite through shared fixtures.
4. Any changed file under ``examples/`` selects ``tests/e2e/test_examples.py``.
5. Any other changed file selects the tests whose source, or whose ``conftest.py``, names its
   repository path. A file below ``inputs/`` also selects its readers: the tests that name its
   folder, what ``INPUT_READERS`` gives for a folder read through the public API, or a constant
   of ``tests/fixtures/__init__.py`` that holds the folder, and the example test.
6. ``tests/unit/test_code_quality.py`` always runs, whatever changed, because the structure and
   style rules apply to every edit.

The selection runs in parallel on the fast dataset and skips tests marked ``slow``; those belong
to the release profile. The import graph is cached in ``.tmp/test_changed/imports.json``.
"""

import argparse
import ast
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ("gemini", "tests", "scripts")
SELECT_ALL = {"pyproject.toml", "tests/conftest.py", "tests/xdist_plugin.py"}
EXAMPLES_TEST = "tests/e2e/test_examples.py"
FIXTURE_PATHS = "tests/fixtures/__init__.py"
INPUTS = "inputs/"
INPUT_READERS = {"examples": "sample_cases", "plants": "example("}
"""What a test names to read a folder of ``inputs/`` through the public API."""
QUALITY_TEST = "tests/unit/test_code_quality.py"
QUALITY_REASON = "always runs: code-quality rules apply to every change"
CACHE = ROOT / ".tmp/test_changed/imports.json"


def git_lines(*args):
    """Return the non-empty output lines of one git command run in the repository root."""
    completed = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True)
    return [line for line in completed.stdout.splitlines() if line]


def changed_files(base=None):
    """Return changed paths: committed since ``base``, uncommitted and untracked files."""
    paths = set(git_lines("diff", "--name-only", "HEAD"))
    paths.update(git_lines("ls-files", "--others", "--exclude-standard"))
    if base is not None:
        paths.update(git_lines("diff", "--name-only", f"{base}...HEAD"))
    return sorted(paths)


def module_name(path):
    """Return the dotted module name of a repository Python path, or ``None``."""
    parts = Path(path).with_suffix("").parts
    if Path(path).suffix != ".py" or not parts or parts[0] not in PACKAGES:
        return None
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def with_parents(name):
    """Return a dotted name together with every parent package it imports first."""
    parts = name.split(".")
    return {".".join(parts[:index]) for index in range(1, len(parts) + 1)}


def _absolute(node, package):
    """Resolve the module named by an ``ImportFrom`` node, including relative imports."""
    if not node.level:
        return node.module
    base = package.split(".")[: len(package.split(".")) - node.level + 1]
    return ".".join([*base, node.module] if node.module else base)


def imported_names(source, name, is_package):
    """Return the dotted names one module imports, each with its parent packages."""
    package = name if is_package else name.rpartition(".")[0]
    names = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = _absolute(node, package)
            names.add(module)
            names.update(f"{module}.{alias.name}" for alias in node.names)
    return set().union(*(with_parents(item) for item in names if item))


def python_files(root):
    """Return the repository-relative Python files of every scanned package."""
    return sorted(
        path.relative_to(root).as_posix()
        for package in PACKAGES
        for path in (root / package).rglob("*.py")
    )


def import_graph(root=ROOT, cache=None):
    """Map every scanned Python file to the dotted names it imports, reusing cached entries."""
    cached = json.loads(cache.read_text()) if cache is not None and cache.exists() else {}
    graph, fresh = {}, {}
    for path in python_files(root):
        stat = (root / path).stat()
        key = [stat.st_mtime_ns, stat.st_size]
        entry = cached.get(path)
        if entry is None or entry["key"] != key:
            source = (root / path).read_text()
            names = imported_names(source, module_name(path), path.endswith("__init__.py"))
            entry = {"key": key, "imports": sorted(names)}
        fresh[path] = entry
        graph[path] = set(entry["imports"])
    if cache is not None:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(fresh))
    return graph


def affected_modules(changed, graph):
    """Return affected file paths with the changed module that made each one affected."""
    names = {module_name(path): path for path in changed if module_name(path)}
    affected = {path: path for path in names.values() if path in graph}
    pending = dict(names)
    while pending:
        name, origin = pending.popitem()
        for path, imports in graph.items():
            if path in affected or path.endswith("conftest.py") or name not in imports:
                continue
            affected[path] = origin
            pending[module_name(path)] = origin
    return affected


def is_test_file(path):
    """Return whether a repository path is a pytest test module."""
    return path.startswith("tests/") and Path(path).name.startswith("test_")


def mirror_test(path):
    """Return the mirrored unit-test path of one ``gemini`` source file, or ``None``."""
    if not path.startswith("gemini/") or path.endswith("__init__.py"):
        return None
    relative = Path(path).relative_to("gemini")
    return (Path("tests/unit") / relative.parent / f"test_{relative.name}").as_posix()


def tests_below(directory, tests):
    """Return every test path inside one directory."""
    prefix = "" if directory in {"", "."} else f"{directory}/"
    return {test for test in tests if test.startswith(prefix)}


def data_names(path, root):
    """Return the texts by which a source reads ``path``: itself and, for inputs, its folder."""
    if not path.startswith(INPUTS):
        return {path}
    folder = Path(path).parts[1]
    name = INPUT_READERS.get(folder, folder)
    fixtures = root / FIXTURE_PATHS
    lines = fixtures.read_text().splitlines() if fixtures.exists() else []
    return {path, name} | {line.split()[0] for line in lines if name in line}


def naming_tests(path, tests, root):
    """Return tests whose own source, or a ``conftest.py`` above them, names ``path``."""
    names = data_names(path, root)
    selected = set()
    for conftest in sorted(root.glob("tests/**/conftest.py")):
        if any(name in conftest.read_text() for name in names):
            selected |= tests_below(conftest.parent.relative_to(root).as_posix(), tests)
    selected.update(
        test for test in tests if any(name in (root / test).read_text() for name in names)
    )
    return selected


def _select_changed_file(path, tests, root):
    """Return the tests and reason selected by one changed file before import analysis."""
    if path in SELECT_ALL:
        return set(tests), f"{path} configures every test"
    if Path(path).name == "conftest.py":
        return tests_below(Path(path).parent.as_posix(), tests), f"{path} scope"
    if is_test_file(path):
        return ({path} & tests), "changed test file"
    if path.startswith("examples/"):
        return ({EXAMPLES_TEST} & tests), f"runs example {path}"
    if path.startswith(INPUTS):
        return naming_tests(path, tests, root) | ({EXAMPLES_TEST} & tests), f"reads {path}"
    if module_name(path) is None and (root / path).is_file():
        return naming_tests(path, tests, root), f"names {path}"
    return set(), ""


def select_tests(changed, graph, root=ROOT):
    """Return ``{test path: reason}`` for the development profile."""
    tests = {path for path in graph if is_test_file(path)}
    selected = {}
    for path in changed:
        chosen, reason = _select_changed_file(path, tests, root)
        for test in sorted(chosen):
            selected.setdefault(test, reason)
    for path, origin in affected_modules(changed, graph).items():
        mirror = mirror_test(path)
        if mirror in tests:
            selected.setdefault(mirror, f"mirror of {path} (imports {origin})")
        if is_test_file(path):
            selected.setdefault(path, f"imports {origin}")
    if QUALITY_TEST in tests:
        selected.setdefault(QUALITY_TEST, QUALITY_REASON)
    return dict(sorted(selected.items()))


def pytest_command(selected, extra):
    """Return the parallel fast-data pytest command for a development selection."""
    return [
        sys.executable,
        "-m",
        "pytest",
        "-n",
        "auto",
        "-m",
        "not slow",
        "--dataset=fast",
        "--profile=development",
        *extra,
        *selected,
    ]


def parse_args(argv):
    """Parse command-line options; arguments after ``--`` go to pytest."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", help="also include changes committed since this git ref")
    parser.add_argument("--dry-run", action="store_true", help="print the selection only")
    parser.add_argument("pytest_args", nargs="*", help="extra pytest arguments after --")
    return parser.parse_args(argv)


def main(argv=None):
    """Select, print and run the development-profile tests; return the pytest exit code."""
    args = parse_args(argv)
    changed = changed_files(args.base)
    selected = select_tests(changed, import_graph(ROOT, CACHE))
    print(f"Changed files: {len(changed)}; selected test files: {len(selected)}")
    for test, reason in selected.items():
        print(f"  {test}  <- {reason}")
    if not selected:
        print("No tests are affected by the changes.")
        return 0
    if args.dry_run:
        return 0
    return subprocess.call(pytest_command(list(selected), args.pytest_args), cwd=ROOT)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
