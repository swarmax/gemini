"""CPU-time measure behind the one-second budget of a fast-tier test call."""

from contextlib import contextmanager
from os import times
from time import process_time

BUDGET_S = 1.0


class CpuSeconds:
    """CPU seconds of the process consumed inside a ``measure_cpu`` block."""

    seconds = 0.0


@contextmanager
def measure_cpu():
    """Measure the CPU time of the whole process around a block, not its elapsed time.

    ``process_time`` adds the user and system time of every thread of the process, so work a test
    hands to its own threads or to the NumPy thread pool still counts, while time spent waiting
    (sleeping, descheduled by a busy machine, blocked on a lock) does not. ``thread_time`` would
    miss that delegated work and let a heavy test pass. The block must be one test call, which a
    pytest-xdist worker runs alone in its process. The user and system time of child processes
    the test started and waited for (a process pool of parallel trials) is added from
    ``os.times``, so work handed to other processes counts too.
    """
    result = CpuSeconds()
    started = _cpu_seconds()
    try:
        yield result
    finally:
        result.seconds = _cpu_seconds() - started


def _cpu_seconds():
    """Return the CPU seconds of this process and of its waited-for children."""
    clock = times()
    return process_time() + clock.children_user + clock.children_system


def exceeds_budget(cpu_seconds):
    """Return whether CPU time is over the one-second budget."""
    return cpu_seconds > BUDGET_S
