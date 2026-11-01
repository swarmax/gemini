# GEMINI examples

Five scripts, each runs alone from any folder with `gemini` installed (`pip install -e .`), reads its
data from `inputs/examples/` through its own path and writes nothing to the repository except the
JSON reports of `hackathon.py` in `.tmp/`.

| File | What it shows | Main names |
| --- | --- | --- |
| [quickstart.py](quickstart.py) | A JSON case and plant, simulate, constraints, report (shallow district) | `gm.Case.from_json`, `gm.Plant.from_json`, `gm.simulate`, `gm.evaluate.constraints`, `gm.evaluate.report` |
| [hackathon.py](hackathon.py) | The whole flow on the hackathon case: size, minimise over the choices, simulate, check, report, compare, sensitivity | `gm.study.size`, `gm.study.minimize`, `gm.evaluate.compare`, `gm.study.sensitivity` |
| [costs.py](costs.py) | Capex per unit, opex, LCTS and CO2, and how a missing assumption is reported | `gm.evaluate.capex`, `opex`, `lcts`, `co2`, `missing_assumption` |
| [uncertainty.py](uncertainty.py) | Spread of LCTS and CO2 over uncertain plant values | `gm.study.sample` |
| [plant.py](plant.py) | A plant dict built in Python, validated, saved and run on a case | `gm.Plant.from_dict`, `validate`, `to_json` |

```bash
python examples/quickstart.py
```
