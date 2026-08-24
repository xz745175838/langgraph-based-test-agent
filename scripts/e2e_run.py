"""End-to-end run: START -> generate_code -> execute_sandbox -> END.

Usage:
  export DEEPSEEK_API_KEY=sk-...
  python -m scripts.e2e_run --setup-vcsim

Artifacts (generated code + full pytest output) are written under:
  artifacts/e2e/<timestamp>/
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from src.agent.graph import app_graph
from src.agent.nodes.sandbox_executor import artifacts_dir
from src.agent.state import DEFAULT_TARGET_API, AgentState
from src.sandbox.setup_vcsim import is_running, setup, teardown, wait_ready

DEFAULT_PROMPT = (
    "编写 pyVmomi unittest：连接 vcsim，找到第一个 ClusterComputeResource，"
    "调用 ReconfigureComputeResource_Task 启用 VSAN（vim.cluster.ConfigSpecEx + "
    "spec.vsanConfig.enabled = True），轮询 task 直到 success 后断言。"
)


def _build_initial_state(prompt: str, target_api: str) -> AgentState:
    return {
        "original_prompt": prompt,
        "target_api": target_api,
        "generated_code": "",
        "execution_status": "PENDING",
        "error_traceback": "",
        "retry_count": 0,
    }


def _print_section(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run full LangGraph E2E pipeline.")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT, help="User requirement prompt")
    parser.add_argument(
        "--target-api",
        default=DEFAULT_TARGET_API,
        help=f"Target API name (default: {DEFAULT_TARGET_API})",
    )
    parser.add_argument(
        "--artifacts-dir",
        default="",
        help="Directory for generated code and pytest logs (default: artifacts/e2e/<timestamp>)",
    )
    parser.add_argument(
        "--setup-vcsim",
        action="store_true",
        help="Start vcsim Docker container if not already running",
    )
    parser.add_argument(
        "--teardown-vcsim",
        action="store_true",
        help="Remove vcsim container after the run",
    )
    parser.add_argument(
        "--skip-vcsim-check",
        action="store_true",
        help="Do not verify vcsim port 8989 is reachable before running",
    )
    args = parser.parse_args()

    if not (os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")):
        print("Set DEEPSEEK_API_KEY (or OPENAI_API_KEY) first.", file=sys.stderr)
        return 1

    run_dir = Path(args.artifacts_dir) if args.artifacts_dir else (
        Path("artifacts/e2e") / datetime.now().strftime("%Y%m%d-%H%M%S")
    )
    run_dir.mkdir(parents=True, exist_ok=True)
    os.environ["SANDBOX_ARTIFACTS_DIR"] = str(run_dir.resolve())

    started_vcsim = False
    if args.setup_vcsim:
        if not is_running():
            print("Starting vcsim ...")
            setup()
            started_vcsim = True
        else:
            print("vcsim container already running.")

    if not args.skip_vcsim_check:
        if not wait_ready(timeout_sec=60):
            print(
                "vcsim is not reachable at localhost:8989. "
                "Run with --setup-vcsim or start Docker manually.",
                file=sys.stderr,
            )
            return 1
        print("vcsim is ready at localhost:8989")

    initial_state = _build_initial_state(args.prompt, args.target_api)
    _print_section("1/2 Running graph: generate_code -> execute_sandbox")
    print(f"prompt: {args.prompt[:120]}{'...' if len(args.prompt) > 120 else ''}")
    print(f"artifacts: {run_dir.resolve()}")

    try:
        final_state = app_graph.invoke(initial_state)
    finally:
        if args.teardown_vcsim and started_vcsim:
            print("Tearing down vcsim ...")
            teardown()

    _print_section("2/2 Final state")
    print(json.dumps(final_state, indent=2, ensure_ascii=False))

    out_dir = artifacts_dir()
    summary_path = out_dir / "run_summary.json"
    if summary_path.exists():
        print(f"\nrun_summary: {summary_path.resolve()}")

    print("\nArtifacts:")
    for name in (
        "test_generated.py",
        "pytest_combined.txt",
        "pytest_stdout.txt",
        "pytest_stderr.txt",
        "error_traceback_filtered.txt",
        "run_summary.json",
    ):
        path = out_dir / name
        if path.exists():
            print(f"  - {path.resolve()}")

    combined = out_dir / "pytest_combined.txt"
    if combined.exists():
        _print_section("Full pytest output (pytest_combined.txt)")
        print(combined.read_text(encoding="utf-8"))

    status = final_state.get("execution_status", "UNKNOWN")
    if status == "SUCCESS":
        return 0
    if status in ("FAILED_SCRIPT_ERROR", "FAILED_SDK_BUG"):
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
