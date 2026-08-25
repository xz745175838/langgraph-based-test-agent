from typing import Literal, TypedDict

DEFAULT_TARGET_API = "ReconfigureComputeResource_Task"

ExecutionStatus = Literal[
    "PENDING",
    "SUCCESS",
    "FAILED_SCRIPT_ERROR",
    "FAILED_SDK_BUG",
]


class AgentState(TypedDict):
    original_prompt: str
    target_api: str
    generated_code: str
    execution_status: ExecutionStatus
    error_traceback: str
    retry_count: int
    # SHA-256 fingerprints of assertions captured after the first successful generation.
    original_assertions: list[str]
