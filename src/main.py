import uuid
from typing import Any

from fastapi import BackgroundTasks, FastAPI
from pydantic import BaseModel, Field

from src.agent.graph import app_graph
from src.agent.state import DEFAULT_TARGET_API, AgentState

app = FastAPI()


class GenerateTestRequest(BaseModel):
    prompt: str
    target_api: str = Field(default=DEFAULT_TARGET_API)


def _run_graph(initial_state: AgentState) -> None:
    app_graph.invoke(initial_state)


@app.post("/api/v1/generate-test", status_code=202)
async def generate_test(
    request: GenerateTestRequest,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    task_id = str(uuid.uuid4())

    initial_state: AgentState = {
        "original_prompt": request.prompt,
        "target_api": request.target_api,
        "generated_code": "",
        "execution_status": "PENDING",
        "error_traceback": "",
        "retry_count": 0,
    }

    background_tasks.add_task(_run_graph, initial_state)

    return {"task_id": task_id, "status": "accepted"}
