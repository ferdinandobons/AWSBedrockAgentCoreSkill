# Deploying Strands Agents — Lambda, Fargate/ECS, EKS

> Part of the **aws-ai-agent-architect** skill. See [SKILL.md](../SKILL.md) for the decision tree. Every source below is official — re-open it to verify details.

## Table of contents

- [Overview](#overview)
- [Key concepts](#key-concepts)
- [Best practices](#best-practices)
- [Code](#code)
  - [Lambda handler (no streaming)](#lambda-handler-minimal-strands-agent-no-streaming)
  - [CDK TypeScript — Lambda with layer and Bedrock permissions](#cdk-typescript--lambda-function-with-custom-layer-and-bedrock-permissions)
  - [Lambda Layer ARN format and commands](#lambda-layer-arn-official-strands-format-and-commands)
  - [MCP on Lambda — context manager (multi-tenant safe)](#mcp-on-lambda--per-invocation-context-manager-multi-tenant-safe-approach)
  - [FastAPI app for Fargate/EKS with streaming](#fastapi-app-for-fargateeks-with-streaming-endpoint)
  - [Dockerfile for Fargate/EKS (Python 3.12, non-root)](#dockerfile-for-fargateeks--python-312-slim-with-non-root-user)
  - [CDK TypeScript — Fargate HA service with circuit breaker and ALB](#cdk-typescript--fargate-service-with-ha-circuit-breaker-and-alb)
  - [AgentCore SDK Integration (HTTP and streaming)](#agentcore-runtime--sdk-integration-with-bedrockagentcoreapp-http-and-streaming)
  - [AgentCore WebSocket bidirectional (GA)](#agentcore-runtime--bidirectional-websocket-with-bedrockagentcoreapp-ga)
  - [AgentCore FastAPI custom (/invocations and /ping required)](#agentcore-runtime--fastapi-custom-with-invocations-and-ping-required)
  - [AgentCore Dockerfile ARM64 with uv](#agentcore-runtime--dockerfile-arm64-with-uv-for-fast-builds)
  - [AgentCore boto3 CreateAgentRuntime with LifecycleConfiguration](#agentcore-runtime--deploy-with-boto3-createagentruntime-with-lifecycleconfiguration)
  - [AgentCore async task and custom ping for long workloads](#agentcore-runtime--async-task-and-custom-ping-for-long-workloads--15-min-sync)
  - [S3SessionManager for distributed production](#session-management--s3sessionmanager-for-distributed-production)
  - [FileSessionManager and multi-agent Graph](#session-management--filesessionmanager-for-local-development-and-multi-agent-graph)
  - [IAM Execution Role for AgentCore Runtime](#iam-execution-role-for-agentcore-runtime--trust-policy-and-minimal-permissions)
  - [AgentCore CLI full workflow](#agentcore-cli--full-workflow-for-scaffolding-local-dev-and-deploy)
  - [AgentCore managed session storage (Preview)](#agentcore-runtime--managed-session-storage-for-persistent-filesystem-preview)
  - [Fargate/EKS deploy and test via CDK and curl](#agentcorefargate-deploy-and-test-via-cdk-and-curl)
- [Configuration reference](#configuration-reference)
- [Gotchas](#gotchas)
- [Official sources](#official-sources)
- [Verify live (open questions)](#verify-live-open-questions)

---

## Overview

Strands Agents SDK (open source, AWS, **GA since May 2026**) supports four main AWS deployment targets:

1. **AWS Lambda** — serverless, no native response streaming. Handler-based, with official Lambda Layers for easy packaging.
2. **AWS Fargate / ECS** — container-based with HTTP streaming via `stream_async()`, FastAPI + Docker, CDK-managed.
3. **Amazon EKS** — Kubernetes with EKS Auto Mode and Pod Identity for Bedrock access; Helm chart provided in the strands-agents/docs GitHub repo.
4. **Amazon Bedrock AgentCore Runtime** — microVM-isolated sessions, GA in 16 regions (including GovCloud US-West), recommended production target in 2026. For full AgentCore Runtime coverage, see `agentcore-runtime.md`; for IaC details, see `deployment-iac.md`.

**Maturity:**
- AgentCore Runtime: **GA** in 16 regions. Container and direct code deployment supported. WebSocket bidirectional: **GA**.
- AgentCore Harness: **Public Preview** in 4 regions (us-east-1, us-west-2, eu-central-1, ap-southeast-2).
- Managed Session Storage (AgentCore Runtime): **Preview**.
- Lambda / Fargate / EKS deployment patterns: **consolidated and stable**.
- AgentCore CLI (`@aws/agentcore` npm): **GA**, CDK supported, Terraform coming.
- `strands.experimental.bidi` namespace streaming: **Experimental** (distinct from AgentCore Runtime WebSocket which is GA).
- Strands Agents SDK v1.0: **GA** (May 2026), with session management, async, multi-agent support.

The standard architectural pattern is a FastAPI or `BedrockAgentCoreApp` container exposing `POST /invocations` and `GET /ping` on port 8080. `BedrockModel` internally uses the Bedrock Converse API (`ConverseStream` / `Converse`), not the legacy `InvokeModel` API.

---

## Key concepts

### Architecture: monolith vs microservices

A Strands agent can be deployed as a monolith (agent loop + tool execution in the same environment) or as microservices (agent invokes tools via API in a separate backend). Five main patterns:
1. Local / CLI
2. API deployment on Lambda / Fargate / EKS
3. Isolated tools with a separate backend
4. Multi-agent orchestration
5. Managed AgentCore Runtime / Harness

### BedrockModel — Converse API (not legacy InvokeModel)

`BedrockModel` internally uses the Bedrock Converse API (`ConverseStream` for streaming, `Converse` for non-streaming). IAM actions required: `bedrock:InvokeModelWithResponseStream` (for streaming) and `bedrock:InvokeModel` (for non-streaming). Constructor parameters: `model_id`, `temperature`, `top_p`, `max_tokens`, `streaming` (default `True`), `guardrail_id`, `cache_config`, `boto_session`, `region_name`.

### BedrockAgentCoreApp (SDK Integration)

Class from the `bedrock-agentcore` pip package that wraps a Strands agent as an HTTP service conforming to the AgentCore Runtime contract. Exposes `/invocations` (POST) and `/ping` (GET) on port 8080. Decorators:
- `@app.entrypoint` — marks the handler function (sync or async generator for streaming)
- `@app.websocket` — handles bidirectional WebSocket on `/ws`
- `@app.ping` — custom health check handler

### AgentCore Runtime Service Contract

Every container on AgentCore Runtime must expose:
- `POST /invocations` port 8080 (main handler)
- `GET /ping` port 8080 (health check — must return `{status: 'Healthy'|'HealthyBusy', time_of_last_update: <unix_timestamp>}`)
- Optional: `GET/WebSocket /ws` port 8080 for bidirectional streaming

Required platform: **linux/arm64**. Supported protocols: HTTP (port 8080), MCP (port 8000), A2A (port 9000), AG-UI (port 8080), WebSocket (port 8080 path `/ws`). Images stored in ECR.

### Session isolation with microVM

In AgentCore Runtime, each user session runs in a dedicated microVM with 2 vCPU / 8 GB memory and isolated filesystem. After termination the microVM is deallocated and memory sanitized. `runtimeSessionId`: if omitted on the first invoke, AgentCore generates it automatically; if provided by the client, must be at least 33 characters. AgentCore does **not** enforce user-to-session mapping — the client backend is responsible for managing this relationship.

### Session Lifecycle in AgentCore Runtime

Three states: **Active** (processing sync requests, commands, or background tasks), **Idle** (complete but available), **Stopped** (microVM terminated due to inactivity, max lifetime, explicit stop, or unhealthy status). When Stopped, the session remains valid and the next invoke creates a new microVM. `idleRuntimeSessionTimeout` and `maxLifetime` are configurable via `LifecycleConfiguration` (range 60-28800 seconds, defaults 900s and 28800s). `InvokeAgentRuntimeCommand` executes deterministic shell commands on the same agent session.

### Async Task Management in AgentCore Runtime

For long tasks: `app.add_async_task(name, metadata)` returns a `task_id`. `app.complete_async_task(task_id)` marks it complete. The `/ping` returns `HealthyBusy` while tasks are active, preventing idle timeout. Alternative: `@app.ping` with custom logic returning `PingStatus.HEALTHY` or `PingStatus.HEALTHY_BUSY`. Sync request timeout: 15 minutes (not modifiable); async job max: 8 hours; streaming max: 60 minutes.

### stream_async() — Async HTTP streaming

Primary method for streaming on Fargate / EKS / AgentCore. Returns an async generator of events. For FastAPI: return `StreamingResponse(generate(), media_type='text/plain')`. **Not natively supported on Lambda**. Events include: `init_event_loop`, `start_event_loop`, `message`, `result`, `force_stop`, `current_tool_use`, `data`. On AgentCore Runtime, `@app.entrypoint async def` + `yield` enables HTTP streaming (max 60 minutes).

### WebSocket bidirectional in AgentCore Runtime (GA)

**GA feature.** `@app.websocket` decorator handles persistent WebSocket connections on port 8080 path `/ws`. Authentication: SigV4 headers, SigV4 presigned URL, or OAuth 2.0. boto3 API: `InvokeAgentRuntimeWithWebSocketStream` (25 TPS, adjustable). Max frame size: 64 KB; max rate: 250 fps per connection. Client uses `AgentCoreRuntimeClient.generate_ws_connection()` or `generate_presigned_url()`. Ideal for real-time voice agents and AG-UI streaming.

### SlidingWindowConversationManager

Context manager that limits conversation history to a fixed number of messages (`window_size`). Essential in production to prevent context window overflow and reduce token costs. Usage: `Agent(conversation_manager=SlidingWindowConversationManager(window_size=10))`. Default Agent retry strategy: `max_attempts=6`, `initial_delay=4s`, `max_delay=240s` (configurable via `retry_strategy` or disabled with `None`).

### SessionManager — Session persistence

Strands abstraction for persisting state and conversation history. Built-in options:
- `FileSessionManager` — local filesystem (development/testing)
- `S3SessionManager` — S3 bucket (distributed production)

In multi-agent setups, **only the orchestrator** (Graph/Swarm) must have a session manager, never individual internal agents. Distinct from AgentCore Runtime session persistence (which manages the microVM filesystem, not conversation history).

### Lambda Layer official Strands

ARN pattern: `arn:aws:lambda:{region}:856699698935:layer:strands-agents-py{python_version}-{architecture}:{layer_version}`

- AWS Account: `856699698935`
- Python versions: 3.10, 3.11, 3.12, 3.13
- Architectures: `x86_64`, `aarch64`
- Layer Version 2 = strands-agents v1.40.0

### AgentCore CLI (`agentcore`)

npm tool (`@aws/agentcore`) for scaffolding, local development, and deployment to AgentCore Runtime. Commands: `agentcore create` (wizard), `agentcore dev` (local), `agentcore deploy` (AWS), `agentcore invoke` (test). Supports both container deployment and direct code deploy (zip). Generates `agentcore.json` and `aws-targets.json`. Available in 14 regions. CDK supported; Terraform coming. Replaces the old `bedrock-agentcore-starter-toolkit`.

### AgentCore Harness [Preview]

Managed agent loop fully managed, powered by Strands Agents. Configuration: model + system prompt + tools (inline or via AgentCore Gateway/MCP). Handles orchestration, tool execution, memory, identity, VPC networking, observability. Supports Amazon Bedrock, OpenAI, Gemini, and mid-session provider switch. Stateful by default: isolated microVM per session, persistent filesystem, integrated AgentCore Memory. **Preview in 4 regions** (us-east-1, us-west-2, eu-central-1, ap-southeast-2). No additional cost (only pay for underlying AgentCore capabilities). Harness invocations share AgentCore Runtime quotas.

### Managed Session Storage vs BYO Filesystem (AgentCore Runtime)

Two categories for filesystem persistence in the AgentCore Runtime container:

- **Managed Session Storage (Preview):** per-session isolated, no VPC required, survives stop/resume, 14-day idle expiry, resets on version update, max 1 GB.
- **BYO (Amazon S3 Files or Amazon EFS):** shared between sessions/agents, VPC mandatory, permanent until explicit deletion.

Up to 5 total configurations per agent runtime. Mount path required: pattern `/mnt/<subdir>`. Configured via `filesystemConfigurations` in `CreateAgentRuntime`.

### EKS Pod Identity for Bedrock

On EKS Auto Mode, access to Bedrock is configured via Amazon EKS Pod Identity, associating an IAM Role to a Kubernetes ServiceAccount. On EKS Auto Mode this is natively integrated (Pod Identity Agent add-on not required separately). The official strands-agents/docs repo on GitHub contains the ServiceAccount YAML and complete ClusterRoleBinding for the Helm deploy.

### AgentCore Runtime — Versioning and Endpoints

Each AgentCore Runtime update creates a new immutable Version (complete config snapshot). The `DEFAULT` endpoint is updated automatically to the latest version. Custom endpoints can be created (e.g., dev, test, prod) pointing to specific versions. Rollback = update endpoint to a previous version. Limits: 10 endpoints per agent, 1000 versions per agent.

---

## Best practices

- **Use AgentCore Runtime for new production deployments** — Offers session isolation with microVM (2 vCPU / 8 GB dedicated), automatic scaling to thousands of sessions, consumption-based pricing, sync execution up to 15 min (not modifiable), streaming up to 60 min, async up to 8 hours, and native integration with Memory / Gateway / Identity. GA in 16 regions including GovCloud. Immutable versioning with rollback. Recommended AWS target for production agents in 2026. _Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agents-tools-runtime.html_

- **Prefer Fargate / EKS over Lambda when HTTP streaming is required** — The official Lambda guide explicitly warns: "This Lambda deployment example does not implement response streaming. If you need streaming capabilities, consider using the AWS Fargate deployment approach." Lambda does not support the `stream_async()` pattern natively without specific adapters. _Source: https://strandsagents.com/docs/user-guide/deploy/deploy_to_aws_lambda/index.md_

- **Explicitly configure the model in production with fixed parameters** — Do not rely on `BedrockModel` defaults. Specify `model_id`, `temperature`, `max_tokens`, `top_p` explicitly. `BedrockModel` internally uses the Converse API (`ConverseStream` / `Converse`). Using the cross-region inference prefix (e.g., `us.`) improves availability. _Source: https://strandsagents.com/docs/user-guide/concepts/model-providers/amazon-bedrock/index.md_

- **Always specify an explicit list of tools in production** — Do not use auto-loading of tools. List only the tools necessary for the use case. Reduces attack surface, improves predictability, and facilitates auditing. Principle of least privilege for tools, parallel to IAM permissions. _Source: https://strandsagents.com/docs/user-guide/deploy/operating-agents-in-production/index.md_

- **Use SlidingWindowConversationManager to control memory in production** — Without limiting history, long conversations cause context window overflow. `SlidingWindowConversationManager(window_size=10)` keeps only the last N messages. The default Agent retry strategy has `max_attempts=6`; disable it (`retry_strategy=None`) if retry logic is handled elsewhere. _Source: https://strandsagents.com/docs/user-guide/deploy/operating-agents-in-production/index.md_

- **In multi-agent: session manager only on the orchestrator, never on individual agents** — Strands raises `ValueError` if an agent with `session_manager` is added to a `Graph` or `Swarm`. The orchestrator snapshots and restores the state of each node on each execution; an agent-level session manager would create conflicts. _Source: https://strandsagents.com/docs/user-guide/concepts/agents/session-management/index.md_

- **Install Lambda dependencies with the correct target architecture** — For Lambda ARM64 use `--platform manylinux2014_aarch64` in `pip install`. Dependencies for the wrong architecture cause runtime errors at execution. _Source: https://strandsagents.com/docs/user-guide/deploy/deploy_to_aws_lambda/index.md_

- **For MCP on Lambda: use context manager per invocation in multi-tenant environments** — The MCP connection must be opened and closed per invocation in multi-tenant setups. Reuse between invocations (module-level `mcp_client` with `mcp_client.start()`) is possible but risks state leakage between different users. Start with context manager and optimize only if necessary. _Source: https://strandsagents.com/docs/user-guide/deploy/deploy_to_aws_lambda/index.md_

- **Do not perform blocking operations in the main thread in AgentCore Runtime** — The main thread also serves `/ping` health checks. If blocked, ping fails and the platform terminates the session even if work is ongoing. Use separate threading or async for long I/O-bound operations; register tasks with `app.add_async_task()`. _Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-long-run.html_

- **For production AgentCore deployments: create custom IAM policies instead of BedrockAgentCoreFullAccess** — Official documentation warns that IAM policies created by the AgentCore CLI are for development/testing. For production, create custom policies with least privilege. The execution role requires: ECR (`BatchGetImage`, `GetDownloadUrlForLayer`, `GetAuthorizationToken`), CloudWatch Logs, X-Ray, and `bedrock:InvokeModel` / `bedrock:InvokeModelWithResponseStream`. _Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-permissions.html_

- **Use S3SessionManager for Strands session persistence in distributed environments** — `FileSessionManager` only works on a single instance. In multi-replica Fargate or EKS environments, Strands sessions must be shared. `S3SessionManager` persists to an S3 bucket accessible from all replicas. Distinct from native AgentCore Runtime session persistence (which manages the microVM filesystem). _Source: https://strandsagents.com/docs/user-guide/concepts/agents/session-management/index.md_

- **Fargate: desiredCount >= 2 + circuit breaker rollback + private subnets with NAT** — The reference CDK uses `desiredCount: 2` for high availability, `circuitBreaker: {rollback: true}` for automatic rollback, `assignPublicIp: false` with private subnets. `minHealthyPercent: 100` and `maxHealthyPercent: 200` ensure zero-downtime deployment. `healthCheckGracePeriod`: at least 60 seconds. _Source: https://strandsagents.com/docs/user-guide/deploy/deploy_to_aws_fargate/index.md_

- **Container ARM64 on Fargate / EKS / AgentCore — buildx with --platform linux/arm64** — All official examples use ARM64 for ~20% lower costs compared to x86_64 and better performance for I/O-bound workloads. `docker buildx build --platform linux/arm64`. For ECR push use the `--push` flag. _Source: https://strandsagents.com/docs/user-guide/deploy/deploy_to_bedrock_agentcore/python/index.md_

- **Separate app code and dependencies in Lambda (separate layer)** — Keep dependencies in a Lambda Layer separate from application code. Keeps application code small, visible, and editable from the Lambda console, and reduces subsequent deployments when only the code changes. _Source: https://strandsagents.com/docs/user-guide/deploy/deploy_to_aws_lambda/index.md_

- **Configure LifecycleConfiguration to optimize cost and availability in AgentCore Runtime** — Default values (`idleTimeout=900s`, `maxLifetime=28800s`) can be adjusted via `LifecycleConfiguration` in `CreateAgentRuntime` / `UpdateAgentRuntime`. For real-time agents with short sessions, reduce `idleTimeout`. For long batch workloads, set `maxLifetime` higher. `idleRuntimeSessionTimeout` must be <= `maxLifetime`. Both in range 60-28800 seconds. _Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-lifecycle-settings.html_

- **Use managed session storage for lightweight filesystem persistence on AgentCore Runtime** — Managed session storage (Preview) does not require a VPC and persists the filesystem across stop/resume. Ideal for agents that need to maintain work files, installed dependencies, or local history between sessions. Configure with `filesystemConfigurations: [{sessionStorage: {mountPath: '/mnt/workspace'}}]`. Data expires after 14 days of inactivity and is reset on every version update. _Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-filesystem-configurations.html_

---

## Code

### Lambda handler minimal Strands Agent (no streaming)

```python
from strands import Agent
from strands_tools import http_request
from typing import Dict, Any

# Initialize Agent at module level = reuse across warm invocations
WEATHER_SYSTEM_PROMPT = "You are a weather assistant."

def handler(event: Dict[str, Any], _context) -> str:
    weather_agent = Agent(
        system_prompt=WEATHER_SYSTEM_PROMPT,
        tools=[http_request],
    )
    response = weather_agent(event.get('prompt'))
    return str(response)
```

_Source: https://strandsagents.com/docs/user-guide/deploy/deploy_to_aws_lambda/index.md_

---

### CDK TypeScript — Lambda function with custom layer and Bedrock permissions

```typescript
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as iam from 'aws-cdk-lib/aws-iam';
import { Duration } from 'aws-cdk-lib';
import * as path from 'path';

const dependenciesLayer = new lambda.LayerVersion(this, 'DependenciesLayer', {
  code: lambda.Code.fromAsset(zipDependencies),
  compatibleRuntimes: [lambda.Runtime.PYTHON_3_12],
  description: 'Dependencies needed for agent-based lambda',
});

const weatherFunction = new lambda.Function(this, 'AgentLambda', {
  runtime: lambda.Runtime.PYTHON_3_12,
  functionName: 'AgentFunction',
  handler: 'agent_handler.handler',
  code: lambda.Code.fromAsset(zipApp),
  timeout: Duration.seconds(30),
  memorySize: 128,
  layers: [dependenciesLayer],
  architecture: lambda.Architecture.ARM_64,
});

// Bedrock permissions (Converse API uses these same actions)
weatherFunction.addToRolePolicy(
  new iam.PolicyStatement({
    actions: ['bedrock:InvokeModel', 'bedrock:InvokeModelWithResponseStream'],
    resources: ['*'],
  }),
);
```

_Source: https://strandsagents.com/docs/user-guide/deploy/deploy_to_aws_lambda/index.md_

---

### Lambda Layer ARN official Strands (format and commands)

```bash
# Official layer ARN format
# arn:aws:lambda:{region}:856699698935:layer:strands-agents-py{python_version}-{architecture}:{layer_version}

# Concrete example: us-east-1, Python 3.12, x86_64, version 2 (SDK v1.40.0)
arn:aws:lambda:us-east-1:856699698935:layer:strands-agents-py3_12-x86_64:2

# Inspect the details of a layer version
aws lambda get-layer-version \
    --layer-name arn:aws:lambda:us-east-1:856699698935:layer:strands-agents-py3_12-x86_64 \
    --version-number 2

# Install dependencies with the correct architecture (ARM64)
pip install -r requirements.txt \
    --python-version 3.12 \
    --platform manylinux2014_aarch64 \
    --target ./packaging/_dependencies \
    --only-binary=:all:
```

_Source: https://strandsagents.com/docs/user-guide/deploy/deploy_to_aws_lambda/index.md_

---

### MCP on Lambda — per-invocation context manager (multi-tenant safe approach)

```python
from mcp.client.streamable_http import streamablehttp_client
from strands import Agent
from strands.tools.mcp import MCPClient

def handler(event, context):
    mcp_client = MCPClient(
        lambda: streamablehttp_client("https://your-mcp-server.example.com/mcp")
    )
    # Context manager ensures safe open/close for every invocation
    with mcp_client:
        tools = mcp_client.list_tools_sync()
        agent = Agent(tools=tools)
        response = agent(event.get("prompt"))
    return str(response)

# Variant: reuse connection across warm invocations (WARNING: state leakage on multi-tenant)
# mcp_client = MCPClient(lambda: streamablehttp_client("https://..."))
# mcp_client.start()  # Module level
# def handler(event, context):
#     tools = mcp_client.list_tools_sync()
#     ...
```

_Source: https://strandsagents.com/docs/user-guide/deploy/deploy_to_aws_lambda/index.md_

---

### FastAPI app for Fargate/EKS with streaming endpoint

```python
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse, PlainTextResponse
from pydantic import BaseModel
from strands import Agent, tool
from strands.models import BedrockModel
from strands_tools import http_request

app = FastAPI(title="Agent API")

SYSTEM_PROMPT = "You are a helpful assistant."

class PromptRequest(BaseModel):
    prompt: str

# Standard endpoint (non-streaming)
@app.post('/agent')
async def invoke_agent(request: PromptRequest):
    agent_model = BedrockModel(
        model_id="us.amazon.nova-premier-v1:0",
        temperature=0.3,
        max_tokens=2000,
    )
    agent = Agent(system_prompt=SYSTEM_PROMPT, model=agent_model, tools=[http_request])
    response = agent(request.prompt)
    return PlainTextResponse(content=str(response))

# Streaming endpoint — uses stream_async()
@app.post('/agent/stream')
async def invoke_agent_streaming(request: PromptRequest):
    async def generate():
        is_summarizing = False

        @tool
        def ready_to_summarize():
            nonlocal is_summarizing
            is_summarizing = True
            return "Ok - continue providing the summary!"

        agent = Agent(
            system_prompt=SYSTEM_PROMPT,
            tools=[http_request, ready_to_summarize],
            callback_handler=None
        )
        async for item in agent.stream_async(request.prompt):
            if not is_summarizing:
                continue
            if "data" in item:
                yield item['data']

    return StreamingResponse(generate(), media_type="text/plain")
```

_Source: https://strandsagents.com/docs/user-guide/deploy/deploy_to_aws_fargate/index.md_

---

### Dockerfile for Fargate/EKS — Python 3.12 slim with non-root user

```dockerfile
FROM public.ecr.aws/docker/library/python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ .

# Run as non-root for security
RUN useradd -m appuser
USER appuser

EXPOSE 8000

# 2 Uvicorn workers for concurrency
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
```

_Source: https://strandsagents.com/docs/user-guide/deploy/deploy_to_aws_fargate/index.md_

---

### CDK TypeScript — Fargate service with HA, circuit breaker and ALB

```typescript
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as ecrAssets from 'aws-cdk-lib/aws-ecr-assets';
import { Duration } from 'aws-cdk-lib';
import * as path from 'path';

// Task role with Bedrock permissions (Converse API)
taskRole.addToPolicy(new iam.PolicyStatement({
  actions: ['bedrock:InvokeModel', 'bedrock:InvokeModelWithResponseStream'],
  resources: ['*'],
}));

const taskDefinition = new ecs.FargateTaskDefinition(this, 'AgentTaskDef', {
  memoryLimitMiB: 512,
  cpu: 256,
  executionRole,
  taskRole,
  runtimePlatform: {
    cpuArchitecture: ecs.CpuArchitecture.ARM64,
    operatingSystemFamily: ecs.OperatingSystemFamily.LINUX,
  },
});

const dockerAsset = new ecrAssets.DockerImageAsset(this, 'AgentImage', {
  directory: path.join(__dirname, '../docker'),
  platform: ecrAssets.Platform.LINUX_ARM64,
});

taskDefinition.addContainer('AgentContainer', {
  image: ecs.ContainerImage.fromDockerImageAsset(dockerAsset),
  logging: ecs.LogDrivers.awsLogs({ streamPrefix: 'agent-service', logGroup }),
  environment: { LOG_LEVEL: 'INFO' },
  portMappings: [{ containerPort: 8000, protocol: ecs.Protocol.TCP }],
});

const service = new ecs.FargateService(this, 'AgentService', {
  cluster,
  taskDefinition,
  desiredCount: 2,
  assignPublicIp: false,
  vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
  circuitBreaker: { rollback: true },
  minHealthyPercent: 100,
  maxHealthyPercent: 200,
  healthCheckGracePeriod: Duration.seconds(60),
});
```

_Source: https://strandsagents.com/docs/user-guide/deploy/deploy_to_aws_fargate/index.md_

---

### AgentCore Runtime — SDK Integration with BedrockAgentCoreApp (HTTP and streaming)

```python
from bedrock_agentcore import BedrockAgentCoreApp
from strands import Agent
from strands.models import BedrockModel
from strands.agent.conversation_manager import SlidingWindowConversationManager

app = BedrockAgentCoreApp()

agent_model = BedrockModel(
    model_id="us.amazon.nova-premier-v1:0",
    temperature=0.3,
    max_tokens=2000,
)
agent = Agent(
    model=agent_model,
    conversation_manager=SlidingWindowConversationManager(window_size=10),
)

# Standard handler (synchronous)
@app.entrypoint
def invoke(payload):
    user_message = payload.get("prompt", "Hello")
    result = agent(user_message)
    return {"result": result.message}

# Streaming handler (async with yield) — max 60 minutes
@app.entrypoint
async def invoke_streaming(payload):
    user_message = payload.get("prompt", "No prompt found")
    stream = agent.stream_async(user_message)
    async for event in stream:
        yield event

if __name__ == "__main__":
    app.run()

# Local test:
# python my_agent.py
# curl -X POST http://localhost:8080/invocations -H 'Content-Type: application/json' -d '{"prompt": "Hello world!"}'
```

_Source: https://strandsagents.com/docs/user-guide/deploy/deploy_to_bedrock_agentcore/python/index.md_

---

### AgentCore Runtime — Bidirectional WebSocket with BedrockAgentCoreApp (GA)

```python
from bedrock_agentcore import BedrockAgentCoreApp
from strands import Agent

app = BedrockAgentCoreApp()
agent = Agent()

# @app.websocket handles connections on port 8080 path /ws
@app.websocket
async def websocket_handler(websocket, context):
    """Bidirectional WebSocket handler for real-time streaming."""
    await websocket.accept()
    try:
        # Receive message from the client
        data = await websocket.receive_json()
        user_message = data.get("prompt", "Hello")
        # Bidirectional streaming: send tokens as they arrive
        async for event in agent.stream_async(user_message):
            if "data" in event:
                await websocket.send_json({"token": event["data"]})
        await websocket.send_json({"done": True})
    except Exception as e:
        print(f"WebSocket error: {e}")
    finally:
        await websocket.close()

if __name__ == "__main__":
    app.run(log_level="info")

# Local test client:
# pip install websockets
# import asyncio, websockets, json
# async def test():
#     async with websockets.connect("ws://localhost:8080/ws") as ws:
#         await ws.send(json.dumps({"prompt": "Hello!"}))
#         while True:
#             msg = json.loads(await ws.recv())
#             if msg.get("done"): break
#             print(msg.get("token", ""), end="", flush=True)
```

_Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-websocket.html_

---

### AgentCore Runtime — FastAPI custom with /invocations and /ping required

```python
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Dict, Any
from datetime import datetime, timezone
from strands import Agent
from strands.models import BedrockModel
from strands.agent.conversation_manager import SlidingWindowConversationManager

app = FastAPI(title="Strands Agent Server", version="1.0.0")

agent_model = BedrockModel(
    model_id="us.amazon.nova-premier-v1:0",
    temperature=0.3,
    max_tokens=2000,
)
strands_agent = Agent(
    model=agent_model,
    conversation_manager=SlidingWindowConversationManager(window_size=10),
)

class InvocationRequest(BaseModel):
    input: Dict[str, Any]

class InvocationResponse(BaseModel):
    output: Dict[str, Any]

# REQUIRED: POST /invocations on port 8080
@app.post("/invocations", response_model=InvocationResponse)
async def invoke_agent(request: InvocationRequest):
    user_message = request.input.get("prompt", "")
    if not user_message:
        raise HTTPException(status_code=400, detail="No prompt in input")
    result = strands_agent(user_message)
    return InvocationResponse(output={
        "message": result.message,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

# REQUIRED: GET /ping on port 8080
@app.get("/ping")
async def ping():
    return {"status": "Healthy", "time_of_last_update": int(datetime.now(timezone.utc).timestamp())}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
```

_Source: https://strandsagents.com/docs/user-guide/deploy/deploy_to_bedrock_agentcore/python/index.md_

---

### AgentCore Runtime — Dockerfile ARM64 with uv for fast builds

```dockerfile
# IMPORTANT: AgentCore Runtime requires linux/arm64
FROM --platform=linux/arm64 ghcr.io/astral-sh/uv:python3.11-bookworm-slim

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-cache

COPY agent.py ./

EXPOSE 8080

CMD ["uv", "run", "uvicorn", "agent:app", "--host", "0.0.0.0", "--port", "8080"]

# Build and push to ECR:
# docker buildx create --use
# docker buildx build --platform linux/arm64 -t <account>.dkr.ecr.us-west-2.amazonaws.com/my-agent:latest --push .
```

_Source: https://strandsagents.com/docs/user-guide/deploy/deploy_to_bedrock_agentcore/python/index.md_

---

### AgentCore Runtime — Deploy with boto3 (CreateAgentRuntime) with LifecycleConfiguration

```python
import boto3
import json
import uuid

# 1. Create the runtime with configurable lifecycle
client = boto3.client('bedrock-agentcore-control', region_name='us-west-2')

response = client.create_agent_runtime(
    agentRuntimeName='my-strands-agent',
    agentRuntimeArtifact={
        'containerConfiguration': {
            'containerUri': '123456789012.dkr.ecr.us-west-2.amazonaws.com/my-strands-agent:latest'
        }
    },
    networkConfiguration={'networkMode': 'PUBLIC'},
    roleArn='arn:aws:iam::123456789012:role/AgentRuntimeRole',
    lifecycleConfiguration={
        'idleRuntimeSessionTimeout': 1800,  # 30 minutes (default 900s)
        'maxLifetime': 28800               # 8 hours (default)
    }
)
agent_runtime_arn = response['agentRuntimeArn']
print(f"Agent Runtime ARN: {agent_runtime_arn}")

# 2. Invoke the agent
# runtimeSessionId is optional: if omitted, AgentCore generates it automatically.
# If provided it must have >= 33 characters.
agent_core_client = boto3.client('bedrock-agentcore', region_name='us-west-2')
payload = json.dumps({'prompt': 'Explain machine learning'}).encode()

response = agent_core_client.invoke_agent_runtime(
    agentRuntimeArn=agent_runtime_arn,
    runtimeSessionId=str(uuid.uuid4()),  # >= 33 chars; or omit
    payload=payload,
    qualifier='DEFAULT'
)

response_body = response['response'].read()
result = json.loads(response_body)
print('Response:', result)
```

_Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-lifecycle-settings.html_

---

### AgentCore Runtime — Async task and custom ping for long workloads (> 15 min sync)

```python
import threading
import time
from strands import Agent, tool
from bedrock_agentcore import BedrockAgentCoreApp
# from bedrock_agentcore.runtime import PingStatus  # if PingStatus enum is needed

app = BedrockAgentCoreApp()

@tool
def start_background_task(duration: int = 5) -> str:
    """Start a background task for the specified duration."""
    # Register the task — ping will respond HealthyBusy until it completes
    task_id = app.add_async_task("background_processing", {"duration": duration})

    def background_work():
        time.sleep(duration)
        app.complete_async_task(task_id)  # Mark as completed

    threading.Thread(target=background_work, daemon=True).start()
    return f"Task {task_id} started for {duration} seconds."

agent = Agent(tools=[start_background_task])

@app.entrypoint
def main(payload):
    user_message = payload.get("prompt", "Start a task")
    return {"message": agent(user_message).message}

# Alternative: custom ping handler
# @app.ping
# def custom_status():
#     if system_busy():
#         return PingStatus.HEALTHY_BUSY
#     return PingStatus.HEALTHY

if __name__ == "__main__":
    app.run()
```

_Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-long-run.html_

---

### Session Management — S3SessionManager for distributed production

```python
from strands import Agent
from strands.session.s3_session_manager import S3SessionManager
from strands.agent.conversation_manager import SlidingWindowConversationManager
from strands.models import BedrockModel
import boto3

# Model with explicit config for production
agent_model = BedrockModel(
    model_id="us.amazon.nova-premier-v1:0",
    temperature=0.3,
    max_tokens=2000,
    top_p=0.8,
)

# Session persistence on S3
boto_session = boto3.Session(region_name="us-west-2")
session_manager = S3SessionManager(
    session_id="user-456-conv-789",  # Unique ID per user/conversation
    bucket="my-agent-sessions",
    prefix="production/",
    boto_session=boto_session,
)

# Conversation manager to limit history
conversation_manager = SlidingWindowConversationManager(window_size=10)

agent = Agent(
    model=agent_model,
    session_manager=session_manager,
    conversation_manager=conversation_manager,
    tools=[weather_research, weather_analysis],  # Explicit tools
)

result = agent("Tell me about the weather in Rome")
```

_Source: https://strandsagents.com/docs/user-guide/concepts/agents/session-management/index.md_

---

### Session Management — FileSessionManager for local development and multi-agent Graph

```python
from strands import Agent
from strands.session.file_session_manager import FileSessionManager
from strands.multiagent import Graph

# SINGLE AGENT
session_manager = FileSessionManager(
    session_id="user-123",
    storage_dir="/path/to/sessions"  # Default: temporary directory
)
agent = Agent(session_manager=session_manager)
agent("Hello, I'm a new user!")  # Persisted to filesystem

# MULTI-AGENT (only orchestrator has session manager)
agent1 = Agent(name="researcher")   # NO session manager
agent2 = Agent(name="writer")       # NO session manager

multi_session = FileSessionManager(session_id="orchestrator-456")
graph = Graph(
    agents={"researcher": agent1, "writer": agent2},
    session_manager=multi_session   # Only on the orchestrator
)
result = graph("Research and write about AI")
```

_Source: https://strandsagents.com/docs/user-guide/concepts/agents/session-management/index.md_

---

### IAM Execution Role for AgentCore Runtime — trust policy and minimal permissions

```json
// Trust Policy for AgentCore Runtime execution role
{
  "Version": "2012-10-17",
  "Statement": [{
    "Sid": "AssumeRolePolicy",
    "Effect": "Allow",
    "Principal": { "Service": "bedrock-agentcore.amazonaws.com" },
    "Action": "sts:AssumeRole",
    "Condition": {
      "StringEquals": { "aws:SourceAccount": "123456789012" },
      "ArnLike": { "aws:SourceArn": "arn:aws:bedrock-agentcore:us-east-1:123456789012:*" }
    }
  }]
}

// Minimal permissions for container deployment
// (attach to the execution role)
{
  "Version": "2012-10-17",
  "Statement": [
    {"Sid": "ECRImageAccess", "Effect": "Allow",
     "Action": ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"],
     "Resource": ["arn:aws:ecr:us-east-1:123456789012:repository/*"]},
    {"Effect": "Allow",
     "Action": ["ecr:GetAuthorizationToken"], "Resource": "*"},
    {"Effect": "Allow",
     "Action": ["logs:DescribeLogStreams", "logs:CreateLogGroup"],
     "Resource": ["arn:aws:logs:us-east-1:123456789012:log-group:/aws/bedrock-agentcore/runtimes/*"]},
    {"Effect": "Allow",
     "Action": ["logs:DescribeLogGroups"],
     "Resource": ["arn:aws:logs:us-east-1:123456789012:log-group:*"]},
    {"Effect": "Allow",
     "Action": ["logs:CreateLogStream", "logs:PutLogEvents"],
     "Resource": ["arn:aws:logs:us-east-1:123456789012:log-group:/aws/bedrock-agentcore/runtimes/*:log-stream:*"]},
    {"Effect": "Allow",
     "Action": ["xray:PutTraceSegments", "xray:PutTelemetryRecords", "xray:GetSamplingRules", "xray:GetSamplingTargets"],
     "Resource": ["*"]},
    {"Effect": "Allow", "Resource": "*",
     "Action": "cloudwatch:PutMetricData",
     "Condition": {"StringEquals": {"cloudwatch:namespace": "bedrock-agentcore"}}},
    {"Sid": "GetAgentAccessToken", "Effect": "Allow",
     "Action": ["bedrock-agentcore:GetWorkloadAccessToken", "bedrock-agentcore:GetWorkloadAccessTokenForJWT", "bedrock-agentcore:GetWorkloadAccessTokenForUserId"],
     "Resource": [
       "arn:aws:bedrock-agentcore:us-east-1:123456789012:workload-identity-directory/default",
       "arn:aws:bedrock-agentcore:us-east-1:123456789012:workload-identity-directory/default/workload-identity/{{agentName}}-*"
     ]},
    {"Sid": "BedrockModelInvocation", "Effect": "Allow",
     "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
     "Resource": ["arn:aws:bedrock:*::foundation-model/*", "arn:aws:bedrock:us-east-1:123456789012:*"]}
  ]
}
```

_Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-permissions.html_

---

### AgentCore CLI — full workflow for scaffolding, local dev and deploy

```bash
# Install AgentCore CLI (replaces bedrock-agentcore-starter-toolkit)
npm install -g @aws/agentcore

# Remove old toolkit if present
pip uninstall bedrock-agentcore-starter-toolkit

# Create new project with interactive wizard
# (select framework: Strands Agents, model provider, deploy type)
agentcore create
cd myproject

# Generated structure:
# myproject/
# ├── agentcore/
# │   ├── agentcore.json       # Resource specifications
# │   └── aws-targets.json     # Deployment targets
# └── app/
#     └── MyAgent/
#         ├── main.py          # Entry point with @app.entrypoint
#         ├── pyproject.toml
#         └── model/

# Local development (starts server on localhost:8080)
agentcore dev

# Deploy to AWS (container or direct code deploy)
agentcore deploy

# Test the deployed agent
agentcore invoke

# NOTE: CDK supported natively; Terraform coming.
# IAM policies generated by agentcore deploy are for DEV/TEST,
# not suitable for production (too permissive).
```

_Source: https://strandsagents.com/docs/user-guide/deploy/deploy_to_bedrock_agentcore/python/index.md_

---

### AgentCore Runtime — Managed session storage for persistent filesystem (Preview)

```python
import boto3

client = boto3.client('bedrock-agentcore-control', region_name='us-west-2')

# Create agent runtime with managed session storage (no VPC required)
response = client.create_agent_runtime(
    agentRuntimeName='my-stateful-agent',
    agentRuntimeArtifact={
        'containerConfiguration': {
            'containerUri': '123456789012.dkr.ecr.us-west-2.amazonaws.com/my-agent:latest'
        }
    },
    networkConfiguration={'networkMode': 'PUBLIC'},
    roleArn='arn:aws:iam::123456789012:role/AgentRuntimeRole',
    filesystemConfigurations=[
        {
            'sessionStorage': {
                'mountPath': '/mnt/workspace'  # Must match /mnt/<subdir>
            }
        }
    ]
)

# The filesystem at /mnt/workspace survives session stop/resume.
# It is reset after 14 days of inactivity or on a version update.
# Supports: regular files, directories, symlinks, chmod, git, npm, pip, cargo.
# Does NOT support: hard links, device files, xattr, fallocate.
print(f"Agent Runtime ARN: {response['agentRuntimeArn']}")
```

_Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-filesystem-configurations.html_

---

### AgentCore/Fargate deploy and test via CDK and curl

```bash
# Bootstrap CDK (only the first time per account/region)
npx cdk bootstrap

# Make sure Docker/Podman is running
podman machine start

# Deploy with Podman as container engine
CDK_DOCKER=podman npx cdk deploy

# Get load balancer URL from CDK output
SERVICE_URL=$(aws cloudformation describe-stacks \
  --stack-name AgentFargateStack \
  --query "Stacks[0].Outputs[?ExportName=='AgentServiceEndpoint'].OutputValue" \
  --output text)

# Test standard endpoint
curl -X POST http://$SERVICE_URL/agent \
  -H 'Content-Type: application/json' \
  -d '{"prompt": "What is machine learning?"}'

# Test streaming endpoint
curl -X POST http://$SERVICE_URL/agent/stream \
  -H 'Content-Type: application/json' \
  -d '{"prompt": "Explain neural networks"}'

# EKS: deploy with Helm (complete config in the GitHub repo strands-agents/docs)
helm install strands-agents-weather ./chart
# Test via port-forward
kubectl port-forward service/strands-agents-weather 8080:80 &
curl -X POST http://localhost:8080/agent -H 'Content-Type: application/json' -d '{"prompt": "Hello"}'
```

_Source: https://strandsagents.com/docs/user-guide/deploy/deploy_to_aws_fargate/index.md_

---

## Configuration reference

| Name | Description | Default / example |
|------|-------------|-------------------|
| `bedrock-agentcore` (Python SDK) | PyPI package required for AgentCore SDK Integration. Provides `BedrockAgentCoreApp`, decorators `@app.entrypoint`, `@app.websocket`, `@app.ping`, `add_async_task()`, `complete_async_task()`, `PingStatus`, and `AgentCoreRuntimeClient` for WebSocket client. | `pip install bedrock-agentcore` |
| `@aws/agentcore` (CLI npm) | AgentCore CLI for scaffolding, local development, and deployment. Supports container and direct code deploy. CDK supported; Terraform coming. Replaces `bedrock-agentcore-starter-toolkit`. Available in 14 regions. | `npm install -g @aws/agentcore` |
| Lambda timeout | Lambda execution limit. For AI agents consider at least 30 seconds; absolute Lambda maximum is 15 minutes. Agents with complex reasoning may exceed this — prefer Fargate in that case. | `Duration.seconds(30)` — increase to 60-300 for more complex agents |
| Lambda memorySize | Memory allocated to the Lambda function. More memory = proportionally more CPU. 128 MB for simple agents; 512 MB-1 GB for real agents with complex tools. | `128` (example), evaluate `512-1024` for real agents |
| Lambda architecture | Lambda CPU architecture. ARM64 (Graviton2) has ~20% lower costs and better performance for I/O-bound workloads. Requires dependencies installed for `manylinux2014_aarch64`. | `lambda.Architecture.ARM_64` (recommended) |
| Fargate task CPU/Memory | Resources allocated to the Fargate task. 256 CPU units (0.25 vCPU) and 512 MB for simple agents; increase for agents with more tools or high concurrency. | `cpu: 256, memoryLimitMiB: 512` |
| Fargate desiredCount | Number of Fargate service replicas. Minimum 2 for high availability. | `desiredCount: 2` |
| AgentCore Runtime platform | Required platform for AgentCore Runtime containers. Must be `linux/arm64`. Build with: `docker buildx build --platform linux/arm64` | `linux/arm64` (MANDATORY for container deployment) |
| AgentCore Runtime port | Port on which the application must run in the AgentCore Runtime container for all HTTP/WebSocket/AG-UI protocols. | `8080` |
| AgentCore Runtime required endpoints | AgentCore Runtime service contract: `POST /invocations` (main handler) and `GET /ping` on port 8080. `/ping` must return `{status: 'Healthy'|'HealthyBusy', time_of_last_update: <unix_timestamp>}`. WebSocket on `/ws` same port. MCP on port 8000, A2A on port 9000. | `POST /invocations`, `GET /ping` — both required. `/ws` for WebSocket. |
| `runtimeSessionId` | Session ID for AgentCore Runtime. OPTIONAL: if omitted on first invoke, AgentCore generates it automatically. If provided by the client, must have at least 33 characters. Use the same ID for all invocations correlated to a conversation. | `str(uuid.uuid4())` or omit for auto-generation |
| `LifecycleConfiguration.idleRuntimeSessionTimeout` | Timeout in seconds for idle sessions in AgentCore Runtime. Configurable via `LifecycleConfiguration` in `CreateAgentRuntime`/`UpdateAgentRuntime`. Range: 60-28800 seconds. Must be <= `maxLifetime`. | `900` (15 minutes) — increase for conversational workloads |
| `LifecycleConfiguration.maxLifetime` | Maximum duration of the microVM in seconds. Configurable. Range: 60-28800 seconds. On reaching this limit, compute is terminated but the session remains valid and recreates a new microVM on the next invoke. | `28800` (8 hours) |
| AgentCore Runtime sync request timeout | Fixed timeout (not modifiable) for synchronous requests on `InvokeAgentRuntime`. | `900` seconds (15 minutes) — fixed, not modifiable |
| AgentCore Runtime streaming timeout | Maximum duration for streaming connections (HTTP response streaming and WebSocket). | `3600` seconds (60 minutes) — fixed, not modifiable |
| AgentCore Runtime active sessions quota | Concurrent active sessions per account. Region-specific default quota, increasable via Service Quotas. | `1000` in us-east-1/us-west-2; `500` in other regions |
| AgentCore Runtime InvokeAgentRuntime TPS | Rate limit for `InvokeAgentRuntime` API. Increasable via Service Quotas. | `25 TPS` per agent per account |
| AgentCore Runtime Docker image max size | Maximum Docker image size for AgentCore Runtime. Not increasable. | `2 GB` |
| AgentCore Runtime direct code deploy max size | Maximum zip package size for direct code deployment. | `250 MB` compressed, `750 MB` uncompressed |
| Session storage filesystem mount path | Mount path for session storage or BYO filesystem in AgentCore Runtime. Must follow pattern `/mnt/<subdir>`. | `/mnt/workspace`, `/mnt/data`, `/mnt/efs` |
| Session storage idle expiry | Managed session storage data is deleted after this period of session inactivity. | `14 days` — then filesystem is reset |
| AgentCore Runtime session header (HTTP/A2A/AG-UI) | HTTP header to include in subsequent requests for routing to the same microVM (session stickiness). | `X-Amzn-Bedrock-AgentCore-Runtime-Session-Id: <session-id>` |
| AgentCore Runtime session header (MCP) | Header to include for session stickiness on MCP protocol. | `Mcp-Session-Id: <session-id>` |
| S3SessionManager IAM permissions | IAM permissions for Strands `S3SessionManager`. The agent's role must have `s3:GetObject`, `s3:PutObject`, `s3:DeleteObject`, `s3:ListBucket` on the sessions bucket. | `s3:GetObject, s3:PutObject, s3:DeleteObject, s3:ListBucket` on `arn:aws:s3:::my-agent-sessions/*` |
| `SlidingWindowConversationManager` window_size | Maximum number of messages to keep in Strands conversation history. Too low loses context; too high exhausts the model's context window. | `window_size=10` (recommended in production) |
| `BedrockModel` model_id | Amazon Bedrock model ID. Use the cross-region inference prefix (e.g., `us.`) for better availability. `BedrockModel` internally uses the Converse API (`ConverseStream`/`Converse`). | `us.amazon.nova-premier-v1:0`, `us.anthropic.claude-sonnet-4-20250514-v1:0` |
| IAM managed policy `BedrockAgentCoreFullAccess` | AWS managed policy for full AgentCore access. DO NOT use in production — create custom policies with least privilege. | Development/testing only, NOT for production |
| Lambda Layer — Strands Agents (Account ID) | Official Strands Agents layer published from AWS account `856699698935`. Layer version 2 = strands-agents v1.40.0. | `arn:aws:lambda:us-east-1:856699698935:layer:strands-agents-py3_12-x86_64:2` |
| Agent `retry_strategy` | Retry strategy for model calls in case of throttling or transient errors. Default: `max_attempts=6`, `initial_delay=4s`, `max_delay=240s`. Pass `None` to disable retries. | `ModelRetryStrategy(max_attempts=6)` — pass `retry_strategy=None` to disable |

---

## Gotchas

- **Lambda does not support native streaming with `stream_async()`**: the official guide states this explicitly. If streaming is needed, use Fargate, App Runner, EKS, or AgentCore Runtime.

- **AgentCore Runtime mandatorily requires**: platform `linux/arm64` (container), endpoints `POST /invocations` and `GET /ping` on port 8080. `runtimeSessionId` is optional: if omitted, AgentCore generates it automatically; if provided, it must have at least 33 characters.

- **The `/ping` in AgentCore Runtime must return `time_of_last_update`** (integer Unix timestamp). Without this field the platform may terminate the session. With `BedrockAgentCoreApp` this is handled automatically.

- **Blocking operations in the main thread of AgentCore Runtime also block the `/ping` health check**, causing the platform to terminate the session. Use separate threading or async for I/O-bound operations.

- **On Lambda, dependencies must match the target architecture.** For ARM64 use `--platform manylinux2014_aarch64`. Wrong architecture causes `ImportError` at runtime.

- **In multi-agent Strands (Graph/Swarm), a single agent with `session_manager` added to the orchestrator raises `ValueError`.** Only the orchestrator must have a session manager.

- **The old package `bedrock-agentcore-starter-toolkit` has been replaced by the AgentCore CLI (`@aws/agentcore` npm).** Having both installed causes conflicts.

- **IAM policies created by the AgentCore CLI are for development/testing, not production.** For production, create custom policies with least privilege for both execution role and user role.

- **`BedrockModel` uses the Converse API internally (`ConverseStream`/`Converse`), not the legacy `InvokeModel` API.** The required IAM actions remain `bedrock:InvokeModelWithResponseStream` and `bedrock:InvokeModel` (Converse API aliases).

- **Managed Session Storage in AgentCore Runtime is in Preview (not GA).** Data is reset on agent runtime version update: every `agentcore deploy` that produces a new version deletes the persistent filesystem of existing sessions.

- **AgentCore Harness is in Preview only in 4 regions** (us-east-1, us-west-2, eu-central-1, ap-southeast-2). AgentCore Runtime is GA in 16 regions. Do not confuse the two services.

- **The sync request timeout of AgentCore Runtime (15 minutes) is fixed and not modifiable.** `LifecycleConfiguration` only configures `idleRuntimeSessionTimeout` and `maxLifetime` (compute duration, not request timeout).

- **Direct code deployment on AgentCore Runtime has a separate quota for new sessions**: 25 TPS (vs 100 TPM for container deployment).

- **For MCP connections on Lambda**: reusing the connection between invocations (module level) risks state leakage in multi-tenant setups. The context manager is safer.

- **On Fargate with ALB, `healthCheckGracePeriod` must be set** (at least 60 seconds) to give the container time to start before health checks begin.

- **For Lambda with container image, the base image MUST be a Lambda-compatible image** (`public.ecr.aws/lambda/python:3.11`). For FastAPI on Lambda container use Mangum (`pip install mangum`).

- **AgentCore Runtime does not enforce user-to-session mapping**: the client backend is responsible for managing this relationship, the maximum number of sessions per user, and cleanup (`StopRuntimeSession` API).

- **EKS with Pod Identity on EKS Auto Mode: the Pod Identity Agent add-on is NOT required** (functionality is integrated). On non-Auto Mode clusters it must be installed manually as an add-on.

---

## Official sources

- [Strands Agents — Deploy to AWS Lambda](https://strandsagents.com/docs/user-guide/deploy/deploy_to_aws_lambda/index.md) — Complete Lambda guide: handler, official layers, packaging, CDK, MCP on Lambda
- [Strands Agents — Deploy to AWS Fargate](https://strandsagents.com/docs/user-guide/deploy/deploy_to_aws_fargate/index.md) — FastAPI + Docker + CDK on Fargate with streaming via `stream_async()`
- [Strands Agents — Deploy to Amazon EKS](https://strandsagents.com/docs/user-guide/deploy/deploy_to_amazon_eks/index.md) — EKS Auto Mode, eksctl, Helm chart, Pod Identity for Bedrock — complete config in the strands-agents/docs GitHub repo
- [Strands Agents — Operating Agents in Production](https://strandsagents.com/docs/user-guide/deploy/operating-agents-in-production/index.md) — Production best practices: model config, tool management, `SlidingWindowConversationManager`, error handling, streaming
- [Strands Agents — Deploy to Bedrock AgentCore Runtime (Python)](https://strandsagents.com/docs/user-guide/deploy/deploy_to_bedrock_agentcore/python/index.md) — Complete guide: SDK Integration (`BedrockAgentCoreApp`), Custom Agent FastAPI, CLI agentcore, manual boto3, observability
- [Strands Agents — Session Management](https://strandsagents.com/docs/user-guide/concepts/agents/session-management/index.md) — `FileSessionManager`, `S3SessionManager`, storage structure, multi-agent sessions, custom `RepositorySessionManager`
- [Strands Agents — Async Iterators for Streaming](https://strandsagents.com/docs/user-guide/concepts/streaming/async-iterators/index.md) — `stream_async()`, lifecycle events, FastAPI/Express.js integration
- [Strands Agents — Amazon Bedrock Model Provider](https://strandsagents.com/docs/user-guide/concepts/model-providers/amazon-bedrock/index.md) — `BedrockModel` uses Converse API (`ConverseStream`/`Converse`). Parameters: `model_id`, `temperature`, `top_p`, `max_tokens`, `streaming`, `guardrail_id`, `cache_config`, `boto_session`, `region_name`
- [Amazon Bedrock AgentCore — What is AgentCore](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/what-is-bedrock-agentcore.html) — Complete overview: Runtime, Harness, Memory, Gateway, Identity, Browser, Code Interpreter, Observability, Payments, Evaluations, Policy, Registry
- [Amazon Bedrock AgentCore — Host agents with AgentCore Runtime](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agents-tools-runtime.html) — Session isolation microVM, extensible up to 8 configurable hours, persistent filesystem, bidirectional streaming WebSocket, consumption-based pricing
- [Amazon Bedrock AgentCore — How it works](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-how-it-works.html) — Key components: AgentCore Runtime (container), Versions (immutable), Endpoints (alias), Sessions (isolated microVM). Versioning with rollback. DEFAULT endpoint updated automatically.
- [Amazon Bedrock AgentCore — IAM Permissions for AgentCore Runtime](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-permissions.html) — Complete policies: user, CLI, execution role, trust policy for AgentCore Runtime
- [Amazon Bedrock AgentCore — Use isolated sessions](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-sessions.html) — Session lifecycle (Active/Idle/Stopped), session headers by protocol, microVM stickiness. `runtimeSessionId` optional: if omitted, Runtime generates it autonomously.
- [Amazon Bedrock AgentCore — Configure lifecycle settings](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-lifecycle-settings.html) — `LifecycleConfiguration`: `idleRuntimeSessionTimeout` (default 900s, range 60-28800s) and `maxLifetime` (default 28800s, range 60-28800s), both configurable via `CreateAgentRuntime`/`UpdateAgentRuntime`.
- [Amazon Bedrock AgentCore — Async and long-running agents](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-long-run.html) — `add_async_task()`, `complete_async_task()`, custom ping handler, configurable idle timeout
- [Amazon Bedrock AgentCore — Stream agent responses](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/response-streaming.html) — Streaming via async generator with `@app.entrypoint async def` + `yield`
- [Amazon Bedrock AgentCore — Bidirectional streaming via WebSocket (GA)](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-websocket.html) — WebSocket GA: `@app.websocket` decorator, endpoint `/ws` on port 8080, SigV4 headers/presigned URL/OAuth authentication. Bidirectional streaming for voice agents and real-time use cases.
- [Amazon Bedrock AgentCore — Quotas (official limits)](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/bedrock-agentcore-limits.html) — 1000 active sessions in us-east-1/us-west-2, 500 in other regions. 25 TPS invoke per agent. 15 min sync timeout, 60 min streaming max, 8 hours async max. 2 GB max Docker image, 100 MB max payload.
- [Amazon Bedrock AgentCore — File system configurations](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-filesystem-configurations.html) — Two categories: managed session storage (Preview, no VPC, per-session, 14-day idle expiry) and BYO (S3 Files or EFS, shared, VPC mandatory). Up to 5 total configurations per agent runtime.
- [Amazon Bedrock AgentCore — Supported AWS Regions](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agentcore-regions.html) — AgentCore Runtime GA in 16 regions (including GovCloud US-West). AgentCore Harness preview only in 4 regions (us-east-1, us-west-2, eu-central-1, ap-southeast-2).
- [Amazon Bedrock AgentCore — Harness [Preview]](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/harness.html) — Managed agent loop powered by Strands Agents. Requires only model + system prompt + tools. Supports Bedrock, OpenAI, Gemini. Isolated microVM, persistent filesystem, integrated memory. Preview in 4 regions, no additional cost.
- [Amazon Bedrock AgentCore — Direct code deployment (Python)](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-code-deploy-python.html) — Deploy via zip file without container. Max 250 MB compressed, 750 MB uncompressed. Same API contract (`@app.entrypoint` or `/invocations` + `/ping`). Rate: 25 TPS for new sessions.
- [Strands Agents — Deploy to Terraform](https://strandsagents.com/docs/user-guide/deploy/deploy_to_terraform/index.md) — Terraform IaC for App Runner, Lambda (with Mangum), Google Cloud Run, Azure Container Instances

---

## Verify live (open questions)

- **EKS Pod Identity — complete YAML files** (ServiceAccount, Pod Identity association via eksctl or AWS CLI) are not included inline in the Strands guide but are in the GitHub repo **strands-agents/docs** at `github.com/strands-agents/docs/tree/main/docs/examples/deploy_to_eks`. Consult directly for the complete eksctl configuration.
