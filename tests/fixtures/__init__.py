"""Immutable reference values, their generators and shared test paths."""

from pathlib import Path

from gemini._utils import paths

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/fixtures"
OLD_PROJECT = paths.INPUTS / "legacy_project"
