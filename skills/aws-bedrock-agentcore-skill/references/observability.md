# Observability & Monitoring for AWS AI Agents

> Part of the **aws-bedrock-agentcore-skill** skill. See [SKILL.md](../SKILL.md) for the decision tree. Every source below is official — re-open it to verify details.

## Table of contents

- [Overview](#overview)
- [Key concepts](#key-concepts)
  - [AgentCore Observability](#agentcore-observability)
  - [GenAI Observability in CloudWatch](#genai-observability-in-cloudwatch)
  - [Sessions → Traces → Spans hierarchy](#sessions--traces--spans-hierarchy)
  - [AWS Distro for OpenTelemetry (ADOT)](#aws-distro-for-opentelemetry-adot)
  - [CloudWatch Transaction Search](#cloudwatch-transaction-search)
  - [OTEL Semantic Conventions GenAI](#otel-semantic-conventions-genai)
  - [CloudWatch namespaces for agents](#cloudwatch-namespaces-for-agents)
  - [StrandsTelemetry (Strands SDK Python)](#strandstelemetry-strands-sdk-python)
  - [Session ID propagation](#session-id-propagation)
  - [Cross-account observability](#cross-account-observability)
  - [Bedrock Agents Classic vs AgentCore tracing](#bedrock-agents-classic-vs-agentcore-tracing)
  - [DISABLE_ADOT_OBSERVABILITY](#disable_adot_observability)
- [Best practices](#best-practices)
- [Code](#code)
  - [Transaction Search setup via AWS CLI](#transaction-search-setup-via-aws-cli)
  - [Strands agent on AgentCore Runtime — zero-config OTEL](#strands-agent-on-agentcore-runtime--zero-config-otel)
  - [OTEL environment variables for non-runtime (self-hosted) agents](#otel-environment-variables-for-non-runtime-self-hosted-agents)
  - [StrandsTelemetry with OTLP exporter and session ID propagation](#strandstelemetry-with-otlp-exporter-and-session-id-propagation)
  - [Custom span inside a Strands agent](#custom-span-inside-a-strands-agent)
  - [Delivery source/destination for Memory and Gateway via boto3](#delivery-sourcedestination-for-memory-and-gateway-via-boto3)
  - [Langfuse integration with AgentCore Runtime (third-party, optional)](#langfuse-integration-with-agentcore-runtime-third-party-optional)
  - [CloudFormation for cross-account observability (OAM)](#cloudformation-for-cross-account-observability-oam)
  - [CloudWatch Alarms on latency and throttling](#cloudwatch-alarms-on-latency-and-throttling)
  - [Local Jaeger for development (optional)](#local-jaeger-for-development-optional)
  - [Bedrock Agents Classic with enableTrace (proprietary, not OTEL)](#bedrock-agents-classic-with-enabletrace-proprietary-not-otel)
- [Configuration reference](#configuration-reference)
- [Gotchas](#gotchas)
- [Official sources](#official-sources)

---

## Overview

Amazon Bedrock AgentCore Observability (GA since October 2025) provides end-to-end visibility into AI agents through three hierarchical levels: sessions, traces, and spans. Telemetry data is emitted in OpenTelemetry (OTEL) format and stored in Amazon CloudWatch under the namespace `bedrock-agentcore`. For agents hosted on AgentCore Runtime, OTEL instrumentation is automatic (zero-config); for self-hosted agents, manual configuration via AWS Distro for OpenTelemetry (ADOT) is required. The Strands Agents SDK exposes the `StrandsTelemetry` class (Python) to connect to any OTEL-compatible backend (CloudWatch/X-Ray, Langfuse, Jaeger, Datadog, Arize Phoenix). For third-party platforms on AgentCore Runtime, `DISABLE_ADOT_OBSERVABILITY=true` must be set before configuring a custom exporter. Relevant CloudWatch namespaces are `bedrock-agentcore` (AgentCore Runtime), `AWS/Bedrock/Agents` (classic Bedrock Agents), and `AWS/Bedrock` (model invocations). There is no additional cost for GenAI Observability — only standard CloudWatch pricing applies for ingested telemetry data.

**Maturity note.** GA: CloudWatch GenAI Observability (October 2025), AgentCore Observability (October 2025), AgentCore Runtime (GA), AgentCore Evaluations (GA since March 31, 2026). GA regions for Evaluations: us-east-1, us-east-2, us-west-2, ap-south-1, ap-southeast-1, ap-southeast-2, ap-northeast-1, eu-central-1, eu-west-1. _Source: https://aws.amazon.com/about-aws/whats-new/2026/03/agentcore-evaluations-generally-available/_ GA regions for all other AgentCore services: us-east-1, us-east-2, us-west-2, eu-central-1, eu-west-1, ap-south-1, ap-northeast-1, ap-southeast-1, ap-southeast-2.

---

## Key concepts

### AgentCore Observability

AWS service (GA) providing tracing, debugging, and monitoring of AI agents in production. Emits data in OpenTelemetry format and stores it in CloudWatch. Supports agents hosted on AgentCore Runtime (auto-instrumented via ADOT with no additional configuration) and non-runtime agents (manual ADOT configuration required). Data is viewable in the CloudWatch GenAI Observability dashboard. Coverage includes Agent Runtime, Memory, Gateway, Built-in Tools, Identity, and Policy.

### GenAI Observability in CloudWatch

Pre-configured dashboard in Amazon CloudWatch (console: `https://console.aws.amazon.com/cloudwatch/home#gen-ai-observability`) with three views:

- **Agents View** — fleet overview
- **Sessions View** — interactions per session
- **Traces View** — execution path with timeline

Includes graphs for latency, token usage, error rates, and cost attribution. Custom OTEL metrics emitted by agent code are published in Enhanced Metric Format (EMF) under the namespace `bedrock-agentcore`. Compatible with Strands, LangChain, and LangGraph.

### Sessions → Traces → Spans hierarchy

Three observability levels:

- **Session** — represents the entire user-agent conversation (with a unique ID) and maintains state and context across multiple exchanges.
- **Trace** — represents a single request-response cycle inside a session (includes tool calls, LLM calls, error paths).
- **Span** — the atomic unit of work inside a trace (with start/end timestamps, parent-child relationships, and contextual attributes).

Sessions contain multiple traces; each trace contains multiple spans.

### AWS Distro for OpenTelemetry (ADOT)

AWS distribution of OpenTelemetry. Python package: `aws-opentelemetry-distro>=0.10.0`. Activated via the command `opentelemetry-instrument python agent.py` or (Docker) `CMD ["opentelemetry-instrument", "python", "main.py"]`. Handles automatic export of traces, metrics, and logs to CloudWatch when `OTEL_*` environment variables are configured correctly. For AgentCore Runtime-hosted agents, ADOT is configured automatically by the runtime CLI with no additional configuration.

### CloudWatch Transaction Search

Feature that must be enabled once per account to visualize spans and traces. Requires:

1. Resource policy for `xray.amazonaws.com` on the `aws/spans` log group.
2. `aws xray update-trace-segment-destination --destination CloudWatchLogs`
3. (Optional) `aws xray update-indexing-rule` to configure the percentage of indexed spans.

The first 1% of spans is indexed for free. Spans available in log group `/aws/spans`. Wait 10 minutes after enabling. Verify with `aws xray get-trace-segment-destination` (expected: `"Status": "ACTIVE"`).

### OTEL Semantic Conventions GenAI

Standard OpenTelemetry attributes for AI telemetry:

| Attribute | Description |
|---|---|
| `gen_ai.system` | AI system identifier |
| `gen_ai.agent.name` | Agent name |
| `gen_ai.request.model` | Model used |
| `gen_ai.usage.input_tokens` | Input token count |
| `gen_ai.usage.output_tokens` | Output token count |
| `gen_ai.usage.total_tokens` | Total tokens |
| `gen_ai.usage.cache_read_input_tokens` | Cache-read input tokens |
| `gen_ai.usage.cache_write_input_tokens` | Cache-write input tokens |
| `gen_ai.tool.name` | Tool name |
| `gen_ai.tool.call.id` | Tool call identifier |
| `tool.status` | Tool execution status |

Enabled via `OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental,gen_ai_tool_definitions`. Used by Strands, LangChain, LangGraph, and the libraries OpenInference, Openllmetry, OpenLit, and Traceloop.

### CloudWatch namespaces for agents

Three distinct namespaces:

1. **`bedrock-agentcore`** — AgentCore Runtime metrics: `Invocations`, `Throttles`, `Latency`, `SessionCount`, `CPUUsed-vCPUHours`, `MemoryUsed-GBHours`.
2. **`AWS/Bedrock/Agents`** — Classic Bedrock Agents metrics: `InvocationCount`, `TotalTime`, `TTFT`, `InputTokenCount`, `outputTokenCount` (**note:** lowercase `o`), `ModelLatency`.
3. **`AWS/Bedrock`** — Model inference metrics: `InvocationLatency`, `TimeToFirstToken`, `CacheReadInputTokens`, `CacheWriteInputTokens`, `EstimatedTPMQuotaUsage`.

### StrandsTelemetry (Strands SDK Python)

Python class in `strands.telemetry` that manages OTEL configuration for Strands agents. Accepts a custom tracer provider: `StrandsTelemetry(tracer_provider=user_tracer_provider)`.

Key methods:

- `setup_otlp_exporter(**kwargs)` — sends traces to an OTLP endpoint.
- `setup_console_exporter(**kwargs)` — prints to console (useful in development).
- `setup_meter(enable_console_exporter, enable_otlp_exporter)` — configures meter provider.

The `trace_attributes` parameter in the `Agent` constructor propagates business attributes (`session.id`, `user.id`, `tags`) to all child spans automatically.

### Session ID propagation

To correlate traces across multiple runs of the same agent:

- **Via OTEL baggage (non-runtime agents):** `from opentelemetry import baggage; ctx = baggage.set_baggage('session.id', session_id); attach(ctx)`.
- **Via ADOT on AgentCore Runtime:** HTTP header `X-Amzn-Bedrock-AgentCore-Runtime-Session-Id` is propagated automatically.
- **Via Strands SDK:** `trace_attributes={'session.id': '...'}` in the `Agent` constructor.

### Cross-account observability

Via CloudWatch Observability Access Manager (OAM): create a sink in the monitoring account and links in source accounts. CloudFormation resources: `AWS::Oam::Sink` (with policy for org or specific accounts) and `AWS::Oam::Link`. Telemetry types to share: `AWS::Logs::LogGroup` and `AWS::CloudWatch::Metric` (both are required). Once configured, the AgentCore dashboard in the monitoring account shows data from all linked accounts.

**Limitation:** cross-account observability works only within the same AWS region.

### Bedrock Agents Classic vs AgentCore tracing

Classic Bedrock Agents (not AgentCore) have a separate proprietary tracing mechanism distinct from OTEL. By setting `enableTrace=True` on the `InvokeAgent` API, the response stream includes `TracePart` objects with `PreProcessingTrace`, `OrchestrationTrace`, `PostProcessingTrace`, `FailureTrace`, and `GuardrailTrace`. This mechanism does **not** use Transaction Search or OTEL spans. There is no OTEL drill-down equivalent for classic Bedrock Agents.

### DISABLE_ADOT_OBSERVABILITY

Officially documented environment variable for AgentCore Runtime. Setting `DISABLE_ADOT_OBSERVABILITY=true` causes the runtime to unset all default ADOT environment variables, allowing configuration of a custom OTEL backend (Langfuse, Datadog, Arize Phoenix, etc.) without conflicts. Must be passed in `env_vars` at runtime launch time — not as a local process variable in the setup script.

---

## Best practices

- **Enable CloudWatch Transaction Search as the first step and verify its status before any agent deploy.** Without Transaction Search enabled, spans and traces are not visible in the CloudWatch console. Requires one-time per-account configuration. Verify with `aws xray get-trace-segment-destination`: the response must show `"Status": "ACTIVE"`. Wait 10 minutes after enabling before sending the first trace. _Source: https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/Enable-TransactionSearch.html_

- **Use consistent, unique service names with `OTEL_RESOURCE_ATTRIBUTES=service.name=<agent-name>`.** `service.name` is the primary identifier in the GenAI Observability dashboard for distinguishing different agents. For non-runtime agents, also add `aws.log.group.names=<log-group>` for correct dashboard grouping. The field `cloud.resource_id=<AgentEndpointArn:AgentEndpointName>` is optional but improves correlation. _Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-configure.html_

- **Use consistent session IDs for multi-turn conversations of the same user.** The Session View in CloudWatch aggregates all traces with the same `session.id`. Without consistent session IDs it is impossible to see the complete conversational flow or troubleshoot specific sessions. Propagate via OTEL baggage (`baggage.set_baggage('session.id', ...)`) or via `trace_attributes` in the Strands `Agent` constructor. _Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-configure.html_

- **Use 100% head sampling + low span indexing (1–10%) for full visibility at controlled cost.** The AWS-documented approach is: head sampling at 100% (all trace spans ingested into CloudWatch Logs) + indexing at 1% (free) for trace summaries. This guarantees complete visibility over all spans while keeping CloudWatch costs low. Do not confuse head sampling with indexing — they are distinct levels. _Source: https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch-Transaction-Search-ingesting-spans.html_

- **Filter sensitive data from OTEL attributes before export.** Strands traces capture the full user prompt (`gen_ai.user.message`) and tool responses (`gen_ai.choice`). If the agent processes PII or confidential data, use CloudWatch Sensitive Data Protection on the log groups or sanitize attributes before export. _Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-get-started.html_

- **Configure CloudWatch Alarms on key metrics: `Throttles` (AgentCore namespace `bedrock-agentcore`), `SystemErrors`, Latency P99.** Alarms detect problems before they impact users. Priorities: throttling (indicates need to increase quota — `InvokeAgentRuntime` default is 25 TPS per agent, adjustable), system errors (AWS infrastructure), high P99 latency (bottleneck in model or tools). For classic Bedrock Agents (namespace `AWS/Bedrock/Agents`), the equivalent metric is `InvocationThrottles`. _Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-runtime-metrics.html_

- **For non-runtime agents, use `opentelemetry-instrument` as a wrapper command instead of modifying source code.** `opentelemetry-instrument python agent.py` auto-instruments Strands, Bedrock calls, tool invocations, and database calls without code changes. Simpler to maintain and upgrade-proof compared to manual instrumentation. ADOT handles correct context header propagation. _Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-get-started.html_

- **Use `trace_attributes` in the `Agent` constructor to add business context (`session.id`, `user.id`, `tags`).** Business attributes are propagated to all child spans automatically, enabling filtering and per-user/session/tenant analysis in the CloudWatch dashboard and third-party OTEL backends. The `tags` field accepts a list of strings. _Source: https://strandsagents.com/docs/user-guide/observability-evaluation/traces/_

- **For multi-account environments, configure OAM Sink/Link at the AWS Organization level.** The organization-wide approach with `aws:PrincipalOrgID` automatically onboards new accounts without manual intervention, reducing the risk of unmonitored agents in newly created accounts. Select both telemetry types: Metrics AND Logs (both are required for complete visibility). _Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-cross-account.html_

- **To integrate with third-party platforms (Langfuse, Datadog, Arize Phoenix), set `DISABLE_ADOT_OBSERVABILITY=true` in the runtime `env_vars` at launch.** `DISABLE_ADOT_OBSERVABILITY=true` is officially documented under "Using other observability platforms". It unsets the default AgentCore Runtime ADOT environment variables. Without this variable, custom OTEL configurations are silently overwritten. Must be passed in `env_vars` at runtime launch — not as a local setup script variable. _Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-configure.html_

- **Configure an explicit retention policy on the `/aws/spans` log group.** The `aws/spans` log group has indefinite retention by default (as do all CloudWatch log groups). On high-volume agents, storage costs can grow rapidly. Set an appropriate retention (e.g., 30 days) with `aws logs put-retention-policy --log-group-name aws/spans --retention-in-days 30`. _Source: https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch-Transaction-Search-ingesting-span-log-groups.html_

- **For Memory and Gateway, explicitly configure log destinations via the console or SDK.** Unlike Agent Runtime (which automatically creates a CloudWatch log group), Memory and Gateway do not automatically configure log destinations. The default path when configured via console is `/aws/vendedlogs/bedrock-agentcore/{resource-type}/APPLICATION_LOGS/{resource-id}`. For Memory, tracing must also be enabled separately in the Tracing panel. _Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-configure.html_

---

## Code

### Transaction Search setup via AWS CLI

One-time per-account prerequisite. Run all steps before deploying agents.

```bash
# Step 1: Grant X-Ray permission to write to CloudWatch Logs
aws logs put-resource-policy \
  --policy-name AgentCoreTransactionSearchPolicy \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Sid": "TransactionSearchXRayAccess",
      "Effect": "Allow",
      "Principal": {"Service": "xray.amazonaws.com"},
      "Action": "logs:PutLogEvents",
      "Resource": [
        "arn:aws:logs:us-east-1:123456789012:log-group:aws/spans:*",
        "arn:aws:logs:us-east-1:123456789012:log-group:/aws/application-signals/data:*"
      ],
      "Condition": {
        "ArnLike": {"aws:SourceArn": "arn:aws:xray:us-east-1:123456789012:*"},
        "StringEquals": {"aws:SourceAccount": "123456789012"}
      }
    }]
  }'

# Step 2: Configure trace segment destination to CloudWatch Logs
aws xray update-trace-segment-destination --destination CloudWatchLogs

# Step 3 (optional): Configure span indexing at 10%
# Note: the first 1% is free; head sampling is separate from indexing
aws xray update-indexing-rule \
  --name "Default" \
  --rule '{"Probabilistic": {"DesiredSamplingPercentage": 10}}'

# Step 4: Verify Transaction Search is active
aws xray get-trace-segment-destination
# Expected response: {"Destination": "CloudWatchLogs", "Status": "ACTIVE"}
# Wait 10 minutes before sending the first trace

# Step 5 (recommended): Set retention on the spans log group
aws logs put-retention-policy \
  --log-group-name aws/spans \
  --retention-in-days 30
```

_Source: https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/Enable-TransactionSearch.html_

---

### Strands agent on AgentCore Runtime — zero-config OTEL

AgentCore Runtime handles ADOT configuration automatically. No OTEL environment variables are needed in agent code.

```python
# requirements.txt:
# strands-agents
# bedrock-agentcore
# strands-tools

from strands import Agent, tool
from strands_tools import calculator
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands.models import BedrockModel
import json
import boto3

app = BedrockAgentCoreApp()

@tool
def weather():
    """Get weather"""
    return "sunny"

model = BedrockModel(
    model_id="us.anthropic.claude-3-7-sonnet-20250219-v1:0",  # use the model available in your account
)
agent = Agent(
    model=model,
    tools=[calculator, weather],
    system_prompt="You're a helpful assistant."
)

@app.entrypoint
def my_agent(payload):
    user_input = payload.get("prompt")
    response = agent(user_input)
    return response.message['content'][0]['text']

if __name__ == "__main__":
    app.run()

# Deploy (agentcore CLI manages OTEL automatically - zero config):
# npm install -g @aws/agentcore
# agentcore create --name MyAgent
# agentcore deploy
# agentcore invoke

# Or programmatic invocation with boto3:
client = boto3.client('bedrock-agentcore')
response = client.invoke_agent_runtime(
    agentRuntimeArn="YOUR_AGENT_RUNTIME_ARN",
    runtimeSessionId="my-observability-session-001",
    payload=json.dumps({"prompt": "What is 2 + 2?"}).encode(),
    qualifier="DEFAULT"
)
print(json.loads(response['response'].read()))
```

_Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-get-started.html_

---

### OTEL environment variables for non-runtime (self-hosted) agents

Full set of officially documented environment variables for agents not running on AgentCore Runtime.

```bash
# AWS credentials
export AWS_ACCOUNT_ID=123456789012
export AWS_DEFAULT_REGION=us-east-1
export AWS_REGION=us-east-1
export AWS_ACCESS_KEY_ID=AKIA...
export AWS_SECRET_ACCESS_KEY=...

# OTEL configuration ADOT
export AGENT_OBSERVABILITY_ENABLED=true          # Activates the ADOT pipeline
export OTEL_PYTHON_DISTRO=aws_distro             # Use AWS Distro for OTEL
export OTEL_PYTHON_CONFIGURATOR=aws_configurator # Required for ADOT Python
export OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
export OTEL_TRACES_EXPORTER=otlp

# Identifies the agent in the GenAI Observability dashboard
# cloud.resource_id is optional but improves correlation
export OTEL_RESOURCE_ATTRIBUTES="service.name=my-weather-agent,aws.log.group.names=/aws/bedrock-agentcore/runtimes/my-agent-id,cloud.resource_id=arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/my-agent-id:my-endpoint"

# Routes logs to the correct CloudWatch log group
export OTEL_EXPORTER_OTLP_LOGS_HEADERS="x-aws-log-group=/aws/bedrock-agentcore/runtimes/my-agent-id,x-aws-log-stream=runtime-logs,x-aws-metric-namespace=bedrock-agentcore"

# Run the agent with auto-instrumentation
opentelemetry-instrument python agent.py
```

_Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-configure.html_

---

### StrandsTelemetry with OTLP exporter and session ID propagation

```python
import os
from strands import Agent
from strands.telemetry import StrandsTelemetry
from strands_tools import http_request
from opentelemetry import baggage
from opentelemetry.context import attach

# Option A: configuration via env var (preferred in production)
os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "http://localhost:4318"
os.environ["OTEL_EXPORTER_OTLP_HEADERS"] = "key1=value1"
# For the most recent semantic conventions (includes tool definitions as spans)
os.environ["OTEL_SEMCONV_STABILITY_OPT_IN"] = "gen_ai_latest_experimental,gen_ai_tool_definitions"

# Option B: programmatic configuration
# Also supports custom providers: StrandsTelemetry(tracer_provider=my_provider)
strands_telemetry = StrandsTelemetry()
strands_telemetry.setup_otlp_exporter(
    endpoint="http://localhost:4318",
    headers={"key1": "value1"}
)
strands_telemetry.setup_console_exporter()  # useful in development
strands_telemetry.setup_meter(
    enable_console_exporter=False,
    enable_otlp_exporter=True
)

# Agent with business context on all spans
agent = Agent(
    model="us.anthropic.claude-3-7-sonnet-20250219-v1:0",
    system_prompt="You are a helpful assistant.",
    tools=[http_request],
    trace_attributes={
        "session.id": "session-abc-1234",
        "user.id": "user@example.com",
        "tags": ["production", "weather-agent"]
    }
)

# Propagate session ID via OTEL baggage (for non-runtime agents)
session_id = "session-abc-1234"
ctx = baggage.set_baggage("session.id", session_id)
token = attach(ctx)  # token needed for subsequent detach

response = agent("What's the weather in Seattle?")
print(response)
```

_Source: https://strandsagents.com/docs/user-guide/observability-evaluation/traces/_

---

### Custom span inside a Strands agent

```python
from opentelemetry import trace
from strands import Agent
from strands.telemetry import StrandsTelemetry

StrandsTelemetry().setup_otlp_exporter()

agent = Agent(
    model="us.anthropic.claude-3-7-sonnet-20250219-v1:0",
    system_prompt="You are a helpful assistant."
)

# The tracer uses the global provider configured by StrandsTelemetry
tracer = trace.get_tracer(__name__)

with tracer.start_as_current_span("my-business-workflow") as span:
    span.set_attribute("workflow.step", "data-retrieval")
    span.set_attribute("customer.id", "cust-456")
    
    # Agent spans become children of my-business-workflow
    response = agent("Analyze the quarterly report")
    
    span.set_attribute("workflow.result", "success")
    span.set_attribute("tokens.used", 1234)  # custom attributes
```

_Source: https://strandsagents.com/docs/user-guide/observability-evaluation/traces/_

---

### Delivery source/destination for Memory and Gateway via boto3

Memory and Gateway do not auto-configure log destinations. Use this pattern to set them up explicitly.

```python
import boto3

def enable_observability_for_resource(resource_arn, resource_id, account_id, region='us-east-1'):
    """
    Enables observability for AgentCore Memory or Gateway resources.
    For Agent Runtime, log destination configuration is optional
    (the runtime creates the log group automatically).
    Note: trace delivery (XRAY) applies only to Memory and Gateway resources.
    """
    logs_client = boto3.client('logs', region_name=region)

    # Step 0: Create log group for vended log delivery
    log_group_name = f'/aws/vendedlogs/bedrock-agentcore/{resource_id}'
    logs_client.create_log_group(logGroupName=log_group_name)
    log_group_arn = f'arn:aws:logs:{region}:{account_id}:log-group:{log_group_name}'

    # Step 1: Delivery source for APPLICATION_LOGS
    logs_source_response = logs_client.put_delivery_source(
        name=f"{resource_id}-logs-source",
        logType="APPLICATION_LOGS",
        resourceArn=resource_arn
    )

    # Step 2: Delivery source for TRACES
    traces_source_response = logs_client.put_delivery_source(
        name=f"{resource_id}-traces-source",
        logType="TRACES",
        resourceArn=resource_arn
    )

    # Step 3: Delivery destination for logs (CloudWatch Logs)
    logs_destination_response = logs_client.put_delivery_destination(
        name=f"{resource_id}-logs-destination",
        deliveryDestinationType='CWL',
        deliveryDestinationConfiguration={
            'destinationResourceArn': log_group_arn,
        }
    )

    # Step 3b: Delivery destination for traces (X-Ray)
    traces_destination_response = logs_client.put_delivery_destination(
        name=f"{resource_id}-traces-destination",
        deliveryDestinationType='XRAY'
    )

    # Step 4: Link sources to destinations
    logs_delivery = logs_client.create_delivery(
        deliverySourceName=logs_source_response['deliverySource']['name'],
        deliveryDestinationArn=logs_destination_response['deliveryDestination']['arn']
    )
    traces_delivery = logs_client.create_delivery(
        deliverySourceName=traces_source_response['deliverySource']['name'],
        deliveryDestinationArn=traces_destination_response['deliveryDestination']['arn']
    )

    print(f"Observability enabled for {resource_id}")
    return {
        'logs_delivery_id': logs_delivery['delivery']['id'],
        'traces_delivery_id': traces_delivery['delivery']['id']
    }

# Example usage for Memory
result = enable_observability_for_resource(
    resource_arn="arn:aws:bedrock-agentcore:us-east-1:123456789012:memory/my-memory-id",
    resource_id="my-memory-id",
    account_id="123456789012"
)
```

_Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-configure.html_

---

### Langfuse integration with AgentCore Runtime (third-party, optional)

> **Third-party / optional.** Langfuse is not an AWS service. The AWS-native path is CloudWatch (shown above). Use this only when you specifically need Langfuse as your OTEL backend.

```python
# requirements.txt:
# bedrock-agentcore   # deploy via the AgentCore CLI (npm i -g @aws/agentcore); the starter-toolkit is legacy
# strands-agents[otel]
# langfuse
# boto3

import os
import base64

# Step 1: Configure Langfuse credentials
os.environ["LANGFUSE_PUBLIC_KEY"] = "pk-lf-..."
os.environ["LANGFUSE_SECRET_KEY"] = "sk-lf-..."
os.environ["LANGFUSE_BASE_URL"] = "https://cloud.langfuse.com"  # or https://us.cloud.langfuse.com

# Step 2: Build the Basic authentication token (official method)
# Do NOT use private SDK methods like _get_basic_auth() — they may change without notice
langfuse_auth = base64.b64encode(
    f"{os.environ['LANGFUSE_PUBLIC_KEY']}:{os.environ['LANGFUSE_SECRET_KEY']}".encode()
).decode()

# Step 3: Configure OTEL endpoint to Langfuse
os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = os.environ["LANGFUSE_BASE_URL"] + "/api/public/otel"
os.environ["OTEL_EXPORTER_OTLP_HEADERS"] = (
    f"Authorization=Basic {langfuse_auth},"
    f"x-langfuse-ingestion-version=4"
)

# Step 4: Pass DISABLE_ADOT_OBSERVABILITY=true in AgentCore Runtime env vars
# This goes in env_vars at deploy/launch time (NOT as a local os.environ)
# Set it via the AgentCore CLI runtime config (or, with the bedrock-agentcore SDK, at launch):
# runtime.launch(
#     env_vars={
#         "DISABLE_ADOT_OBSERVABILITY": "true",
#         "OTEL_EXPORTER_OTLP_ENDPOINT": os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"],
#         "OTEL_EXPORTER_OTLP_HEADERS": os.environ["OTEL_EXPORTER_OTLP_HEADERS"],
#     }
# )

# Step 5: Configure StrandsTelemetry in agent code
from strands import Agent
from strands.models import BedrockModel
from strands.telemetry import StrandsTelemetry

strands_telemetry = StrandsTelemetry()
strands_telemetry.setup_otlp_exporter()

agent = Agent(
    model=BedrockModel(model_id="us.anthropic.claude-3-7-sonnet-20250219-v1:0"),
    system_prompt="You are a helpful assistant.",
    trace_attributes={
        "session.id": "session-001",
        "user.id": "user@example.com"
    }
)

response = agent("What is the capital of France?")
print(response)

# IMPORTANT: in short-lived apps (scripts, tests, Lambda), explicit flush to avoid data loss
# If using langfuse.get_client() for custom observations:
# from langfuse import get_client
# langfuse = get_client()
# langfuse.auth_check()
# ... use the client ...
# langfuse.flush()
```

_Source: https://langfuse.com/integrations/frameworks/amazon-agentcore_

---

### CloudFormation for cross-account observability (OAM)

```yaml
# monitoring-account-sink.yaml
# Option 1: Organization-wide (recommended - automatically onboards new accounts)
AWSTemplateFormatVersion: '2010-09-09'
Description: OAM Sink for cross-account AgentCore Observability (organization-wide)

Resources:
  ObservabilitySink:
    Type: AWS::Oam::Sink
    Properties:
      Name: AgentCoreObservabilitySink
      Policy:
        Version: '2012-10-17'
        Statement:
          - Effect: Allow
            Principal: '*'
            Action:
              - 'oam:CreateLink'
              - 'oam:UpdateLink'
            Resource: '*'
            Condition:
              StringEquals:
                aws:PrincipalOrgID: 'o-a1b2c3d4e5'  # Your AWS Organization ID
              ForAllValues:StringEquals:
                oam:ResourceTypes:
                  - 'AWS::Logs::LogGroup'
                  - 'AWS::CloudWatch::Metric'
      Tags:
        Purpose: AgentCoreObservability

Outputs:
  SinkArn:
    Value: !GetAtt ObservabilitySink.Arn
    Description: Distribute this ARN to source accounts to create links

---
# source-account-link.yaml (deploy via StackSets across all source accounts)
AWSTemplateFormatVersion: '2010-09-09'
Description: OAM Link for cross-account AgentCore Observability

Parameters:
  MonitoringAccountSinkArn:
    Type: String
    Description: ARN of the sink in the monitoring account

Resources:
  ObservabilityLink:
    Type: AWS::Oam::Link
    Properties:
      LabelTemplate: '$AccountName'
      ResourceTypes:
        - 'AWS::Logs::LogGroup'
        - 'AWS::CloudWatch::Metric'
      SinkIdentifier: !Ref MonitoringAccountSinkArn
      Tags:
        Purpose: AgentCoreObservability

# Limitation: cross-account observability works only within the same AWS region
```

_Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-cross-account.html_

---

### CloudWatch Alarms on latency and throttling

```python
import boto3

cw = boto3.client('cloudwatch', region_name='us-east-1')

# Alarm on P99 latency > 5 seconds for AgentCore Runtime
cw.put_metric_alarm(
    AlarmName='AgentCore-HighLatency-P99',
    AlarmDescription='Agent P99 latency exceeds 5 seconds',
    Namespace='bedrock-agentcore',
    MetricName='Latency',
    Dimensions=[
        {'Name': 'Service', 'Value': 'AgentCore.Runtime'},
        {'Name': 'Resource', 'Value': 'arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/my-agent'}
    ],
    Period=60,
    EvaluationPeriods=3,
    Threshold=5000,  # milliseconds
    ComparisonOperator='GreaterThanThreshold',
    ExtendedStatistic='p99',
    TreatMissingData='notBreaching',
    AlarmActions=['arn:aws:sns:us-east-1:123456789012:agent-alerts']
)

# Alarm on throttling for classic Bedrock Agents
cw.put_metric_alarm(
    AlarmName='BedrockAgents-ThrottlingHigh',
    AlarmDescription='Bedrock Agent throttling exceeds 10 in 5 minutes',
    Namespace='AWS/Bedrock/Agents',
    MetricName='InvocationThrottles',
    Dimensions=[
        {'Name': 'Operation', 'Value': 'InvokeAgent'}
    ],
    Period=300,
    EvaluationPeriods=1,
    Statistic='Sum',
    Threshold=10,
    ComparisonOperator='GreaterThanThreshold',
    TreatMissingData='notBreaching',
    AlarmActions=['arn:aws:sns:us-east-1:123456789012:agent-alerts']
)

# Alarm on token usage for cost control
# Note: OutputTokenCount uses uppercase O in AWS/Bedrock namespace
cw.put_metric_alarm(
    AlarmName='Bedrock-HighTokenUsage',
    AlarmDescription='Output tokens exceed 1M in 5 minutes',
    Namespace='AWS/Bedrock',
    MetricName='OutputTokenCount',
    Dimensions=[{'Name': 'ModelId', 'Value': 'anthropic.claude-3-7-sonnet-20250219-v1:0'}],
    Period=300,
    EvaluationPeriods=1,
    Statistic='Sum',
    Threshold=1000000,
    ComparisonOperator='GreaterThanThreshold',
    TreatMissingData='notBreaching',
    AlarmActions=['arn:aws:sns:us-east-1:123456789012:agent-alerts']
)
```

_Source: https://docs.aws.amazon.com/bedrock/latest/userguide/monitoring-agents-cw-metrics.html_

---

### Local Jaeger for development (optional)

Useful for visualizing traces during local development without needing CloudWatch.

```bash
# Start Jaeger all-in-one container
docker run -d --name jaeger \
  -e COLLECTOR_OTLP_ENABLED=true \
  -p 16686:16686 \
  -p 4317:4317 \
  -p 4318:4318 \
  jaegertracing/all-in-one:latest

# Configure Strands to send to local Jaeger
export OTEL_EXPORTER_OTLP_ENDPOINT="http://localhost:4318"

# Then in Python code:
# from strands.telemetry import StrandsTelemetry
# StrandsTelemetry().setup_otlp_exporter()

# View traces: http://localhost:16686
# Select the service name configured in OTEL_RESOURCE_ATTRIBUTES
# Jaeger is useful only for local development; in production use CloudWatch or a dedicated platform
```

_Source: https://strandsagents.com/docs/user-guide/observability-evaluation/traces/_

---

### Bedrock Agents Classic with enableTrace (proprietary, not OTEL)

This mechanism is **separate** from Transaction Search, OTEL, and AgentCore Observability. Classic Bedrock Agents do not emit OTEL spans.

```python
import boto3
import json

# CLASSIC Bedrock Agents (not AgentCore): use proprietary tracing via enableTrace,
# which is SEPARATE from Transaction Search / OTEL / AgentCore Observability.
# There are no OTEL spans for classic Bedrock Agents.

client = boto3.client('bedrock-agent-runtime', region_name='us-east-1')

response = client.invoke_agent(
    agentId='YOUR_AGENT_ID',
    agentAliasId='TSTALIASID',  # or your alias
    sessionId='my-session-123',
    inputText='What is the weather in Seattle?',
    enableTrace=True  # Enables trace in the response stream (proprietary mechanism)
)

# Iterate over the streaming response to extract text and traces
for event in response['completion']:
    if 'chunk' in event:
        text = event['chunk']['bytes'].decode('utf-8')
        print(f"Output: {text}")
    if 'trace' in event:
        trace_data = event['trace']
        # trace_data contains: agentId, sessionId, trace (PreProcessingTrace/
        # OrchestrationTrace/PostProcessingTrace/FailureTrace/GuardrailTrace)
        print(f"Trace type: {list(trace_data.get('trace', {}).keys())}")
        # Note: this trace JSON is distinct from AgentCore OTEL spans
```

_Source: https://docs.aws.amazon.com/bedrock/latest/userguide/trace-events.html_

---

## Configuration reference

| Name | Description | Default / example |
|---|---|---|
| `AGENT_OBSERVABILITY_ENABLED` | Activates the ADOT pipeline for non-runtime agents. Must be `true` to enable export of traces/metrics/logs to CloudWatch. | `true` |
| `OTEL_PYTHON_DISTRO` | Specifies the OTEL distribution to use. For AWS ADOT must be `aws_distro`. | `aws_distro` |
| `OTEL_PYTHON_CONFIGURATOR` | ADOT configurator for Python. Required only for ADOT Python (not Java/Node). | `aws_configurator` |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | Export protocol for OTLP. Use `http/protobuf` for CloudWatch compatibility. | `http/protobuf` |
| `OTEL_TRACES_EXPORTER` | Trace export destination. Use `otlp` for CloudWatch/OTEL backend. | `otlp` |
| `OTEL_RESOURCE_ATTRIBUTES` | OTEL resource attributes. Minimum: `service.name` to identify the agent in the dashboard. For non-runtime agents also add `aws.log.group.names`. Optional: `cloud.resource_id=<AgentEndpointArn:AgentEndpointName>` for improved correlation. | `service.name=my-agent,aws.log.group.names=/aws/bedrock-agentcore/runtimes/my-agent-id,cloud.resource_id=arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/my-agent-id:my-endpoint` |
| `OTEL_EXPORTER_OTLP_LOGS_HEADERS` | HTTP headers for the OTLP logs exporter. Used for routing to CloudWatch Logs by specifying log group, stream, and metric namespace. | `x-aws-log-group=/aws/bedrock-agentcore/runtimes/my-agent-id,x-aws-log-stream=runtime-logs,x-aws-metric-namespace=bedrock-agentcore` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP endpoint for trace/metric export. Default Strands SDK: `http://localhost:4318` if not specified. | `http://localhost:4318` (dev) \| `https://cloud.langfuse.com/api/public/otel` (Langfuse EU) \| `https://us.cloud.langfuse.com/api/public/otel` (Langfuse US) |
| `OTEL_SEMCONV_STABILITY_OPT_IN` | Enables the most recent OTEL GenAI semantic conventions. The value `gen_ai_tool_definitions` includes tool definitions in spans. | `gen_ai_latest_experimental,gen_ai_tool_definitions` |
| `OTEL_TRACES_SAMPLER` | Sampling strategy for traces. `traceidratio` allows specifying a percentage. Separate from Transaction Search span indexing (configured with `UpdateIndexingRule`). | `traceidratio` |
| `OTEL_TRACES_SAMPLER_ARG` | Argument for the sampler. With `traceidratio`: value between 0.0 and 1.0 (e.g., `0.1` = 10%). | `0.1` |
| `DISABLE_ADOT_OBSERVABILITY` | Officially documented under "Using other observability platforms". Set to `true` to disable default AgentCore Runtime ADOT env vars and use a custom OTEL backend without conflicts. Must be passed in `env_vars` at runtime launch. | `true` |
| `LANGFUSE_PUBLIC_KEY` | Langfuse project public key for OTEL integration. Required with `strands-agents[otel]` + langfuse. (Third-party/optional) | `pk-lf-...` |
| `LANGFUSE_SECRET_KEY` | Langfuse project secret key. (Third-party/optional) | `sk-lf-...` |
| `LANGFUSE_BASE_URL` | Regional Langfuse endpoint. Choose the correct region for data residency compliance. (Third-party/optional) | `https://cloud.langfuse.com` (EU) \| `https://us.cloud.langfuse.com` (US) |
| `IAM: cloudwatch:PutMetricData` (conditional on namespace) | The Bedrock agent service role must have `cloudwatch:PutMetricData` permission with condition `StringEquals cloudwatch:namespace=AWS/Bedrock/Agents` to publish metrics in the correct namespace. | `{"Action": "cloudwatch:PutMetricData", "Condition": {"StringEquals": {"cloudwatch:namespace": "AWS/Bedrock/Agents"}}}` |
| `IAM: logs:PutLogEvents` (for Transaction Search) | Resource policy on CloudWatch Logs required for `xray.amazonaws.com` to write spans to `aws/spans` and `/aws/application-signals/data` log groups. Additional IAM required to enable Transaction Search: `xray:UpdateTraceSegmentDestination`, `xray:UpdateIndexingRule`, `logs:PutRetentionPolicy`, `application-signals:StartDiscovery`. | `aws logs put-resource-policy --policy-name MyResourcePolicy --policy-document ...` |
| Log group paths — AgentCore Runtime | Standard logs (stdout/stderr): `/aws/bedrock-agentcore/runtimes/<agent_id>-<endpoint_name>/[runtime-logs] <UUID>`. OTEL structured logs: `/aws/bedrock-agentcore/runtimes/<agent_id>-<endpoint_name>/otel-rt-logs`. Spans: `/aws/spans`. Memory/Gateway (console default): `/aws/vendedlogs/bedrock-agentcore/{resource-type}/APPLICATION_LOGS/{resource-id}`. | `/aws/bedrock-agentcore/runtimes/my-agent-abc123-myendpoint/otel-rt-logs` |
| CloudWatch namespace `bedrock-agentcore` (AgentCore Runtime metrics) | Dimensions: `Service=AgentCore.Runtime`, `Resource=Agent ARN`, `Name=AgentName::EndpointName`. Metrics: `Invocations`, `Throttles`, `SystemErrors`, `UserErrors`, `Latency`, `SessionCount`, `ActiveStreamingConnections`, `InboundStreamingBytesProcessed`, `OutboundStreamingBytesProcessed`, `CPUUsed-vCPUHours`, `MemoryUsed-GBHours`. | `Namespace: bedrock-agentcore` |
| CloudWatch namespace `AWS/Bedrock/Agents` (classic Bedrock Agents) | Dimensions: `Operation`, `ModelId`, `AgentAliasArn`. Metrics: `InvocationCount`, `TotalTime`, `TTFT`, `InvocationThrottles`, `InvocationServerErrors`, `InvocationClientErrors`, `ModelLatency`, `ModelInvocationCount`, `ModelInvocationThrottles`, `ModelInvocationClientErrors`, `ModelInvocationServerErrors`, `InputTokenCount`, `outputTokenCount` (WARNING: lowercase `o` in the CloudWatch API). | `Namespace: AWS/Bedrock/Agents` |
| AgentCore Runtime invocation quota | `InvokeAgentRuntime`: 25 TPS per agent per account (adjustable via Service Quotas). Active session workloads: 1000 in us-east-1/us-west-2, 500 in other regions (adjustable). Maximum timeout for synchronous invocation: 15 minutes (not adjustable). Maximum payload: 100 MB. | `25 TPS per agent per account` |

---

## Gotchas

- **Transaction Search must be enabled BEFORE deploying agents.** If enabled after, already-generated traces are not retroactively indexed. Wait 10 minutes after enabling and verify with `aws xray get-trace-segment-destination` before sending the first trace.

- **`DISABLE_ADOT_OBSERVABILITY=true` is mandatory for third-party backends (Langfuse, Datadog, etc.) on AgentCore Runtime.** Without this variable, default AgentCore ADOT env vars silently overwrite custom OTEL configuration. Must be passed in `env_vars` at runtime launch time — not set in the local Python process.

- **The OTEL structured log group on AgentCore Runtime is `otel-rt-logs`, not `runtime-logs`.** Confusing the two paths leads to searching for data in the wrong place. Standard logs (stdout/stderr) go to `[runtime-logs] <UUID>`; OTEL structured logs go to `otel-rt-logs`.

- **For non-runtime agents, `OTEL_RESOURCE_ATTRIBUTES` must include `aws.log.group.names` with the AgentCore log group path.** This is the value the GenAI Observability dashboard uses to group the agent. Without this value the agent does not appear in the dashboard.

- **`EstimatedTPMQuotaUsage` in `AWS/Bedrock` is an explicit approximation and does NOT correspond to the quota consumption that drives throttling** (which is based on upfront reservation of input tokens + `max_tokens`). Official documentation explicitly warns against using it as the sole indicator for capacity planning.

- **Memory and Gateway do not automatically configure log destinations (unlike Agent Runtime).** Delivery must be explicitly enabled via the console or SDK (`put_delivery_source` + `put_delivery_destination` + `create_delivery`). For Memory, tracing must also be enabled separately.

- **For cross-account OAM, both telemetry types (Metrics AND Logs) must be selected in both the monitoring account and source accounts.** Selecting only one causes incomplete data in the dashboard. Additional limitation: cross-account observability works only within the same AWS region.

- **The metric `outputTokenCount` in `AWS/Bedrock/Agents` has a lowercase first letter (not `OutputTokenCount`).** Be careful about case sensitivity in CloudWatch Metrics queries, alarm filters, and CloudWatch APIs.

- **For non-Strands/LangChain/CrewAI agents, a separate instrumentation library may be needed** to emit valid OTEL GenAI semantic conventions (OpenInference, Openllmetry, OpenLit, or Traceloop).

- **`langfuse.flush()` is mandatory in short-lived applications (scripts, Lambda, tests).** Without explicit flush, observations may not be exported before process termination. (Third-party/optional — applies only when using Langfuse.)

- **The `/aws/spans` log group has indefinite retention by default.** On high-volume agents, storage costs can grow. Set explicit retention with `aws logs put-retention-policy --log-group-name aws/spans --retention-in-days <N>`.

- **AgentCore Evaluations (distinct from Observability) is now GA** (since March 31, 2026, available in 9 regions: us-east-1, us-east-2, us-west-2, ap-south-1, ap-southeast-1, ap-southeast-2, ap-northeast-1, eu-central-1, eu-west-1). _Source: https://aws.amazon.com/about-aws/whats-new/2026/03/agentcore-evaluations-generally-available/_

- **Classic Bedrock Agents (not AgentCore) do NOT use OTEL/Transaction Search for tracing.** Their mechanism is the `enableTrace=True` parameter on `InvokeAgent`, which returns proprietary trace JSON in the response stream. There is no OTEL drill-down equivalent for classic Bedrock Agents.

- **Langfuse authentication in the OTEL header must be constructed with `base64.b64encode(f'{PUBLIC_KEY}:{SECRET_KEY}'.encode()).decode()`.** Do not rely on private SDK methods such as `_get_basic_auth()`, which may change without notice. (Third-party/optional.)

- **Head sampling (100% trace capture) and span indexing (% for trace summaries in Transaction Search) are two DISTINCT and independent mechanisms.** It is possible and recommended to have 100% head sampling with 1% indexing (free) to maximize visibility at minimum cost.

---

## Official sources

- [Observe your agent applications on Amazon Bedrock AgentCore Observability](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability.html) — Main AgentCore Observability page: overview, links to all sub-topics (configure, telemetry, service-provided data, view, cross-account)
- [Get started with AgentCore Observability](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-get-started.html) — Step-by-step guide: enabling Transaction Search, configuring ADOT for runtime and non-runtime agents, complete environment variables, code examples, links to official GitHub notebooks
- [Add observability to your Amazon Bedrock AgentCore resources](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-configure.html) — Detailed ADOT SDK configuration, enabling Transaction Search via API, delivery sources/destinations with boto3, custom HTTP headers for enhanced tracing, section "Using other observability platforms" with DISABLE_ADOT_OBSERVABILITY
- [Understand observability for agentic resources in AgentCore (sessions/traces/spans)](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-telemetry.html) — Definitions and hierarchical relationships between sessions, traces, and spans; required attributes at each level
- [AgentCore generated runtime observability data](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-runtime-metrics.html) — Complete list of AgentCore runtime metrics: Invocations, Throttles, Latency, SessionCount, WebSocket metrics, CPU/Memory vended metrics, InvokeAgentRuntime span with all attributes, error types
- [Amazon Bedrock AgentCore generated observability data (overview per resource type)](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-service-provided.html) — Summary table: which resource type (Agent, Memory, Gateway, Tools, Policy) provides metrics/spans/logs and where they are visible (CloudWatch GenAI vs CloudWatch Logs)
- [View observability data for your Amazon Bedrock AgentCore agents](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-view.html) — How to navigate the CloudWatch GenAI dashboard: Agents View, Sessions View, Traces View; log group paths for standard and OTEL structured logs; OTEL metrics published in EMF format under namespace bedrock-agentcore
- [Generative AI observability (CloudWatch User Guide)](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/GenAI-observability.html) — Overview CloudWatch GenAI Observability: pre-built dashboards for Model Invocations and AgentCore agents, key metrics, compatibility with Strands/LangChain/LangGraph
- [Enable transaction search](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/Enable-TransactionSearch.html) — Complete procedure (console + API) for enabling Transaction Search; required IAM permissions; verifying status with GetTraceSegmentDestination; 1% of spans indexed for free
- [Ingesting spans for complete visibility](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch-Transaction-Search-ingesting-spans.html) — Head sampling vs span indexing; configuration of 100% head sampling + low indexing percentage for cost-effective approach; spans in log group aws/spans use standard CloudWatch Logs features
- [Spans log group](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch-Transaction-Search-ingesting-span-log-groups.html) — Features available for the aws/spans log group: Metric filters, Subscriptions, Log anomaly detection, Contributor Insights. Does NOT support direct PutLogEvents or log transformation.
- [Monitor AgentCore resources across accounts](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-cross-account.html) — Cross-account observability via CloudWatch OAM (Observability Access Manager): sink/link setup, CloudFormation templates, account filtering. Limitation: only within the same AWS region.
- [Monitor Amazon Bedrock Agents using CloudWatch Metrics](https://docs.aws.amazon.com/bedrock/latest/userguide/monitoring-agents-cw-metrics.html) — CloudWatch metrics for classic Bedrock Agents: namespace AWS/Bedrock/Agents, InvocationCount, TotalTime, TTFT, InputTokenCount, outputTokenCount (lowercase), dimensions Operation/ModelId/AgentAliasArn
- [Monitor bedrock-runtime inference using CloudWatch metrics](https://docs.aws.amazon.com/bedrock/latest/userguide/monitoring-runtime-metrics.html) — Namespace AWS/Bedrock metrics: InvocationLatency, TimeToFirstToken, InputTokenCount, OutputTokenCount, CacheReadInputTokens, CacheWriteInputTokens, EstimatedTPMQuotaUsage; official note that EstimatedTPMQuotaUsage is an approximation
- [Track agent's step-by-step reasoning process using trace (Bedrock Agents classic)](https://docs.aws.amazon.com/bedrock/latest/userguide/trace-events.html) — Native tracing mechanism for classic Bedrock Agents (not AgentCore): enableTrace=true on InvokeAgent returns TracePart in the response stream with PreProcessingTrace, OrchestrationTrace, PostProcessingTrace, FailureTrace, GuardrailTrace. Separate mechanism from OTEL/Transaction Search.
- [Amazon Bedrock AgentCore and AWS X-Ray](https://docs.aws.amazon.com/xray/latest/devguide/xray-services-agentcore.html) — AgentCore + X-Ray integration: context propagation via X-Amzn-Trace-Id header, custom ADOT SDK instrumentation. Requires Transaction Search enabled.
- [Quotas for Amazon Bedrock AgentCore](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/bedrock-agentcore-limits.html) — Complete quotas: Runtime 25 TPS per agent (adjustable), 1000 active session workloads per account (us-east-1/us-west-2), 500 other regions; 15-minute timeout, 100 MB payload, 8-hour max session
- [Strands Agents SDK - Traces documentation](https://strandsagents.com/docs/user-guide/observability-evaluation/traces/) — Official Strands SDK documentation: StrandsTelemetry class, setup_otlp_exporter(), setup_console_exporter(), trace_attributes, custom spans, full attribute table, CloudWatch X-Ray integration
- [Open Source Observability for Amazon Bedrock AgentCore - Langfuse](https://langfuse.com/integrations/frameworks/amazon-agentcore) — **Third-party / optional.** Official Langfuse + AgentCore integration: DISABLE_ADOT_OBSERVABILITY=true, building Basic auth header with base64, OTEL_EXPORTER_OTLP_ENDPOINT pointing to Langfuse OTEL endpoint
- [Generative AI observability now generally available for Amazon CloudWatch](https://aws.amazon.com/about-aws/whats-new/2025/10/generative-ai-observability-amazon-cloudwatch/) — GA announcement October 2025: extended coverage to Built-in Tools, Gateways, Memory, Identity; no additional pricing
