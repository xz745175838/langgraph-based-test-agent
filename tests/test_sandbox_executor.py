from unittest.mock import MagicMock, patch

import pytest

from src.agent.nodes.sandbox_executor import (
    execute_sandbox_node,
    filter_traceback,
)
from src.agent.state import AgentState


PYTEST_FAILURE_OUTPUT = """
============================= test session starts ==============================
platform darwin -- Python 3.10.0, pytest-8.0.0, pluggy-1.4.0
rootdir: /tmp/sandbox
collected 1 item

test_generated.py::ClusterTest::test_reconfigure FAILED                  [100%]

=================================== FAILURES ===================================
_______________________ ClusterTest.test_reconfigure _______________________

self = <test_generated.ClusterTest testMethod=test_reconfigure>

    def test_reconfigure(self):
        spec = vim.cluster.ConfigSpecEx()
>       spec.enableVsan = True
E       AttributeError: 'ConfigSpecEx' object has no attribute 'enableVsan'

test_generated.py:18: AttributeError
=========================== short test summary info ============================
FAILED test_generated.py::ClusterTest::test_reconfigure - AttributeError: ...
"""

VIM_FAULT_OUTPUT = """
FAILED test_generated.py::ClusterTest::test_reconfigure - vim.fault.InternalError: (...)
vim.fault.InternalError: (vim.fault.InternalError) {
   dynamicType = <unset>,
   msg = "Not supported in simulator",
}
"""


def test_filter_traceback_keeps_attribute_error():
    filtered = filter_traceback(PYTEST_FAILURE_OUTPUT)
    assert "AttributeError" in filtered
    assert "enableVsan" in filtered
    assert "test_generated.py:18" in filtered
    assert "test session starts" not in filtered
    assert "pluggy" not in filtered


def test_filter_traceback_keeps_vim_fault():
    filtered = filter_traceback(VIM_FAULT_OUTPUT)
    assert "vim.fault.InternalError" in filtered


def test_filter_traceback_keeps_vmodl_fault():
    raw = "vmodl.fault.InvalidArgument: Invalid property spec.fooBar"
    filtered = filter_traceback(raw)
    assert "vmodl.fault.InvalidArgument" in filtered


def test_execute_sandbox_node_success(tmp_path, monkeypatch):
    monkeypatch.setenv("SANDBOX_ARTIFACTS_DIR", str(tmp_path))
    state: AgentState = {
        "original_prompt": "test",
        "target_api": "ReconfigureComputeResource_Task",
        "generated_code": "def test_ok():\n    assert True\n",
        "execution_status": "PENDING",
        "error_traceback": "",
        "retry_count": 0,
    }
    mock_result = MagicMock(returncode=0, stdout="1 passed", stderr="")
    with patch("src.agent.nodes.sandbox_executor.subprocess.run", return_value=mock_result):
        update = execute_sandbox_node(state)
    assert update["execution_status"] == "SUCCESS"
    assert update["error_traceback"] == ""
    assert (tmp_path / "test_generated.py").exists()
    assert (tmp_path / "pytest_combined.txt").exists()
    assert (tmp_path / "run_summary.json").exists()


def test_execute_sandbox_node_script_error(tmp_path, monkeypatch):
    monkeypatch.setenv("SANDBOX_ARTIFACTS_DIR", str(tmp_path))
    state: AgentState = {
        "original_prompt": "test",
        "target_api": "ReconfigureComputeResource_Task",
        "generated_code": "def test_bad():\n    raise ValueError('bad')\n",
        "execution_status": "PENDING",
        "error_traceback": "",
        "retry_count": 0,
    }
    mock_result = MagicMock(
        returncode=1,
        stdout=PYTEST_FAILURE_OUTPUT,
        stderr="",
    )
    with patch("src.agent.nodes.sandbox_executor.subprocess.run", return_value=mock_result):
        update = execute_sandbox_node(state)
    assert update["execution_status"] == "FAILED_SCRIPT_ERROR"
    assert "AttributeError" in update["error_traceback"]
    assert (tmp_path / "error_traceback_filtered.txt").exists()


def test_execute_sandbox_node_sdk_bug(tmp_path, monkeypatch):
    monkeypatch.setenv("SANDBOX_ARTIFACTS_DIR", str(tmp_path))
    state: AgentState = {
        "original_prompt": "test",
        "target_api": "ReconfigureComputeResource_Task",
        "generated_code": "def test_bad():\n    pass\n",
        "execution_status": "PENDING",
        "error_traceback": "",
        "retry_count": 0,
    }
    mock_result = MagicMock(returncode=1, stdout=VIM_FAULT_OUTPUT, stderr="")
    with patch("src.agent.nodes.sandbox_executor.subprocess.run", return_value=mock_result):
        update = execute_sandbox_node(state)
    assert update["execution_status"] == "FAILED_SDK_BUG"
    assert "vim.fault.InternalError" in update["error_traceback"]


def test_execute_sandbox_node_not_supported_is_sdk_bug(tmp_path, monkeypatch):
    monkeypatch.setenv("SANDBOX_ARTIFACTS_DIR", str(tmp_path))
    raw = "vim.fault.NotSupported: The operation is not supported on the object."
    mock_result = MagicMock(returncode=1, stdout=raw, stderr="")
    state: AgentState = {
        "original_prompt": "test",
        "target_api": "ReconfigureComputeResource_Task",
        "generated_code": "def test_x(): pass",
        "execution_status": "PENDING",
        "error_traceback": "",
        "retry_count": 0,
    }
    with patch("src.agent.nodes.sandbox_executor.subprocess.run", return_value=mock_result):
        update = execute_sandbox_node(state)
    assert update["execution_status"] == "FAILED_SDK_BUG"
