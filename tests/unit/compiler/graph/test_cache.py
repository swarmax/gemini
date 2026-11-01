"""The cache retraces only when a guard changes."""

import copy
import threading

import numpy as np

import gemini as gm
from gemini.compiler.graph import GraphCache, evaluate, graph_cache, graph_feeds
from tests.fixtures.designs import with_values


def _wired(first, second):
    """Return a plant of two valves in series, ``first`` then ``second``."""
    plant = gm.Plant("series")
    plant.add(
        "Valve", name="a", params={"flow_coefficient": gm.units.Quantity(1e-3, "m3/s/Pa^0.5")}
    )
    plant.add(
        "Valve", name="b", params={"flow_coefficient": gm.units.Quantity(2e-3, "m3/s/Pa^0.5")}
    )
    plant.connect("fluid_in", f"{first}.fluid_in")
    plant.connect(f"{first}.fluid_out", f"{second}.fluid_in")
    plant.connect(f"{second}.fluid_out", "fluid_out")
    return with_values(plant)


def _inlets(fluid):
    return {
        "fluid_in": gm.Stream(
            m_dot=gm.units.Quantity(np.ones(2), "kg/s"),
            T=gm.units.Quantity(np.full(2, 300.0), "K"),
            p=gm.units.Quantity(np.ones(2), "Pa"),
            fluid=fluid,
        )
    }


def test_numeric_parameter_values_do_not_retrace_but_guards_do(gain):
    """New numeric values reuse the graph; text values, hooks and output mode retrace."""
    cache = GraphCache()
    fluids = {"fluid_in": gain.fluid}
    first = cache.graph(gain, fluids)
    gain.set_params("", {"scale": 7.0})
    assert cache.graph(gain, fluids) is first and cache.traces == 1
    gain.set_params("", {"label": "y"})
    assert cache.graph(gain, fluids) is not first and cache.traces == 2
    handle = gain.register_forward_hook(lambda module, inlets, outlets: None)
    cache.graph(gain, fluids)
    handle.remove()
    with gm.modules.no_outputs():
        cache.graph(gain, fluids)
    assert cache.traces == 4


def test_a_changed_module_fluid_retraces(gain):
    """The module's own fluid is baked into a trace, so changing it makes a new graph."""
    cache = GraphCache()
    fluids = {"fluid_in": gain.fluid}
    first = cache.graph(gain, fluids)
    gain.fluid = gm.WATER
    assert cache.graph(gain, fluids) is not first and cache.traces == 2


def test_graph_breaks_are_remembered(gain):
    """A module that cannot be traced is a cached root break graph, never an error."""
    cache = GraphCache()
    gain.register_forward_pre_hook(lambda module, inlets: None)
    graphs = [cache.graph(gain, {"fluid_in": gain.fluid}) for _ in range(2)]
    assert graphs[0] is graphs[1] and graphs[0].root_break
    assert "pre-hooks" in graphs[0].breaks[0][1]
    assert cache.traces == 1


def test_structural_parameter_values_are_guards(stepper):
    """A structural value retraces when it changes; a numeric one next to it does not."""
    module = stepper
    cache = GraphCache()
    fluids = {"fluid_in": module.fluid}
    first = cache.graph(module, fluids)
    assert "steps" not in first.inputs and "increment" in first.inputs
    module.set_params("", {"increment": 5.0})
    assert cache.graph(module, fluids) is first and cache.traces == 1
    module.set_params("", {"steps": 3})
    assert cache.graph(module, fluids) is not first and cache.traces == 2


def test_a_change_deep_in_the_tree_retraces(line):
    """Guards cover every module: a text parameter or a fluid below the root retrace."""
    cache = GraphCache()
    fluids = {"fluid_in": line.fluid}
    first = cache.graph(line, fluids)
    line.gain.set_params("", {"scale": 9.0})
    line.second.set_params("", {"scale": 9.0})
    assert cache.graph(line, fluids) is first and cache.traces == 1
    line.gain.set_params("", {"label": "y"})
    assert cache.graph(line, fluids) is not first and cache.traces == 2
    line.first.fluid = gm.WATER
    cache.graph(line, fluids)
    assert cache.traces == 3


def test_a_hook_below_the_root_is_a_guard(line):
    """Adding a writing hook to a child retraces the composite."""
    cache = GraphCache()
    fluids = {"fluid_in": line.fluid}
    cache.graph(line, fluids)
    line.gain.register_forward_hook(lambda module, inlets, outlets: setattr(module, "rise", 1.0))
    cache.graph(line, fluids)
    assert cache.traces == 2


def test_stepped_is_a_guard(tank):
    """A stepped graph of a stateful module is a different graph from the unstepped one."""
    cache = GraphCache()
    fluids = {"fluid_in": tank.fluid}
    unstepped = cache.graph(tank, fluids)
    stepped = cache.graph(tank, fluids, stepped=True)
    assert stepped is not unstepped and stepped.stepped and not unstepped.stepped
    assert cache.graph(tank, fluids, stepped=True) is stepped and cache.traces == 2


def test_the_cache_of_the_process_is_one_that_an_engine_uses(gain):
    """The graphs outlive an engine and a plant: a new engine finds them."""
    assert graph_cache() is graph_cache()
    assert gm.Engine(gain)._executor.cache is graph_cache()


def test_a_copy_with_other_numeric_values_shares_the_graph_and_gets_its_numbers(gain):
    """A graph holds no module: a copy reuses it and is evaluated with its own values."""
    cache = GraphCache()
    fluids = {"fluid_in": gain.fluid}
    other = copy.deepcopy(gain)
    other.set_params("", {"scale": 9.0})
    first = cache.graph(gain, fluids)
    assert cache.graph(other, fluids) is first and cache.traces == 1
    inlets = _inlets(gain.fluid)
    inputs = {"gain": np.array([1.0, 2.0])}
    shared = graph_feeds(first, other, inlets, inputs)
    fresh = graph_feeds(GraphCache().graph(other, fluids), other, inlets, inputs)
    assert shared["scale"] == fresh["scale"] == 9.0
    other.set_params("", {"label": "y"})
    assert cache.graph(other, fluids) is not first and cache.traces == 2


def test_a_shared_break_runs_the_module_it_is_evaluated_for(line):
    """A break node holds a path: each copy runs its own module, with its own parameters."""
    line.gain.register_forward_pre_hook(lambda module, inlets: None)
    other = copy.deepcopy(line)
    other.gain.set_params("", {"scale": 9.0})
    cache = GraphCache()
    fluids = {"fluid_in": line.fluid}
    graph = cache.graph(line, fluids)
    assert cache.graph(other, fluids) is graph and cache.traces == 1 and graph.breaks
    rises = []
    for module in (line, other):
        feeds = graph_feeds(graph, module, _inlets(line.fluid), {})
        fresh = GraphCache().graph(module, fluids)
        shared = evaluate(graph, feeds, 2, module=module).output("outputs.rise")
        own = evaluate(fresh, feeds, 2, module=module).output("outputs.rise")
        assert shared.tolist() == own.tolist()
        rises.append(shared.tolist())
    assert rises[0] != rises[1]


def test_a_different_wiring_or_path_retraces():
    """The connections of a plant and the path of the root are in the key."""
    cache = GraphCache()
    plant = _wired("a", "b")
    fluids = {"fluid_in": plant.fluid}
    first = cache.graph(plant, fluids)
    assert cache.graph(copy.deepcopy(plant), fluids) is first
    assert cache.graph(_wired("b", "a"), fluids) is not first
    renamed = copy.deepcopy(plant)
    renamed._set_path("other")
    assert cache.graph(renamed, fluids) is not first


def test_the_cache_keeps_the_most_recent_graphs_only(gain):
    """The oldest graph is dropped beyond ``maxsize``; a hit makes a graph recent."""
    cache = GraphCache(maxsize=2)
    fluids = {"fluid_in": gain.fluid}
    modules = [copy.deepcopy(gain) for _ in range(3)]
    for index, module in enumerate(modules):
        module.set_params("", {"label": str(index)})
    first = cache.graph(modules[0], fluids)
    cache.graph(modules[1], fluids)
    assert cache.graph(modules[0], fluids) is first
    cache.graph(modules[2], fluids)
    assert cache.graph(modules[0], fluids) is first and cache.traces == 3
    cache.graph(modules[1], fluids)
    assert cache.traces == 4


def test_threads_with_their_own_plants_share_a_cache(gain):
    """Two threads that trace one structure at once both get a usable graph."""
    cache = GraphCache()
    fluids = {"fluid_in": gain.fluid}
    graphs = []
    threads = [
        threading.Thread(target=lambda m=copy.deepcopy(gain): graphs.append(cache.graph(m, fluids)))
        for _ in range(4)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(graphs) == 4 and cache.graph(gain, fluids) in graphs
