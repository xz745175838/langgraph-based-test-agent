import ast
import os
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from src.agent.state import AgentState

SYSTEM_PROMPT = """你是一位精通 VMware pyVmomi 的高级测试工程师。请根据用户需求生成可直接运行的 Python unittest 脚本。

[环境约束]
- 目标 vCenter URL 固定为：http://localhost:8989/sdk
- 连接时必须禁用 SSL 校验（disableSslCertValidation=True 或等价写法）
- 默认账号可使用 vcsim 常见凭据：user='user', pwd='pass'

[格式约束]
- 输出必须是符合 pyVmomi 标准的完整 Python unittest 脚本，测试类名必须以 Test 开头，测试方法名必须以 test_ 开头
- 使用 unittest.TestCase 组织用例
- 最终只输出一个 markdown Python 代码块（```python ... ``` 或 ```py ... ```），不要输出多余解释

[结构约束]
- 配置对象必须严格遵循 VMODL 层级，禁止捏造文档中不存在的属性
- 以 vim.cluster.ConfigSpecEx 为例，正确写法类似：
  spec = vim.cluster.ConfigSpecEx()
  spec.vsanConfig = vim.vsan.cluster.ConfigInfo()
  spec.vsanConfig.enabled = True
- 禁止写成扁平或不存在的字段（例如随意编造 spec.enableVsan、spec.fooBar 等）

[轮询约束]
- 调用 ReconfigureComputeResource_Task（或等价的 cluster.ReconfigureComputeResource_Task）后，必须轮询 task.info.state
- 只有当 task.info.state == 'success' 时才进行断言；中间态继续等待，失败态应使测试失败
- 轮询必须包含 deadline/timeout 保护，超时后 raise TimeoutError，禁止无界 while True
- 参考以下 Few-Shot 片段（请按同样模式编写）：

```python
import time
from pyVim.connect import SmartConnect, Disconnect
from pyVmomi import vim

si = SmartConnect(
    host="localhost",
    port=8989,
    user="user",
    pwd="pass",
    disableSslCertValidation=True,
)
content = si.RetrieveContent()
# ... 定位目标 cluster ...
spec = vim.cluster.ConfigSpecEx()
spec.vsanConfig = vim.vsan.cluster.ConfigInfo()
spec.vsanConfig.enabled = True

task = cluster.ReconfigureComputeResource_Task(spec=spec, modify=True)
TASK_POLL_TIMEOUT_SEC = 120
deadline = time.time() + TASK_POLL_TIMEOUT_SEC
while True:
    state = task.info.state
    if state == "success":
        break
    if state in ("error", "failed"):
        raise AssertionError(f"task failed: {task.info.error}")
    if time.time() > deadline:
        raise TimeoutError(
            f"task polling timed out after {TASK_POLL_TIMEOUT_SEC}s, last state={state!r}"
        )
    time.sleep(1)

self.assertEqual(task.info.state, "success")
Disconnect(si)
```
"""

_CODE_BLOCK_RE = re.compile(
    r"```(?:python|py)\s*\n(.*?)```",
    re.DOTALL | re.IGNORECASE,
)


class CodeExtractionError(Exception):
    """Raised when no python markdown fenced block can be extracted."""


def _get_llm() -> ChatOpenAI:
    return ChatOpenAI(
        model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        api_key=os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY"),
        base_url=os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com"),
        # temperature=0：降低随机性，让生成结果更稳定、可复现（适合代码生成）
        temperature=0,
    )


def _extract_python_code(text: str) -> str:
    """Extract the last ```python/```py fenced block; fail if none found."""
    matches = list(_CODE_BLOCK_RE.finditer(text))
    if not matches:
        raise CodeExtractionError(
            "No python markdown code block found in LLM response "
            "(expected ```python or ```py fenced block)"
        )
    return matches[-1].group(1).strip()


def _references_task_state(code: str) -> bool:
    return "task.info.state" in code


def _imports_unittest(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name == "unittest" for alias in node.names):
                return True
        if isinstance(node, ast.ImportFrom):
            if node.module == "unittest":
                return True
        if isinstance(node, ast.ClassDef):
            for base in node.bases:
                base_name = _expression_name(base)
                if base_name and base_name.endswith("TestCase"):
                    return True
    return False


def _expression_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        value = _expression_name(node.value)
        if value:
            return f"{value}.{node.attr}"
        return node.attr
    return None


def _is_timeout_error(exc: ast.AST | None) -> bool:
    if exc is None:
        return False
    if isinstance(exc, ast.Name):
        return exc.id == "TimeoutError"
    if isinstance(exc, ast.Call):
        return _is_timeout_error(exc.func)
    if isinstance(exc, ast.Attribute):
        return exc.attr == "TimeoutError"
    return False


def _contains_deadline_check(node: ast.AST) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Compare):
            names = {n.id for n in ast.walk(child) if isinstance(n, ast.Name)}
            if "deadline" in names:
                return True
            for call in ast.walk(child):
                if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute):
                    if (
                        call.func.attr == "time"
                        and isinstance(call.func.value, ast.Name)
                        and call.func.value.id == "time"
                    ):
                        return True
    return False


def _while_loop_has_timeout_guard(while_node: ast.While) -> bool:
    if _contains_deadline_check(while_node.test):
        return True
    for node in ast.walk(while_node):
        if isinstance(node, ast.Raise) and _is_timeout_error(node.exc):
            return True
        if isinstance(node, ast.If) and _contains_deadline_check(node.test):
            return True
    return False


def _has_unbounded_while_true(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.While):
            if isinstance(node.test, ast.Constant) and node.test.value is True:
                if not _while_loop_has_timeout_guard(node):
                    return True
    return False


def validate_generated_code(code: str) -> list[str]:
    """Run static checks on extracted Python source; return human-readable errors."""
    errors: list[str] = []
    if not code.strip():
        errors.append("Generated code is empty")
        return errors

    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        errors.append(f"Syntax error: {exc.msg} (line {exc.lineno})")
        return errors

    if not _imports_unittest(tree):
        errors.append("Generated code must use unittest (import unittest or subclass TestCase)")

    if _references_task_state(code) and not _contains_deadline_check(tree):
        errors.append(
            "Task state polling must include a deadline guard "
            "(e.g. deadline = time.time() + N and if time.time() > deadline: raise TimeoutError)"
        )

    if _has_unbounded_while_true(tree):
        errors.append(
            "Found unbounded `while True` without deadline/timeout guard; "
            "use deadline + TimeoutError or a bounded while condition"
        )

    return errors


def _generation_failure(error_message: str, generated_code: str = "") -> dict[str, Any]:
    return {
        "generated_code": generated_code,
        "execution_status": "FAILED_SCRIPT_ERROR",
        "error_traceback": error_message,
    }


def generate_code_node(state: AgentState) -> dict[str, Any]:
    """Call DeepSeek to generate a pyVmomi unittest script and update state."""
    llm = _get_llm()
    user_prompt = (
        f"Target API: {state['target_api']}\n"
        f"Requirement:\n{state['original_prompt']}"
    )
    response = llm.invoke(
        [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=user_prompt),
        ]
    )
    content = response.content if isinstance(response.content, str) else str(response.content)

    try:
        extracted_code = _extract_python_code(content)
    except CodeExtractionError as exc:
        return _generation_failure(str(exc))

    validation_errors = validate_generated_code(extracted_code)
    if validation_errors:
        return _generation_failure("\n".join(validation_errors), generated_code=extracted_code)

    return {"generated_code": extracted_code}
