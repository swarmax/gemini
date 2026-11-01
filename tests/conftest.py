"""Shared test-tier configuration."""

import copy
import warnings
from pathlib import Path
from time import perf_counter

import pandas as pd
import pytest

import gemini as gm
from gemini._utils import paths
from gemini.modules import Module
from tests.cpu_budget import BUDGET_S, exceeds_budget, measure_cpu
from tests.fixtures.sample_cases import example_plant

TIER_MARKERS = {
    "unit": pytest.mark.unit,
    "integration": pytest.mark.integration,
    "e2e": pytest.mark.e2e,
}

ROOT = Path(__file__).parents[1]
CPU_SECONDS = pytest.StashKey[float]()
SESSION_BUDGET_S = 300.0
DATASETS = {
    "fast": paths.doublet_heat("doublet_2024_15min_month.csv"),
    "slow": paths.doublet_heat("doublet_2024_15min.csv"),
}


@pytest.fixture(scope="session")
def dataset_name(request):
    """Return the selected committed dataset name."""
    return request.config.getoption("--dataset")


@pytest.fixture(scope="session")
def dataset_path(dataset_name):
    """Return the selected committed dataset path."""
    return DATASETS[dataset_name]


@pytest.fixture(scope="session")
def selected_frame(dataset_path):
    """Load the selected committed frame once for read-only test use."""
    return pd.read_csv(dataset_path, parse_dates=["time"])


@pytest.fixture(scope="session")
def selected_dataset(selected_frame):
    """Build the selected immutable in-memory dataset once."""
    return gm.Dataset.from_frame(selected_frame, time_column="time")


@pytest.fixture(scope="session")
def fast_frame():
    """Load the short-window source once, independent of e2e dataset selection."""
    return pd.read_csv(DATASETS["fast"], parse_dates=["time"])


@pytest.fixture(scope="session")
def fast_dataset(fast_frame):
    """Build the immutable fast dataset once for behaviour tests."""
    return gm.Dataset.from_frame(fast_frame, time_column="time")


@pytest.fixture(scope="session")
def reference_dataset():
    """Load the 96-row June window tied to immutable engine-reference goldens."""
    frame = pd.read_csv(DATASETS["slow"], parse_dates=["time"], nrows=96)
    return gm.Dataset.from_frame(frame, time_column="time")


@pytest.fixture(scope="session")
def shared_plant():
    """Load and validate one read-only shared plant design."""
    with warnings.catch_warnings(record=True) as warnings_seen:
        warnings.simplefilter("always")
        plant = example_plant("DoubletHeatPlant")
    assert not warnings_seen
    return plant


def shipped_module_classes():
    """Return every concrete module class shipped in ``gemini`` and a class per spec plant."""
    exported = [getattr(gm.modules, name) for name in gm.modules.__all__]
    classes = [
        item
        for item in exported
        if isinstance(item, type) and issubclass(item, Module) and item is not Module
    ]
    return tuple(classes)


def pytest_generate_tests(metafunc):
    """Run a test that takes ``module_class`` once per shipped module class."""
    if "module_class" in metafunc.fixturenames:
        classes = shipped_module_classes()
        metafunc.parametrize("module_class", classes, ids=[cls.__name__ for cls in classes])


@pytest.fixture
def fresh_plant(shared_plant):
    """Give mutating tests a cheap isolated copy of the shared plant."""
    return copy.deepcopy(shared_plant)


@pytest.fixture(scope="module")
def module_plant(shared_plant):
    """Give a module-scoped shared workflow one isolated plant copy."""
    return copy.deepcopy(shared_plant)


def pytest_collection_modifyitems(items):
    """Mark every test from its top-level test folder."""
    tests = Path(__file__).parent
    for item in items:
        try:
            tier = item.path.relative_to(tests).parts[0]
        except ValueError:
            continue
        marker = TIER_MARKERS.get(tier)
        if marker is not None:
            item.add_marker(marker)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item):
    """Record the CPU time of the test call itself, without fixture setup or teardown."""
    try:
        with measure_cpu() as cpu:
            return (yield)
    finally:
        item.stash[CPU_SECONDS] = cpu.seconds


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Fail a development-profile fast-tier call whose CPU time exceeds the one-second budget.

    Elapsed time is not the measure: under a parallel run or a busy machine a test is descheduled
    and its wall time grows without any extra work. See ``tests/cpu_budget.py``.
    """
    outcome = yield
    report = outcome.get_result()
    markers = {marker.name for marker in item.iter_markers()}
    cpu_seconds = item.stash.get(CPU_SECONDS, 0.0)
    if (
        report.when == "call"
        and report.passed
        and exceeds_budget(cpu_seconds)
        and item.config.getoption("--profile") == "development"
        and not markers.intersection({"e2e", "slow"})
    ):
        report.outcome = "failed"
        report.longrepr = (
            f"Fast-tier test used {cpu_seconds:.2f}s of CPU time in {report.duration:.2f}s "
            f"elapsed (budget: {BUDGET_S:.2f}s CPU). "
            "Move it to slow or make it faster, see .claude/docs/testing.md."
        )


class DevelopmentBudget:
    """Fail a development-profile run whose wall time exceeds the session budget.

    Registered only in the controlling process, so under xdist it measures the whole parallel
    run and sees every worker's reports.
    """

    def __init__(self):
        """Start timing when the controller configures the session."""
        self.started = perf_counter()
        self.durations = []
        self.elapsed = 0.0

    def pytest_runtest_logreport(self, report):
        """Remember each test phase duration for the slowest-test listing."""
        self.durations.append((report.duration, report.when, report.nodeid))

    @pytest.hookimpl(trylast=True)
    def pytest_sessionfinish(self, session):
        """Turn an over-budget run into a failed run."""
        self.elapsed = perf_counter() - self.started
        if self.elapsed > SESSION_BUDGET_S:
            session.exitstatus = pytest.ExitCode.TESTS_FAILED

    def pytest_terminal_summary(self, terminalreporter):
        """Explain an over-budget run with its ten slowest test phases."""
        if self.elapsed <= SESSION_BUDGET_S:
            return
        terminalreporter.section("development profile over budget", red=True)
        terminalreporter.write_line(
            f"Run took {self.elapsed:.0f}s (budget: {SESSION_BUDGET_S:.0f}s). "
            "See .claude/docs/testing.md, section 'Test profiles'. Slowest tests:"
        )
        for duration, when, nodeid in sorted(self.durations, reverse=True)[:10]:
            terminalreporter.write_line(f"{duration:8.2f}s {when:<8} {nodeid}")


def pytest_configure(config):
    """Register the session budget for development-profile runs in the controller."""
    is_worker = hasattr(config, "workerinput")
    if config.getoption("--profile") == "development" and not is_worker:
        config.pluginmanager.register(DevelopmentBudget(), "development-budget")
