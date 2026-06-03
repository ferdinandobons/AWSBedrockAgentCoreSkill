# Hosting Any Framework on Bedrock AgentCore Runtime (LangGraph, CrewAI, LlamaIndex, Google ADK, Strands)

> Part of the **aws-ai-agent-architect** skill. See [SKILL.md](../SKILL.md) for the decision tree. Every source below is official — re-open it to verify details.

## Table of contents

1. [Overview](#overview)
2. [Key concepts](#key-concepts)
3. [The service contract](#the-service-contract)
4. [Deployment toolchain](#deployment-toolchain)
5. [Per-framework integration notes](#per-framework-integration-notes)
   - [Strands Agents](#strands-agents)
   - [LangGraph](#langgraph)
   - [CrewAI](#crewai)
   - [LlamaIndex](#llamaindex)
   - [Google ADK](#google-adk)
6. [Strands Python vs TypeScript SDK differences](#strands-python-vs-typescript-sdk-differences)
7. [Best practices](#best-practices)
8. [Code](#code)
9. [Configuration reference](#configuration-reference)
10. [Gotchas](#gotchas)
11. [Official sources](#official-sources)

---

## Overview

**Amazon Bedrock AgentCore Runtime** (GA) is a secure, serverless, consumption-billed environment for running any AI agent or tool at scale. It is fully **framework-agnostic**: the only contract it imposes is an HTTP server exposing `POST /invocations` and `GET /ping` on port 8080 inside an `linux/arm64` container image stored in ECR. Any language or framework that can speak HTTP satisfies this contract.

Officially documented frameworks with integration samples (as of June 2026):

| Framework | Language | Official sample |
|---|---|---|
| Strands Agents | Python, TypeScript | [awslabs/amazon-bedrock-agentcore-samples](https://github.com/awslabs/amazon-bedrock-agentcore-samples/tree/main/03-integrations/agentic-frameworks/strands-agents) |
| LangGraph | Python | [sample](https://github.com/awslabs/amazon-bedrock-agentcore-samples/tree/main/03-integrations/agentic-frameworks/langgraph) |
| CrewAI | Python | [sample](https://github.com/awslabs/amazon-bedrock-agentcore-samples/tree/main/03-integrations/agentic-frameworks/crewai) |
| LlamaIndex | Python | [sample](https://github.com/awslabs/amazon-bedrock-agentcore-samples/tree/main/03-integrations/agentic-frameworks/llamaindex) |
| Google ADK | Python | [sample](https://github.com/awslabs/amazon-bedrock-agentcore-samples/tree/main/03-integrations/agentic-frameworks/adk) |
| OpenAI Agents SDK | Python | [sample](https://github.com/awslabs/amazon-bedrock-agentcore-samples/tree/main/03-integrations/agentic-frameworks/openai-agents) |
| PydanticAI | Python | [sample](https://github.com/awslabs/amazon-bedrock-agentcore-samples/tree/main/03-integrations/agentic-frameworks/pydanticai-agents) |
| AutoGen | Python | [sample](https://github.com/awslabs/amazon-bedrock-agentcore-samples/tree/main/03-integrations/agentic-frameworks/autogen) |
| Mastra | TypeScript | [sample](https://github.com/awslabs/amazon-bedrock-agentcore-samples/tree/main/03-integrations/agentic-frameworks/typescript_mastra) |

Additional capabilities: supports any LLM (Bedrock, Anthropic, OpenAI, Gemini, Ollama, etc.), any protocol (HTTP, MCP, A2A, AG-UI), and runs sessions in dedicated microVMs with up to 8-hour extended execution.

_Source: [agents-tools-runtime — Amazon Bedrock AgentCore](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agents-tools-runtime.html)_ — GA

> For Bedrock-specific deployment alternatives (Lambda, Fargate, App Runner, EC2, EKS) see [deployment-best-practices.md](deployment-best-practices.md).
> For IAM, security, and cost details see [security-iam-cost.md](security-iam-cost.md).
> For AgentCore Memory, Gateway, and Identity integration see [agentcore-runtime.md](agentcore-runtime.md).
> For the Strands Agents SDK in depth see [strands.md](strands.md).
> For multi-agent patterns see [multi-agent.md](multi-agent.md).
> For observability see [observability.md](observability.md).

---

## Key concepts

| Concept | Detail |
|---|---|
| **Session isolation** | Each user session runs in a dedicated microVM with isolated CPU, memory, and filesystem. Memory is sanitized after session completion. |
| **Extended execution** | Sessions can run up to 8 hours, enabling long-running agent loops and async workloads. |
| **Protocol support** | HTTP (REST/SSE/WebSocket), MCP, A2A, AG-UI — all routable to the same container. |
| **Consumption pricing** | Charges only for actual CPU consumed; billing pauses during I/O wait (e.g., waiting for LLM token generation). |
| **Model agnostic** | The runtime does not care which model the agent calls; any LLM reachable from inside the microVM works. |
| **Persistent filesystem** | Filesystem state survives session stop/resume cycles without external storage. |
| **`bedrock-agentcore` SDK** | Optional Python library (v1.13.0 as of June 2026, pip install `bedrock-agentcore`) that wraps any Python callable in a Starlette-based ASGI server, auto-generating the required endpoints. |
| **AgentCore CLI** | The recommended deployment tool (`npm install -g @aws/agentcore`); replaces the legacy `bedrock-agentcore-starter-toolkit`. |

---

## The service contract

AgentCore Runtime imposes a minimal, framework-agnostic HTTP contract. You can satisfy it from scratch (plain FastAPI, Express, etc.) or let the `bedrock-agentcore` Python SDK handle it automatically via `BedrockAgentCoreApp`.

### HTTP protocol contract (most common)

| Requirement | Value |
|---|---|
| Host | `0.0.0.0` |
| Port | `8080` |
| Container platform | `linux/arm64` |
| Required endpoint | `POST /invocations` — receives JSON payload; returns JSON or SSE stream |
| Required endpoint | `GET /ping` — returns `{"status": "Healthy", "time_of_last_update": <unix_ts>}` with HTTP 200 |
| Optional endpoint | `GET /ws` (WebSocket, same port) — for bidirectional streaming |

_Source: [HTTP protocol contract — Amazon Bedrock AgentCore](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-http-protocol-contract.html)_

### Additional protocol ports (non-HTTP)

| Protocol | Port | Path |
|---|---|---|
| MCP | 8000 | `/mcp` |
| A2A | 9000 | `/` (root) |
| AG-UI | 8080 | `/invocations` (SSE) or `/ws` |

_Source: [Service contract — Amazon Bedrock AgentCore](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-service-contract.html)_

### `BedrockAgentCoreApp` wrapper (Python SDK)

The `bedrock-agentcore` package provides `BedrockAgentCoreApp`, a thin decorator-based wrapper that auto-generates `/invocations` and `/ping`, runs a Starlette ASGI server on port 8080, and handles SSE streaming. This is the quickest path when wrapping a Python-native agent.

```python
from bedrock_agentcore.runtime import BedrockAgentCoreApp

app = BedrockAgentCoreApp()

@app.entrypoint
def invoke(payload, context):
    # payload: dict from POST /invocations body
    # context: runtime context (session_id, etc.)
    result = my_agent(payload.get("prompt", ""))
    return {"result": str(result)}

if __name__ == "__main__":
    app.run()   # starts on 0.0.0.0:8080
```

For async agents or SSE streaming, the entrypoint can be `async def` and can `yield` chunks.

_Source: [Python deployment — Strands Agents Docs](https://strandsagents.com/docs/user-guide/deploy/deploy_to_bedrock_agentcore/python/index.md)_

---

## Deployment toolchain

### AgentCore CLI (recommended)

```bash
npm install -g @aws/agentcore      # requires Node.js 20+

agentcore create                    # interactive wizard — picks framework, language, protocol
agentcore dev                       # local dev server on :8080, hot-reload
agentcore dev "Hello"               # invoke local agent
agentcore deploy                    # CDK-backed deploy to ECR + AgentCore Runtime
agentcore invoke "Tell me a joke"   # invoke deployed agent
agentcore logs                      # stream CloudWatch logs
agentcore traces list               # view X-Ray traces
```

Supported `--framework` values: `Strands`, `LangChain_LangGraph`, `GoogleADK`, `OpenAIAgents`.
Supported `--language` values: Python (default), TypeScript.
Supported `--build` values: `CodeZip` (default, no Docker required), `Container`.

_Source: [Get started with the AgentCore CLI](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-cli.html)_

> **Note:** The legacy `bedrock-agentcore-starter-toolkit` (Python CLI) is now superseded by the AgentCore CLI. If both are installed, uninstall the toolkit to avoid conflicts: `pip uninstall bedrock-agentcore-starter-toolkit`.

### Manual / SDK deployment (boto3)

For full control, package the container, push to ECR, then call `CreateAgentRuntime`:

```python
import boto3

client = boto3.client("bedrock-agentcore-control", region_name="us-east-1")
response = client.create_agent_runtime(
    agentRuntimeName="my-agent",
    agentRuntimeArtifact={
        "containerConfiguration": {
            "containerUri": "123456789012.dkr.ecr.us-east-1.amazonaws.com/my-agent:latest"
        }
    },
    networkConfiguration={"networkMode": "PUBLIC"},
    protocolConfiguration={"serverProtocol": "HTTP"},
    roleArn="arn:aws:iam::123456789012:role/AgentCoreRuntimeRole",
)
```

_Source: [Python deployment — Strands Agents Docs](https://strandsagents.com/docs/user-guide/deploy/deploy_to_bedrock_agentcore/python/index.md)_

### IAM: Execution role trust policy

The runtime execution role must trust `bedrock-agentcore.amazonaws.com`:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Service": "bedrock-agentcore.amazonaws.com"},
    "Action": "sts:AssumeRole",
    "Condition": {
      "StringEquals": {"aws:SourceAccount": "<ACCOUNT_ID>"},
      "ArnLike": {"aws:SourceArn": "arn:aws:bedrock-agentcore:<REGION>:<ACCOUNT_ID>:*"}
    }
  }]
}
```

Minimum permissions for the execution role: `ecr:BatchGetImage`, `ecr:GetDownloadUrlForLayer`, `ecr:GetAuthorizationToken`, `logs:CreateLogGroup`, `logs:CreateLogStream`, `logs:PutLogEvents`, and `bedrock:InvokeModel` / `bedrock:InvokeModelWithResponseStream` for the models the agent calls.

_Source: [IAM Permissions for AgentCore Runtime](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-permissions.html)_

---

## Per-framework integration notes

All examples below follow the same wrapping pattern: instantiate the framework's agent/graph/crew, then hand off to `BedrockAgentCoreApp` (or write your own FastAPI/Express server that exposes `/invocations` and `/ping`).

### Strands Agents

The simplest integration because `bedrock-agentcore` and `strands-agents` are both AWS-native. The SDK's `BedrockAgentCoreApp` wraps the Strands `Agent` callable directly.

```python
from strands import Agent
from strands_tools import file_read, file_write, editor
from bedrock_agentcore.runtime import BedrockAgentCoreApp

agent = Agent(tools=[file_read, file_write, editor])

app = BedrockAgentCoreApp()

@app.entrypoint
def agent_invocation(payload, context):
    user_message = payload.get("prompt", "No prompt provided")
    result = agent(user_message)
    return {"result": str(result)}

app.run()
```

For streaming, make the entrypoint `async def` and use `agent.stream_async(user_message)`.

- `pip install strands-agents bedrock-agentcore`
- Full sample: [awslabs/amazon-bedrock-agentcore-samples — strands-agents](https://github.com/awslabs/amazon-bedrock-agentcore-samples/tree/main/03-integrations/agentic-frameworks/strands-agents)

_Source: [Use any agent framework — AgentCore docs](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/using-any-agent-framework.html)_

### LangGraph

Build the `StateGraph` graph as normal. The `@app.entrypoint` function receives the JSON payload and calls `graph.invoke(...)`.

```python
from langchain.chat_models import init_chat_model
from langgraph.graph import StateGraph, START
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from bedrock_agentcore.runtime import BedrockAgentCoreApp

app = BedrockAgentCoreApp()

llm = init_chat_model(
    "us.anthropic.claude-3-5-haiku-20241022-v1:0",
    model_provider="bedrock_converse",
)

# --- build your graph as usual ---
graph_builder = StateGraph(...)
# add nodes, edges, compile ...
graph = graph_builder.compile()

@app.entrypoint
def agent_invocation(payload, context):
    messages = {"messages": [{"role": "user", "content": payload.get("prompt", "")}]}
    output = graph.invoke(messages)
    return {"result": output["messages"][-1].content}

app.run()
```

Key consideration: LangGraph state and checkpointers are entirely managed inside your container; AgentCore provides the durable session boundary via the microVM filesystem, not LangGraph's own store.

- `pip install langgraph langchain-aws bedrock-agentcore`
- Full sample: [awslabs/amazon-bedrock-agentcore-samples — langgraph](https://github.com/awslabs/amazon-bedrock-agentcore-samples/tree/main/03-integrations/agentic-frameworks/langgraph)

_Source: [Use any agent framework — AgentCore docs](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/using-any-agent-framework.html)_

### CrewAI

Define the `Crew` (agents + tasks) as normal. Wrap the crew's `kickoff()` call inside `@app.entrypoint`.

```python
from crewai import Crew, Agent, Task
from bedrock_agentcore.runtime import BedrockAgentCoreApp

app = BedrockAgentCoreApp()

researcher = Agent(role="Researcher", goal="Research topics", ...)
writer = Agent(role="Writer", goal="Write content", ...)
research_task = Task(description="{prompt}", agent=researcher, ...)
write_task = Task(description="Write based on research", agent=writer, ...)

crew = Crew(agents=[researcher, writer], tasks=[research_task, write_task])

@app.entrypoint
def agent_invocation(payload, context):
    result = crew.kickoff(inputs={"prompt": payload.get("prompt", "")})
    return {"result": str(result)}

app.run()
```

- `pip install crewai bedrock-agentcore`
- Workshop sample (notebook): [06-workshops/01-AgentCore-runtime/01-hosting-agent/04-crewai-with-bedrock-model](https://github.com/awslabs/amazon-bedrock-agentcore-samples/tree/main/06-workshops/01-AgentCore-runtime/01-hosting-agent/04-crewai-with-bedrock-model)
- Integrations sample: [03-integrations/agentic-frameworks/crewai](https://github.com/awslabs/amazon-bedrock-agentcore-samples/tree/main/03-integrations/agentic-frameworks/crewai)

_Source: [what-is-bedrock-agentcore (Runtime integrations table)](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/what-is-bedrock-agentcore.html)_

### LlamaIndex

Use any LlamaIndex agent (e.g., `FunctionAgent`, `ReActAgent`) with any model. Wrap the agent's async `run()` inside an async entrypoint.

```python
from llama_index.core.agent.workflow import FunctionAgent
from llama_index.core.tools import FunctionTool
from bedrock_agentcore.runtime import BedrockAgentCoreApp
import asyncio

# Define tools as LlamaIndex FunctionTool instances
def multiply(a: float, b: float) -> float:
    """Multiply two numbers."""
    return a * b

tool = FunctionTool.from_defaults(fn=multiply)
agent = FunctionAgent(tools=[tool], llm=..., system_prompt="You are a financial assistant.")

app = BedrockAgentCoreApp()

@app.entrypoint
async def agent_invocation(payload, context):
    response = await agent.run(payload.get("prompt", ""))
    return {"result": str(response)}

app.run()
```

- The official sample uses Yahoo Finance tools and `FunctionAgent` with OpenAI GPT-4o-mini, demonstrating model-agnostic deployment.
- `pip install llama-index bedrock-agentcore`
- Full sample: [03-integrations/agentic-frameworks/llamaindex](https://github.com/awslabs/amazon-bedrock-agentcore-samples/tree/main/03-integrations/agentic-frameworks/llamaindex)

_Source: [Building Production-Ready AI Agents with LlamaIndex and Amazon Bedrock AgentCore](https://dev.to/aws/building-production-ready-ai-agents-with-llamaindex-and-amazon-bedrock-agentcore-1fm3) (AWS Dev.to, official AWS content)_

### Google ADK

Google's Agent Development Kit (`google-adk`) agents are async; use `asyncio.run()` inside the entrypoint. The `context.session_id` provided by AgentCore maps naturally to ADK's session ID concept.

```python
from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools import google_search
from google.genai import types
from bedrock_agentcore.runtime import BedrockAgentCoreApp
import asyncio

APP_NAME = "my_adk_agent"

root_agent = Agent(
    model="gemini-2.0-flash",
    name="my_agent",
    description="Agent that can search the web.",
    instruction="Answer questions by searching the internet.",
    tools=[google_search],
)

async def call_agent(query: str, user_id: str, session_id: str) -> str:
    session_service = InMemorySessionService()
    await session_service.create_session(
        app_name=APP_NAME, user_id=user_id, session_id=session_id
    )
    runner = Runner(agent=root_agent, app_name=APP_NAME, session_service=session_service)
    content = types.Content(role="user", parts=[types.Part(text=query)])
    events = runner.run_async(user_id=user_id, session_id=session_id, new_message=content)
    async for event in events:
        if event.is_final_response():
            return event.content.parts[0].text
    return ""

app = BedrockAgentCoreApp()

@app.entrypoint
def agent_invocation(payload, context):
    return asyncio.run(
        call_agent(
            query=payload.get("prompt", ""),
            user_id=payload.get("user_id", "default_user"),
            session_id=context.session_id,
        )
    )

app.run()
```

- `pip install google-adk bedrock-agentcore`
- Full sample: [03-integrations/agentic-frameworks/adk](https://github.com/awslabs/amazon-bedrock-agentcore-samples/tree/main/03-integrations/agentic-frameworks/adk)

_Source: [Use any agent framework — AgentCore docs](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/using-any-agent-framework.html)_

### TypeScript agents (manual server)

For TypeScript frameworks not yet supported by the `agentcore create` wizard (e.g., Mastra), build an Express/Fastify server manually. The contract is identical: `POST /invocations`, `GET /ping`, port 8080, `linux/arm64` container.

```typescript
import express from 'express'
import * as strands from '@strands-agents/sdk'

const app = express()

const agent = new strands.Agent({
  model: new strands.BedrockModel({ region: 'us-east-1' }),
  tools: [],
})

// REQUIRED health check
app.get('/ping', (_, res) =>
  res.json({ status: 'Healthy', time_of_last_update: Math.floor(Date.now() / 1000) })
)

// REQUIRED invocation — AWS sends raw binary; use express.raw
app.post('/invocations', express.raw({ type: '*/*' }), async (req, res) => {
  const prompt = new TextDecoder().decode(req.body as Buffer)
  const response = await agent.invoke(prompt)
  res.json({ response })
})

app.listen(8080, '0.0.0.0')
```

Dockerfile must use `--platform=linux/arm64`.

_Source: [TypeScript deployment — Strands Agents Docs](https://strandsagents.com/docs/user-guide/deploy/deploy_to_bedrock_agentcore/typescript/index.md)_

---

## Strands Python vs TypeScript SDK differences

This section summarizes the key behavioral differences between the Strands Agents Python SDK (`strands-agents` v1.42.0, June 2026) and the TypeScript SDK (`@strands-agents/sdk` v1.4.0, June 2026; re-verify — changes frequently).

> The TypeScript SDK is the active codebase; the original `sdk-typescript` repository has been archived and development moved to the `strands-agents/harness-sdk` monorepo.

### Workflow primitive: Python only

The `Workflow` orchestration primitive — a developer-defined task DAG that executes as a single non-conversational tool — exists **only in Python**. The `strands-agents-tools` Python package (v0.7.0) ships a `workflow` tool that handles task dependencies and parallel execution automatically.

In TypeScript, only `Graph` and `Swarm` are available as built-in multi-agent orchestrators. To implement workflow-style pipelines in TypeScript, chain agents in code or use `Graph` with a linear topology.

_Source: [Multi-agent Patterns — Strands Agents Docs](https://strandsagents.com/docs/user-guide/concepts/multi-agent/multi-agent-patterns/index.md)_

### Graph: conditional-edge semantics differ

| Behavior | Python SDK | TypeScript SDK |
|---|---|---|
| **Dependency resolution** | **OR semantics** — a node fires when *any single* incoming edge from the completed batch is satisfied | **AND semantics** — a node runs only when *all* incoming edge sources are completed |
| **Scheduling model** | Executes in discrete batches; waits for the entire batch before scheduling the next set | Launches nodes individually as they become ready (up to `maxConcurrency`) |
| **Node state** | Accumulates agent state across executions unless `reset_on_revisit=True` is explicitly set | **Stateless by default** — snapshots and restores agent state on each execution; set `preserveContext: true` on an `AgentNode` to opt into accumulation |
| **Error handling** | Node failure throws exception (fail-fast); orchestrator limit violations return `FAILED` result | Node failure produces `FAILED` result (parallel paths continue); orchestrator `maxSteps` exceeded throws exception |
| **Node cancellation** | Cancelled node results in `FAILED` status | Cancelled node produces `CANCELLED` status (distinguishable from failure) |
| **Graph construction** | Mutable `GraphBuilder` — `add_node()`, `add_edge()`, `set_entry_point()`, `build()` | Declarative `Graph({ nodes, edges, sources, maxSteps, maxConcurrency, timeout })` constructor |
| **Conditional edges with runtime context** | Supported (`invocation_state` dict passed to edge condition) | **Not supported** — edge handlers receive node state only |

_Source: [Graph — Strands Agents TypeScript API](https://strandsagents.com/docs/api/typescript/Graph/index.md) and [Graph pattern user guide](https://strandsagents.com/docs/user-guide/concepts/multi-agent/graph/index.md)_

### Model and API surface parity

| Feature | Python SDK | TypeScript SDK |
|---|---|---|
| Supported model providers | Amazon Bedrock, Anthropic, Gemini, LiteLLM, Llama, Ollama, OpenAI, Writer, custom | Amazon Bedrock, Anthropic, OpenAI, Gemini (subset of Python; verify at SDK docs) |
| Swarm pattern | Yes | Yes |
| Graph pattern | Yes | Yes |
| Workflow pattern | Yes (via `strands-agents-tools`) | No |
| A2A remote agents in Graph | Yes | Not documented |
| Swarm tool in `strands-agents-tools` | Yes | No (Python only) |
| Streaming | `agent.stream_async()` | `agent.stream()` (AsyncGenerator) |
| AgentCore CLI scaffolding | `agentcore create --framework Strands` | `agentcore create … --language TypeScript --framework Strands` |

_Sources: [Strands Python SDK — GitHub](https://github.com/strands-agents/sdk-python), [Strands TypeScript SDK — GitHub](https://github.com/strands-agents/sdk-typescript) (archived; active repo: [strands-agents/harness-sdk](https://github.com/strands-agents/harness-sdk)), [AgentCore CLI get started (TypeScript)](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-cli-typescript.html)_

### Current SDK versions (June 2026)

| Package | Version | Install |
|---|---|---|
| `strands-agents` (Python) | 1.42.0 | `pip install strands-agents` |
| `strands-agents-tools` (Python) | 0.7.0 | `pip install strands-agents-tools` |
| `@strands-agents/sdk` (TypeScript) | 1.4.0 | `npm install @strands-agents/sdk` |
| `bedrock-agentcore` (Python SDK) | 1.13.0 | `pip install bedrock-agentcore` |
| AgentCore CLI | latest | `npm install -g @aws/agentcore` |

> Version numbers change frequently. Verify against PyPI / npm before pinning in production manifests.

---

## Best practices

- **Test locally before deploying.** Use `agentcore dev` to start a local server that mirrors the runtime environment; invoke it with `curl -X POST http://localhost:8080/invocations -d '{"prompt":"hello"}'` before running `agentcore deploy`. _Source: [Get started with the AgentCore CLI](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-cli.html)_

- **Always target `linux/arm64` in your Dockerfile.** The runtime environment is ARM64; an x86 image will fail at cold start. Use `FROM --platform=linux/arm64 ...` in every `Dockerfile`. _Source: [HTTP protocol contract — container requirements](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-http-protocol-contract.html)_

- **Use the `bedrock-agentcore` Python SDK to avoid boilerplate.** It auto-generates `/ping` with the correct JSON schema and wires `/invocations` to your entrypoint, including SSE streaming. _Source: [Python deployment — Strands Agents Docs](https://strandsagents.com/docs/user-guide/deploy/deploy_to_bedrock_agentcore/python/index.md)_

- **For TypeScript agents, use `express.raw({ type: '*/*' })` on `/invocations`.** The AWS SDK sends a binary-encoded payload; without the raw middleware, body-parsing middleware will corrupt the input. _Source: [TypeScript deployment — Strands Agents Docs](https://strandsagents.com/docs/user-guide/deploy/deploy_to_bedrock_agentcore/typescript/index.md)_

- **Implement meaningful `/ping` responses.** Return `{"status": "HealthyBusy", ...}` when your agent is processing async background tasks; the runtime uses this to keep the session alive. _Source: [HTTP protocol contract — /ping](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-http-protocol-contract.html)_

- **Use least-privilege IAM for the execution role.** The `BedrockAgentCoreFullAccess` managed policy is broad; for production, scope `bedrock:InvokeModel` to the specific model ARNs your agent uses and restrict ECR access to the specific repository. _Source: [IAM Permissions for AgentCore Runtime](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-permissions.html)_

- **Prefer `CodeZip` build for pure-Python agents; use `Container` only when you need native dependencies or a custom OS layer.** `CodeZip` avoids the ECR push step during iteration. _Source: [Get started with the AgentCore CLI (advanced options — build types)](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-cli.html)_

- **Enable CloudWatch Transaction Search for observability before your first production invocation.** Without it, AgentCore's built-in tracing (X-Ray spans for reasoning steps and tool calls) is not visible. _Source: [Get started with the AgentCore CLI — Step 4: Enable observability](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-cli.html)_

- **When using async Python frameworks (Google ADK, LlamaIndex async), call `asyncio.run()` inside a sync entrypoint, or make the entrypoint itself `async def`.** The `BedrockAgentCoreApp` ASGI server supports both. _Source: [Use any agent framework — AgentCore docs](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/using-any-agent-framework.html)_

- **Pin the Strands Graph conditional-edge semantics.** If migrating a Python Graph to TypeScript or vice versa, audit every node with multiple incoming edges: Python fires on OR (any completed edge), TypeScript fires on AND (all incoming edges completed). A "join" node that correctly waits for all branches in TypeScript will fire prematurely in Python if any one branch finishes first. _Source: [Graph SDK Differences — Strands Agents Docs](https://strandsagents.com/docs/user-guide/concepts/multi-agent/graph/index.md)_

---

## Code

### Minimal custom HTTP server (any framework — Python FastAPI)

_Source: [Python deployment Option B: Custom Agent — Strands Agents Docs](https://strandsagents.com/docs/user-guide/deploy/deploy_to_bedrock_agentcore/python/index.md)_

```python
from fastapi import FastAPI
from datetime import datetime, timezone
from strands import Agent

app = FastAPI()
agent = Agent()

@app.get("/ping")
def ping():
    return {
        "status": "Healthy",
        "time_of_last_update": int(datetime.now(timezone.utc).timestamp()),
    }

@app.post("/invocations")
async def invoke(body: dict):
    prompt = body.get("prompt", "")
    result = agent(prompt)
    return {"result": str(result)}
```

Run with: `uvicorn agent:app --host 0.0.0.0 --port 8080`

### Invoking a deployed agent with boto3

_Source: [Python deployment — Strands Agents Docs](https://strandsagents.com/docs/user-guide/deploy/deploy_to_bedrock_agentcore/python/index.md)_

```python
import boto3
import json

client = boto3.client("bedrock-agentcore")

response = client.invoke_agent_runtime(
    agentRuntimeArn="arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/my-agent",
    runtimeSessionId="session-uuid-here",
    payload=json.dumps({"prompt": "What is the weather in Seattle?"}).encode(),
)
print(response["response"].read().decode())
```

### ARM64 Dockerfile (Python — uv)

_Source: [Python deployment — Strands Agents Docs](https://strandsagents.com/docs/user-guide/deploy/deploy_to_bedrock_agentcore/python/index.md)_

```dockerfile
FROM --platform=linux/arm64 ghcr.io/astral-sh/uv:python3.11-bookworm-slim

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen

COPY agent.py .

EXPOSE 8080
CMD ["uv", "run", "python", "agent.py"]
```

### ARM64 Dockerfile (TypeScript — Node.js)

_Source: [TypeScript deployment — Strands Agents Docs](https://strandsagents.com/docs/user-guide/deploy/deploy_to_bedrock_agentcore/typescript/index.md)_

```dockerfile
FROM --platform=linux/arm64 public.ecr.aws/docker/library/node:22-slim

WORKDIR /app
COPY package*.json ./
RUN npm ci --omit=dev
COPY dist/ ./dist/

EXPOSE 8080
CMD ["node", "dist/index.js"]
```

### Strands Graph (Python) — OR semantics join example

_Source: [Graph user guide — Strands Agents Docs](https://strandsagents.com/docs/user-guide/concepts/multi-agent/graph/index.md)_

```python
from strands import Agent
from strands.multiagent import GraphBuilder

researcher = Agent(name="researcher", system_prompt="Research specialist")
analyst   = Agent(name="analyst",    system_prompt="Data analysis specialist")
writer    = Agent(name="writer",     system_prompt="Report writer")

builder = GraphBuilder()
builder.add_node(researcher, "research")
builder.add_node(analyst,   "analysis")
builder.add_node(writer,    "report")

builder.add_edge("research", "analysis")
builder.add_edge("analysis", "report")
builder.set_entry_point("research")

graph = builder.build()
result = graph.invoke("Analyse Q1 sales trends")
```

### Strands Graph (TypeScript) — AND semantics join example

_Source: [Graph TypeScript API — Strands Agents Docs](https://strandsagents.com/docs/api/typescript/Graph/index.md)_

```typescript
import { Agent } from '@strands-agents/sdk'
import { Graph } from '@strands-agents/sdk/multiagent'

const researcher = new Agent({ name: 'researcher', systemPrompt: 'Research specialist' })
const analyst    = new Agent({ name: 'analyst',    systemPrompt: 'Analysis specialist' })
const writer     = new Agent({ name: 'writer',     systemPrompt: 'Report writer' })

// writer fires only when BOTH researcher AND analyst have completed (AND semantics)
const graph = new Graph({
  nodes: [researcher, analyst, writer],
  edges: [
    ['researcher', 'writer'],
    ['analyst',    'writer'],
  ],
})

const result = await graph.invoke('Analyse Q1 sales trends')
```

---

## Configuration reference

### AgentCore CLI — `agentcore.json` agent keys

| Key | Values | Notes |
|---|---|---|
| `framework` | `Strands`, `LangChain_LangGraph`, `GoogleADK`, `OpenAIAgents` | Framework used to scaffold `main.py` / `main.ts` |
| `language` | `Python`, `TypeScript` | Target language |
| `build` | `CodeZip`, `Container` | `CodeZip`: no Docker required; `Container`: full Dockerfile |
| `protocol` | `HTTP`, `MCP`, `A2A` | Default `HTTP`; determines which port/path the CLI configures |
| `modelProvider` | `Bedrock`, `Anthropic`, `OpenAI`, `Gemini` | Sets default model env vars in the scaffolded agent |
| `memory` | `none`, `shortTerm`, `longAndShortTerm` | Provisions AgentCore Memory store |

_Source: [Get started with the AgentCore CLI](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-cli.html)_

### HTTP protocol at a glance

| Item | Value |
|---|---|
| Container platform | `linux/arm64` |
| Listening address | `0.0.0.0:8080` |
| Invocation endpoint | `POST /invocations` — `Content-Type: application/json` |
| Health endpoint | `GET /ping` — returns `{"status":"Healthy","time_of_last_update":<ts>}` |
| Streaming response | `Content-Type: text/event-stream` (SSE) |
| WebSocket endpoint | `GET /ws` (optional, same port) |
| Max payload | 100 MB (supports multimodal — text, images, audio, video) |
| Max session duration | 8 hours |

_Source: [HTTP protocol contract](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-http-protocol-contract.html) and [agents-tools-runtime](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agents-tools-runtime.html)_

### Strands Graph: Python vs TypeScript constructor comparison

| Parameter | Python (`GraphBuilder`) | TypeScript (`Graph` constructor) |
|---|---|---|
| Add node | `builder.add_node(agent, "id")` | `nodes: [agent, ...]` (auto-uses `agent.id`) |
| Add edge | `builder.add_edge("from", "to")` | `edges: [["from","to"], ...]` or `{source, target, handler}` |
| Conditional edge | `builder.add_edge("a","b", condition=fn)` | `{source:"a", target:"b", handler: EdgeHandler}` |
| Entry points | `builder.set_entry_point("id")` | `sources: ["id"]` (auto-detected if omitted) |
| Execution limit | `builder.set_max_node_executions(N)` | `maxSteps: N` |
| Concurrency | Not configurable per-graph | `maxConcurrency: N` |
| Node state | Accumulates (set `reset_on_revisit=True` to clear) | Stateless by default (set `preserveContext: true` to accumulate) |

_Source: [Graph user guide — SDK Differences section](https://strandsagents.com/docs/user-guide/concepts/multi-agent/graph/index.md)_

---

## Gotchas

- **Wrong platform architecture.** Building your Docker image on an Apple Silicon Mac or an x86 CI runner without explicitly specifying `--platform linux/arm64` produces an `x86_64` image. AgentCore Runtime rejects it at cold start. Always set the platform in the `FROM` line or pass `--platform linux/arm64` to `docker build`.

- **Binary body decoding in TypeScript.** The AgentCore control plane sends the invocation payload as a raw binary stream. If you use `express.json()` middleware instead of `express.raw({ type: '*/*' })`, the body is silently discarded and `req.body` is undefined. Decode with `new TextDecoder().decode(req.body)` after the raw middleware.

- **`bedrock-agentcore-starter-toolkit` vs `bedrock-agentcore` package name.** The legacy toolkit (`pip install bedrock-agentcore-starter-toolkit`) and the current SDK (`pip install bedrock-agentcore`) coexist on PyPI but conflict when both are installed. The toolkit is legacy; remove it before installing the SDK.

- **`/ping` schema must be exact.** AgentCore's health monitor expects a JSON response with the keys `status` and `time_of_last_update`. A plain `200 OK` with no body, or a non-JSON body, will cause the session to be marked unhealthy. Returning `"HealthyBusy"` instead of `"Healthy"` is valid and keeps the session alive when running async tasks.

- **Strands Graph OR vs AND semantics.** A Python graph with a diamond topology (two parallel branches merging at one node) fires the merge node when the *first* branch finishes. The equivalent TypeScript graph waits for *both*. Porting graphs between SDKs without adjusting edge logic produces silently wrong execution order.

- **Workflow primitive is Python-only.** There is no `Workflow` class or tool in `@strands-agents/sdk`. If your architecture needs parallel task DAG execution in TypeScript, model it as a `Graph` with sequential or parallel edges instead.

- **TypeScript AgentCore CLI scaffolding currently supports Strands only.** The `agentcore create --language TypeScript` wizard only offers `Strands` as a framework option. To deploy LangGraph.js or other TypeScript frameworks, write the Express/Fastify server manually and use `agentcore deploy --build Container`.

- **Google ADK agents are async; avoid blocking the event loop.** `asyncio.run()` inside a synchronous `@app.entrypoint` is safe for simple cases, but wrapping long-running ADK sessions in a blocking call can stall the server under load. For production ADK agents, make the entrypoint `async def` and `await` the ADK runner directly.

- **AgentCore Memory integration requires separate setup.** `BedrockAgentCoreApp` does not automatically provision or attach a Memory store; you must create one via `agentcore add memory` (CLI) or the `bedrock-agentcore-control` boto3 client. See [agentcore-runtime.md](agentcore-runtime.md) for details.

---

## Official sources

- [Host agent or tools with Amazon Bedrock AgentCore Runtime](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agents-tools-runtime.html)
- [Use any agent framework](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/using-any-agent-framework.html)
- [HTTP protocol contract](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-http-protocol-contract.html)
- [Service contract (protocol comparison table)](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-service-contract.html)
- [Get started with the AgentCore CLI (Python)](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-cli.html)
- [Get started with the AgentCore CLI (TypeScript)](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-cli-typescript.html)
- [IAM Permissions for AgentCore Runtime](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-permissions.html)
- [What is Amazon Bedrock AgentCore?](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/what-is-bedrock-agentcore.html)
- [AgentCore CLI — GitHub](https://github.com/aws/agentcore-cli)
- [bedrock-agentcore-starter-toolkit — GitHub (legacy)](https://github.com/aws/bedrock-agentcore-starter-toolkit)
- [awslabs/amazon-bedrock-agentcore-samples — GitHub](https://github.com/awslabs/amazon-bedrock-agentcore-samples)
- [03-integrations/agentic-frameworks — all framework samples](https://github.com/awslabs/amazon-bedrock-agentcore-samples/tree/main/03-integrations/agentic-frameworks)
- [Strands Agents — Deploy to Bedrock AgentCore (Python)](https://strandsagents.com/docs/user-guide/deploy/deploy_to_bedrock_agentcore/python/index.md)
- [Strands Agents — Deploy to Bedrock AgentCore (TypeScript)](https://strandsagents.com/docs/user-guide/deploy/deploy_to_bedrock_agentcore/typescript/index.md)
- [Strands Agents — Graph user guide (Python + TypeScript)](https://strandsagents.com/docs/user-guide/concepts/multi-agent/graph/index.md)
- [Strands Agents — Multi-agent patterns](https://strandsagents.com/docs/user-guide/concepts/multi-agent/multi-agent-patterns/index.md)
- [Strands Agents — TypeScript Graph API reference](https://strandsagents.com/docs/api/typescript/Graph/index.md)
- [strands-agents — PyPI](https://pypi.org/project/strands-agents/)
- [strands-agents-tools — PyPI](https://pypi.org/project/strands-agents-tools/)
- [bedrock-agentcore — PyPI](https://pypi.org/project/bedrock-agentcore/)
- [strands-agents/sdk-python — GitHub](https://github.com/strands-agents/sdk-python)
- [strands-agents/sdk-typescript — GitHub](https://github.com/strands-agents/sdk-typescript) _(archived; development moved to [strands-agents/harness-sdk](https://github.com/strands-agents/harness-sdk) monorepo, `strands-ts/` directory)_
