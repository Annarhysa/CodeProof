from unittest.mock import MagicMock

from evaluator.dependencies import install_dependencies
from sandbox.runner import CommandResult


def _cmd(command, exit_code=0):
    return CommandResult(command=command, exit_code=exit_code, stdout="", stderr="", duration_seconds=0.1, timed_out=False)


def test_no_manifest_detected():
    sandbox = MagicMock()
    sandbox.list_files.return_value = ["README.md", "main.py"]

    result = install_dependencies(sandbox)

    assert result.attempted is False
    assert result.success is True
    sandbox.run.assert_not_called()


def test_pip_requirements_installed():
    sandbox = MagicMock()
    sandbox.list_files.return_value = ["requirements.txt", "app.py"]
    sandbox.run.return_value = _cmd("pip install", exit_code=0)

    result = install_dependencies(sandbox)

    assert result.attempted is True
    assert result.success is True
    assert "pip (requirements.txt)" in result.detected
    sandbox.run.assert_called_once()
    assert "pip install" in sandbox.run.call_args[0][0]


def test_npm_install_retries_after_cleanup_on_failure():
    sandbox = MagicMock()
    sandbox.list_files.return_value = ["package.json", "package-lock.json"]
    sandbox.run.side_effect = [
        _cmd("npm ci", exit_code=1),      # first attempt fails
        _cmd("rm -rf node_modules", exit_code=0),
        _cmd("npm install", exit_code=0),  # retry succeeds
    ]

    result = install_dependencies(sandbox)

    assert result.attempted is True
    assert result.success is True  # judged by the retry's outcome, not the first failure
    assert sandbox.run.call_count == 3


def test_npm_install_fails_even_after_retry():
    sandbox = MagicMock()
    sandbox.list_files.return_value = ["package.json"]
    sandbox.run.side_effect = [
        _cmd("npm install", exit_code=1),
        _cmd("rm -rf node_modules", exit_code=0),
        _cmd("npm install", exit_code=1),
    ]

    result = install_dependencies(sandbox)

    assert result.success is False
