"""The seven error classes, ``GeminiWarning`` and the fixed code lists, as ``gm.errors.<Name>``.

What a former class meant is a ``code``: ``CODES`` and ``ROW_CODES`` are the fixed lists. A built-in
base appears only where Python needs one: ``ValidationError`` is a ``ValueError``, and the private
classes of ``gemini.errors.lookup`` add ``KeyError`` and ``AttributeError`` for ``hasattr``,
``getattr`` with a default and mapping lookups. Nothing in this package imports from the rest of
``gemini``.
"""

from gemini.errors.base import (
    CODES,
    ROW_CODES,
    Cancelled,
    DefinitionError,
    GeminiError,
    GeminiWarning,
    NotImplementedYet,
    PhysicsError,
    RunError,
    ValidationError,
)

__all__ = [
    "CODES",
    "ROW_CODES",
    "GeminiError",
    "GeminiWarning",
    "ValidationError",
    "DefinitionError",
    "PhysicsError",
    "RunError",
    "Cancelled",
    "NotImplementedYet",
]
