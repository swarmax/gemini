"""The verdict of a list of checks."""


def verdict(verdicts):
    """Return ``False`` if any verdict failed, else ``True`` if any passed, else ``None``."""
    if False in verdicts:
        return False
    return True if True in verdicts else None
