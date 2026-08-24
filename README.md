# LangGraph-based Test Agent

基于 LangGraph 的 pyVmomi 测试用例生成与沙箱执行 Agent。根据自然语言需求调用 LLM 生成 unittest 脚本，并在 vcsim 沙箱中运行 pytest 验证。

## 架构

```
START → generate_code → execute_sandbox → END
```

| 节点 | 职责 |
|------|------|
| `generate_code` | 调用 DeepSeek 生成 pyVmomi unittest；提取 Markdown 代码块并做静态检查 |
| `execute_sandbox` | 将代码写入沙箱目录，执行 pytest，过滤 traceback 并分类失败原因 |

`AgentState` 核心字段：`original_prompt`、`target_api`、`generated_code`、`execution_status`、`error_traceback`、`retry_count`。

执行状态：

- `SUCCESS` — pytest 通过
- `FAILED_SCRIPT_ERROR` — 生成/脚本逻辑错误（如 AttributeError）
- `FAILED_SDK_BUG` — 命中 `vim.fault.InternalError` / `vim.fault.NotSupported` 等 SDK 问题

## 前置条件

- Python 3.10+
- Docker（用于 vcsim 模拟 vCenter）
- DeepSeek / OpenAI 兼容 API Key

## 快速开始

```bash
# 克隆并进入项目
cd langgraph-based-test-agent

# 创建虚拟环境并安装依赖
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 配置 LLM API Key
export DEEPSEEK_API_KEY=sk-...
# 可选
export DEEPSEEK_API_BASE=https://api.deepseek.com
export DEEPSEEK_MODEL=deepseek-v4-flash
```

### 启动 vcsim（可选）

```bash
python -c "from src.sandbox.setup_vcsim import setup, wait_ready; setup(); print('ready' if wait_ready() else 'timeout')"
```

Apple Silicon 如遇平台警告，可显式指定：

```bash
docker run -d --name vcsim-sandbox --platform linux/amd64 -p 8989:8989 vmware/vcsim:latest
```

默认连接：`https://localhost:8989/sdk`，凭据 `user` / `pass`。

### 端到端运行

```bash
python -m scripts.e2e_run --setup-vcsim
```

产物写入 `artifacts/e2e/<timestamp>/`（`test_generated.py`、pytest 输出、`run_summary.json` 等）。

常用参数：

```bash
python -m scripts.e2e_run --help
python -m scripts.e2e_run --setup-vcsim --teardown-vcsim
python -m scripts.e2e_run --prompt "你的测试需求" --target-api ReconfigureComputeResource_Task
```

### 仅测试代码生成

```bash
python -m scripts.smoke_generate
```

### 启动 HTTP API

```bash
uvicorn src.main:app --reload --port 8000
```

```bash
curl -X POST http://localhost:8000/api/v1/generate-test \
  -H "Content-Type: application/json" \
  -d '{"prompt": "test reconfigure cluster", "target_api": "ReconfigureComputeResource_Task"}'
```

返回 `202 Accepted`；图在 BackgroundTasks 线程池中异步执行。

### 运行单元测试

```bash
pytest tests/ -v
```

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `DEEPSEEK_API_KEY` | LLM API Key | — |
| `OPENAI_API_KEY` | 备用 API Key | — |
| `DEEPSEEK_API_BASE` | API Base URL | `https://api.deepseek.com` |
| `DEEPSEEK_MODEL` | 模型名称 | `deepseek-v4-flash` |
| `SANDBOX_ARTIFACTS_DIR` | 沙箱产物目录 | `/tmp/sandbox` |

## 项目结构

```
src/
  main.py                 # FastAPI 入口
  agent/
    graph.py              # LangGraph 图定义
    state.py              # AgentState TypedDict
    nodes/
      code_generator.py   # LLM 代码生成 + 静态检查
      sandbox_executor.py # pytest 执行 + traceback 过滤
  sandbox/
    setup_vcsim.py        # vcsim Docker 生命周期
scripts/
  e2e_run.py              # 端到端流水线
  smoke_generate.py       # 代码生成 smoke test
tests/
  test_code_generator.py
  test_sandbox_executor.py
```

## 开发说明

- 生成的测试脚本要求使用 unittest，并对 task 轮询包含 deadline + `TimeoutError` 保护。
- `sandbox_executor` 对 pytest 子进程设置 `timeout=300s`；超时后子进程会被 SIGKILL 终止。
- 本地产物与缓存目录已在 `.gitignore` 中排除，请勿提交 API Key 或 `artifacts/` 内容。
