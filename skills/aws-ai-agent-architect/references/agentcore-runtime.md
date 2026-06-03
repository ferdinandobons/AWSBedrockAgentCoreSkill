# Amazon Bedrock AgentCore Runtime — Serverless Agent Hosting

> Part of the **aws-ai-agent-architect** skill. See [SKILL.md](../SKILL.md) for the decision tree. Every source below is official — re-open it to verify details.

## Table of contents

- [Overview](#overview)
- [Key concepts](#key-concepts)
  - [AgentCore Runtime](#agentcore-runtime-1)
  - [MicroVM session isolation](#microvm-session-isolation)
  - [Runtime service contract (HTTP)](#runtime-service-contract-http)
  - [/invocations endpoint](#invocations-endpoint)
  - [/ping endpoint](#ping-endpoint)
  - [BedrockAgentCoreApp](#bedrockagentcoreapp)
  - [Versions and endpoints](#versions-and-endpoints)
  - [Deployment methods](#deployment-methods)
  - [Session state and persistence](#session-state-and-persistence)
  - [Supported frameworks](#supported-frameworks)
  - [Protocol support (MCP, A2A, AG-UI)](#protocol-support-mcp-a2a-ag-ui)
  - [Async and long-running tasks](#async-and-long-running-tasks)
  - [Streaming responses (SSE and WebSocket)](#streaming-responses-sse-and-websocket)
  - [AgentCore Harness (Preview)](#agentcore-harness-preview)
  - [Direct code deploy runtime identifiers](#direct-code-deploy-runtime-identifiers)
  - [filesystemConfigurations](#filesystemconfigurations)
  - [Calling the runtime from a web backend](#calling-the-runtime-from-a-web-backend)
- [Best practices](#best-practices)
- [Code](#code)
  - [Minimal Strands agent with BedrockAgentCoreApp](#minimal-strands-agent-with-bedrockagentcoreapp)
  - [LangGraph agent with BedrockAgentCoreApp](#langgraph-agent-with-bedrockagentcoreapp)
  - [Google ADK agent with BedrockAgentCoreApp](#google-adk-agent-with-bedrockagentcoreapp)
  - [Streaming response via async generator (SSE)](#streaming-response-via-async-generator-sse)
  - [Async background task with /ping management](#async-background-task-with-ping-management)
  - [Custom /ping handler (low-level)](#custom-ping-handler-low-level)
  - [Bidirectional WebSocket handler](#bidirectional-websocket-handler)
  - [WebSocket client with SigV4 headers](#websocket-client-with-sigv4-headers)
  - [WebSocket client with SigV4 pre-signed URL](#websocket-client-with-sigv4-pre-signed-url)
  - [Custom FastAPI agent (no SDK)](#custom-fastapi-agent-no-sdk)
  - [ARM64 Dockerfile](#arm64-dockerfile)
  - [Build and push ARM64 image to ECR](#build-and-push-arm64-image-to-ecr)
  - [Create AgentCore Runtime — container deployment](#create-agentcore-runtime--container-deployment)
  - [Create AgentCore Runtime — direct code (ZIP) deployment](#create-agentcore-runtime--direct-code-zip-deployment)
  - [Build ARM64-compatible ZIP package for direct code deploy](#build-arm64-compatible-zip-package-for-direct-code-deploy)
  - [Invoke a deployed agent (data plane)](#invoke-a-deployed-agent-data-plane)
  - [Stop a runtime session explicitly](#stop-a-runtime-session-explicitly)
  - [Update endpoint to a new version](#update-endpoint-to-a-new-version)
  - [Execution role trust policy with confused-deputy prevention](#execution-role-trust-policy-with-confused-deputy-prevention)
  - [Minimal direct-deploy execution role policy](#minimal-direct-deploy-execution-role-policy)
  - [AgentCore CLI quickstart commands](#agentcore-cli-quickstart-commands)
  - [AgentCore Harness — invoke via boto3 (Preview)](#agentcore-harness--invoke-via-boto3-preview)
  - [Configure persistent session storage (filesystemConfigurations)](#configure-persistent-session-storage-filesystemconfigurations)
- [Configuration reference](#configuration-reference)
- [Gotchas](#gotchas)
- [Official sources](#official-sources)

---

## Overview

Amazon Bedrock AgentCore Runtime is a **GA** serverless, framework-agnostic hosting environment for deploying and running AI agents and tools at production scale. It provisions dedicated microVMs per session for complete isolation, supports extended runtimes up to 8 hours, accepts container images (ARM64) or direct code ZIP uploads (Python/Node.js), and exposes a well-defined HTTP service contract (`/invocations` POST, `/ping` GET on port 8080). The primary deployment path is the AgentCore CLI (`@aws/agentcore` npm package), backed by CDK. The runtime integrates natively with Strands Agents, LangGraph, Google ADK, OpenAI Agents SDK, and custom frameworks via the `bedrock-agentcore` Python SDK (`BedrockAgentCoreApp`). Consumption-based pricing charges only for active processing time, not idle wait.

**Maturity note:** GA as of late 2025. Initial preview July 2025. Direct code deployment (Python) GA November 2025; Node.js GA April 2026. Bidirectional WebSocket streaming GA December 2025. Stateful MCP server features GA March 2026. AG-UI protocol support GA March 2026. Shell command execution (`InvokeAgentRuntimeCommand`) GA March 2026. **Managed Harness (config-based agent loop) is in PUBLIC PREVIEW as of June 2026** — available only in `us-east-1`, `us-west-2`, `eu-central-1`, `ap-southeast-2`. Persistent filesystem session storage is in Preview; BYO S3 Files and EFS are GA. Available in 16 AWS regions. _Source: [Quotas for Amazon Bedrock AgentCore](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/bedrock-agentcore-limits.html)_

> For framework-specific deployment patterns (Lambda, Fargate, EKS) and Terraform/CDK IaC, see `deployment-iac.md` in this references directory.

---

## Key concepts

### AgentCore Runtime

The core serverless resource that hosts your agent or tool. Created via the `CreateAgentRuntime` API (`bedrock-agentcore-control` boto3 client). Each runtime has a unique ARN, is versioned, and consists of a container image or ZIP artifact plus configuration (network mode, lifecycle, execution role). Upon creation, Version 1 and a DEFAULT endpoint are automatically created.

### MicroVM session isolation

Every unique `runtimeSessionId` gets its own dedicated microVM with isolated CPU (up to 2 vCPU), memory (up to 8 GB), and filesystem. After session termination the entire microVM is destroyed and memory is sanitized — cross-session data contamination is architecturally impossible.

- **Idle timeout:** 15 minutes (default, configurable via `idleRuntimeSessionTimeout`)
- **Max session lifetime:** 8 hours (configurable via `maxLifetime`)
- **Session states:** Active, Idle, Stopped
- A Stopped session resumes on next invocation with a **new** microVM (in-memory state is not preserved)

### Runtime service contract (HTTP)

Any agent deployed to AgentCore Runtime must expose exactly two mandatory HTTP endpoints on **port 8080** over **ARM64**:

| Endpoint | Method | Purpose |
|---|---|---|
| `/invocations` | POST | Receives user payload; returns JSON or SSE stream |
| `/ping` | GET | Health check for session lifecycle management |
| `/ws` | WebSocket | Optional; enables bidirectional streaming |

The `BedrockAgentCoreApp` SDK automatically serves all of these when you call `app.run()`.

Beyond HTTP, the runtime natively supports MCP (port 8000, path `/mcp`, JSON-RPC), A2A (port 9000, root path, JSON-RPC 2.0), and AG-UI (port 8080, `/invocations` SSE or `/ws` WebSocket).

_Source: [Understand the AgentCore Runtime service contract](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-service-contract.html)_

### /invocations endpoint

The primary interaction endpoint. Receives POST requests with a JSON body (e.g., `{"prompt": "..."}` or `{"input": {"prompt": "..."}`). Must respond with:

- `Content-Type: application/json` for synchronous responses
- `Content-Type: text/event-stream` for SSE streaming

**Payload limit:** 100 MB. **Request timeout for synchronous calls:** 15 minutes. The SDK passes the deserialized dict to the `@app.entrypoint`-decorated function.

_Source: [HTTP protocol contract](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-http-protocol-contract.html)_

### /ping endpoint

GET health check polled by AgentCore to manage session lifecycle. Must return HTTP 200 with JSON:

```json
{"status": "Healthy" | "HealthyBusy", "time_of_last_update": <unix_seconds>}
```

- `Healthy` — agent is idle; session terminates after the configured idle timeout (default 15 min)
- `HealthyBusy` — keeps the session alive for background async work
- **Both fields are required.** Omitting `time_of_last_update` causes premature session termination even when `HealthyBusy` is set.

_Source: [Handle asynchronous and long-running agents](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-long-run.html)_

### BedrockAgentCoreApp

Main class from the `bedrock-agentcore` Python SDK (`pip install bedrock-agentcore`). Wraps your agent logic and handles the service contract automatically.

- Use `@app.entrypoint` on your handler — receives `(payload: dict, context)` where `context.session_id` exposes the current `runtimeSessionId`
- Use `@app.websocket` for WebSocket handlers (registered at `/ws` automatically)
- Use `@app.ping` to override the default ping handler
- Call `app.run()` at the bottom to start the HTTP server on port 8080

_Source: [Use any agent framework](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/using-any-agent-framework.html)_

### Versions and endpoints

Each update to a runtime's configuration (container image, protocol, network) creates a new **immutable version**. Endpoints are named references to specific versions.

- The **DEFAULT** endpoint always points to the latest version automatically
- Custom endpoints (e.g., `production`, `staging`) can be pinned to specific versions via `update_agent_runtime_endpoint()` and remain stable during updates — enabling blue/green and canary deployments
- Maximum 10 endpoints per agent (adjustable via Service Quotas)

_Source: [AgentCore Runtime versioning and endpoints](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agent-runtime-versioning.html)_

### Deployment methods

Three deployment paths exist:

1. **AgentCore CLI (recommended, GA)** — `npm install -g @aws/agentcore`, then `agentcore create/dev/deploy`. Uses CDK under the hood; supports both CodeZip and Container build types. Hot-reload dev server included.
2. **Direct code deploy (ZIP)** — ZIP artifact with Python or Node.js code. Max 250 MB compressed / 750 MB uncompressed, uploaded to S3. **25 new sessions/sec cold start rate.**
3. **Container image** — Docker ARM64 image pushed to ECR. Up to 2 GB. **100 new sessions/min cold start rate.**

_Source: [Direct code deployment overview](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-code-deploy.html)_

### Session state and persistence

By default all microVM state is **ephemeral** and lost when the session stops. Persistent options:

- **Managed session storage (Preview):** `filesystemConfigurations.sessionStorage` — survives stop/resume cycles, 1 GB limit, 14-day idle expiry, resets on version update, no VPC required
- **BYO S3 Files (GA):** `s3FilesAccessPoint` — shared across sessions, VPC required
- **BYO EFS (GA):** `efsAccessPoint` — shared across sessions, full POSIX semantics, VPC required
- **AgentCore Memory:** For structured data persistence across sessions (separate service)
- Session IDs must be **at least 33 characters**

_Source: [Use isolated sessions for agents](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-sessions.html)_

### Supported frameworks

Officially supported and tested: Strands Agents, LangChain/LangGraph, Google Agent Development Kit (ADK), OpenAI Agents SDK. Any other Python or Node.js framework works as long as it respects the `/invocations` and `/ping` contract — either via `BedrockAgentCoreApp` SDK or a custom HTTP server (e.g., FastAPI/uvicorn).

_Source: [Use any agent framework](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/using-any-agent-framework.html)_

### Protocol support (MCP, A2A, AG-UI)

Beyond HTTP, Runtime natively supports:

| Protocol | Port | Path | Format | Session header |
|---|---|---|---|---|
| HTTP | 8080 | `/invocations` | JSON / SSE | `X-Amzn-Bedrock-AgentCore-Runtime-Session-Id` |
| WebSocket | 8080 | `/ws` | JSON frames | `X-Amzn-Bedrock-AgentCore-Runtime-Session-Id` |
| MCP | 8000 | `/mcp` | JSON-RPC | `Mcp-Session-Id` |
| A2A | 9000 | `/` (root) | JSON-RPC 2.0 | `X-Amzn-Bedrock-AgentCore-Runtime-Session-Id` |
| AG-UI | 8080 | `/invocations` SSE or `/ws` | SSE / WebSocket | `X-Amzn-Bedrock-AgentCore-Runtime-Session-Id` |

MCP supports both stateless and stateful modes. AG-UI enables real-time frontend streaming.

_Source: [Understand the AgentCore Runtime service contract](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-service-contract.html)_

### Async and long-running tasks

Agents can start background work that outlives the HTTP response:

- Use `app.add_async_task(name)` to register a task — the SDK automatically sets `/ping` to `HealthyBusy` while tasks are running
- Use `app.complete_async_task(task_id)` to mark it done — SDK reverts `/ping` to `Healthy`
- Alternatively, implement a custom `@app.ping` handler returning `PingStatus.HEALTHY_BUSY`
- Max session lifetime: 8 hours. Streaming connections have a separate 60-minute maximum duration.

_Source: [Handle asynchronous and long-running agents](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-long-run.html)_

### Streaming responses (SSE and WebSocket)

- **SSE (unidirectional):** Implement `@app.entrypoint` as an `async generator` and `yield` events — the runtime streams these as Server-Sent Events. SDK automatically sets `Content-Type: text/event-stream`.
- **Bidirectional WebSocket:** Use `@app.websocket` decorator; endpoint registered at `/ws` on port 8080. Clients use `AgentCoreRuntimeClient` from `bedrock_agentcore.runtime` with `generate_ws_connection()` or `generate_presigned_url()` methods, or supply an OAuth bearer token.
- IAM action required for WebSocket: `bedrock-agentcore:InvokeAgentRuntimeWithWebSocketStream`

_Source: [Stream agent responses (SSE)](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/response-streaming.html)_

### AgentCore Harness (Preview)

> **WARNING: PUBLIC PREVIEW** — Only available in `us-east-1`, `us-west-2`, `eu-central-1`, `ap-southeast-2`. Do not use in production outside these regions.

A managed, config-based agent loop that requires no custom agent code. Declare model, tools, system prompt, and memory; AgentCore provides the orchestration. Backed by Strands Agents.

- **Default model:** Anthropic Claude Sonnet 4.6 on Bedrock
- Supports Bedrock, OpenAI, and Google Gemini model providers, with mid-session model switching
- Invoked via `invoke_harness()` (boto3 data plane) or `agentcore invoke --harness`
- No separate harness charge — pay for underlying AgentCore resources

_Source: [AgentCore Harness overview](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/harness.html)_

### Direct code deploy runtime identifiers

Supported identifiers for the `runtime` field in `codeConfiguration` (all on Amazon Linux 2023):

| Identifier | Status |
|---|---|
| `PYTHON_3_14` | GA |
| `PYTHON_3_13` | GA, **recommended** |
| `PYTHON_3_12` | GA |
| `PYTHON_3_11` | GA, deprecating **6/30/2026** |
| `PYTHON_3_10` | GA, deprecating **6/30/2026** |
| `NODE_22` | GA |

Runtime patches are applied automatically by AgentCore; customer is responsible for their own code dependencies. Always use `SCREAMING_SNAKE_CASE` format.

_Source: [Supported language runtimes and deprecation policy](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-code-deploy-supported-runtimes.html)_

### filesystemConfigurations

Optional parameter on `CreateAgentRuntime`/`UpdateAgentRuntime` to mount persistent storage. Up to 5 configurations total.

| Type | Key | VPC required | Scope | Limit |
|---|---|---|---|---|
| Session storage (Preview) | `sessionStorage` | No | Per-session, isolated | 1 GB, 14-day idle expiry |
| S3 Files (GA) | `s3FilesAccessPoint` | Yes | Shared across sessions | S3 bucket limits |
| EFS (GA) | `efsAccessPoint` | Yes | Shared across sessions | EFS limits |

Managed session storage resets to empty on runtime version update (new container image or code package).

_Source: [File system configurations for AgentCore Runtime](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-filesystem-configurations.html)_

### Calling the runtime from a web backend

How a server-side web backend (Node.js, Python, etc.) authenticates to AgentCore Runtime, maps user sessions, and proxies the streaming response to the browser.

#### 1. Authenticating to AgentCore Runtime

**IAM SigV4 (service-to-service, default):** The default and recommended approach for trusted backends. The caller must have `bedrock-agentcore:InvokeAgentRuntime` on the runtime ARN. Use any AWS SDK — boto3 signs the request automatically.

```python
# boto3 signs with SigV4 automatically; no extra auth setup required
client = boto3.client('bedrock-agentcore', region_name='us-west-2')
response = client.invoke_agent_runtime(
    agentRuntimeArn='arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/myAgent-suffix',
    runtimeSessionId=session_id,   # >=33 chars
    payload=json.dumps({"prompt": user_message}).encode(),
)
```

_Source: [Invoke an AgentCore Runtime agent](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-invoke-agent.html)_

If you also pass the `X-Amzn-Bedrock-AgentCore-Runtime-User-Id` header, the caller needs `bedrock-agentcore:InvokeAgentRuntimeForUser` in addition to `bedrock-agentcore:InvokeAgentRuntime`.

_Source: [InvokeAgentRuntime API Reference](https://docs.aws.amazon.com/bedrock-agentcore/latest/APIReference/API_InvokeAgentRuntime.html)_

**JWT bearer token (end-user-facing agents):** When the runtime is configured with `authorizerConfiguration.customJWTAuthorizer` (OIDC discovery URL + allowed clients/audiences), callers authenticate with a JWT issued by an IdP (e.g., Cognito). The AWS SDK cannot sign OAuth-authenticated requests — use a plain HTTPS client:

```python
import requests, urllib.parse, json, os

escaped_arn = urllib.parse.quote(agent_arn, safe='')
url = f"https://bedrock-agentcore.{REGION}.amazonaws.com/runtimes/{escaped_arn}/invocations?qualifier=DEFAULT"

response = requests.post(
    url,
    headers={
        "Authorization": f"Bearer {jwt_token}",
        "Content-Type": "application/json",
        "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": session_id,
    },
    data=json.dumps({"prompt": user_message}),
    stream=True,   # for SSE; omit for JSON
)
```

**A runtime supports either IAM SigV4 or JWT inbound auth — not both simultaneously.** Create separate runtime versions for different auth types. For the full JWT inbound auth setup (Cognito user pool, authorizer configuration, invoke example), see [gateway-identity.md](gateway-identity.md).

_Source: [Authenticate and authorize with Inbound Auth and Outbound Auth](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-oauth.html)_

#### 2. Mapping user/session to runtimeSessionId

`runtimeSessionId` must be **at least 33 characters**; requests with shorter IDs are rejected. `uuid.uuid4()` produces 36 characters and satisfies the minimum.

**AgentCore does not enforce user-to-session mapping.** Your backend must own that relationship:
- Generate a new session ID at the start of each user conversation; store the mapping server-side.
- Reuse the same session ID for all turns of that conversation — this routes all follow-up requests to the same microVM, preserving in-memory state.
- Never share a session ID across different authenticated users; doing so exposes their conversation context to each other.

```python
import uuid

# One session per conversation; regenerate for a new conversation
session_id = str(uuid.uuid4())   # 36 chars — satisfies >=33 requirement
```

_Source: [Use isolated sessions for agents](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-sessions.html)_

#### 3. Proxying the SSE response to the browser

When the agent's `@app.entrypoint` is an `async generator`, the runtime returns `Content-Type: text/event-stream`. The backend should stream the response body directly to the browser rather than buffering it:

```python
# Flask example — stream SSE from AgentCore Runtime to browser
from flask import Response, stream_with_context
import boto3, json

def invoke_and_stream(agent_arn, session_id, user_message):
    client = boto3.client('bedrock-agentcore', region_name='us-west-2')
    response = client.invoke_agent_runtime(
        agentRuntimeArn=agent_arn,
        runtimeSessionId=session_id,
        payload=json.dumps({"prompt": user_message}).encode(),
    )

    def generate():
        for line in response['response'].iter_lines(chunk_size=64):
            if line:
                yield line.decode('utf-8') + '\n\n'

    return Response(
        stream_with_context(generate()),
        content_type='text/event-stream',
        headers={'X-Accel-Buffering': 'no', 'Cache-Control': 'no-cache'},
    )
```

Key points:
- Check `response['contentType']` to distinguish SSE (`text/event-stream`) from JSON (`application/json`) before choosing a streaming vs. buffered path.
- Disable proxy buffering (`X-Accel-Buffering: no` for nginx; equivalent for other proxies) so chunks reach the browser immediately.
- Streaming connections have a **60-minute maximum duration** (separate from the 8-hour session lifetime).

_Source: [Stream agent responses (SSE)](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/response-streaming.html); [Invoke an AgentCore Runtime agent](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-invoke-agent.html)_

---

## Best practices

- **Use the AgentCore CLI (`@aws/agentcore`) for new projects** — The CLI scaffolds CDK infrastructure, handles ARM64 packaging, supports CodeZip and Container builds, provides local hot-reload dev server (`agentcore dev`), and wraps all SDK calls. Install with `npm install -g @aws/agentcore`. Use `npm install -g @aws/agentcore@preview` for Harness and other preview features. _Source: <https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-cli.html>_

- **Use CodeZip (direct code deploy) for rapid prototyping; switch to Container for production complexity** — CodeZip allows 25 new sessions/second vs 100/minute for containers, enables faster redeployment, and auto-patches the language runtime. Use containers when package size exceeds 250 MB compressed (750 MB uncompressed), you have existing container CI/CD pipelines, or need specialized system dependencies. A hybrid approach is common: CodeZip for prototyping, container for production. _Source: <https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-code-deploy.html>_

- **Always build container images as `linux/arm64`** — AgentCore Runtime requires ARM64 architecture. Building on x86 without `buildx` will produce `exec /bin/sh: exec format error` at runtime. Use `docker buildx build --platform linux/arm64` or build in CodeBuild. The AgentCore CLI handles this automatically for both CodeZip and Container build types. _Source: <https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-troubleshooting.html>_

- **Implement `/ping` with BOTH `status` and `time_of_last_update` fields** — The platform uses `time_of_last_update` to determine whether a `HealthyBusy` session is still actively working. Omitting this field causes the idle timeout to fire even when status is `HealthyBusy`, terminating sessions prematurely after 15 minutes of background work. The SDK task tracking handles this automatically via `add_async_task`/`complete_async_task`. _Source: <https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-long-run.html>_

- **Never perform blocking calls in the `@app.entrypoint` if using async background tasks** — The entrypoint and `/ping` health check share threads in single-threaded setups. A blocking invocation path stalls `/ping` health checks, causing the platform to deem the session unhealthy and terminate it. Use `threading.Thread` or `asyncio` for background work. _Source: <https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-long-run.html>_

- **Generate session IDs of at least 33 characters — one per user conversation** — AgentCore uses the `runtimeSessionId` for microVM sticky routing. IDs shorter than 33 characters are rejected. `uuid.uuid4()` produces 36 characters and satisfies the minimum. Using the same ID across different users is a security boundary violation — enforce user-to-session mapping in your backend. _Source: <https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-sessions.html>_

- **Always include the session header in follow-up requests** — Without the correct session header (`X-Amzn-Bedrock-AgentCore-Runtime-Session-Id` for HTTP/A2A/AG-UI; `Mcp-Session-Id` for MCP), requests may be routed to a new microVM, causing a cold start and losing all in-memory session context. Capture the session ID from the first response and propagate it. _Source: <https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-sessions.html>_

- **Scope IAM execution role to minimum required permissions; do not use CLI-generated policies in production** — The CLI creates broad development-friendly policies. In production, scope `Resource` fields to specific runtime ARNs and restrict `bedrock:InvokeModel` to specific model ARNs. MMDS provides execution role credentials to any code in the microVM, so over-permissioned roles are a lateral escalation risk. _Source: <https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-security-best-practices.html>_

- **Add `aws:SourceArn` and `aws:SourceAccount` to execution role trust policies (confused deputy prevention)** — Without these conditions, any AgentCore principal could assume your execution role. The Condition block limits which specific AgentCore resources can assume the role, preventing cross-account or cross-resource privilege escalation. Use the full runtime ARN in `aws:SourceArn` when possible instead of wildcards. _Source: <https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-security-best-practices.html>_

- **Use JWT bearer token authentication for end-user-facing agents; use IAM SigV4 for service-to-service** — JWT path (`GetWorkloadAccessTokenForJWT`) validates issuer, signature, and expiry against the IdP. The UserId path (`GetWorkloadAccessTokenForUserId` / `X-Amzn-Bedrock-AgentCore-Runtime-User-Id` header) treats the user ID as an opaque string with no cryptographic verification — only safe for dev or architectures that resolve identity upstream. Explicitly deny `GetWorkloadAccessTokenForUserId` in production where JWTs are available. _Source: <https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-security-best-practices.html>_

- **Deploy runtimes in VPC with private subnets + NAT for accessing private resources** — Public network mode does not provide access to private VPCs. For agents that call internal databases or APIs, configure VPC connectivity. Required interface VPC endpoints: ECR (`dkr` + `api`), CloudWatch Logs. Required S3 gateway endpoint eliminates NAT gateway data charges for image layer pulls. S3 Files and EFS file system mounts also require VPC mode. _Source: <https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-security-best-practices.html>_

- **Stop idle sessions explicitly with `stop_runtime_session()` to control costs** — Sessions remain alive (and billable) for up to 15 minutes of idle time by default. Calling `stop_runtime_session()` immediately after workflow completion avoids unnecessary charges from long `idleRuntimeSessionTimeout` values. _Source: <https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/getting-started-custom.html>_

- **Use custom endpoints to manage dev/staging/prod rollouts** — Create separate named endpoints (`dev`, `staging`, `prod`) pointing to specific versions. Update the prod endpoint only after validating in staging. The DEFAULT endpoint auto-tracks the latest version on every create/update, which can break production if not handled carefully. Max 10 endpoints per agent (adjustable via Service Quotas). _Source: <https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agent-runtime-versioning.html>_

- **Install minimum boto3 1.39.8+ / botocore 1.33.8+ before using AgentCore APIs** — Older boto3 versions raise `Unknown service: bedrock-agent-core-runtime` because the service model did not exist. This is the most common gotcha when first integrating via Python SDK. _Source: <https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-troubleshooting.html>_

- **Use `PYTHON_3_13` as the direct code deploy runtime identifier (recommended)** — `PYTHON_3_13` on Amazon Linux 2023 is the currently recommended runtime. `PYTHON_3_10` and `PYTHON_3_11` are both deprecating on 6/30/2026 and should be migrated. `PYTHON_3_14` is also available for forward compatibility. Always use the `SNAKE_CASE` identifier format (e.g., `PYTHON_3_13`, not `PYTHON3_12`). _Source: <https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-code-deploy-supported-runtimes.html>_

---

## Code

### Minimal Strands agent with BedrockAgentCoreApp

```python
# pip install bedrock-agentcore strands-agents strands-tools
import os
from strands import Agent
from strands_tools import file_read, file_write, editor

agent = Agent(tools=[file_read, file_write, editor])

from bedrock_agentcore.runtime import BedrockAgentCoreApp
app = BedrockAgentCoreApp()

@app.entrypoint
def agent_invocation(payload, context):
    """Handler for agent invocation.
    payload: dict deserialized from the POST /invocations body
    context.session_id: the runtimeSessionId from the caller
    """
    user_message = payload.get(
        "prompt",
        "No prompt found in input, please guide customer to create a json payload with prompt key"
    )
    result = agent(user_message)
    print("context:\n-------\n", context)
    print("result:\n*******\n", result)
    return {"result": result.message}

app.run()  # Starts HTTP server on 0.0.0.0:8080 serving /invocations and /ping
```

_Source: <https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/using-any-agent-framework.html>_

---

### LangGraph agent with BedrockAgentCoreApp

```python
# pip install bedrock-agentcore langchain-aws langgraph
from langchain.chat_models import init_chat_model
from typing_extensions import TypedDict
from typing import Annotated
from langgraph.graph import StateGraph, START
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from bedrock_agentcore.runtime import BedrockAgentCoreApp

app = BedrockAgentCoreApp()

class State(TypedDict):
    messages: Annotated[list, add_messages]

llm = init_chat_model(
    "us.anthropic.claude-3-5-haiku-20241022-v1:0",
    model_provider="bedrock_converse",
)

graph_builder = StateGraph(State)
# ... add nodes and edges ...
graph = graph_builder.compile()

@app.entrypoint
def agent_invocation(payload, context):
    tmp_msg = {"messages": [{"role": "user", "content": payload.get("prompt", "")}]}
    tmp_output = graph.invoke(tmp_msg)
    return {"result": tmp_output['messages'][-1].content}

app.run()
```

_Source: <https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/using-any-agent-framework.html>_

---

### Google ADK agent with BedrockAgentCoreApp

```python
# pip install bedrock-agentcore google-adk
from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools import google_search
from google.genai import types
import asyncio
import os

APP_NAME = "google_search_agent"
USER_ID = "user1234"

root_agent = Agent(
    model="gemini-2.0-flash",
    name="openai_agent",
    description="Agent to answer questions using Google Search.",
    instruction="I can answer your questions by searching the internet. Just ask me anything!",
    tools=[google_search]
)

async def setup_session_and_runner(user_id, session_id):
    session_service = InMemorySessionService()
    session = await session_service.create_session(
        app_name=APP_NAME, user_id=user_id, session_id=session_id
    )
    runner = Runner(agent=root_agent, app_name=APP_NAME, session_service=session_service)
    return session, runner

async def call_agent_async(query, user_id, session_id):
    content = types.Content(role='user', parts=[types.Part(text=query)])
    session, runner = await setup_session_and_runner(user_id, session_id)
    events = runner.run_async(user_id=user_id, session_id=session_id, new_message=content)
    async for event in events:
        if event.is_final_response():
            return event.content.parts[0].text

from bedrock_agentcore.runtime import BedrockAgentCoreApp
app = BedrockAgentCoreApp()

@app.entrypoint
def agent_invocation(payload, context):
    # context.session_id is the runtimeSessionId — reuse for ADK session continuity
    return asyncio.run(
        call_agent_async(
            payload.get("prompt", "what is Bedrock AgentCore Runtime?"),
            payload.get("user_id", USER_ID),
            context.session_id
        )
    )

app.run()
```

_Source: <https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/using-any-agent-framework.html>_

---

### Streaming response via async generator (SSE)

```python
# pip install bedrock-agentcore strands-agents
from strands import Agent
from bedrock_agentcore import BedrockAgentCoreApp

app = BedrockAgentCoreApp()
agent = Agent()

@app.entrypoint
async def agent_invocation(payload):
    """Async generator: each yielded value becomes an SSE data chunk.
    SDK automatically sets Content-Type: text/event-stream.
    """
    user_message = payload.get("prompt", "No prompt found")
    stream = agent.stream_async(user_message)
    async for event in stream:
        yield event  # SDK serializes each chunk to SSE format

if __name__ == "__main__":
    app.run()
```

_Source: <https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/response-streaming.html>_

---

### Async background task with /ping management

```python
# pip install bedrock-agentcore strands-agents
import threading
import time
from strands import Agent, tool
from bedrock_agentcore.runtime import BedrockAgentCoreApp

app = BedrockAgentCoreApp()

@tool
def start_background_task(duration: int = 5) -> str:
    """Start a task that runs in the background while ping reports HealthyBusy."""
    # Register task — SDK sets /ping to HealthyBusy automatically
    task_id = app.add_async_task("background_processing", {"duration": duration})

    def background_work():
        time.sleep(duration)                  # Simulate work
        app.complete_async_task(task_id)      # SDK reverts /ping to Healthy

    threading.Thread(target=background_work, daemon=True).start()
    return f"Started background task (ID: {task_id}) for {duration} seconds."

agent = Agent(tools=[start_background_task])

@app.entrypoint
def main(payload):
    """Main entrypoint — handles user messages."""
    user_message = payload.get("prompt", "Try: start_background_task(3)")
    return {"message": agent(user_message).message}

if __name__ == "__main__":
    app.run()
```

_Source: <https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-long-run.html>_

---

### Custom /ping handler (low-level)

```python
from bedrock_agentcore.runtime import BedrockAgentCoreApp, PingStatus

app = BedrockAgentCoreApp()

_busy = False  # Managed by your own logic

@app.ping
def custom_status():
    """Override the default /ping handler.
    Must return PingStatus.HEALTHY or PingStatus.HEALTHY_BUSY.
    The SDK fills in time_of_last_update automatically.
    """
    if _busy:
        return PingStatus.HEALTHY_BUSY
    return PingStatus.HEALTHY

@app.entrypoint
def invoke(payload, context):
    global _busy
    _busy = True
    # ... do work ...
    _busy = False
    return {"done": True}

if __name__ == "__main__":
    app.run()
```

_Source: <https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-long-run.html>_

---

### Bidirectional WebSocket handler

```python
# pip install bedrock-agentcore
from bedrock_agentcore import BedrockAgentCoreApp

app = BedrockAgentCoreApp()

@app.websocket
async def websocket_handler(websocket, context):
    """Echo WebSocket handler. Registered at /ws on port 8080 automatically."""
    await websocket.accept()
    try:
        data = await websocket.receive_json()
        await websocket.send_json({"echo": data})
    except Exception as e:
        print(f"Error: {e}")
    finally:
        await websocket.close()

if __name__ == "__main__":
    app.run(log_level="info")
```

_Source: <https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-websocket.html>_

---

### WebSocket client with SigV4 headers

```python
# pip install bedrock-agentcore websockets
# IAM action required: bedrock-agentcore:InvokeAgentRuntimeWithWebSocketStream
from bedrock_agentcore.runtime import AgentCoreRuntimeClient
import websockets
import asyncio
import json
import os

async def main():
    runtime_arn = os.getenv('AGENT_ARN')
    if not runtime_arn:
        raise ValueError("AGENT_ARN environment variable is required")

    client = AgentCoreRuntimeClient(region="us-west-2")

    # Returns (wss_url, signed_headers) tuple
    ws_url, headers = client.generate_ws_connection(runtime_arn=runtime_arn)

    try:
        async with websockets.connect(ws_url, additional_headers=headers) as ws:
            await ws.send(json.dumps({"inputText": "Hello!"}))
            response = await ws.recv()
            print(f"Received: {response}")
    except websockets.exceptions.InvalidStatus as e:
        print(f"Handshake failed: {e.response.status_code}")
        print(f"Body: {e.response.body.decode()}")

if __name__ == "__main__":
    asyncio.run(main())
```

_Source: <https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-websocket.html>_

---

### WebSocket client with SigV4 pre-signed URL

```python
# pip install bedrock-agentcore websockets
from bedrock_agentcore.runtime import AgentCoreRuntimeClient
import websockets
import asyncio
import json
import os

async def main():
    runtime_arn = os.getenv('AGENT_ARN')
    client = AgentCoreRuntimeClient(region="us-west-2")

    # Generates pre-signed WSS URL (SigV4 via query parameters, valid 5 minutes)
    # wss://bedrock-agentcore.<region>.amazonaws.com/runtimes/<arn>/ws?X-Amz-Algorithm=...
    presigned_url = client.generate_presigned_url(
        runtime_arn=runtime_arn,
        expires=300  # seconds
    )

    async with websockets.connect(presigned_url) as ws:
        await ws.send(json.dumps({"inputText": "Hello pre-signed!"}))
        response = await ws.recv()
        print(f"Received: {response}")

if __name__ == "__main__":
    asyncio.run(main())
```

_Source: <https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-websocket.html>_

---

### Custom FastAPI agent (no SDK)

```python
# pip install fastapi uvicorn strands-agents
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Dict, Any
from datetime import datetime
from strands import Agent
import time

app = FastAPI(title="Strands Agent Server", version="1.0.0")
strands_agent = Agent()

class InvocationRequest(BaseModel):
    input: Dict[str, Any]

@app.post("/invocations")
async def invoke_agent(request: InvocationRequest):
    user_message = request.input.get("prompt", "")
    if not user_message:
        raise HTTPException(status_code=400, detail="Missing prompt")
    result = strands_agent(user_message)
    return {
        "output": {
            "message": result.message,
            "timestamp": datetime.utcnow().isoformat()
        }
    }

@app.get("/ping")
async def ping():
    # Full /ping contract for production (required if using async tasks):
    # status must be 'Healthy' or 'HealthyBusy' (case-sensitive)
    # time_of_last_update must be present for HealthyBusy to suppress idle timeout
    return {"status": "Healthy", "time_of_last_update": int(time.time())}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
```

_Source: <https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/getting-started-custom.html>_

---

### ARM64 Dockerfile

```dockerfile
# Required: linux/arm64 platform
FROM --platform=linux/arm64 ghcr.io/astral-sh/uv:python3.11-bookworm-slim

WORKDIR /app

# Copy uv files
COPY pyproject.toml uv.lock ./

# Install dependencies (including strands-agents)
RUN uv sync --frozen --no-cache

# Copy agent file
COPY agent.py ./

# Expose port
EXPOSE 8080

# Run application
CMD ["uv", "run", "uvicorn", "agent:app", "--host", "0.0.0.0", "--port", "8080"]
```

_Source: <https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/getting-started-custom.html>_

---

### Build and push ARM64 image to ECR

```bash
# Set up buildx for cross-platform builds
docker buildx create --use

# Build for ARM64 and test locally with AWS credentials
docker buildx build --platform linux/arm64 -t my-agent:arm64 --load .

docker run --platform linux/arm64 -p 8080:8080 \
  -e AWS_ACCESS_KEY_ID="$AWS_ACCESS_KEY_ID" \
  -e AWS_SECRET_ACCESS_KEY="$AWS_SECRET_ACCESS_KEY" \
  -e AWS_SESSION_TOKEN="$AWS_SESSION_TOKEN" \
  -e AWS_REGION="$AWS_REGION" \
  my-agent:arm64

# Create ECR repository
aws ecr create-repository --repository-name my-strands-agent --region us-west-2

# Login
aws ecr get-login-password --region us-west-2 | \
  docker login --username AWS --password-stdin account-id.dkr.ecr.us-west-2.amazonaws.com

# Build and push
docker buildx build --platform linux/arm64 \
  -t account-id.dkr.ecr.us-west-2.amazonaws.com/my-strands-agent:latest --push .
```

_Source: <https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/getting-started-custom.html>_

---

### Create AgentCore Runtime — container deployment

```python
import boto3

# Control plane client (creates/manages runtimes)
client = boto3.client('bedrock-agentcore-control', region_name='us-west-2')

response = client.create_agent_runtime(
    agentRuntimeName='strands_agent',
    agentRuntimeArtifact={
        'containerConfiguration': {
            'containerUri': 'account-id.dkr.ecr.us-west-2.amazonaws.com/my-strands-agent:latest'
        }
        # For direct code deploy use codeConfiguration instead (see next snippet)
    },
    networkConfiguration={"networkMode": "PUBLIC"},  # or 'VPC'
    roleArn='arn:aws:iam::account-id:role/AgentRuntimeRole',
    lifecycleConfiguration={
        'idleRuntimeSessionTimeout': 300,   # seconds; default 900 (15 min)
        'maxLifetime': 1800                 # seconds; max 28800 (8 hours)
    },
    # Optional: persistent session storage (Preview)
    # filesystemConfigurations=[{
    #     'sessionStorage': {'mountPath': '/mnt/workspace'}
    # }],
)

print("Runtime ARN:", response['agentRuntimeArn'])
print("Status:", response['status'])
```

_Source: <https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/getting-started-custom.html>_

---

### Create AgentCore Runtime — direct code (ZIP) deployment

```python
import boto3

account_id = "your-aws-account-id"
agent_name = "my_strands_agent"
region = "us-west-2"

# Step 1: Upload ZIP to S3
s3_client = boto3.client('s3', region_name=region)
s3_client.upload_file(
    'deployment_package.zip',
    f"bedrock-agentcore-code-{account_id}-{region}",   # bucket name
    f"{agent_name}/deployment_package.zip",             # S3 key (prefix)
    ExtraArgs={'ExpectedBucketOwner': account_id}
)

# Step 2: Create the runtime using codeConfiguration
agentcore_client = boto3.client('bedrock-agentcore-control', region_name=region)
response = agentcore_client.create_agent_runtime(
    agentRuntimeName=agent_name,
    agentRuntimeArtifact={
        'codeConfiguration': {
            'code': {
                's3': {
                    'bucket': f"bedrock-agentcore-code-{account_id}-{region}",
                    'prefix': f"{agent_name}/deployment_package.zip"
                }
            },
            'runtime': 'PYTHON_3_13',          # Also: PYTHON_3_14, PYTHON_3_12, NODE_22
            'entryPoint': ['main.py']          # or ['opentelemetry-instrument', 'main.py'] with OTEL
        }
    },
    networkConfiguration={"networkMode": "PUBLIC"},
    roleArn=f"arn:aws:iam::{account_id}:role/AmazonBedrockAgentCoreSDKRuntime-{region}",
    lifecycleConfiguration={
        'idleRuntimeSessionTimeout': 300,
        'maxLifetime': 1800
    },
)
print(f"Agent Runtime ARN: {response['agentRuntimeArn']}")
print(f"Status: {response['status']}")
```

_Source: <https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-code-deploy-python.html>_

---

### Build ARM64-compatible ZIP package for direct code deploy

```bash
# Install arm64-compatible wheels using uv
uv pip install \
  --python-platform aarch64-manylinux2014 \
  --python-version 3.13 \
  --target=deployment_package \
  --only-binary=:all: \
  -r pyproject.toml

# Create ZIP with libraries
cd deployment_package
zip -r ../deployment_package.zip .

# Add your agent entry point to the root of the ZIP
cd ..
zip deployment_package.zip main.py

# Verify size limits: compressed max 250 MB, uncompressed max 750 MB
ls -lh deployment_package.zip
```

_Source: <https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-code-deploy-python.html>_

---

### Invoke a deployed agent (data plane)

```python
import boto3
import json
import uuid

# Data plane client (invokes agents)
agent_core_client = boto3.client('bedrock-agentcore', region_name='us-west-2')

agent_arn = 'arn:aws:bedrock-agentcore:us-west-2:account-id:runtime/myAgent-suffix'
# Session ID must be >= 33 characters; reuse across turns for same conversation
session_id = str(uuid.uuid4())  # uuid4 gives 36 chars — satisfies the minimum

# First invocation
response = agent_core_client.invoke_agent_runtime(
    agentRuntimeArn=agent_arn,
    runtimeSessionId=session_id,
    payload=json.dumps({"prompt": "Tell me about Amazon Bedrock"}).encode(),
    qualifier='DEFAULT',  # optional; defaults to DEFAULT endpoint
)

# Correct pattern: response['response'] is a StreamingBody; call .read()
response_body = response['response'].read()
result = json.loads(response_body)
print(result)

# Follow-up using same session_id maintains conversation context
response2 = agent_core_client.invoke_agent_runtime(
    agentRuntimeArn=agent_arn,
    runtimeSessionId=session_id,
    payload=json.dumps({"prompt": "What models does it support?"}).encode(),
)
print(json.loads(response2['response'].read()))
```

_Source: <https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-cli.html>_

---

### Stop a runtime session explicitly

```python
import boto3

client = boto3.client('bedrock-agentcore', region_name='us-west-2')

response = client.stop_runtime_session(
    agentRuntimeArn='arn:aws:bedrock-agentcore:us-west-2:account-id:runtime/agent-name-suffix',
    runtimeSessionId='your-session-id-at-least-33-chars',
    qualifier='DEFAULT'
)
print(response)
```

_Source: <https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/getting-started-custom.html>_

---

### Update endpoint to a new version

```python
import boto3

# Control-plane client required — update_agent_runtime_endpoint is a control-plane operation
client = boto3.client('bedrock-agentcore-control', region_name='us-west-2')

# Point a named endpoint to a specific version
# Note: update_agent_runtime_endpoint takes agentRuntimeId (not ARN)
response = client.update_agent_runtime_endpoint(
    agentRuntimeId='agent-runtime-12345',
    endpointName='production-endpoint',
    agentRuntimeVersion='v2.1',
    description='Rolled out v2.1 to production after staging validation'
)
print(response)
```

_Source: <https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agent-runtime-versioning.html>_

---

### Execution role trust policy with confused-deputy prevention

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "bedrock-agentcore.amazonaws.com"
      },
      "Action": "sts:AssumeRole",
      "Condition": {
        "StringEquals": {
          "aws:SourceAccount": "123456789012"
        },
        "ArnLike": {
          "aws:SourceArn": "arn:aws:bedrock-agentcore:us-east-1:123456789012:*"
        }
      }
    }
  ]
}
```

_Source: <https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-security-best-practices.html>_

---

### Minimal direct-deploy execution role policy

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["logs:DescribeLogStreams", "logs:CreateLogGroup"],
      "Resource": ["arn:aws:logs:us-east-1:123456789012:log-group:/aws/bedrock-agentcore/runtimes/*"]
    },
    {
      "Effect": "Allow",
      "Action": ["logs:DescribeLogGroups"],
      "Resource": ["arn:aws:logs:us-east-1:123456789012:log-group:*"]
    },
    {
      "Effect": "Allow",
      "Action": ["logs:CreateLogStream", "logs:PutLogEvents"],
      "Resource": ["arn:aws:logs:us-east-1:123456789012:log-group:/aws/bedrock-agentcore/runtimes/*:log-stream:*"]
    },
    {
      "Effect": "Allow",
      "Action": [
        "xray:PutTraceSegments",
        "xray:PutTelemetryRecords",
        "xray:GetSamplingRules",
        "xray:GetSamplingTargets"
      ],
      "Resource": ["*"]
    },
    {
      "Effect": "Allow",
      "Action": "cloudwatch:PutMetricData",
      "Resource": "*",
      "Condition": {"StringEquals": {"cloudwatch:namespace": "bedrock-agentcore"}}
    },
    {
      "Sid": "BedrockModelInvocation",
      "Effect": "Allow",
      "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
      "Resource": [
        "arn:aws:bedrock:*::foundation-model/*",
        "arn:aws:bedrock:us-east-1:123456789012:*"
      ]
    }
  ]
}
```

_Source: <https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-permissions.html>_

---

### AgentCore CLI quickstart commands

```bash
# Install CLI (requires Node.js 20+ and AWS CDK)
npm install -g @aws/agentcore

# For Harness and other preview features
npm install -g @aws/agentcore@preview

# Create project non-interactively (all flags)
agentcore create --name MyAgent --framework Strands --protocol HTTP \
  --model-provider Bedrock --memory none --build CodeZip

# Or accept all defaults
agentcore create --name MyAgent --defaults

# Interactive wizard
agentcore create

# Local dev server with hot reload + browser inspector (port 8080)
cd MyAgent && agentcore dev

# Dev server without browser (terminal TUI)
agentcore dev --no-browser

# Dev server on a different port
agentcore dev -p 3000

# Invoke local dev server
agentcore dev "Hello, tell me a joke"

# Deploy to AWS via CDK
agentcore deploy

# Preview changes without deploying
agentcore deploy --plan

# Verbose deploy
agentcore deploy -v

# Invoke deployed agent
agentcore invoke "Tell me a joke"
agentcore invoke --prompt "Tell me a joke" --stream
agentcore invoke --session-id my-session "What else?"

# Stream logs
agentcore logs
agentcore logs --since 30m --level error

# View traces
agentcore traces list
agentcore traces get <trace-id>

# Status dashboard
agentcore status

# Add capabilities
agentcore add agent --name SecondAgent --language Python --framework Strands
agentcore add memory --name MyMemory --strategies SEMANTIC
agentcore add credential --name MyApiKey --type api-key --api-key your-api-key
agentcore add harness  # Harness (preview)

# Validate config
agentcore validate

# Tear down
agentcore remove all && agentcore deploy
```

_Source: <https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-cli.html>_

---

### AgentCore Harness — invoke via boto3 (Preview)

> **WARNING: PUBLIC PREVIEW** — Available only in `us-east-1`, `us-west-2`, `eu-central-1`, `ap-southeast-2`.

```python
# pip install boto3>=1.39.8
# Requires: preview regions only (us-east-1, us-west-2, eu-central-1, ap-southeast-2)
# IAM action: bedrock-agentcore:InvokeHarness
import boto3

client = boto3.client("bedrock-agentcore", region_name="us-west-2")

# invoke_harness streams events; default model is claude-sonnet-4-6
response = client.invoke_harness(
    harnessArn="arn:aws:bedrock-agentcore:us-west-2:123456789012:harness/MyHarness-XyZ123",
    runtimeSessionId="1234abcd-12ab-34cd-56ef-1234567890ab",  # min 33 chars
    messages=[{
        "role": "user",
        "content": [{"text": "Research three tropical vacation options under $3k."}]
    }],
    # Optional per-invocation overrides (do not change harness defaults permanently):
    # model={"bedrockModelConfig": {"modelId": "us.anthropic.claude-opus-4-5-20251101-v1:0"}},
    # systemPrompt=[{"text": "You are a terse research assistant."}],
)

# Consume the streaming response
for event in response["stream"]:
    if "contentBlockDelta" in event:
        delta = event["contentBlockDelta"].get("delta", {})
        if "text" in delta:
            print(delta["text"], end="", flush=True)
    elif "messageStop" in event:
        print(f"\nStop reason: {event['messageStop']['stopReason']}")
    elif "runtimeClientError" in event:
        print(f"\nError: {event['runtimeClientError']['message']}")
```

_Source: <https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/harness-get-started.html>_

---

### Configure persistent session storage (filesystemConfigurations)

```python
import boto3

client = boto3.client('bedrock-agentcore-control', region_name='us-west-2')

# Option 1: Managed session storage (Preview) — no VPC required, per-session isolated
# 1 GB max, survives stop/resume, resets after 14 days idle or version update
response = client.create_agent_runtime(
    agentRuntimeName='agent-with-session-storage',
    agentRuntimeArtifact={...},
    networkConfiguration={"networkMode": "PUBLIC"},
    roleArn='arn:aws:iam::account-id:role/AgentRuntimeRole',
    filesystemConfigurations=[
        {'sessionStorage': {'mountPath': '/mnt/workspace'}}
    ]
)

# Option 2: BYO Amazon EFS (shared across sessions, VPC required)
# Also requires elasticfilesystem:ClientMount + ClientWrite on the execution role
# and TCP 2049 outbound to EFS mount target security group
response2 = client.create_agent_runtime(
    agentRuntimeName='agent-with-efs',
    agentRuntimeArtifact={...},
    networkConfiguration={"networkMode": "VPC"},
    roleArn='arn:aws:iam::account-id:role/AgentRuntimeRole',
    filesystemConfigurations=[
        {'efsAccessPoint': {
            'accessPointArn': 'arn:aws:elasticfilesystem:us-west-2:account-id:access-point/fsap-xxx',
            'mountPath': '/mnt/efs'
        }}
    ]
)

# Option 3: Combine up to 5 configurations
# filesystemConfigurations=[
#     {'sessionStorage': {'mountPath': '/mnt/workspace'}},
#     {'efsAccessPoint': {'accessPointArn': '...', 'mountPath': '/mnt/shared'}}
# ]
```

_Source: <https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-filesystem-configurations.html>_

---

## Configuration reference

| Name | Description | Default / example |
|---|---|---|
| `PORT` | HTTP server port inside the container. Must be 8080 for HTTP, WebSocket (`/ws`), and AG-UI protocols. MCP uses port 8000. A2A uses port 9000. | `8080` (HTTP/WS/AG-UI), `8000` (MCP), `9000` (A2A) |
| `PLATFORM` | Container architecture. Must be `linux/arm64` for all container-based deployments. Direct code deploy (ZIP) handles this automatically via AWS-managed runtime environment. Max hardware: 2 vCPU / 8 GB RAM per session. | `linux/arm64` |
| `idleRuntimeSessionTimeout` | Seconds of idle (no active requests, Healthy ping) before a session is terminated. Configurable in `lifecycleConfiguration` when creating or updating a runtime. | `900` (15 minutes); configurable via `CreateAgentRuntime lifecycleConfiguration.idleRuntimeSessionTimeout` |
| `maxLifetime` | Maximum duration in seconds a microVM session can run before forced termination, regardless of activity. | `28800` (8 hours) maximum; configurable lower in `lifecycleConfiguration.maxLifetime` |
| `networkMode` | Network mode for the runtime. `PUBLIC` means internet-accessible. `VPC` requires subnet and security group IDs in the network configuration. VPC is required for EFS and S3 Files filesystem configurations. | `PUBLIC` or `VPC` |
| `qualifier` | Endpoint name used when invoking. Defaults to `DEFAULT` which tracks the latest version. Can point to named endpoints like `production` or `staging`. Max 10 endpoints per agent. | `DEFAULT` |
| `runtimeSessionId` | Session identifier, minimum 33 characters. Provided by the caller or auto-generated by runtime on first invocation if omitted. Reuse across turns for conversation continuity. | `str(uuid.uuid4())` — 36 chars, satisfies the 33-char minimum |
| `codeConfiguration.runtime` | Runtime identifier for direct code deploy. Must use `SCREAMING_SNAKE_CASE` format. Supported values: `PYTHON_3_14`, `PYTHON_3_13` (recommended), `PYTHON_3_12`, `PYTHON_3_11` (deprecating 6/30/2026), `PYTHON_3_10` (deprecating 6/30/2026), `NODE_22`. All run on Amazon Linux 2023. | `PYTHON_3_13` |
| `codeConfiguration.entryPoint` | Array of strings forming the command to start the agent. For plain Python: `['main.py']`. For OpenTelemetry-instrumented agents: `['opentelemetry-instrument', 'main.py']`. | `["main.py"]` |
| `codeConfiguration.code.s3.bucket` / `.prefix` | S3 location of the ZIP deployment package. `bucket` is the bucket name (not ARN); `prefix` is the full S3 key (path + filename). Use the nested `s3` object structure — NOT `s3Location.uri`. | `{"bucket": "bedrock-agentcore-code-<account>-<region>", "prefix": "<agent_name>/deployment_package.zip"}` |
| `X-Amzn-Bedrock-AgentCore-Runtime-Session-Id` (header) | HTTP header carrying the session ID for HTTP, A2A, and AG-UI protocols. Must be included in all follow-up requests for session affinity routing. Also readable inside the container via `context.session_id` in the SDK. | `X-Amzn-Bedrock-AgentCore-Runtime-Session-Id: <uuid>` |
| `Mcp-Session-Id` (header) | MCP protocol equivalent of the session header. Required for MCP stateful sessions. | `Mcp-Session-Id: <session-id>` |
| `bedrock-agentcore:InvokeAgentRuntime` (IAM action) | Required IAM permission to call `InvokeAgentRuntime` (HTTP/SSE). When using `X-Amzn-Bedrock-AgentCore-Runtime-User-Id` header, also requires `bedrock-agentcore:InvokeAgentRuntimeForUser`. | `bedrock-agentcore:InvokeAgentRuntime` |
| `bedrock-agentcore:InvokeAgentRuntimeWithWebSocketStream` (IAM action) | Required IAM permission to establish WebSocket connections to the `/ws` endpoint. | `bedrock-agentcore:InvokeAgentRuntimeWithWebSocketStream` |
| Package size limits | Direct code deploy: 250 MB compressed ZIP, 750 MB uncompressed. Container image: up to 2 GB. Session creation rate: direct deploy 25 TPS vs container 100 TPM. | 250 MB compressed / 750 MB uncompressed (ZIP); 2 GB (container) |
| Payload size limit | Maximum inbound payload to `/invocations` endpoint. Streaming chunk size limit is 10 MB. WebSocket frame size limit is 64 KB. | 100 MB (invocation payload); 10 MB (streaming chunk); 64 KB (WebSocket frame) |
| Active sessions quota | Maximum concurrent active session workloads per account per region. Higher in primary regions. | 1,000 in `us-east-1` and `us-west-2`; 500 in all other regions; adjustable via Service Quotas |
| Total agents per account | Maximum number of AgentCore Runtime resources per account per region. | 1,000 (adjustable via Service Quotas) |
| CloudWatch log group pattern | Standard log group where runtime logs are written. Used to diagnose 403 `RuntimeClientError` and other startup failures. | `/aws/bedrock-agentcore/runtimes/<agent_id>-DEFAULT/runtime-logs` |
| Minimum boto3/botocore versions | Minimum SDK versions with the `bedrock-agentcore` service model. Older versions raise `Unknown service` errors. | `boto3 >= 1.39.8`, `botocore >= 1.33.8` |
| Session storage limits | Managed session storage (Preview) per-session limits. | 1 GB max size; ~100,000–200,000 files (~50 MB metadata); 200 levels directory depth; 14-day idle expiry |
| VPC endpoints required (container agents in VPC) | Interface VPC endpoints to avoid internet traversal: `com.amazonaws.<region>.ecr.dkr`, `com.amazonaws.<region>.ecr.api`, `com.amazonaws.<region>.logs`. S3 gateway endpoint: `com.amazonaws.<region>.s3`. Also: `com.amazonaws.<region>.bedrock-agentcore` (data plane) and `com.amazonaws.<region>.bedrock-agentcore-control` (control plane). | `com.amazonaws.us-east-1.bedrock-agentcore`, `com.amazonaws.us-east-1.bedrock-agentcore-control` |

---

## Gotchas

- Container MUST be ARM64 (`linux/arm64`). Building on x86 without `docker buildx build --platform linux/arm64` produces `exec /bin/sh: exec format error` at runtime. There is no fallback to x86. The AgentCore CLI handles this automatically for both CodeZip and Container build types.

- `boto3 < 1.39.8` raises `Unknown service: bedrock-agent-core-runtime`. Run `pip install --upgrade boto3 botocore` before any SDK integration.

- The `/ping` endpoint MUST return both `status` AND `time_of_last_update` (Unix timestamp in seconds). Returning only `"status": "HealthyBusy"` without the timestamp causes the idle timer to fire anyway, killing long-running sessions after 15 minutes of background work.

- Never put blocking I/O in the `@app.entrypoint` if using the SDK's async task tracking. The ping and invocations share threads in single-threaded setups; a blocking entrypoint stalls `/ping` health checks and triggers unhealthy session termination.

- Session IDs shorter than 33 characters are rejected. `uuid.uuid4()` produces 36 characters and is safe to use directly.

- AgentCore does NOT enforce session-to-user mapping. Your backend must track which session IDs belong to which authenticated user. Using the same session ID for two different users exposes their context to each other.

- OAuth-integrated agents CANNOT be invoked via the AWS SDK / boto3. You must make a raw HTTPS request with the bearer token in the `Authorization` header. The SDK returns an error if you attempt it.

- `InvokeAgentRuntimeForUser` permission is required IN ADDITION TO `InvokeAgentRuntime` when passing the `X-Amzn-Bedrock-AgentCore-Runtime-User-Id` header. Missing this permission causes 403.

- The DEFAULT endpoint auto-updates to the latest version on every `CreateAgentRuntime`/`UpdateAgentRuntime` call. If your production traffic points to DEFAULT, a new deploy immediately affects production. Use named custom endpoints for stable prod targeting.

- Code changes to your agent are NOT reflected in existing sessions. Active microVMs run the image/code that was current when the session started. Only new sessions after redeployment pick up the new code.

- Docker 403 Forbidden when pulling from `public.ecr.aws` is caused by an expired ECR Public token. Fix: `docker logout public.ecr.aws` or re-login. Alternatively use Docker Hub base images.

- The `bedrock-agentcore-starter-toolkit` (`pip install bedrock-agentcore-starter-toolkit`) is LEGACY — superseded by the AgentCore CLI. The core SDK (`pip install bedrock-agentcore`) is NOT deprecated and is required for `BedrockAgentCoreApp`.

- MicroVM execution role credentials are accessible to ALL code in the VM via MMDS (similar to EC2 IMDS). Any library or tool loaded by the agent can call the metadata endpoint. Scope execution roles to minimum required permissions.

- The `codeConfiguration.code` field uses a nested `s3` object with `bucket` and `prefix` keys — NOT `s3Location.uri`. Using the wrong schema causes a validation error at `create_agent_runtime` time.

- `PYTHON_3_10` and `PYTHON_3_11` runtimes for direct code deploy are both scheduled for deprecation on **6/30/2026**. Migrate to `PYTHON_3_13` before that date to avoid disruption.

- Managed session storage (`filesystemConfigurations.sessionStorage`) is in Preview and resets to empty when the runtime version is updated (new container image or code package). Plan code rollouts to minimize state loss.

- The AgentCore Harness (`invoke_harness` API) is in public preview and only available in 4 regions: `us-east-1`, `us-west-2`, `eu-central-1`, `ap-southeast-2`. Attempting to use it in other regions will fail.

- Sessions do NOT resume with the same microVM after stopping. A subsequent invocation with the same `runtimeSessionId` creates a NEW microVM. Ephemeral in-memory state is lost unless you use AgentCore Memory or managed session storage.

- The `invoke_agent_runtime` response body is a `StreamingBody` object. Read it with `response['response'].read()` — not by iterating `response.get('response', [])` as a list, which is incorrect.

---

## Official sources

- [What is Amazon Bedrock AgentCore? (Overview)](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/what-is-bedrock-agentcore.html) — Service overview with all component descriptions and integration table
- [Host agent or tools with AgentCore Runtime](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agents-tools-runtime.html) — Runtime feature overview and links to all sub-topics
- [How it works (Runtime key concepts)](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-how-it-works.html) — Architecture: runtimes, versions, endpoints, sessions, auth
- [Understand the AgentCore Runtime service contract](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-service-contract.html) — Supported protocols (HTTP, MCP, A2A, AG-UI), port/path table, and links to each protocol spec
- [HTTP protocol contract (/invocations, /ping, /ws)](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-http-protocol-contract.html) — Detailed spec: port 8080, ARM64, /invocations POST, /ping GET, /ws WebSocket, SSE streaming, OAuth 401 behavior
- [Get started with the AgentCore CLI (full tutorial)](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-cli.html) — Step-by-step with all CLI flags, project structure, and invoke_agent.py code
- [Get started without the AgentCore CLI (custom agent / FastAPI)](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/getting-started-custom.html) — Manual path: FastAPI, Dockerfile ARM64, ECR push, boto3 create_agent_runtime, invoke, stop
- [Direct code deployment overview](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-code-deploy.html) — ZIP-based deployment vs container: session creation rates, size limits, shared responsibility
- [Direct code deployment for Python](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-code-deploy-python.html) — boto3 codeConfiguration schema, S3 upload, create_agent_runtime with codeConfiguration, entryPoint array, runtime identifiers
- [Supported language runtimes and deprecation policy](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-code-deploy-supported-runtimes.html) — Full table of runtime identifiers: PYTHON_3_10 through PYTHON_3_14, NODE_22, with deprecation dates
- [Use any agent framework (Strands, LangGraph, Google ADK, OpenAI)](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/using-any-agent-framework.html) — Copy-pasteable code for each framework using BedrockAgentCoreApp
- [Use isolated sessions for agents](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-sessions.html) — MicroVM lifecycle, session states, headers by protocol, ephemeral vs persistent storage
- [Handle asynchronous and long-running agents](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-long-run.html) — /ping contract details (Healthy / HealthyBusy), add_async_task / complete_async_task SDK methods
- [Stream agent responses (SSE)](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/response-streaming.html) — Async generator entrypoint pattern for SSE streaming
- [Get started with bidirectional streaming using WebSocket](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-websocket.html) — @app.websocket decorator, AgentCoreRuntimeClient, generate_ws_connection(), generate_presigned_url(), InvokeAgentRuntimeWithWebSocketStream IAM action
- [AgentCore Runtime versioning and endpoints](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agent-runtime-versioning.html) — Immutable versions, DEFAULT endpoint, update_agent_runtime_endpoint API
- [File system configurations for AgentCore Runtime](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-filesystem-configurations.html) — filesystemConfigurations parameter; session storage (Preview), S3 Files, EFS; up to 5 mounts; 1 GB session storage limit; 14-day idle expiry
- [IAM Permissions for AgentCore Runtime](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-permissions.html) — Full IAM policies for CLI user, console user, execution role (container and direct deploy)
- [Security best practices for AgentCore Runtime](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-security-best-practices.html) — 12 security domains: session isolation, IAM least privilege, confused deputy, network, encryption, auditing
- [Troubleshoot AgentCore Runtime](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-troubleshooting.html) — 504 timeouts, ARM64 build errors, boto3 version, 403 errors, CloudWatch log patterns, HTTP error codes
- [Quotas for Amazon Bedrock AgentCore](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/bedrock-agentcore-limits.html) — Full quota table: 1000 active sessions (us-east-1/us-west-2), 1000 agents/account, 25 TPS InvokeAgentRuntime, 100 TPM new sessions (container), 25 TPS new sessions (direct deploy), session storage 1 GB
- [AgentCore CLI (GitHub)](https://github.com/aws/agentcore-cli) — Source and issues for the @aws/agentcore npm CLI
- [Amazon Bedrock AgentCore Samples (GitHub)](https://github.com/awslabs/amazon-bedrock-agentcore-samples) — End-to-end examples per framework, including framework-specific subdirectories
- [Strands Agents — Deploy to Bedrock AgentCore Runtime](https://strandsagents.com/docs/user-guide/deploy/deploy_to_bedrock_agentcore/) — Strands-specific deployment guide including Python and TypeScript paths
- [bedrock-agentcore Python SDK (GitHub)](https://github.com/aws/bedrock-agentcore-sdk-python) — Source for bedrock-agentcore PyPI package, BedrockAgentCoreApp class, memory integrations
- [AgentCore Harness overview](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/harness.html) — Managed agent harness (Preview): config-based agent loop, no custom code needed, powered by Strands Agents
- [AgentCore Harness — Get started](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/harness-get-started.html) — CLI and boto3 paths; create-harness API, invoke_harness streaming response format, session ID requirements
- [AgentCore Harness — Configure agents and models](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/harness-config-and-models.html) — Default model claude-sonnet-4-6, override per invocation, multi-provider mid-session model switching
