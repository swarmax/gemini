"""Environment report for bug reports."""

from gemini._utils import collect_env, version


def test_environment_lists_python_package_and_dependencies():
    """The report names Python, the package and every main dependency."""
    names = [name for name, _ in collect_env.environment()]
    assert names[:5] == ["python", "platform", "gemini", "gemini path", "git commit"]
    assert set(collect_env.DEPENDENCIES) <= set(names)
    assert collect_env.version("surely-not-installed-package") == "not installed"


def test_git_commit_outside_a_checkout_is_unknown(tmp_path):
    """A folder that is not a git checkout reports an unknown commit."""
    assert collect_env.git_commit(tmp_path) == "unknown"


def test_main_prints_one_line_per_item(capsys):
    """``python -m gemini._utils.collect_env`` prints ``name: value`` lines."""
    collect_env.main()
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("python: ")
    assert len(lines) == len(collect_env.environment())


def test_the_gemini_row_is_the_source_version():
    """The report names the version of the source, not that of an installed copy."""
    assert dict(collect_env.environment())["gemini"] == version.package_version()
