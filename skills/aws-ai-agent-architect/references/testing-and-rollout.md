# Testing & Safe Rollout for AWS AI Agents

> Part of the **aws-ai-agent-architect** skill. See [SKILL.md](../SKILL.md) for the decision tree. Every source below is official — re-open it to verify details.

## Table of contents

1. [Overview](#overview)
2. [Key concepts](#key-concepts)
3. [Best practices](#best-practices)
4. [Phase 1 — Local development and testing](#phase-1--local-development-and-testing)
   - [AgentCore CLI `dev` server](#agentcore-cli-dev-server)
   - [BedrockAgentCoreApp SDK wrapper (manual)](#bedrockagentcoreapp-sdk-wrapper-manual)
5. [Phase 2 — Unit testing Strands tools and agents](#phase-2--unit-testing-strands-tools-and-agents)
   - [Testing `@tool` functions directly](#testing-tool-functions-directly)
   - [Strands Evals SDK — deterministic evaluators](#strands-evals-sdk--deterministic-evaluators)
   - [Strands Evals SDK — LLM-based evaluators](#strands-evals-sdk--llm-based-evaluators)
   - [ToolSimulator for safe tool mocking](#toolsimulator-for-safe-tool-mocking)
6. [Phase 3 — Pre-production evaluation with AgentCore Evaluations](#phase-3--pre-production-evaluation-with-agentcore-evaluations)
   - [On-demand evaluation](#on-demand-evaluation)
   - [Dataset / batch evaluation for CI regression](#dataset--batch-evaluation-for-ci-regression)
7. [Phase 4 — Safe rollout with AgentCore Runtime versioning](#phase-4--safe-rollout-with-agentcore-runtime-versioning)
   - [How versions and endpoints work](#how-versions-and-endpoints-work)
   - [Multi-environment endpoint pattern](#multi-environment-endpoint-pattern)
8. [Phase 5 — Production traffic management and A/B testing](#phase-5--production-traffic-management-and-ab-testing)
   - [Online evaluation for continuous monitoring](#online-evaluation-for-continuous-monitoring)
   - [A/B testing via AgentCore Gateway](#ab-testing-via-agentcore-gateway)
   - [Configuration bundles for rollback](#configuration-bundles-for-rollback)
9. [Code](#code)
10. [Configuration reference](#configuration-reference)
11. [Gotchas](#gotchas)
12. [Test-before-deploy checklist](#test-before-deploy-checklist)
13. [Official sources](#official-sources)

---

## Overview

Testing and safe rollout for AWS AI agents requires a layered approach because agents are non-deterministic: the same input may produce different, yet valid, outputs. This file covers the full lifecycle from first local run to production traffic shifting.

**Maturity indicators (as of June 2026):**

| Capability | Maturity |
|---|---|
| AgentCore CLI (`agentcore dev`, `deploy`, `invoke`) | GA |
| AgentCore Runtime versioning + endpoints | GA |
| AgentCore Evaluations (on-demand, batch) | GA |
| AgentCore Evaluations online evaluation | GA |
| Strands Evals SDK (`strands-agents-evals`) | GA |
| AgentCore optimization (recommendations, A/B testing, configuration bundles) | Preview |

Cross-links to companion reference files:

- Observability (CloudWatch traces, ADOT, Transaction Search) → [observability.md](observability.md)
- AgentCore Gateway routing and identity → [gateway-identity.md](gateway-identity.md)
- Managed alternatives (Bedrock Agents) → [managed-alternatives.md](managed-alternatives.md)
- AgentCore Runtime deploy mechanics → [agentcore-runtime.md](agentcore-runtime.md)

---

## Key concepts

| Term | Meaning |
|---|---|
| **AgentCore CLI** | `npm install -g @aws/agentcore` — scaffolds, runs locally, deploys via CDK, invokes. Supersedes the old `bedrock-agentcore-starter-toolkit`. |
| **`agentcore dev`** | Local development server on `http://localhost:8080` that mimics the AgentCore Runtime environment; hot-reload included. |
| **`BedrockAgentCoreApp`** | Python SDK wrapper (`pip install bedrock-agentcore`) that auto-exposes `/invocations` and `/ping` so any callable becomes AgentCore-compatible. |
| **Version** | Immutable snapshot of an AgentCore Runtime created automatically on every update. Numbered V1, V2, …. |
| **DEFAULT endpoint** | Auto-created endpoint; always points to the **latest** version after each update. Use for dev / CI. |
| **Custom endpoint** | Named endpoint (e.g., `production`) pinned to a specific version. Must be explicitly updated to receive new traffic. |
| **Strands Evals** | Open-source evaluation framework (`strands-agents-evals`). Provides Cases, Experiments, deterministic evaluators, LLM judges, ToolSimulator. |
| **AgentCore Evaluations** | Managed AWS service for on-demand, batch, and online evaluation of agents via CloudWatch traces. |
| **Configuration bundle** | Versioned, immutable snapshot of agent configuration (system prompt, model ID, tool descriptions). Decouples behavior from code. |
| **A/B test** | Traffic split between two variants (control / treatment) through AgentCore Gateway, with online evaluation scoring each session. |

---

## Best practices

- **Never skip local testing.** Run `agentcore dev` and invoke the `/invocations` and `/ping` endpoints before building a container image. Catching HTTP contract errors locally costs seconds; catching them post-deploy costs hours. _Source: [docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-cli.html](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-cli.html)_

- **Use deterministic evaluators as a first CI gate.** `Equals`, `Contains`, `ToolCalled`, `StateEquals` from `strands-agents-evals` require no LLM calls, are fast, and produce the same score for the same input — ideal for a blocking PR check. _Source: [strandsagents.com/docs/user-guide/evals-sdk/evaluators/deterministic_evaluators/](https://strandsagents.com/docs/user-guide/evals-sdk/evaluators/deterministic_evaluators/index.md)_

- **Add LLM-as-a-judge evaluators (`OutputEvaluator`, `TrajectoryEvaluator`, `HelpfulnessEvaluator`) for nuanced quality gates.** Run them in a parallel CI job to avoid blocking the pipeline while the judge model responds. _Source: [strandsagents.com/blog/evaluating-ai-agents-practical-guide-strands-evals/](https://strandsagents.com/blog/evaluating-ai-agents-practical-guide-strands-evals/index.md)_

- **Use ToolSimulator instead of live API calls in tests.** Live APIs impose rate limits, cause side effects, and expose PII. `ToolSimulator` intercepts registered tool calls, generates realistic LLM-powered responses, and maintains stateful context across multi-turn flows. _Source: [strandsagents.com/blog/toolsimulator-scalable-tool-testing-ai-agents/](https://strandsagents.com/blog/toolsimulator-scalable-tool-testing-ai-agents/index.md)_

- **Never route production traffic to the DEFAULT endpoint.** The DEFAULT endpoint auto-updates on every runtime change. Pin a named endpoint (e.g., `production`) to a known-good version and only advance it after explicit sign-off. _Source: [docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agent-runtime-versioning.html](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agent-runtime-versioning.html)_

- **Enable CloudWatch Transaction Search before any production invocation.** Without it, AgentCore Evaluations cannot collect spans and evaluation jobs will fail. _Source: [docs.aws.amazon.com/bedrock-agentcore/latest/devguide/getting-started-on-demand.html](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/getting-started-on-demand.html)_

- **Use the on-demand dataset runner for CI, batch runner for large baselines.** The on-demand runner (`OnDemandEvaluationDatasetRunner`) collects spans SDK-side and returns per-scenario detail immediately. The batch runner (`BatchEvaluationRunner`) delegates to the service asynchronously and is better for large datasets. _Source: [docs.aws.amazon.com/bedrock-agentcore/latest/devguide/dataset-evaluations.html](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/dataset-evaluations.html)_

- **Use configuration bundles to decouple prompt/model changes from code deployments.** A bundle version is immutable; rolling back is as simple as pointing the endpoint or A/B test back to a previous version ID. _Source: [docs.aws.amazon.com/bedrock-agentcore/latest/devguide/configuration-bundles.html](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/configuration-bundles.html)_

- **Validate A/B test significance before committing a full rollout.** The service computes a p-value per evaluator. A p-value < 0.05 indicates the difference is statistically significant. Stop the test and route 100% of traffic only when significance is confirmed. _Source: [docs.aws.amazon.com/bedrock-agentcore/latest/devguide/ab-testing.html](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/ab-testing.html)_

---

## Phase 1 — Local development and testing

### AgentCore CLI dev server

The AgentCore CLI (GA) is the recommended path for new projects. It scaffolds the project, runs a local server that faithfully mirrors the AgentCore Runtime environment, and deploys via CDK.

**Install:**

```bash
npm install -g @aws/agentcore
```

_Source: [docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-cli.html](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-cli.html)_

**Scaffold and start local server:**

```bash
# Interactive wizard
agentcore create

# Or non-interactive with defaults (Strands + Bedrock)
agentcore create --name MyAgent --defaults

cd MyAgent

# Start local dev server (opens Agent Inspector in browser, runs on :8080)
agentcore dev

# In a second terminal: invoke the local server
agentcore dev "Hello, tell me a joke"

# Stream the response in real time
agentcore dev "What can you do?" --stream
```

_Source: [docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-cli.html](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-cli.html)_

The `agentcore dev` command:
- Auto-creates a Python venv and installs dependencies.
- Starts a local HTTP server on `http://localhost:8080` that exposes `/invocations` (POST) and `/ping` (GET) — the exact contract required by AgentCore Runtime.
- Supports hot-reload. Use `--logs` to tail server logs in non-interactive mode.

> The `bedrock-agentcore-starter-toolkit` package is **deprecated**. Uninstall it to avoid conflicts: `pip uninstall bedrock-agentcore-starter-toolkit`. _Source: [strandsagents.com/docs/user-guide/deploy/deploy_to_bedrock_agentcore/python/](https://strandsagents.com/docs/user-guide/deploy/deploy_to_bedrock_agentcore/python/index.md)_

### BedrockAgentCoreApp SDK wrapper (manual)

For agents that do not use the CLI scaffolding, wrap your agent function with `BedrockAgentCoreApp`. This auto-wires the required HTTP endpoints.

```python
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import Agent

app = BedrockAgentCoreApp()
agent = Agent()

@app.entrypoint
def invoke(payload):
    user_message = payload.get("prompt", "Hello")
    result = agent(user_message)
    return {"result": result.message}

if __name__ == "__main__":
    app.run()
```

_Source: [strandsagents.com/docs/user-guide/deploy/deploy_to_bedrock_agentcore/python/](https://strandsagents.com/docs/user-guide/deploy/deploy_to_bedrock_agentcore/python/index.md)_

**Smoke-test the running server with curl:**

```bash
# Health check
curl http://localhost:8080/ping

# Invocation
curl -X POST http://localhost:8080/invocations \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Hello world!"}'
```

_Source: [strandsagents.com/docs/user-guide/deploy/deploy_to_bedrock_agentcore/python/](https://strandsagents.com/docs/user-guide/deploy/deploy_to_bedrock_agentcore/python/index.md)_

**Docker-based local test (Container build type only):**

```bash
# Build for the required linux/arm64 platform
docker buildx build --platform linux/arm64 -t my-agent:arm64 --load .

# Run locally with AWS credentials injected
docker run --platform linux/arm64 -p 8080:8080 \
  -e AWS_ACCESS_KEY_ID="$AWS_ACCESS_KEY_ID" \
  -e AWS_SECRET_ACCESS_KEY="$AWS_SECRET_ACCESS_KEY" \
  -e AWS_SESSION_TOKEN="$AWS_SESSION_TOKEN" \
  -e AWS_REGION="$AWS_REGION" \
  my-agent:arm64
```

_Source: [strandsagents.com/docs/user-guide/deploy/deploy_to_bedrock_agentcore/python/](https://strandsagents.com/docs/user-guide/deploy/deploy_to_bedrock_agentcore/python/index.md)_

---

## Phase 2 — Unit testing Strands tools and agents

### Testing `@tool` functions directly

A Strands `@tool`-decorated function is a plain Python callable. The decorator extracts metadata and generates a JSON schema, but the function body executes normally. You can call it directly in pytest without an Agent or Bedrock connection.

```python
# tools.py
from strands import tool

@tool
def get_exchange_rate(base_currency: str, target_currency: str) -> dict:
    """
    Fetches the current exchange rate between two currencies.

    Args:
        base_currency: ISO 4217 code for the base currency (e.g., USD).
        target_currency: ISO 4217 code for the target currency (e.g., EUR).

    Returns:
        A dict with status and rate.
    """
    # ... real implementation using an FX API ...
    return {"status": "success", "content": [{"text": "1 USD = 0.92 EUR"}]}
```

```python
# test_tools.py
from unittest.mock import patch
from tools import get_exchange_rate

def test_get_exchange_rate_returns_rate():
    # Call the tool function directly — no Agent or Bedrock needed
    result = get_exchange_rate(base_currency="USD", target_currency="EUR")
    assert result["status"] == "success"
    assert "EUR" in result["content"][0]["text"]

def test_get_exchange_rate_with_mocked_api():
    with patch("tools.requests.get") as mock_get:
        mock_get.return_value.json.return_value = {"rate": 0.92}
        result = get_exchange_rate(base_currency="USD", target_currency="EUR")
    assert result["status"] == "success"
```

_Source: [strandsagents.com/docs/api/python/strands.tools.decorator/](https://strandsagents.com/docs/api/python/strands.tools.decorator/index.md)_

### Strands Evals SDK — deterministic evaluators

`pip install strands-agents-evals`. Deterministic evaluators require **no LLM calls** and produce consistent results — ideal as a fast, first-pass CI gate.

Available deterministic evaluators:

| Evaluator | What it checks |
|---|---|
| `Equals` | Exact match against `expected_output` or an explicit `value` |
| `Contains` | Substring match (optional `case_sensitive`) |
| `StartsWith` | Prefix match |
| `ToolCalled` | Whether a named tool appeared in the trajectory |
| `StateEquals` | Whether a named environment state equals an expected value |

```python
# eval_deterministic.py
from strands import Agent
from strands_evals import Case, Experiment
from strands_evals.evaluators import Contains, ToolCalled

cases = [
    Case(
        name="capital-france",
        input="What is the capital of France?",
        expected_output="Paris",
    ),
    Case(
        name="calculator-use",
        input="What is 15% of 230?",
        expected_trajectory=["calculator"],
    ),
]

def run_agent(case):
    agent = Agent(callback_handler=None)
    result = str(agent(case.input))
    return {"output": result, "trajectory": agent.messages}

experiment = Experiment(
    cases=cases,
    evaluators=[
        Contains(value="Paris", case_sensitive=False),
        ToolCalled(tool_name="calculator"),
    ],
)
reports = experiment.run_evaluations(run_agent)
reports[0].run_display()
```

_Source: [strandsagents.com/docs/user-guide/evals-sdk/evaluators/deterministic_evaluators/](https://strandsagents.com/docs/user-guide/evals-sdk/evaluators/deterministic_evaluators/index.md)_

### Strands Evals SDK — LLM-based evaluators

Ten built-in evaluators use an LLM as judge (default: Claude 4 via Amazon Bedrock):

| Evaluator | Dimension |
|---|---|
| `OutputEvaluator` | Custom rubric against final response |
| `TrajectoryEvaluator` | Tool call sequence — supports exact, in-order, any-order scoring |
| `InteractionsEvaluator` | Multi-agent / orchestrator interaction sequences |
| `HelpfulnessEvaluator` | 7-point scale from user's perspective |
| `FaithfulnessEvaluator` | Grounding in conversation history (critical for RAG) |
| `HarmfulnessEvaluator` | Binary safety flag |
| `ToolSelectionAccuracyEvaluator` | Was choosing this tool justified? |
| `ToolParameterAccuracyEvaluator` | Were the tool parameters correct? |
| `GoalSuccessRateEvaluator` | Did the user achieve their goal across the session? |
| `CorrectnessEvaluator` | Factual accuracy |

```python
from strands import Agent
from strands_evals import eval_task, Case, Experiment
from strands_evals.evaluators import OutputEvaluator, HelpfulnessEvaluator

@eval_task()  # decorator handles boilerplate; just return an Agent
def get_response():
    return Agent(
        system_prompt="You are a helpful assistant.",
        callback_handler=None,
    )

test_cases = [
    Case(
        name="knowledge-paris",
        input="What is the capital of France?",
        expected_output="Paris",
    ),
]

evaluators = [
    OutputEvaluator(
        rubric=(
            "Score 1.0 if factually correct and clear. "
            "Score 0.5 if partially correct. Score 0.0 if incorrect."
        ),
        include_inputs=True,
    ),
    HelpfulnessEvaluator(),
]

experiment = Experiment(cases=test_cases, evaluators=evaluators)
reports = experiment.run_evaluations(get_response)
reports[0].run_display()

# Persist results for comparison across runs
experiment.to_file("pre_deploy_eval")
```

_Source: [strandsagents.com/blog/evaluating-ai-agents-practical-guide-strands-evals/](https://strandsagents.com/blog/evaluating-ai-agents-practical-guide-strands-evals/index.md)_

### ToolSimulator for safe tool mocking

`ToolSimulator` (part of `strands-agents-evals`) replaces live API calls with LLM-generated realistic responses. It validates parameters, maintains shared state across multi-turn calls, and enforces Pydantic response schemas.

```python
from strands import Agent
from strands_evals.simulation.tool_simulator import ToolSimulator

tool_simulator = ToolSimulator()

@tool_simulator.tool(
    initial_state_description=(
        "Flight database: SEA->JFK flights available at 8am, 12pm, 6pm. "
        "Prices $180–$420. No bookings active."
    ),
    share_state_id="flight_booking",
)
def search_flights(origin: str, destination: str, date: str) -> dict:
    """Search for available flights between two airports on a given date."""
    pass  # Body never executes — ToolSimulator intercepts calls

@tool_simulator.tool(share_state_id="flight_booking")
def get_booking_status(booking_id: str) -> dict:
    """Retrieve the current status of a flight booking by booking ID."""
    pass

# Inspect state before and after agent execution
initial_state = tool_simulator.get_state("flight_booking")

flight_tool = tool_simulator.get_tool("search_flights")
agent = Agent(
    system_prompt="You are a flight search assistant.",
    tools=[flight_tool],
)
response = agent("Find me flights from Seattle to New York on March 15.")

final_state = tool_simulator.get_state("flight_booking")
# Assert final_state reflects bookings if applicable
```

_Source: [strandsagents.com/blog/toolsimulator-scalable-tool-testing-ai-agents/](https://strandsagents.com/blog/toolsimulator-scalable-tool-testing-ai-agents/index.md)_

---

## Phase 3 — Pre-production evaluation with AgentCore Evaluations

AgentCore Evaluations (GA) computes goal attainment, tool invocation accuracy, and custom metrics against agent traces stored in CloudWatch. It works with agents hosted on AgentCore Runtime **and** agents hosted externally. Supported frameworks: Strands Agents and LangGraph.

See [observability.md](observability.md) for how to enable ADOT instrumentation and CloudWatch Transaction Search.

### On-demand evaluation

On-demand evaluation targets specific sessions or traces by ID. Use it for build-time testing, CI regression checks against curated sessions, and investigation of specific failures.

**Via AgentCore CLI (simplest):**

```bash
# Run on a specific session — CLI auto-queries CloudWatch
RUNTIME_NAME="your_runtime_name"
SESSION_ID="your_session_id"

agentcore run eval \
  --runtime $RUNTIME_NAME \
  --session-id $SESSION_ID \
  --evaluator "Builtin.Helpfulness" \
  --evaluator "Builtin.GoalSuccessRate"

# If inside an agentcore project, runtime is read from agentcore.json:
agentcore run eval \
  --evaluator "Builtin.Helpfulness" \
  --evaluator "Builtin.GoalSuccessRate"

# View history of past eval runs
agentcore evals history
```

_Source: [docs.aws.amazon.com/bedrock-agentcore/latest/devguide/getting-started-on-demand.html](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/getting-started-on-demand.html)_

**Via boto3 AWS SDK:**

```python
import boto3
import json

# Step 1: Invoke your deployed agent and capture the session ID
agent_core_client = boto3.client("bedrock-agentcore", region_name="us-east-1")
session_id = "test-session-18a1dba0-62a0-462g"

response = agent_core_client.invoke_agent_runtime(
    agentRuntimeArn="arn:aws:...",
    runtimeSessionId=session_id,
    payload=json.dumps({"prompt": "Analyze this text..."}),
    qualifier="DEFAULT",
)

# Step 2: Wait a couple of minutes for logs to populate in CloudWatch,
# then call Evaluate with the session spans.
# See official docs for the CloudWatch log-query helper.
```

_Source: [docs.aws.amazon.com/bedrock-agentcore/latest/devguide/getting-started-on-demand.html](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/getting-started-on-demand.html)_

Built-in evaluator IDs available today (verify current list in console — names may change as the service evolves): `Builtin.Helpfulness`, `Builtin.GoalSuccessRate`, `Builtin.ToolInvocationAccuracy`. Custom evaluators (LLM-as-judge and code-based Lambda) are also supported.

_Source: [docs.aws.amazon.com/bedrock-agentcore/latest/devguide/evaluators.html](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/evaluators.html)_

### Dataset / batch evaluation for CI regression

Dataset evaluations run your agent against a curated set of scenarios and score automatically. Use them for:
- Baseline measurement before making changes.
- Pre/post comparison after prompt or model updates.
- Regression testing across curated session sets in CI/CD.

**Prerequisites:** Python 3.10+, `pip install bedrock-agentcore`, agent deployed on AgentCore Runtime with observability enabled, CloudWatch Transaction Search enabled.

| Runner | Span collection | Execution | Best for |
|---|---|---|---|
| `OnDemandEvaluationDatasetRunner` | SDK-side via `AgentSpanCollector` | Synchronous (invoke → wait → evaluate) | CI, small datasets, immediate per-scenario detail |
| `BatchEvaluationRunner` | Server-side from CloudWatch | Asynchronous (invoke → wait → submit → poll) | Large datasets, production baselines, aggregate scores |

_Source: [docs.aws.amazon.com/bedrock-agentcore/latest/devguide/dataset-evaluations.html](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/dataset-evaluations.html)_

---

## Phase 4 — Safe rollout with AgentCore Runtime versioning

### How versions and endpoints work

AgentCore Runtime versions are **immutable** — every configuration change (container image, protocol settings, network settings) automatically creates a new numbered version. _Source: [docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agent-runtime-versioning.html](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agent-runtime-versioning.html)_

| Event | Version behavior | DEFAULT endpoint | Custom endpoint |
|---|---|---|---|
| Initial creation | V1 created automatically | Points to V1 | — |
| Protocol change | V2 created | Auto-updates to V2 | Stays on V1 |
| Create `PROD` endpoint pointing to V2 | No new version | V2 | PROD → V2 |
| Container image update | V3 created | Auto-updates to V3 | PROD stays on V2 |
| Manually update `PROD` to V3 | No new version | V3 | PROD → V3 |

_Source: [docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agent-runtime-versioning.html](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agent-runtime-versioning.html)_

**Endpoint lifecycle states:** `CREATING` → `READY` → `UPDATING` → `READY` (or `CREATE_FAILED` / `UPDATE_FAILED`). Updates happen without downtime.

_Source: [docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-how-it-works.html](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-how-it-works.html)_

### Multi-environment endpoint pattern

Use one runtime with multiple named endpoints to promote versions through environments:

```
DEFAULT (auto-latest)  →  dev/CI testing
staging endpoint       →  manual QA / pre-production eval
production endpoint    →  live traffic, explicit manual update only
```

**Pinning a custom endpoint to a specific version:**

```python
import boto3

client = boto3.client("bedrock-agentcore", region_name="us-west-2")

# Create a production endpoint pinned to V2
client.create_agent_runtime_endpoint(
    agentRuntimeId="agent-runtime-12345",
    endpointName="production-endpoint",
    agentRuntimeVersion="v2",
    description="Stable production endpoint",
)

# Later: promote production to V3 after staging validation
client.update_agent_runtime_endpoint(
    agentRuntimeId="agent-runtime-12345",
    endpointName="production-endpoint",
    agentRuntimeVersion="v3",
    description="Promoted after staging eval passed",
)
```

_Source: [docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agent-runtime-versioning.html](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agent-runtime-versioning.html)_

**Using the `qualifier` parameter to invoke a specific endpoint:**

```python
response = agent_core_client.invoke_agent_runtime(
    agentRuntimeArn="arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/...",
    runtimeSessionId="session-abc-123-...",
    payload=json.dumps({"prompt": "Hello"}),
    qualifier="DEFAULT",          # or "production-endpoint", "staging-endpoint"
)
```

_Source: [strandsagents.com/docs/user-guide/deploy/deploy_to_bedrock_agentcore/python/](https://strandsagents.com/docs/user-guide/deploy/deploy_to_bedrock_agentcore/python/index.md)_

**AWS CDK — `RuntimeEndpoint` construct (TypeScript / Python):**

```python
from aws_cdk import aws_bedrockagentcore as agentcore

staging_endpoint = agentcore.RuntimeEndpoint(
    self, "StagingEndpoint",
    agent_runtime_id="agent-runtime-12345",
    agent_runtime_version="2",       # pinned version
    endpoint_name="staging",
    description="Staging endpoint for pre-production validation",
)
```

_Source: [docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.aws_bedrockagentcore/RuntimeEndpoint.html](https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.aws_bedrockagentcore/RuntimeEndpoint.html)_

**List versions and endpoints:**

```python
# List all versions
client.list_agent_runtime_versions(agentRuntimeId="agent-runtime-12345")

# List endpoints for this runtime
client.list_agent_runtime_endpoints(agentRuntimeId="agent-runtime-12345")
```

_Source: [docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agent-runtime-versioning.html](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agent-runtime-versioning.html)_

---

## Phase 5 — Production traffic management and A/B testing

### Online evaluation for continuous monitoring

Online evaluation (GA) continuously samples live production sessions and scores them using built-in or custom evaluators. Configure via the AgentCore CLI, SDK, or console.

- **Percentage-based sampling:** e.g., evaluate 10% of all sessions.
- **Conditional filtering:** target specific session characteristics.
- Scores appear in aggregated dashboards; low-scoring sessions can be drilled into for trace-level inspection.

_Source: [docs.aws.amazon.com/bedrock-agentcore/latest/devguide/evaluations-types.html](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/evaluations-types.html)_

See [observability.md](observability.md) for viewing evaluation scores in CloudWatch GenAI Observability dashboards.

### A/B testing via AgentCore Gateway

> **Note:** AgentCore optimization (including A/B testing) is in **public preview**. CloudTrail audit trail support is not yet available. APIs may change before GA.

A/B tests split live production traffic between two variants (control and treatment) via **AgentCore Gateway**. Session assignment is sticky — a given `runtimeSessionId` always routes to the same variant.

Two patterns:

| Pattern | When to use | Routing |
|---|---|---|
| **Target-based variants** | Code changes, framework upgrades, different agent implementations | Different gateway targets → different runtime endpoints |
| **Configuration bundle variants** | Prompt, model ID, or tool description changes only | Same target, different config bundle versions injected via W3C baggage headers |

_Source: [docs.aws.amazon.com/bedrock-agentcore/latest/devguide/ab-testing.html](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/ab-testing.html)_

**Typical A/B test lifecycle:**

1. Generate a recommendation (optional) via the Recommendations API analyzing failure traces.
2. Create a configuration bundle version (or deploy to a separate runtime endpoint) for the treatment.
3. Create the A/B test: specify gateway, two variants, traffic weights, and an online evaluation config.
4. Start the test. Gateway splits traffic by `runtimeSessionId`.
5. Poll results. When a p-value < 0.05 is reached, the difference is statistically significant.
6. Stop the test. Route 100% of traffic to the winning variant.

_Source: [docs.aws.amazon.com/bedrock-agentcore/latest/devguide/optimization-how-it-works.html](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/optimization-how-it-works.html)_

See [gateway-identity.md](gateway-identity.md) for AgentCore Gateway target configuration and routing details.

### Configuration bundles for rollback

Configuration bundles (Preview) store system prompts, model IDs, and tool descriptions as versioned, immutable snapshots — independent of your container image.

```python
import boto3

client = boto3.client("bedrock-agentcore-control", region_name="us-east-1")

# Create a bundle
bundle = client.create_configuration_bundle(
    bundleName="my_agent_config",
    components=[
        {
            "resourceArn": "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/my-agent",
            "configuration": {
                "systemPrompt": "You are a helpful customer support agent...",
                "modelId": "anthropic.claude-sonnet-4-5",
            },
        }
    ],
)

# Update the bundle (creates a new immutable version)
updated = client.update_configuration_bundle(
    bundleId=bundle["bundleId"],
    parentVersionIds=[bundle["versionId"]],
    commitMessage="Optimized system prompt for helpfulness",
    components=[
        {
            "resourceArn": "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/my-agent",
            "configuration": {
                "systemPrompt": "You are an expert customer support agent...",
                "modelId": "anthropic.claude-sonnet-4-5",
            },
        }
    ],
)

# Rollback: just reference the previous versionId in your endpoint or A/B test
```

_Source: [docs.aws.amazon.com/bedrock-agentcore/latest/devguide/configuration-bundles.html](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/configuration-bundles.html)_

---

## Code

### CI pipeline pattern (GitHub Actions sketch)

```yaml
# .github/workflows/agent-ci.yml
jobs:
  unit-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install strands-agents strands-agents-evals pytest
      - name: Unit-test @tool functions
        run: pytest tests/unit/ -v
      - name: Deterministic eval gate
        run: python evals/deterministic_eval.py  # fast, no LLM needed

  llm-eval:
    needs: unit-test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install strands-agents strands-agents-evals
      - name: LLM-as-judge eval (parallel, non-blocking)
        run: python evals/output_eval.py
        # Set a threshold: exit 1 if mean score < 0.7

  deploy-staging:
    needs: llm-eval
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: npm install -g @aws/agentcore
      - name: Deploy to AgentCore Runtime
        run: agentcore deploy -y
      - name: Invoke deployed agent smoke test
        run: agentcore invoke "Hello, what can you do?" --stream
      - name: Run on-demand AgentCore Evaluation
        run: |
          agentcore run eval \
            --evaluator "Builtin.Helpfulness" \
            --evaluator "Builtin.GoalSuccessRate"
      # Manual step: advance production endpoint after QA sign-off
```

### Endpoint promotion script

```python
# promote_to_production.py
import boto3, sys

client = boto3.client("bedrock-agentcore", region_name="us-west-2")
runtime_id = sys.argv[1]
new_version = sys.argv[2]

client.update_agent_runtime_endpoint(
    agentRuntimeId=runtime_id,
    endpointName="production-endpoint",
    agentRuntimeVersion=new_version,
    description=f"Promoted to production: v{new_version}",
)
print(f"Production endpoint updated to version {new_version}")
```

_Source: [docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agent-runtime-versioning.html](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agent-runtime-versioning.html)_

---

## Configuration reference

### AgentCore CLI flags reference

| Command | Key flag | Purpose |
|---|---|---|
| `agentcore create` | `--framework Strands\|LangChain_LangGraph\|GoogleADK\|OpenAIAgents` | Agent framework |
| `agentcore create` | `--build CodeZip\|Container` | Packaging method |
| `agentcore create` | `--memory none\|shortTerm\|longAndShortTerm` | Memory config |
| `agentcore dev` | `--logs` | Tail server logs non-interactively |
| `agentcore dev` | `-p <port>` | Override default port 8080 |
| `agentcore deploy` | `--plan` | Preview (dry-run) without deploying |
| `agentcore deploy` | `-y` | Auto-confirm without prompt |
| `agentcore invoke` | `--stream` | Stream response in real time |
| `agentcore invoke` | `--session-id <id>` | Maintain conversation across invocations |
| `agentcore run eval` | `--evaluator <id>` | Evaluator ID (repeatable) |
| `agentcore run eval` | `--session-id <id>` | Target specific session |

_Source: [docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-cli.html](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-cli.html)_

### Strands Evals evaluator quick-reference

| Evaluator | Package | LLM required | CI-safe |
|---|---|---|---|
| `Equals` | `strands-agents-evals` | No | Yes |
| `Contains` | `strands-agents-evals` | No | Yes |
| `StartsWith` | `strands-agents-evals` | No | Yes |
| `ToolCalled` | `strands-agents-evals` | No | Yes |
| `StateEquals` | `strands-agents-evals` | No | Yes |
| `OutputEvaluator` | `strands-agents-evals` | Yes (Claude 4) | Parallel job |
| `TrajectoryEvaluator` | `strands-agents-evals` | Yes (Claude 4) | Parallel job |
| `HelpfulnessEvaluator` | `strands-agents-evals` | Yes (Claude 4) | Parallel job |
| `FaithfulnessEvaluator` | `strands-agents-evals` | Yes (Claude 4) | Parallel job |
| `HarmfulnessEvaluator` | `strands-agents-evals` | Yes (Claude 4) | Parallel job |
| `GoalSuccessRateEvaluator` | `strands-agents-evals` | Yes (Claude 4) | Parallel job |
| `ToolSelectionAccuracyEvaluator` | `strands-agents-evals` | Yes (Claude 4) | Parallel job |
| `ToolParameterAccuracyEvaluator` | `strands-agents-evals` | Yes (Claude 4) | Parallel job |

_Source: [strandsagents.com/docs/user-guide/evals-sdk/quickstart/](https://strandsagents.com/docs/user-guide/evals-sdk/quickstart/index.md)_

### AgentCore Evaluations dataset runner comparison

| Aspect | `OnDemandEvaluationDatasetRunner` | `BatchEvaluationRunner` |
|---|---|---|
| Span collection | SDK-side (`AgentSpanCollector`) | Server-side from CloudWatch |
| Evaluate API calls | One per evaluator per scenario | `startBatchEvaluation()` once |
| Execution model | Synchronous 3-phase | Asynchronous 4-phase |
| Results | Structured per-scenario detail | Aggregate summary + CloudWatch detail |
| Best for | CI/CD, dev-time, small datasets | Large baselines, production audits |

_Source: [docs.aws.amazon.com/bedrock-agentcore/latest/devguide/dataset-evaluations.html](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/dataset-evaluations.html)_

### AgentCore Runtime endpoint lifecycle states

| State | Meaning |
|---|---|
| `CREATING` | Endpoint creation in progress |
| `CREATE_FAILED` | Creation failed (check IAM, container, network) |
| `READY` | Accepting requests |
| `UPDATING` | Being updated to a new version |
| `UPDATE_FAILED` | Update failed |

_Source: [docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-how-it-works.html](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-how-it-works.html)_

---

## Gotchas

1. **The `bedrock-agentcore-starter-toolkit` is deprecated.** Uninstall it before installing the new `bedrock-agentcore` SDK and AgentCore CLI to avoid import conflicts. _Source: [strandsagents.com/docs/user-guide/deploy/deploy_to_bedrock_agentcore/python/](https://strandsagents.com/docs/user-guide/deploy/deploy_to_bedrock_agentcore/python/index.md)_

2. **CloudWatch Transaction Search must be enabled before evaluating.** Evaluation jobs query span data from CloudWatch. If Transaction Search is disabled, spans are never written and evaluation returns empty results with no obvious error. _Source: [docs.aws.amazon.com/bedrock-agentcore/latest/devguide/getting-started-on-demand.html](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/getting-started-on-demand.html)_

3. **CloudWatch spans may take a few minutes to appear after invocation.** Calling the Evaluate API immediately after `invoke_agent_runtime` may return empty or incomplete results. Wait 2–3 minutes before triggering evaluation in scripts. _Source: [docs.aws.amazon.com/bedrock-agentcore/latest/devguide/getting-started-on-demand.html](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/getting-started-on-demand.html)_

4. **The DEFAULT endpoint is not safe for production traffic.** It auto-updates on every runtime change. Any deploy of a bug causes immediate production impact. Always create a named endpoint for production and advance it only after staged validation. _Source: [docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agent-runtime-versioning.html](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agent-runtime-versioning.html)_

5. **ToolSimulator uses an LLM to generate responses.** While it eliminates live API calls, it still requires a Bedrock model invocation per simulated tool call. This has a small cost and latency impact. Not suitable for pure offline / air-gapped CI. _Source: [strandsagents.com/blog/toolsimulator-scalable-tool-testing-ai-agents/](https://strandsagents.com/blog/toolsimulator-scalable-tool-testing-ai-agents/index.md)_

6. **Static mocks break multi-turn stateful workflows.** A hardcoded mock response for `search_flights` cannot reflect state changes made by a preceding `book_flight` call. Use ToolSimulator's `share_state_id` for multi-turn scenarios. _Source: [strandsagents.com/blog/toolsimulator-scalable-tool-testing-ai-agents/](https://strandsagents.com/blog/toolsimulator-scalable-tool-testing-ai-agents/index.md)_

7. **A/B testing requires AgentCore optimization to be enabled (Preview).** CloudTrail audit trail is not yet supported in the optimization preview. Do not use for workloads requiring a CloudTrail audit trail until this is resolved. _Source: [docs.aws.amazon.com/bedrock-agentcore/latest/devguide/optimization.html](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/optimization.html)_

8. **Configuration bundle names cannot contain hyphens.** Pattern: `[a-zA-Z][a-zA-Z0-9_]{0,99}`. Using a hyphen causes a validation error. _Source: [docs.aws.amazon.com/bedrock-agentcore/latest/devguide/configuration-bundles.html](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/configuration-bundles.html)_

9. **`agentcore run eval` requires an active project directory.** Running outside an `agentcore create`-generated directory requires the `--agent-arn` flag. _Source: [docs.aws.amazon.com/bedrock-agentcore/latest/devguide/getting-started-on-demand.html](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/getting-started-on-demand.html)_

10. **Session IDs for `invoke_agent_runtime` must be ≥ 33 characters.** Shorter IDs cause a validation error. _Source: [strandsagents.com/docs/user-guide/deploy/deploy_to_bedrock_agentcore/python/](https://strandsagents.com/docs/user-guide/deploy/deploy_to_bedrock_agentcore/python/index.md)_

---

## Test-before-deploy checklist

Use this checklist for every agent change before advancing the production endpoint.

**Local (every commit):**
- [ ] `agentcore dev` starts without errors.
- [ ] `GET /ping` returns `200 OK`.
- [ ] `POST /invocations` with a sample payload returns a valid response.
- [ ] All `@tool` function unit tests pass (`pytest tests/unit/`).
- [ ] Deterministic eval suite passes (`Equals`, `Contains`, `ToolCalled` evaluators).

**Pre-deploy (every PR / merge to main):**
- [ ] LLM-based eval suite (parallel CI job) meets the defined score threshold (e.g., mean helpfulness ≥ 0.7).
- [ ] If tools call live APIs in tests: verify ToolSimulator is used instead of real endpoints.
- [ ] Docker image builds for `linux/arm64` without error (Container build type only).
- [ ] `agentcore deploy --plan` shows expected CloudFormation changes.

**Post-deploy to staging:**
- [ ] `agentcore invoke "..." --stream` returns a valid response on the staging endpoint.
- [ ] On-demand AgentCore Evaluation passes on at least 3–5 curated sessions: `agentcore run eval --evaluator "Builtin.Helpfulness" --evaluator "Builtin.GoalSuccessRate"`.
- [ ] CloudWatch traces visible in GenAI Observability dashboard (see [observability.md](observability.md)).
- [ ] No regressions vs. the saved baseline experiment file.

**Production rollout:**
- [ ] Staging eval scores meet or exceed production baseline.
- [ ] Named production endpoint (`production-endpoint`) is pinned to the new version (not DEFAULT).
- [ ] (Optional) A/B test running if the change is a prompt/model update — wait for p-value < 0.05 before full rollout.
- [ ] Online evaluation configured to monitor the production endpoint continuously.
- [ ] Rollback plan documented: previous runtime version ID or config bundle version ID recorded.

---

## Official sources

- [AgentCore CLI get-started tutorial](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-cli.html) — full scaffold → dev → deploy → invoke walkthrough (GA)
- [AgentCore Runtime versioning and endpoints](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agent-runtime-versioning.html) — immutable versions, DEFAULT vs. named endpoints, boto3 examples (GA)
- [AgentCore Runtime how it works](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-how-it-works.html) — key components, sessions, endpoint lifecycle states (GA)
- [AgentCore Evaluations overview](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/how-it-works-evaluations.html) — evaluation architecture (GA)
- [Evaluation types](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/evaluations-types.html) — online, on-demand, batch (GA)
- [Dataset evaluations](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/dataset-evaluations.html) — on-demand and batch dataset runners, CI/CD integration (GA)
- [Getting started with on-demand evaluation](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/getting-started-on-demand.html) — step-by-step CLI and SDK samples (GA)
- [Evaluators](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/evaluators.html) — built-in and custom evaluators (GA)
- [AgentCore optimization overview](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/optimization.html) — recommendations, configuration bundles, A/B testing (Preview)
- [AgentCore optimization how it works](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/optimization-how-it-works.html) — improvement loop (Preview)
- [A/B testing](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/ab-testing.html) — traffic split patterns, statistical significance (Preview)
- [Configuration bundles](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/configuration-bundles.html) — versioned config snapshots, rollback, audit trail (Preview)
- [RuntimeEndpoint CDK construct (Python)](https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.aws_bedrockagentcore/RuntimeEndpoint.html) — CDK IaC for pinned endpoints (GA)
- [RuntimeEndpoint CDK construct (TypeScript)](https://docs.aws.amazon.com/cdk/api/v2/docs/aws-cdk-lib.aws_bedrockagentcore.RuntimeEndpoint.html) — CDK IaC for pinned endpoints (GA)
- [Deploy Python agents to AgentCore — Strands guide](https://strandsagents.com/docs/user-guide/deploy/deploy_to_bedrock_agentcore/python/index.md) — SDK integration, custom FastAPI, local testing, observability (GA)
- [Strands Evals SDK quickstart](https://strandsagents.com/docs/user-guide/evals-sdk/quickstart/index.md) — Cases, Experiments, evaluators, async eval, experiment management (GA)
- [Strands deterministic evaluators](https://strandsagents.com/docs/user-guide/evals-sdk/evaluators/deterministic_evaluators/index.md) — Equals, Contains, ToolCalled, StateEquals (GA)
- [Evaluating AI agents — practical guide to Strands Evals](https://strandsagents.com/blog/evaluating-ai-agents-practical-guide-strands-evals/index.md) — all 10 built-in evaluators, task functions, multi-turn simulation, CI/CD integration (GA)
- [ToolSimulator: scalable tool testing for AI agents](https://strandsagents.com/blog/toolsimulator-scalable-tool-testing-ai-agents/index.md) — stateful mocking, schema enforcement, Evals integration (GA)
- [Strands `@tool` decorator API reference](https://strandsagents.com/docs/api/python/strands.tools.decorator/index.md) — metadata extraction, parameter validation (GA)
