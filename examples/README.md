# GEMINI examples

Five scripts, each runs alone from any folder with `gemini` installed (`pip install -e .`), reads its
data from `inputs/examples/` through its own path and writes nothing to the repository except the
JSON reports of `hackathon.py` in `.tmp/`.

| File | What it shows | Main names |
| --- | --- | --- |
| [quickstart.py](quickstart.py) | A JSON case and plant, simulate, constraints, report (shallow district) | `gm.Case.from_json`, `gm.Plant.from_json`, `gm.simulate`, `gm.evaluate.constraints`, `gm.evaluate.report` |
| [hackathon.py](hackathon.py) | The whole flow on the hackathon case: every candidate sized and searched on one list of `<role>.<parameter>` variables, its feasibility and reasons, compare in readable units, the Pareto front of the feasible designs, sensitivity | `gm.study.size`, `gm.study.minimize`, `gm.evaluate.compare`, `gm.study.sensitivity` |
| [costs.py](costs.py) | Capex per unit, opex, LCTS and CO2, a limit on the electricity bought as a constraint of the case, and how a missing assumption is reported | `gm.evaluate.capex`, `opex`, `lcts`, `co2`, `constraints`, `missing_assumption` |
| [uncertainty.py](uncertainty.py) | Spread of LCTS and CO2 over the values the case declares uncertain | `gm.study.sample` |
| [plant.py](plant.py) | A plant built from its class: `missing_parameters`, values set as quantities, `gm.plants.validate(plant)`, sized and run on a case, failed steps grouped | `missing_parameters`, `set_params`, `gm.plants.validate`, `gm.study.size`, `gm.evaluate.failures` |

```bash
python examples/quickstart.py
```
