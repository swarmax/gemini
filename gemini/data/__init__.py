"""Input data: demand profiles in the run-input format and old project files.

gemini ships no profile. ``from_csv(path, columns, unit)`` reads one from a file and
``from_values(values, unit, start, step, quantity)`` builds one from numbers; both return a pandas
DataFrame with a UTC index called ``time`` at a constant step and one column per demand quantity in
W, ready for ``gm.schedule``. ``profile_schema()`` is the JSON Schema of the profile document.
"""

from gemini.case._utils.demand import from_csv, from_values

from .schema import profile_schema

__all__ = ["from_csv", "from_values", "profile_schema"]
