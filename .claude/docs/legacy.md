# Legacy bridge

The old format has one boundary in two places, both internal. `gemini/plants/_utils/legacy/` reads a
project into a plant: `project.py` (`GeminiProject`), `tables.py`, `design.py` and `reader.py`
(`from_folder`, `to_plant`). `gemini.data.legacy` holds what needs a run or a frame: `files.py`
(`from_csv`, `to_csv`) and `convert.py` (`to_dataset`, `from_plant`, `to_frame`,
`check_wiring`), and re-exports `GeminiProject` and `to_plant`. The one public entry is
`gm.Plant.from_legacy(folder)`.
`GeminiProject.from_folder(folder)`/`project.to_folder(folder)` handle raw diagram and `.param`
files through typed models; the in-memory project, including edits to it, is what the conversion
reads. `from_csv`/`to_csv` handle semicolon data and old timestamps
(`%Y-%m-%d %H:%M:%S`, or ISO 8601 when reading). Parsed projects write the same values after
JSON whitespace normalisation, keeping each `.param` file's tag-name order; auxiliary files are
copied byte-for-byte. Malformed or unconvertible files raise `gm.errors.ValidationError`.

`to_plant(project, plant)` fills an existing plant with converted SI parameters,
dated histories, fluids, bindings, explicit assumptions (`plant.boundary`) and the scenario inputs
and plant inlet streams (`plant.set_inputs`), and returns it.
Old fields it cannot map are listed in one `GeminiWarning`. `to_dataset(project, frame)` renames
tag columns and converts values to SI; old timestamps are taken as UTC wall time.
`from_plant(plant, template)` writes through an old template without inventing fields.
`to_frame(results, project)` maps predicted measured outputs back to old tag units, and
`check_wiring(plant, project)` compares observed stream identities with the old diagram. It runs
one step on a copy of the plant with its assumed root inputs and `tables.TRACE_CONTROLS`, so the
caller's plant is not changed, and returns an empty list when the wiring matches.

`gm.Plant.from_legacy(folder)` returns the plant of an old project folder: it reads the folder with
`GeminiProject.from_folder`, fills `DoubletHeatPlant` (`gm.plants.get`) with `to_plant` and returns it;
`plant.to_json(path)` stores it. The folder holds `diagram.json`, one `.param` file per diagram node
and any other file (the data CSV, `well_trajectory.csv`, `plant.conf`), which is read as-is and not
converted; the data CSV is converted with `to_dataset`. On the example project the result equals
`example_plant("DoubletHeatPlant")` (`tests/fixtures/sample_cases.py`) exactly (`tests/unit/plants/_utils/legacy/test_reader.py`).
The function is `gemini/plants/_utils/legacy/reader.py: from_folder`, which `Plant.from_legacy`
calls.

The bridge maps exactly the example project: its ten old nodes (`tables.NODE_PATHS`), a project
folder with exactly one data CSV besides trajectory files, and its data columns and assumptions.
Any other node set is rejected rather than guessed. Type, property, port, tag and old-node path
tables, the deliberately unbound tags with their reasons (`IGNORED_TAGS`) and the property
converters live in `plants/_utils/legacy/tables.py`; `plants/_utils/legacy/design.py` interprets a
parsed project with them. New engine/modules/examples contain no old naming or conversion logic. No example reads old files; `tests/e2e/test_legacy_bridge.py` covers the bridge through
`gm.Plant.from_legacy`.

Converted control columns use their owning leaf path. The shared doublet therefore uses
`doublet.reservoir.production_rate`, `doublet.esp.frequency`, and
`injection_pump.pressure_setpoint`, without duplicate plant-level control columns.
