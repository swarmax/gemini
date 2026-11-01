"""Check that one source gives the same numbers on floats, arrays and traced graphs.

``assert_function_matches`` compares a physics function called once per row on Python floats
with one traced run on the stacked columns (``gemini.compiler.graph.run_function``), so an array
row can cross a ``where`` around a ``check`` as it does in the engine; a direct call on arrays
raises at
the first failing row. ``assert_module_matches`` compares a module called once per row
with one traced call. ``RTOL`` is the documented tolerance of the NumPy backend against the
Python path; a ``None`` on the Python path is NaN on arrays. ``assert_same_error`` checks that a
failing row raises the same class and message on both paths, the graph's error being the first
failing row that reaches the result.
"""

import dataclasses
import math
from collections.abc import Mapping

import numpy as np
import pytest

from gemini.compiler.graph import run, run_function
from gemini.types import Stream
from gemini.types.flows import STREAM_FIELDS
from gemini.types.ports import Ports
from gemini.types.results import ModuleResult, Values
from tests.fixtures.parity import REFERENCE, RTOL, on_each_backend, others


def flatten(value):
    """Return a result as a dict of named leaf values, for dataclasses, mappings and tuples."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {field.name: getattr(value, field.name) for field in dataclasses.fields(value)}
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, tuple):
        return dict(enumerate(value))
    return {"value": value}


def assert_close(actual, expected, label):
    """Compare per-row Python values ``expected`` with an array or scalar ``actual``.

    A row may be a list of numbers (a vector output); ``actual`` is then an array of shape
    ``(rows, length)``.
    """
    reference = np.array([math.nan if item is None else item for item in expected], dtype=float)
    actual = np.broadcast_to(np.asarray(actual, dtype=float), reference.shape)
    np.testing.assert_allclose(actual, reference, rtol=RTOL, atol=0, equal_nan=True, err_msg=label)


def assert_function_matches(function, rows, **fixed):
    """Assert ``function(*row, **fixed)`` per row equals one traced run on the stacked columns."""
    expected = [flatten(function(*row, **fixed)) for row in rows]
    columns = [np.array(column, dtype=float) for column in zip(*rows)]
    actual = flatten(run_function(function, *columns, **fixed))
    assert actual.keys() == expected[0].keys()
    for name, value in actual.items():
        assert_close(value, [row[name] for row in expected], f"{function.__name__}: {name}")


def assert_same_error(function, rows, error, **fixed):
    """Assert the first failing row raises the same ``error`` and message as the traced run."""
    with pytest.raises(error) as on_arrays:
        run_function(function, *(np.array(c, dtype=float) for c in zip(*rows)), **fixed)
    for row in rows:
        try:
            function(*row, **fixed)
        except error as on_floats:
            assert str(on_arrays.value) == str(on_floats)
            return
    pytest.fail(f"{function.__name__}: no row failed on Python floats")


def _stacked_result(module, results):
    """Return one ``ModuleResult`` of arrays holding the rows of per-row ``results``."""
    names = results[0].outputs.keys()
    outputs = {name: np.array([r.outputs[name] for r in results]) for name in names}
    ports = {
        section: Ports(
            {
                name: _stacked_stream([getattr(r, section)[name] for r in results])
                for name in getattr(results[0], section)
            },
            path=module.path,
        )
        for section in ("inlets", "outlets")
    }
    return ModuleResult(
        outputs=Values(outputs, module._outputs),
        outlets=ports["outlets"],
        inlets=ports["inlets"],
        inputs={k: np.array([r.inputs[k] for r in results]) for k in results[0].inputs},
    )


def assert_health_matches(module, results, measured):
    """Assert ``health`` on stacked arrays equals one call per row: every field, every row.

    ``results`` are per-row ``ModuleResult`` objects and ``measured`` one dict per row.
    """
    expected = [module.health(result, row) for result, row in zip(results, measured)]
    stacked = {key: np.array([row[key] for row in measured]) for key in measured[0]}
    actual = module.health(_stacked_result(module, results), stacked)
    rows = len(results)
    for field in ("assessed", "alarm", "message"):
        values = np.broadcast_to(np.asarray(getattr(actual, field)), (rows,)).tolist()
        assert values == [getattr(row, field) for row in expected], field
    assert_close(actual.score, [row.score for row in expected], "score")
    assert actual.metrics.keys() == expected[0].metrics.keys()
    for name, value in actual.metrics.items():
        assert_close(value, [row.metrics[name] for row in expected], name)


def _stacked_stream(streams):
    if not isinstance(streams[0], Stream):
        return np.array(streams)
    return Stream._si(
        **{field: np.array([getattr(s, field) for s in streams]) for field in STREAM_FIELDS},
        fluid=streams[0].fluid,
    )


def assert_module_matches(module, rows, breaks=False):
    """Assert one traced call of ``module`` on every backend equals one call per row.

    Each row maps inlet names to ``Stream`` objects and control or boundary names to numbers.
    The graph runs once on each backend of ``tests.fixtures.parity.BACKENDS``, forced for the
    whole call, tracing included; each is compared with the eager calls and the others with the
    reference backend, so every module test is a backend parity test.
    ``breaks=True`` accepts a graph break, for a module documented as one.
    """
    calls = [module(**row) for row in rows]
    inlets = {
        name: _stacked_stream([row[name] for row in rows]) for name in module._fed_inlets() if rows
    }
    inputs = {
        name: np.array([row[name] for row in rows], dtype=float)
        for name in rows[0]
        if name not in inlets
    }
    traced = on_each_backend(lambda backend: run(module, inlets, inputs, backend=backend))
    for backend, outcome in traced.items():
        assert breaks or outcome.breaks == [], outcome.breaks
        _assert_matches_calls(module, calls, outcome, backend)
    reference = traced[REFERENCE]
    for backend, outcome in others(traced):
        _assert_matches_run(module, reference, outcome, backend)


def _assert_matches_calls(module, calls, outcome, backend):
    for name in calls[0].outputs:
        values = [call.outputs[name] for call in calls]
        assert_close(outcome.outputs[name], values, f"{backend}: {module.path}.{name}")
    for port, fields in outcome.outlets.items():
        for field, traced in fields.items():
            values = [_port_field(module, call, port, field) for call in calls]
            label = f"{backend}: {module.path}.{port}.{field}"
            assert_close(traced, values, label)


def _port_field(module, call, port, field):
    """Return one field of a port of a direct call: a stream field, or the ``power``."""
    value = (call.inlets if port in module._inlets else call.outlets)[port]
    return value if field == "power" else getattr(value, field)


def _assert_matches_run(module, reference, outcome, backend):
    assert outcome.outputs.keys() == reference.outputs.keys()
    for name, values in reference.outputs.items():
        assert_close(outcome.outputs[name], values, f"{backend} against reference: {name}")
    for port, fields in reference.outlets.items():
        for field, values in fields.items():
            label = f"{backend} against reference: {port}.{field}"
            assert_close(outcome.outlets[port][field], values, label)
