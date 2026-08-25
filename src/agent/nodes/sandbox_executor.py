import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from src.agent.state import AgentState
from src.agent.utils.ast_checker import verify_assertions_unchanged

DEFAULT_ARTIFACTS_DIR = Path("/tmp/sandbox")
PYTEST_TIMEOUT_SEC = 300

_SDK_BUG_FAULTS = ("vim.fault.InternalError", "vim.fault.NotSupported")

# pytest / pluggy / assertion rewrite noise
_NOISE_LINE_RE = re.compile(
    r"(?:"
    r"^={3,}|"
    r"^_{3,}|"
    r"^platform |^cachedir:|^rootdir:|^plugins:|^collecting |^collected |"
    r"^PASSED |^FAILED |^ERROR |"
    r"short test summary info|"
    r"^\s*@pytest\.|^\s*@staticmethod|"
    r"pytest\.|_pytest\.|pluggy\.|"
    r"^\s*def test_|"
    r"^\s*self = <"
    r")",
    re.IGNORECASE,
)

_EXCEPTION_LINE_RE = re.compile(
    r"(?:"
    r"Traceback \(most recent call last\)|"
    r'^\s*File "[^"]+"|'
    r"^\s*E\s+|"
    r"(?:^|\s)(?:AttributeError|TypeError|ValueError|AssertionError|RuntimeError|"
    r"KeyError|ImportError|SyntaxError|TimeoutError|NameError|IndexError|"
    r"OSError|ConnectionError|Exception)(?::|\s*$)|"
    r"^[A-Za-z0-9_./-]+\.py:\d+:\s*\w+"
    r")",
    re.MULTILINE,
)

_FAULT_RE = re.compile(r"(?:vmodl|vim)\.fault\.[\w.]+(?:\([^)]*\))?", re.IGNORECASE)


def artifacts_dir() -> Path:
    return Path(os.getenv("SANDBOX_ARTIFACTS_DIR", str(DEFAULT_ARTIFACTS_DIR)))


def filter_traceback(stderr: str) -> str:
    """Strip pytest framework noise; keep native tracebacks and VMODL fault strings."""
    if not stderr.strip():
        return ""

    lines = stderr.splitlines()
    kept: list[str] = []
    in_failures = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        if re.search(r"FAILURES", stripped) or stripped.startswith("___"):
            in_failures = True
            continue

        if _NOISE_LINE_RE.search(stripped):
            continue

        if _FAULT_RE.search(stripped):
            kept.append(stripped)
            continue

        if _EXCEPTION_LINE_RE.search(line):
            kept.append(line.rstrip())
            continue

        if in_failures and (
            stripped.startswith(">")
            or "Error:" in stripped
            or stripped.endswith("Error")
        ):
            kept.append(line.rstrip())

    # Fallback: last traceback block if filtering removed everything useful
    if not kept:
        traceback_blocks = re.findall(
            r"(Traceback \(most recent call last\):.*?)(?:\n\S|\Z)",
            stderr,
            flags=re.DOTALL,
        )
        if traceback_blocks:
            kept.append(traceback_blocks[-1].strip())
        kept.extend(_FAULT_RE.findall(stderr))

    seen: set[str] = set()
    unique: list[str] = []
    for line in kept:
        if line not in seen:
            seen.add(line)
            unique.append(line)

    return "\n".join(unique).strip()


def _classify_failure(filtered: str) -> str:
    if any(fault in filtered for fault in _SDK_BUG_FAULTS):
        return "FAILED_SDK_BUG"
    return "FAILED_SCRIPT_ERROR"


def _save_artifacts(
    *,
    generated_code: str,
    stdout: str,
    stderr: str,
    exit_code: int | None,
    execution_status: str,
    error_traceback: str,
) -> Path:
    out_dir = artifacts_dir()
    out_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / "test_generated.py").write_text(generated_code, encoding="utf-8")
    (out_dir / "pytest_stdout.txt").write_text(stdout, encoding="utf-8")
    (out_dir / "pytest_stderr.txt").write_text(stderr, encoding="utf-8")
    (out_dir / "pytest_combined.txt").write_text(
        f"=== stderr ===\n{stderr}\n\n=== stdout ===\n{stdout}",
        encoding="utf-8",
    )
    if error_traceback:
        (out_dir / "error_traceback_filtered.txt").write_text(
            error_traceback, encoding="utf-8"
        )

    summary = {
        "execution_status": execution_status,
        "exit_code": exit_code,
        "artifacts_dir": str(out_dir.resolve()),
        "generated_code": str((out_dir / "test_generated.py").resolve()),
        "pytest_combined": str((out_dir / "pytest_combined.txt").resolve()),
    }
    (out_dir / "run_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return out_dir


def execute_sandbox_node(state: AgentState) -> dict[str, Any]:
    """Write generated code to sandbox, run pytest, and persist full output."""
    # Hard gate: refuse to run if assertions were tampered after baseline capture.
    verify_assertions_unchanged(
        state.get("original_assertions") or [],
        state.get("generated_code") or "",
    )

    generated_code = state["generated_code"]
    out_dir = artifacts_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    test_file = out_dir / "test_generated.py"
    test_file.write_text(generated_code, encoding="utf-8")

    stdout = ""
    stderr = ""
    exit_code: int | None = None

    try:
        result = subprocess.run(
            ["pytest", str(test_file), "-v"],
            capture_output=True,
            text=True,
            timeout=PYTEST_TIMEOUT_SEC,
        )
        stdout = result.stdout or ""
        stderr = result.stderr or ""
        exit_code = result.returncode
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        combined = f"{stderr}\n{stdout}"
        filtered = filter_traceback(combined)
        error_traceback = filtered or f"pytest timed out after {PYTEST_TIMEOUT_SEC}s"
        _save_artifacts(
            generated_code=generated_code,
            stdout=stdout,
            stderr=stderr,
            exit_code=None,
            execution_status="FAILED_SCRIPT_ERROR",
            error_traceback=error_traceback,
        )
        return {
            "execution_status": "FAILED_SCRIPT_ERROR",
            "error_traceback": error_traceback,
        }

    combined_output = f"{stderr}\n{stdout}"

    if exit_code == 0:
        _save_artifacts(
            generated_code=generated_code,
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            execution_status="SUCCESS",
            error_traceback="",
        )
        return {"execution_status": "SUCCESS", "error_traceback": ""}

    filtered = filter_traceback(combined_output)
    execution_status = _classify_failure(filtered)
    _save_artifacts(
        generated_code=generated_code,
        stdout=stdout,
        stderr=stderr,
        exit_code=exit_code,
        execution_status=execution_status,
        error_traceback=filtered,
    )
    return {
        "execution_status": execution_status,
        "error_traceback": filtered,
    }
