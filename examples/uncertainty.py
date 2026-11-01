"""Spread of LCTS and CO2 when a few values of the case and the plant are uncertain.

Draws the electricity price and the permeability of the case and the efficiency of the boiler and
the nominal flow of the plant, one simulation per draw, and prints the mean and the 5th to 95th
percentile of the two metrics.

Shows ``gm.study.sample``.

Run with ``python examples/uncertainty.py``.
"""

from pathlib import Path

import gemini as gm

SAMPLE = Path(__file__).resolve().parents[1] / "inputs/examples/hackathon_2026"
DRAWS = 20
"""Simulations: enough for stable percentiles of a smooth response."""
Q = gm.units.Quantity
UNCERTAIN = {
    "case.assumptions.finance.opex.electricity": {
        "kind": "triangular",
        "lower": Q(70, "EUR/MWh"),
        "mode": Q(100, "EUR/MWh"),
        "upper": Q(160, "EUR/MWh"),
    },
    "case.environment.reservoir.permeability": {
        "kind": "uniform",
        "lower": Q(150, "mD"),
        "upper": Q(250, "mD"),
    },
    "peak_boiler.efficiency": {"kind": "uniform", "lower": 0.85, "upper": 0.95},
    "d0.nominal_flow": {"kind": "normal", "mean": Q(250, "m3/h"), "std": Q(15, "m3/h")},
}
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
    spread = gm.study.sample(plant, case, UNCERTAIN, list(UNITS), DRAWS, seed=1)
    print(f"Draws: {len(spread['samples'])}")
    print_spread(spread["summary"])


if __name__ == "__main__":
    main()
