"""Independent trials of a study in worker processes, in the order of a serial run."""

from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context

from gemini import runtime
from gemini.ops.backend import forced_name

_shared = {}
"""What a worker process holds: the arguments every item of the map shares."""


def _start(shared, state, backend):
    """Set the runtime of a worker like its parent's, one process, and keep ``shared``."""
    _shared["value"] = shared
    _shared["settings"] = runtime.settings(backend, **(state | {"processes": 1}))
    _shared["settings"].__enter__()


def _call(job):
    """Return ``function(shared, item)`` for a ``(function, item)`` job in a worker."""
    function, item = job
    return function(_shared["value"], item)


def mapped(function, shared, items):
    """Return ``[function(shared, item) for item in items]``, over the processes of the runtime.

    ``runtime.settings(processes=n)`` sets how many worker processes run the items; with one, or
    one item, they run here in turn. The items are independent and the results come back in the
    order of ``items``, the same numbers as a serial run: a worker applies the settings of its
    parent (the backend, the precision, the display units, the default fluid) with one process, so
    it starts no pool of its own. ``function`` is a module level function, and ``shared`` and
    every item and result can be pickled. A worker starts from a ``forkserver`` that has imported
    gemini, so a call pays that import once for the process, not for every worker.
    """
    count = min(runtime.get_processes(), len(items))
    if count <= 1:
        return [function(shared, item) for item in items]
    context = get_context("forkserver")
    context.set_forkserver_preload(["gemini"])
    initargs = (shared, runtime.state(), forced_name())
    with ProcessPoolExecutor(
        count, mp_context=context, initializer=_start, initargs=initargs
    ) as pool:
        return list(pool.map(_call, [(function, item) for item in items]))
