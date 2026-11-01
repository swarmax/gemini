"""Why steps failed: the failed and skipped rows of a run, grouped by module and error code."""

from dataclasses import dataclass

import pandas as pd

FIELDS = ("path", "code", "kind", "count", "first", "last", "message")
"""The columns of ``Failures.to_frame``, one row per group."""

SKIPPED = "missing_value"
"""The code of a row skipped for a missing value; every other code is a row that failed."""


@dataclass(frozen=True)
class Failures:
    """The groups of failed and skipped rows of a run, the most frequent first.

    Each group is ``{path, code, kind, count, first, last, message}``: the module path, the code of
    ``gm.errors.ROW_CODES``, ``"skipped"`` or ``"failed"``, the number of rows, the time of the
    first and the last row, and the message of the first row. A run with no failed or skipped row
    has no group.
    """

    groups: tuple

    def __len__(self):
        """Count the groups."""
        return len(self.groups)

    @property
    def total(self):
        """The number of failed and skipped rows."""
        return sum(group["count"] for group in self.groups)

    def to_dict(self):
        """Return ``{total, groups}`` as plain JSON."""
        return {"total": self.total, "groups": [dict(group) for group in self.groups]}

    def to_frame(self):
        """Return the groups as a table with the columns ``FIELDS``, in the same order."""
        return pd.DataFrame(list(self.groups), columns=list(FIELDS))


def failures(results):
    """Group the failed and skipped rows of ``results`` by module path and error code.

    ``results`` is the ``Results`` of a run. Rows come from ``results.errors()``, which are in
    time order. The groups are sorted by count, largest first, then by path and code.
    """
    found = {}
    for row in results.errors():
        key = (row["path"], row["code"])
        group = found.get(key)
        if group is None:
            kind = "skipped" if row["code"] == SKIPPED else "failed"
            found[key] = {
                "path": row["path"],
                "code": row["code"],
                "kind": kind,
                "count": 1,
                "first": row["time"],
                "last": row["time"],
                "message": row["message"],
            }
        else:
            group["count"] += 1
            group["last"] = row["time"]
    ordered = sorted(
        found.values(), key=lambda group: (-group["count"], group["path"], group["code"])
    )
    return Failures(tuple(ordered))
