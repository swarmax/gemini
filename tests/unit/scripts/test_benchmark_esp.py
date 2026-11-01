"""The inputs the ESP benchmark reads exist in the dataset it times."""

from scripts import benchmark_esp


def test_the_benchmark_loads_its_inputs_from_the_dataset():
    """A renamed dataset column must fail here, not in a benchmark nobody runs."""
    esp, rows = benchmark_esp.load()
    assert rows.shape[1] == len(benchmark_esp.COLUMNS)
    assert len(rows) > 0
    assert esp is not None
