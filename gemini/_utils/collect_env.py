"""Print the environment details a bug report needs: ``python -m gemini._utils.collect_env``."""

import platform
import subprocess
import sys
from importlib import metadata
from pathlib import Path

from gemini._utils.version import package_version

DEPENDENCIES = ("numpy", "pandas", "scipy", "pydantic", "pytest")


def version(name):
    """Return an installed distribution's version, or ``not installed``."""
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return "not installed"


def git_commit(folder):
    """Return the git commit of ``folder``, or ``unknown`` outside a git checkout."""
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=folder,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return completed.stdout.strip()


def environment():
    """Return the environment report as ordered ``(name, value)`` pairs."""
    package = Path(__file__).resolve().parents[1]
    rows = [
        ("python", sys.version.split()[0]),
        ("platform", platform.platform()),
        ("gemini", package_version()),
        ("gemini path", str(package)),
        ("git commit", git_commit(package)),
    ]
    rows.extend((name, version(name)) for name in DEPENDENCIES)
    return rows


def main():
    """Print the environment report."""
    for name, value in environment():
        print(f"{name}: {value}")


if __name__ == "__main__":
    main()
