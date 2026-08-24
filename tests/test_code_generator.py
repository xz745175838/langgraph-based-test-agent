import pytest

from src.agent.nodes.code_generator import (
    CodeExtractionError,
    _extract_python_code,
    validate_generated_code,
)

VALID_POLLING_SNIPPET = '''
import time
import unittest
from pyVmomi import vim

class DemoTest(unittest.TestCase):
    def test_task(self):
        task = None  # placeholder
        TASK_POLL_TIMEOUT_SEC = 120
        deadline = time.time() + TASK_POLL_TIMEOUT_SEC
        while True:
            state = task.info.state
            if state == "success":
                break
            if time.time() > deadline:
                raise TimeoutError("timed out")
            time.sleep(1)
'''

UNBOUNDED_WHILE_SNIPPET = '''
import unittest

class DemoTest(unittest.TestCase):
    def test_task(self):
        task = None
        while True:
            state = task.info.state
            if state == "success":
                break
            time.sleep(1)
'''


def test_extract_last_python_block():
    text = (
        "First draft:\n```python\nprint('old')\n```\n\n"
        "Final version:\n```py\nprint('new')\n```\n"
    )
    assert _extract_python_code(text) == "print('new')"


def test_extract_python_tag_case_insensitive():
    text = "```Python\nx = 1\n```"
    assert _extract_python_code(text) == "x = 1"


def test_extract_failure_without_fence():
    with pytest.raises(CodeExtractionError, match="No python markdown code block"):
        _extract_python_code("Here is code without fences: x = 1")


def test_extract_failure_unsupported_fence_tag():
    with pytest.raises(CodeExtractionError):
        _extract_python_code("```javascript\nconsole.log(1)\n```")


def test_validate_accepts_deadline_polling():
    assert validate_generated_code(VALID_POLLING_SNIPPET) == []


def test_validate_rejects_unbounded_while_true():
    errors = validate_generated_code(UNBOUNDED_WHILE_SNIPPET)
    assert any("unbounded `while True`" in err for err in errors)
    assert any("deadline guard" in err for err in errors)


def test_validate_rejects_syntax_error():
    errors = validate_generated_code("import unittest\n def broken(")
    assert any("Syntax error" in err for err in errors)
