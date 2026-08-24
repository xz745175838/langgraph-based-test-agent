from langgraph.graph import END, START, StateGraph

from src.agent.nodes.code_generator import generate_code_node
from src.agent.nodes.sandbox_executor import execute_sandbox_node
from src.agent.state import AgentState


builder = StateGraph(AgentState)
builder.add_node("generate_code", generate_code_node)
builder.add_node("execute_sandbox", execute_sandbox_node)
builder.add_edge(START, "generate_code")
builder.add_edge("generate_code", "execute_sandbox")
builder.add_edge("execute_sandbox", END)

app_graph = builder.compile()
