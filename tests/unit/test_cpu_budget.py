"""The fast-tier budget measures CPU time, so waiting never fails and heavy work always does."""

import multiprocessing
import threading
import time

from tests.cpu_budget import BUDGET_S, exceeds_budget, measure_cpu


def burn(seconds):
    """Spin on the calling thread until its CPU clock has advanced by ``seconds``."""
    deadline = time.thread_time() + seconds
    while time.thread_time() < deadline:
        pass


def test_sleeping_longer_than_the_budget_uses_no_cpu():
    """A test that only waits for more than a second of elapsed time stays within budget."""
    started = time.perf_counter()
    with measure_cpu() as cpu:
        time.sleep(BUDGET_S + 0.05)
    assert time.perf_counter() - started > BUDGET_S
    assert cpu.seconds < 0.1
    assert not exceeds_budget(cpu.seconds)


def test_burning_cpu_is_measured():
    """CPU work is counted: a quarter second burned reads as at least a quarter second."""
    with measure_cpu() as cpu:
        burn(0.25)
    assert 0.25 <= cpu.seconds < 0.5


def test_work_in_another_thread_is_counted():
    """Process CPU time includes threads, so delegating the work does not hide it."""
    worker = threading.Thread(target=burn, args=(0.25,))
    with measure_cpu() as cpu:
        worker.start()
        worker.join()
    assert cpu.seconds >= 0.25


def test_budget_boundary_is_one_second_of_cpu():
    """The budget is exactly one second: equal passes, over fails."""
    assert BUDGET_S == 1.0
    assert not exceeds_budget(1.0)
    assert exceeds_budget(1.01)


def test_work_in_a_child_process_is_counted():
    """CPU time of a child process the test waited for is counted, so a process pool hides nothing."""
    child = multiprocessing.get_context("spawn").Process(target=burn, args=(0.25,))
    with measure_cpu() as cpu:
        child.start()
        child.join()
    assert cpu.seconds >= 0.25
