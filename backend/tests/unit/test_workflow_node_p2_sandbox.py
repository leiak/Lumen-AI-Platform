"""Tests for app.core.sandbox.runner — RestrictedPython 8.x wrapper.

P2 Task 8. Tests use the project's asyncio.run() pattern (not @pytest.mark.asyncio)
to match the convention in test_executor_helpers.py / test_workflow_nodes.py.
"""
import asyncio
import io

import pytest

from lumen_core.sandbox.runner import run_python_restricted


def _run(coro):
    return asyncio.run(coro)


def test_basic_arithmetic():
    stdout = io.StringIO()
    result = _run(run_python_restricted(
        code="RESULT = 1 + 2", inputs={}, output_var="RESULT", stdout=stdout
    ))
    assert result == 3


def test_inputs_mapping_injects_globals():
    stdout = io.StringIO()
    result = _run(run_python_restricted(
        code="RESULT = x.upper()",
        inputs={"x": "hello"},
        output_var="RESULT",
        stdout=stdout,
    ))
    assert result == "HELLO"


def test_print_goes_to_stdout_buffer():
    stdout = io.StringIO()
    _run(run_python_restricted(
        code="print('hi')\nRESULT = None",
        inputs={},
        output_var="RESULT",
        stdout=stdout,
    ))
    assert stdout.getvalue() == "hi\n"


def test_import_os_blocked():
    stdout = io.StringIO()
    with pytest.raises(NameError):
        _run(run_python_restricted(
            code="import os\nRESULT = os.getcwd()",
            inputs={}, output_var="RESULT", stdout=stdout,
        ))


def test_open_blocked():
    stdout = io.StringIO()
    with pytest.raises(NameError):
        _run(run_python_restricted(
            code="open('/etc/passwd')",
            inputs={}, output_var="RESULT", stdout=stdout,
        ))


def test_syntax_error_raises_value_error():
    stdout = io.StringIO()
    with pytest.raises(ValueError, match="compile error"):
        _run(run_python_restricted(
            code="def broken(:\n  pass",
            inputs={}, output_var="RESULT", stdout=stdout,
        ))


def test_json_dumps_loads_available():
    stdout = io.StringIO()
    result = _run(run_python_restricted(
        code="RESULT = json.dumps({'a': 1})",
        inputs={}, output_var="RESULT", stdout=stdout,
    ))
    assert result == '{"a": 1}'


def test_result_not_set_returns_none():
    stdout = io.StringIO()
    result = _run(run_python_restricted(
        code="x = 5",
        inputs={}, output_var="RESULT", stdout=stdout,
    ))
    assert result is None
