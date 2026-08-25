import pytest

from src.agent.graph import record_assertions_node, verify_assertions_node
from src.agent.state import AgentState
from src.agent.utils.ast_checker import (
    AssertionTamperedError,
    assertion_hashes,
    extract_asserts,
    verify_assertions_unchanged,
)

CODE_WITH_ASSERTS = """
def test_x():
    assert task.info.state == "success"
    assert cluster.configurationEx is not None
"""

CODE_UNITTEST = """
import unittest

class T(unittest.TestCase):
    def test_x(self):
        self.assertEqual(task.info.state, "success")
        self.assertTrue(enabled)
"""

CODE_WEAKENED = """
def test_x():
    assert True
    assert True
"""

CODE_DELETED = """
def test_x():
    assert task.info.state == "success"
"""


def test_extract_asserts_python_assert():
    items = extract_asserts(CODE_WITH_ASSERTS)
    assert len(items) == 2
    exprs = [i["expression"] for i in items]
    assert "task.info.state == 'success'" in exprs or 'task.info.state == "success"' in exprs
    assert all(len(i["hash"]) == 64 for i in items)


def test_extract_asserts_unittest_calls():
    items = extract_asserts(CODE_UNITTEST)
    assert len(items) == 2
    joined = " ".join(i["expression"] for i in items)
    assert "assertEqual" in joined
    assert "assertTrue" in joined


def test_verify_passes_when_unchanged():
    hashes = assertion_hashes(CODE_WITH_ASSERTS)
    verify_assertions_unchanged(hashes, CODE_WITH_ASSERTS)


def test_verify_passes_when_no_baseline():
    verify_assertions_unchanged([], CODE_WITH_ASSERTS)
    verify_assertions_unchanged(None, CODE_WITH_ASSERTS)


def test_verify_fails_when_assert_deleted():
    hashes = assertion_hashes(CODE_WITH_ASSERTS)
    with pytest.raises(AssertionTamperedError, match="count decreased"):
        verify_assertions_unchanged(hashes, CODE_DELETED)


def test_verify_fails_when_rewritten_to_assert_true():
    hashes = assertion_hashes(CODE_WITH_ASSERTS)
    with pytest.raises(AssertionTamperedError, match="hash mismatch"):
        verify_assertions_unchanged(hashes, CODE_WEAKENED)


def test_record_assertions_node_snapshots_hashes():
    state: AgentState = {
        "original_prompt": "p",
        "target_api": "ReconfigureComputeResource_Task",
        "generated_code": CODE_WITH_ASSERTS,
        "execution_status": "PENDING",
        "error_traceback": "",
        "retry_count": 0,
        "original_assertions": [],
    }
    update = record_assertions_node(state)
    assert update["original_assertions"] == assertion_hashes(CODE_WITH_ASSERTS)


def test_record_assertions_node_does_not_overwrite():
    state: AgentState = {
        "original_prompt": "p",
        "target_api": "ReconfigureComputeResource_Task",
        "generated_code": CODE_WEAKENED,
        "execution_status": "PENDING",
        "error_traceback": "",
        "retry_count": 0,
        "original_assertions": ["frozen-hash"],
    }
    assert record_assertions_node(state) == {}


def test_verify_assertions_node_raises_on_tamper():
    hashes = assertion_hashes(CODE_WITH_ASSERTS)
    state: AgentState = {
        "original_prompt": "p",
        "target_api": "ReconfigureComputeResource_Task",
        "generated_code": CODE_WEAKENED,
        "execution_status": "PENDING",
        "error_traceback": "",
        "retry_count": 0,
        "original_assertions": hashes,
    }
    with pytest.raises(AssertionTamperedError):
        verify_assertions_node(state)
