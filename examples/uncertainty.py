"""Spread of LCTS and CO2 when the values the case declares uncertain are drawn.

Draws every value that `case.json` gives an `uncertainty` (prices, permeability, temperature
gradient, discount rate), one simulation per draw, and prints the mean and the 5th to 95th
percentile of the two metrics.

Shows ``gm.study.sample``.

Run with ``python examples/uncertainty.py``.
"""

from pathlib import Path

import gemini as gm

SAMPLE = Path(__file__).resolve().parents[1] / "inputs/examples/hackathon_2026"
SEED = 1
"""The seed of the draws: the same seed gives the same draws."""
DRAWS = 20
"""Simulations: enough for stable percentiles of a smooth response."""
UNITS = {"lcts": "EUR/MWh", "co2": "kt"}


def print_spread(summary):
    """Print the mean and the 5th to 95th percentile of each metric."""
    for name, unit in UNITS.items():
        mean, low, high = (summary[name][key].to(unit).value for key in ("mean", "p5", "p95"))
        print(f"{name:<5} mean {mean:8.2f}  p5 {low:8.2f}  p95 {high:8.2f} {unit}")


def main():
    """Draw the uncertain values and print the spread of the metrics."""
    case = gm.Case.from_json(SAMPLE / "case.json")
    plant = gm.Plant.from_json(SAMPLE / "plants/HeatingPlant.json")
    spread = gm.study.sample(plant, case, list(UNITS), DRAWS, SEED)
    print(f"Draws: {len(spread['samples'])}")
    print_spread(spread["summary"])


if __name__ == "__main__":
    main()
