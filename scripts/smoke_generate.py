"""Smoke-test generate_code_node without starting FastAPI.

Usage:
  export DEEPSEEK_API_KEY=sk-...
  python -m scripts.smoke_generate
"""

from __future__ import annotations

import os
import sys

from src.agent.nodes.code_generator import generate_code_node
from src.agent.state import DEFAULT_TARGET_API, AgentState


def main() -> int:
    if not (os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")):
        print("Set DEEPSEEK_API_KEY (or OPENAI_API_KEY) first.", file=sys.stderr)
        return 1

    state: AgentState = {
        "original_prompt": "编写用例：对集群调用 ReconfigureComputeResource_Task，启用 VSAN。",
        "target_api": DEFAULT_TARGET_API,
        "generated_code": "",
        "execution_status": "PENDING",
        "error_traceback": "",
        "retry_count": 0,
    }

    print("AgentState keys:", sorted(state.keys()))
    print("Calling generate_code_node ...")
    update = generate_code_node(state)
    code = update.get("generated_code", "")
    status = update.get("execution_status")
    error = update.get("error_traceback", "")
    if status:
        print(f"execution_status={status}")
    if error:
        print(f"error_traceback={error}")
    print("--- generated_code (first 800 chars) ---")
    print(code[:800] if code else "(empty)")
    print("--- end ---")
    print(f"length={len(code)}")
    #1 = 配置/环境问题，没真正调用 LLM
    #2 = 环境 OK，但 generate 这一步业务失败
    if status == "FAILED_SCRIPT_ERROR":
        return 2
    return 0 if code else 2


if __name__ == "__main__":
    raise SystemExit(main())
