# Strands Agents SDK — Fundamentals

> Part of the **aws-bedrock-agentcore-skill** skill. See [SKILL.md](../SKILL.md) for the decision tree. Every source below is official — re-open it to verify details.

## Table of contents

- [Overview](#overview)
- [Key concepts](#key-concepts)
  - [Agent Loop](#agent-loop)
  - [Stop Reasons](#stop-reasons)
  - [Agent Class](#agent-class)
  - [Model Provider Abstraction](#model-provider-abstraction)
  - [Conversation Management](#conversation-management)
  - [Agent State vs Conversation History vs Invocation State](#agent-state-vs-conversation-history-vs-invocation-state)
  - [Hooks System](#hooks-system)
  - [Structured Output](#structured-output)
  - [Session Management](#session-management)
  - [Snapshots (take_snapshot / load_snapshot)](#snapshots-take_snapshot--load_snapshot)
  - [Streaming (Async Iterator and Callback Handler)](#streaming-async-iterator-and-callback-handler)
  - [ContextOffloader Plugin](#contextoffloader-plugin)
  - [BedrockModel — Converse API and Service Tiers](#bedrockmodel--converse-api-and-service-tiers)
- [Best practices](#best-practices)
- [Code](#code)
  - [Installation with available extras](#installation-with-available-extras)
  - [Minimal agent with BedrockModel (default) — uses Converse API](#minimal-agent-with-bedrockmodel-default--uses-converse-api)
  - [Agent constructor with all main parameters](#agent-constructor-with-all-main-parameters)
  - [BedrockModel — full configuration with cache, guardrails, service tier and reasoning](#bedrockmodel--full-configuration-with-cache-guardrails-service-tier-and-reasoning)
  - [AnthropicModel — direct Anthropic API (not via Bedrock)](#anthropicmodel--direct-anthropic-api-not-via-bedrock)
  - [OpenAIModel — GPT and OpenAI-compatible endpoints](#openaimodel--gpt-and-openai-compatible-endpoints)
  - [LiteLLMModel — unified gateway for 100+ providers](#litellmmodel--unified-gateway-for-100-providers)
  - [OllamaModel — local models (Python-only)](#ollamamodel--local-models-python-only)
  - [LlamaCppModel — local models via llama.cpp server (Python-only, official provider)](#llamacppmodel--local-models-via-llamacpp-server-python-only-official-provider)
  - [Limits — per-invocation budget caps](#limits--per-invocation-budget-caps)
  - [Async streaming with async iterator (ideal for FastAPI)](#async-streaming-with-async-iterator-ideal-for-fastapi)
  - [Synchronous callback handler for non-async apps (Python-only)](#synchronous-callback-handler-for-non-async-apps-python-only)
  - [Structured output with Pydantic BaseModel](#structured-output-with-pydantic-basemodel)
  - [Hooks — registration with type hints, Plugin pattern and HookProvider](#hooks--registration-with-type-hints-plugin-pattern-and-hookprovider)
  - [Snapshots — manual save/restore of state](#snapshots--manual-saverestore-of-state)
  - [Session Management with FileSessionManager (dev) and S3SessionManager (prod)](#session-management-with-filesessionmanager-dev-and-s3sessionmanager-prod)
  - [Agent State — persistable key-value store with ToolContext](#agent-state--persistable-key-value-store-with-toolcontext)
  - [ContextOffloader plugin — preventing context window overflow](#contextoffloader-plugin--preventing-context-window-overflow)
  - [Cancellation with async watchdog timeout](#cancellation-with-async-watchdog-timeout)
- [Configuration reference](#configuration-reference)
- [Gotchas](#gotchas)
- [Official sources](#official-sources)

---

## Overview

Strands Agents SDK is an open-source AWS framework (Python and TypeScript) for building AI agents with minimal code. The core is the **agent loop**: a recursive cycle of LLM inference → tool selection → tool execution → re-inference, which terminates when the model produces a final response. The `Agent` class encapsulates this loop with support for multiple model providers (`BedrockModel` default — uses Bedrock's Converse API, not the legacy InvokeModel — `AnthropicModel`, `OpenAIModel`, `OpenAIResponsesModel`, `LiteLLMModel`, `OllamaModel`, `LlamaCppModel`, and others), conversation management (`SlidingWindowConversationManager` default), structured output via Pydantic, async/callback streaming, a typed hooks system, manual snapshots (`take_snapshot`/`load_snapshot`), and persistent session management (`FileSessionManager`, `S3SessionManager`).

**Maturity:** GA (Generally Available). Released as open-source preview in May 2025; reached v1.0 GA with session management, structured output, async, and multi-agent support. Current version: **1.42.0** (PyPI, 1 June 2026). Requires Python ≥ 3.10. TypeScript SDK (`@strands-agents/sdk`) available at v1.4.0 (1 June 2026). **Experimental features:** `BidiAgent` / bidirectional streaming (`strands.experimental.bidi`) — explicitly experimental for all three providers (Nova Sonic, OpenAI Realtime, Google Gemini Live). Community providers (CLOVA Studio, Cohere, Fireworks AI, MLX, NVIDIA NIM, vLLM, xAI, SGLang, Nebius, OVHcloud) are not maintained by AWS. `LlamaCppModel` is an official provider (not community). Notable features introduced after v1.0 GA: `service_tier` (v1.35+), `ContextOffloader` plugin, `Snapshots` API, native token counting for multiple providers, Tool Result Offloading.

---

## Key concepts

### Agent Loop

The nucleus of Strands: a recursive cycle that invokes the model (via Bedrock Converse API or equivalent), checks whether it wants to use tools, executes them, and re-invokes the model with the results. Repeats until `stop_reason='end_turn'`. Each cycle appends messages to the conversation history. **Errors in tools do NOT interrupt the loop**: they are passed to the model as a `tool_result` with `status='error'`, giving the LLM the opportunity to recover. `Limits` (budget caps) are checked at the start of each iteration, not during a model call, so tools requested in the previous turn always complete before a cap fires.

### Stop Reasons

The loop ends with a `stop_reason`:

| stop_reason | Meaning |
|---|---|
| `end_turn` | Normal completion |
| `tool_use` | Executes tools and continues |
| `cancelled` | `agent.cancel()` was called |
| `max_tokens` | Response truncated — not recoverable, loop ends immediately |
| `stop_sequence` | Configured stop sequence encountered |
| `content_filtered` | Safety filter triggered |
| `guardrail_intervention` | Bedrock guardrail triggered |
| `limit_turns` | `Limits.turns` cap reached (graceful, reinvocable) |
| `limit_output_tokens` | `Limits.output_tokens` cap reached (soft cap, graceful) |
| `limit_total_tokens` | `Limits.total_tokens` cap reached (soft cap, graceful) |

Token caps are **soft**: a single oversized response can exceed the cap by one turn because the check occurs at turn boundaries.

### Agent Class

The main class in `strands.agent`. Constructor with ~20 key parameters. Two invocation patterns: (1) NL via `__call__`: `agent('prompt')` or `invoke_async` for async; (2) direct tool call via `agent.tool.tool_name(params)`. Always returns `AgentResult` with `stop_reason`, `message`, `metrics`, `state`, `structured_output`. **Thread-safe** for `cancel()`; for concurrent invocations use `concurrent_invocation_mode='unsafe_reentrant'` or `ConcurrentInvocationMode.UNSAFE_REENTRANT` consciously (no behavioral guarantees). Note: `agent.structured_output()` and `agent.structured_output_async()` are DEPRECATED in Python; use the `structured_output_model` parameter in `__call__` / `invoke_async` for new code.

### Model Provider Abstraction

All providers implement the `Model` interface and are interchangeable. **Default:** `BedrockModel` with Claude Sonnet 4.6 (`anthropic.claude-sonnet-4-6`), uses the Bedrock Converse API (not legacy InvokeModel).

**Official GA providers — Python:**
- `BedrockModel`, `AnthropicModel`, `OpenAIModel`, `OpenAIResponsesModel`
- `LiteLLMModel`, `OllamaModel`, `LlamaCppModel`, `LlamaAPIModel`
- `GoogleModel`, `MistralAIModel`, `SageMakerModel`, `WriterModel`, `AmazonNovaModel`

**Official providers — TypeScript:**
- `BedrockModel`, `AnthropicModel`, `OpenAIModel`, `GoogleModel`, Vercel AI SDK

**Community providers (not maintained by AWS):** CLOVA Studio, Cohere, Fireworks AI, MLX, Nebius, NVIDIA NIM, OVHcloud, SGLang, vLLM, xAI.

All non-Bedrock providers require a separate `pip install` extra.

### Conversation Management

System to manage context within context window limits. Three built-in managers:

- **`NullConversationManager`** — no modifications; history grows unbounded
- **`SlidingWindowConversationManager`** (default) — keeps N most recent messages; automatic tool result truncation to 200 chars head/tail; `per_turn` controls when to apply
- **`SummarizingConversationManager`** — summarises old messages via a secondary agent; parameters: `summary_ratio` (0.1–0.8), `preserve_recent_messages`, `summarization_system_prompt`

Both `SlidingWindow` and `Summarizing` support **`proactive_compression`** — activates compression before a call when projected tokens exceed a threshold. `S3SessionManager` now also requires `s3:ListBucket` in addition to `GetObject`/`PutObject`/`DeleteObject`.

### Agent State vs Conversation History vs Invocation State

Three distinct forms of state:

1. **Conversation History** — the user/assistant message sequence, passed to the model on each inference; accessible via `agent.messages`; direct tool calls can be excluded with `record_direct_tool_call=False`
2. **Agent State** (`appState` in TypeScript) — JSON-serialisable key-value store (`agent.state.get/set/delete`); NOT passed to the model; persistable with `SessionManager`; accessible from tools via `ToolContext`; non-serialisable values raise `ValueError`
3. **Invocation State** — temporary dictionary for a single invocation, shared by reference between hooks and tools; not included in model context; accessible also via `result.state`

### Hooks System

Composable, type-safe extensibility mechanism. Hook callbacks receive typed events at defined lifecycle points. Registered via `agent.add_hook(callback)` with Python type hint inference, or via `Plugin`/`@hook` (groups multiple hooks), or `HookProvider` protocol (reusable collections without a full Plugin). **Before** events fire in registration order; **After** events fire in reverse order (cleanup symmetry). In TypeScript, `HookOrder` is configurable (`SDK_FIRST=-100`, `DEFAULT=0`, `SDK_LAST=100`). Python vs TypeScript difference: Python uses `cancel_tool` on `BeforeToolCallEvent`, TypeScript uses `cancel`. TypeScript has more granular streaming events (`ModelStreamUpdateEvent`, `ContentBlockEvent`, `ToolStreamUpdateEvent`).

### Structured Output

Converts Pydantic (Python) or Zod (TypeScript) schemas into tool specifications, guides the model, validates, and returns typed objects in `result.structured_output`. Supported by all providers. Use the `structured_output_model` parameter in `__call__` / `invoke_async` as the primary approach. `agent.structured_output()` and `agent.structured_output_async()` are DEPRECATED in Python; use `structured_output_model` in `__call__` / `invoke_async` for new code. On validation failure: `StructuredOutputException` (Python) / `StructuredOutputError` (TypeScript). Works in combination with streaming: the validated object appears in the `result` field of the last stream event.

### Session Management

Automatic persistence of the complete state (conversation history + agent state + conversation manager state) via the `session_manager` parameter.

**Built-in:**
- `FileSessionManager` — local filesystem; for development
- `S3SessionManager` — S3; for production; requires `s3:GetObject`, `s3:PutObject`, `s3:DeleteObject`, `s3:ListBucket`

**Third-party:** `AgentCoreMemorySessionManager` (Amazon Bedrock AgentCore — advanced memory with intelligent short-term + long-term retrieval).

**Critical rule for Graph/Swarm:** `session_manager` only on the orchestrator, never on inner agents (`ValueError` in Python).

### Snapshots (take_snapshot / load_snapshot)

API for manual in-memory state control, distinct from session management. `take_snapshot(preset, include, exclude, app_data)`: preset `'session'` captures `messages`, `state`, `conversation_manager_state`, `interrupt_state`. Note: `system_prompt` is NOT included by default in Python — add it explicitly with `include=["system_prompt"]` if needed. `load_snapshot(snapshot)` restores only the fields present in the snapshot. `app_data` lets you attach transparent application metadata (labels, workflow steps, user preferences — Strands passes it through verbatim without reading it). Useful for explicit save-points, undo/redo, and state inspection. Distinct from session management which is automatic.

### Streaming (Async Iterator and Callback Handler)

Two patterns for accessing streaming events in Python:

1. **Async Iterator** via `agent.stream_async()` — ideal for FastAPI/aiohttp; requires `callback_handler=None`
2. **Callback Handler** via `callback_handler` parameter — synchronous; Python-only (TypeScript uses async iterator exclusively with `agent.stream()`)

**Python event types:** `init_event_loop`, `start_event_loop`, `data` (text), `current_tool_use`, `message`, `result`, `force_stop`, `force_stop_reason`, `delta`, `reasoning`, `reasoningText`, `tool_stream_event`, `multiagent_node_*` events. TypeScript has a hook-based streaming system with more granular events. `PrintingCallbackHandler` is the default (prints to stdout).

### ContextOffloader Plugin

Built-in plugin (`strands.vended_plugins.context_offloader`) that prevents context window overflow by intercepting large tool results. When a result exceeds `max_result_tokens` tokens, each content block is persisted to external storage (`InMemoryStorage`, `FileStorage`) and the content in context is replaced with a preview (`preview_tokens`) + reference. With `include_retrieval_tool=True`, automatically adds a tool to the agent for on-demand retrieval of offloaded blocks. A proactive alternative to the reactive truncation of `SlidingWindowConversationManager`.

### BedrockModel — Converse API and Service Tiers

`BedrockModel` uses exclusively the Bedrock Converse API (not the legacy InvokeModel API) for all invocations. From v1.35+ supports `service_tier`: `'default'` (standard), `'priority'` (faster, premium), `'flex'` (cheaper, slower). The field is omitted if not specified and Bedrock uses default behaviour. If the tier is not supported by the model/region, Bedrock returns `ValidationException`. Reasoning/thinking enabled via `additional_request_fields` with `{'thinking': {'type': 'enabled', 'budget_tokens': N}}` (minimum 1024). Interleaved thinking (Claude 4) also requires `anthropic_beta: ['interleaved-thinking-2025-05-14']`.

---

## Best practices

- **Use `BedrockModel` as the default provider on AWS; specify `model_id` as a string in the `Agent` constructor for simplicity** — Does not require extra imports; credential resolution happens automatically via boto3 (IAM role > env var > AWS profile). Works on ECS/Lambda/EC2 without explicit configuration. `Agent(model='anthropic.claude-sonnet-4-6')` is equivalent to `Agent(model=BedrockModel(model_id='...'))`. _Source: https://strandsagents.com/docs/user-guide/concepts/model-providers/amazon-bedrock/index.md_

- **Always set `region_name` on `BedrockModel` or `AWS_DEFAULT_REGION` explicitly; do not rely on `AWS_REGION`** — boto3 has a non-obvious priority order: `BedrockModel(region_name=...)` > boto3 session region (AWS_DEFAULT_REGION or profile) > `AWS_REGION` > default (us-west-2). `AWS_REGION` is the lowest-priority fallback (just above the hardcoded default) and can cause surprises in production; prefer `AWS_DEFAULT_REGION` or `BedrockModel(region_name=...)`. _Source: https://strandsagents.com/docs/user-guide/concepts/model-providers/amazon-bedrock/index.md_

- **Use the Bedrock Converse API (BedrockModel default) — do not configure legacy InvokeModel** — `BedrockModel` already uses the Converse API internally for all invocations. No extra configuration needed. InvokeModel is the legacy API and is not exposed directly by Strands. Converse supports tool use, multimodal, caching, and reasoning in a unified way. _Source: https://strandsagents.com/docs/api/python/strands.models.bedrock/_

- **For streaming on async servers use `agent.stream_async()` with `callback_handler=None`; not the synchronous callback handler** — The synchronous callback handler blocks the thread. For FastAPI/aiohttp/Django Channels you need the async iterator pattern to avoid blocking the event loop. TypeScript does not support callback handlers — always use `agent.stream()` async. _Source: https://strandsagents.com/docs/user-guide/concepts/streaming/async-iterators/index.md_

- **Disable the default callback handler (`callback_handler=None`) when using `stream_async()`** — If not disabled, `PrintingCallbackHandler` prints to stdout AND data also arrives from the stream: double output and potential race conditions. _Source: https://strandsagents.com/docs/user-guide/concepts/streaming/async-iterators/index.md_

- **Use `SlidingWindowConversationManager` with `per_turn=True` for agent loops with many tool calls** — The default (`per_turn=False`) applies window management only at the end of the full loop. With many tool calls the context can explode before then. `per_turn=True` applies truncation before each model call. Alternatively use the `ContextOffloader` plugin for a proactive approach that preserves offloaded data instead of truncating it. _Source: https://strandsagents.com/docs/user-guide/concepts/agents/conversation-management/index.md_

- **Use `ContextOffloader` plugin for tools that return large data (file readers, APIs, DB queries)** — `SlidingWindowConversationManager` truncates reactively (200 chars head/tail) after a failed API call. `ContextOffloader` is proactive: offloads before sending to the model, preserving complete data retrievable on demand. Configure `max_result_tokens` and `include_retrieval_tool=True` for maximum control. _Source: https://strandsagents.com/docs/user-guide/concepts/plugins/context-offloader/index.md_

- **Implement cancellation with `agent.cancel()` from a separate thread/task for timeouts or disconnects** — `cancel()` is thread-safe and idempotent. The result returns `stop_reason='cancelled'`. The signal resets automatically, so the agent is immediately reusable. Without `cancel()`, a pending request blocks the lock (`ConcurrencyException`). In TypeScript also supports external `AbortSignal`. _Source: https://strandsagents.com/docs/user-guide/concepts/agents/agent-loop/index.md_

- **Use the `structured_output_model` parameter in `__call__` / `invoke_async` as the primary approach for structured output** — This is the current recommended API. Returns the result in `AgentResult.structured_output`. Works in combination with streaming. `agent.structured_output()` and `agent.structured_output_async()` are DEPRECATED in Python; use the `structured_output_model` parameter in `__call__` / `invoke_async` for new code. _Source: https://strandsagents.com/docs/user-guide/concepts/agents/structured-output/index.md_

- **Use `S3SessionManager` for persistence in production; `FileSessionManager` only for local development** — `S3SessionManager` uses S3 operations for safe writes in distributed environments. Requires: `s3:GetObject`, `s3:PutObject`, `s3:DeleteObject`, `s3:ListBucket`. `FileSessionManager` is designed for local dev and testing (default: tmpdir). _Source: https://strandsagents.com/docs/user-guide/concepts/agents/session-management/index.md_

- **Do not assign `session_manager` to agents inside a Graph/Swarm: assign it only to the orchestrator** — Python raises `ValueError` if an agent with `session_manager` is added to a Graph or Swarm. The orchestrator manages snapshot/restore for all nodes; a manager at agent level creates state conflicts. _Source: https://strandsagents.com/docs/user-guide/concepts/agents/session-management/index.md_

- **Use typed hooks with type hints for concise, refactoring-safe registration** — `agent.add_hook(callback)` automatically infers the type from the parameter annotation. Also works with Union types to register the same callback on multiple events. In TypeScript use `HookOrder` to position callbacks relative to internal SDK hooks. _Source: https://strandsagents.com/docs/user-guide/concepts/agents/hooks/index.md_

- **Use `service_tier='flex'` for non-time-sensitive batch workloads, `'priority'` for latency-sensitive interactive agents** — `service_tier` is a `BedrockModel` parameter (introduced ~v1.35) that controls the latency/cost trade-off at request level. If the tier is not supported by the model/region, Bedrock returns `ValidationException` — verify AWS documentation on supported service tiers. _Source: https://strandsagents.com/docs/api/python/strands.models.bedrock/_

- **Enable reasoning with `additional_request_fields` rather than looking for a dedicated parameter** — `BedrockModel` exposes `additional_request_fields` as an escape hatch for model-specific parameters not normalised in the common interface. For Claude 4 with interleaved thinking: `{'anthropic_beta': ['interleaved-thinking-2025-05-14'], 'thinking': {'type': 'enabled', 'budget_tokens': 8000}}`. _Source: https://strandsagents.com/blog/interleaved-thinking-claude-4/index.md_

- **Keep tool descriptions unambiguous and non-overlapping across different tools** — Tool selection depends on the description. Tools with overlapping descriptions cause erratic selections. Review descriptions from the model's perspective, not the developer's. _Source: https://strandsagents.com/docs/user-guide/concepts/agents/agent-loop/index.md_

- **Call `agent.cleanup()` explicitly when the agent uses MCP tool providers or external resources** — `cleanup()` frees MCP clients and other resources. The finalizer (`__del__`) works as a fallback but is not guaranteed. Critical in long-lived or server contexts to avoid leaks. _Source: https://strandsagents.com/docs/api/python/strands.agent.agent/_

- **Do not use `BidiAgent` (`strands.experimental.bidi`) in production without a migration plan** — The documentation explicitly states: "This feature is experimental and may change in future versions. Use with caution in production environments." Supported providers are Nova Sonic, OpenAI Realtime, Google Gemini Live — but the API may change before GA. _Source: https://strandsagents.com/docs/user-guide/concepts/bidirectional-streaming/agent/_

---

## Code

### Installation with available extras

```bash
# Bedrock only (default, already included)
pip install strands-agents

# With specific providers
pip install 'strands-agents[anthropic]'
pip install 'strands-agents[openai]'
pip install 'strands-agents[litellm]'
pip install 'strands-agents[ollama]'
pip install 'strands-agents[gemini]'
pip install 'strands-agents[mistral]'
pip install 'strands-agents[llamaapi]'
pip install 'strands-agents[sagemaker]'
pip install 'strands-agents[writer]'
pip install 'strands-agents[otel]'         # OpenTelemetry tracing
pip install 'strands-agents[bidi]'          # Bidirectional streaming (experimental)
pip install 'strands-agents[bidi-all]'      # All bidi providers

# All providers (dev)
pip install 'strands-agents[all]'

# Community tools
pip install strands-agents-tools
```

_Source: https://pypi.org/project/strands-agents/_

---

### Minimal agent with BedrockModel (default) — uses Converse API

```python
from strands import Agent

# BedrockModel + Claude Sonnet 4.6 are the default
# BedrockModel uses the Bedrock Converse API internally (not legacy InvokeModel)
# Requires: AWS credentials configured (IAM role, env var, or aws configure)
agent = Agent()
result = agent("What is the capital of France?")
print(result)               # prints the response
print(result.stop_reason)   # 'end_turn'
print(result.metrics.get_summary())  # latency, token usage, tool stats

# Shortcut: model as string automatically creates BedrockModel
agent2 = Agent(model="anthropic.claude-sonnet-4-6")

# Debug logging
import logging
logging.getLogger("strands").setLevel(logging.DEBUG)
logging.basicConfig(
    format="%(levelname)s | %(name)s | %(message)s",
    handlers=[logging.StreamHandler()]
)
```

_Source: https://strandsagents.com/docs/user-guide/quickstart/python/index.md_

---

### Agent constructor with all main parameters

```python
from strands import Agent
from strands.models import BedrockModel
from strands.agent.conversation_manager import SlidingWindowConversationManager
from strands.session.s3_session_manager import S3SessionManager
from strands.types.agent import ConcurrentInvocationMode
from strands_tools import calculator, current_time

model = BedrockModel(
    model_id="anthropic.claude-sonnet-4-6",
    region_name="us-east-1",
    temperature=0.3,
    max_tokens=4096,
    streaming=True,         # default True — uses Converse streaming
    service_tier="default", # 'default' | 'priority' | 'flex'
)

session_manager = S3SessionManager(
    session_id="user-123",
    bucket="my-agent-sessions",
    prefix="prod/",
    # Requires IAM: s3:GetObject, s3:PutObject, s3:DeleteObject, s3:ListBucket
)

agent = Agent(
    model=model,
    system_prompt="You are a helpful assistant that uses tools to answer questions.",
    tools=[calculator, current_time],
    conversation_manager=SlidingWindowConversationManager(
        window_size=40,
        per_turn=True,      # apply before each model call (recommended with many tools)
    ),
    session_manager=session_manager,
    agent_id="support-bot",
    name="SupportBot",
    description="Customer support agent",
    callback_handler=None,  # disables output to stdout
    concurrent_invocation_mode=ConcurrentInvocationMode.THROW,  # default: ConcurrencyException
)
```

_Source: https://strandsagents.com/docs/api/python/strands.agent.agent/_

---

### BedrockModel — full configuration with cache, guardrails, service tier and reasoning

```python
import boto3
from botocore.config import Config as BotocoreConfig
from strands import Agent
from strands.models import BedrockModel, CacheConfig

boto_config = BotocoreConfig(
    retries={"max_attempts": 3, "mode": "standard"},
    connect_timeout=5,
    read_timeout=60,
)

# Standard configuration with caching and guardrails
model = BedrockModel(
    model_id="anthropic.claude-sonnet-4-6",
    region_name="us-east-1",
    temperature=0.3,
    top_p=0.8,
    max_tokens=8192,
    stop_sequences=["###"],
    boto_client_config=boto_config,
    # Prompt caching: 'auto' for Claude (automatic cache point management)
    # Amazon Nova supports caching but does not accept cache checkpoints in the tools field
    # Minimum: 1024 tokens for Claude Sonnet, 4096 for Claude Haiku; expires after 5 min
    cache_config=CacheConfig(strategy="auto"),   # only for Claude models
    cache_tools="default",               # tool definition caching (TTL 5 min default)
    # Service tier (from v1.35+): 'default' | 'priority' | 'flex'
    # ValidationException if not supported by model/region
    service_tier="priority",
    # Bedrock Guardrails
    guardrail_id="my-guardrail-id",
    guardrail_version="1",
    guardrail_trace="enabled",           # 'enabled' | 'disabled' | 'enabled_full'
    guardrail_redact_input=True,         # default True
    guardrail_redact_output=False,       # default False
    guardrail_latest_message=False,      # only last user msg (reduces costs)
)

agent = Agent(model=model)

# With reasoning/extended thinking (Claude Sonnet 4.6)
model_reasoning = BedrockModel(
    model_id="us.anthropic.claude-sonnet-4-6",
    region_name="us-east-1",
    additional_request_fields={
        "thinking": {
            "type": "enabled",
            "budget_tokens": 8000,  # minimum 1024
        }
    },
)

# Interleaved thinking (Claude Sonnet 4.6) — also requires anthropic_beta
model_interleaved = BedrockModel(
    model_id="us.anthropic.claude-sonnet-4-6",
    additional_request_fields={
        "anthropic_beta": ["interleaved-thinking-2025-05-14"],
        "thinking": {"type": "enabled", "budget_tokens": 8000},
    },
)

# With custom boto3 session (cross-account or MFA)
session = boto3.Session(
    profile_name="prod-profile",
    region_name="us-east-1",
)
model_with_session = BedrockModel(
    model_id="anthropic.claude-sonnet-4-6",
    boto_session=session,
)
```

_Source: https://strandsagents.com/docs/user-guide/concepts/model-providers/amazon-bedrock/index.md_

---

### AnthropicModel — direct Anthropic API (not via Bedrock)

```python
import os
from strands import Agent
from strands.models.anthropic import AnthropicModel
from strands_tools import calculator

# pip install 'strands-agents[anthropic]'
model = AnthropicModel(
    client_args={
        "api_key": os.environ["ANTHROPIC_API_KEY"],
    },
    model_id="claude-sonnet-4-6",
    max_tokens=4096,
    params={
        "temperature": 0.7,
    },
    use_native_token_count=True,  # uses the native token counting API
)

agent = Agent(model=model, tools=[calculator])
result = agent("What is 2+2?")
print(result)
```

_Source: https://strandsagents.com/docs/user-guide/concepts/model-providers/anthropic/index.md_

---

### OpenAIModel — GPT and OpenAI-compatible endpoints

```python
import os
from strands import Agent
from strands.models.openai import OpenAIModel

# pip install 'strands-agents[openai]'

# Standard OpenAI
model = OpenAIModel(
    client_args={"api_key": os.environ["OPENAI_API_KEY"]},
    model_id="gpt-4o",
    params={"max_tokens": 2000, "temperature": 0.5},
)

# OpenAI-compatible endpoint (e.g. vLLM, LM Studio, custom endpoint)
model_compatible = OpenAIModel(
    client_args={
        "api_key": "not-needed",
        "base_url": "http://localhost:8000/v1",
    },
    model_id="meta-llama/Llama-3-8b-instruct",
    params={"max_tokens": 2000},
)

# GPT-OSS on non-managed endpoint: configure explicit stop sequences
model_oss = OpenAIModel(
    client_args={"api_key": "...", "base_url": "http://localhost:8000/v1"},
    model_id="some-oss-model",
    params={
        "stop": ["<|call|>", "<|return|>", "<|end|>"],  # OpenAI Harmony message format
        "max_tokens": 2000,
    },
)

agent = Agent(model=model)
result = agent("Explain async/await in Python")
```

_Source: https://strandsagents.com/docs/user-guide/concepts/model-providers/openai/index.md_

---

### LiteLLMModel — unified gateway for 100+ providers

```python
from strands import Agent
from strands.models.litellm import LiteLLMModel

# pip install 'strands-agents[litellm]'

# Via Bedrock through LiteLLM
model = LiteLLMModel(
    model_id="bedrock/us.anthropic.claude-3-7-sonnet-20250219-v1:0",
    params={"max_tokens": 2000, "temperature": 0.7},
)

# Via LiteLLM Proxy Server (option 1: use_litellm_proxy)
model_proxy = LiteLLMModel(
    client_args={
        "api_key": "proxy-key",
        "api_base": "http://localhost:4000",
        "use_litellm_proxy": True,
    },
    model_id="claude-3-7-sonnet",
)

# Via LiteLLM Proxy Server (option 2: prefix in model_id)
model_proxy2 = LiteLLMModel(
    client_args={"api_key": "proxy-key", "api_base": "http://localhost:4000"},
    model_id="litellm_proxy/amazon.nova-lite-v1:0",
)

# Note on caching: works via SystemContentBlock but the behaviour
# depends on the underlying provider — not all LiteLLM providers actually
# support caching in production. Verify the specific provider's documentation.

agent = Agent(model=model)
result = agent("Hello!")
```

_Source: https://strandsagents.com/docs/user-guide/concepts/model-providers/litellm/index.md_

---

### OllamaModel — local models (Python-only)

```python
from strands import Agent
from strands.models.ollama import OllamaModel
from strands_tools import calculator

# pip install 'strands-agents[ollama]'
# Note: OllamaModel is Python-only (no TypeScript support planned)

model = OllamaModel(
    host="http://localhost:11434",  # default Ollama port
    model_id="llama3.1",
    temperature=0.7,
    max_tokens=2000,
    keep_alive="5m",    # how long to keep the model in memory (default: "5m")
    top_p=0.9,
    stop_sequences=["<|eot_id|>"],
    options={"top_k": 40},           # extra Ollama-specific parameters
    additional_args={},              # extra arguments for the request
)

agent = Agent(model=model, tools=[calculator])
result = agent("Calculate the area of a circle with radius 5")

# Update config at runtime
model.update_config(temperature=0.9, model_id="mistral")
```

_Source: https://strandsagents.com/docs/user-guide/concepts/model-providers/ollama/index.md_

---

### LlamaCppModel — local models via llama.cpp server (Python-only, official provider)

```python
from strands import Agent
from strands.models.llamacpp import LlamaCppModel

# Included in the base package (no extra pip required)
# Note: LlamaCppModel is Python-only and is now an official provider (not community)
# Prerequisite: llama.cpp server running on localhost:8080

model = LlamaCppModel(
    base_url="http://localhost:8080",  # default
    model_id="default",
    params={
        "temperature": 0.7,
        "max_tokens": 2000,
        "top_k": 40,
        "repeat_penalty": 1.1,
        # Supports GBNF grammar for structured output:
        # "grammar": "root ::= ...",
        # "json_schema": {"type": "object", ...},
    },
    use_native_token_count=True,  # uses the server's /tokenize endpoint
)

agent = Agent(model=model)
result = agent("Explain the Fibonacci sequence")

# Update config at runtime
model.update_config(params={"temperature": 0.9})
```

_Source: https://strandsagents.com/docs/user-guide/concepts/model-providers/llamacpp/_

---

### Limits — per-invocation budget caps

```python
import asyncio
from strands import Agent
from strands.types.agent import Limits
from strands_tools import calculator

agent = Agent(tools=[calculator])

# Limits is a TypedDict — all fields are optional (positive int)
# When a cap is reached, the loop terminates gracefully without exception
# Check occurs at the start of each iteration (turn boundary)
# Token caps are 'soft': a single oversized response can exceed the cap by one turn

# TypedDict syntax
result = agent(
    "Calculate fibonacci numbers up to 1000, then sum them",
    limits=Limits(
        turns=5,           # max 5 loop iterations
        total_tokens=4000, # max 4000 cumulative input + output tokens
        # output_tokens=2000,  # max tokens generated by the model
    ),
)

# If 'turns' and 'total_tokens' fire together:
# priority: turns > total_tokens > output_tokens
if result.stop_reason == "limit_turns":
    print("Reached turn limit, continuing from where we left off...")
    # agent.messages is in reinvocable state
elif result.stop_reason == "limit_total_tokens":
    print("Reached token budget")
else:
    print(f"Completed: {result.stop_reason}")

# Async variant
async def main():
    result = await agent.invoke_async(
        "Analyze this large dataset step by step",
        limits=Limits(turns=10, output_tokens=8000),
    )
    return result
```

_Source: https://strandsagents.com/docs/api/python/strands.types.agent/index.md_

---

### Async streaming with async iterator (ideal for FastAPI)

```python
import asyncio
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from strands import Agent
from strands_tools import calculator

app = FastAPI()

@app.post("/stream")
async def stream_response(request: Request, prompt: str):
    async def generate():
        agent = Agent(
            tools=[calculator],
            callback_handler=None,  # REQUIRED: disables stdout
        )
        try:
            async for event in agent.stream_async(prompt):
                if "data" in event:
                    # Text generated in streaming
                    yield event["data"]
                elif "current_tool_use" in event and event["current_tool_use"].get("name"):
                    # Tool being executed
                    yield f"[tool: {event['current_tool_use']['name']}]"
                elif event.get("force_stop"):
                    yield f"[stopped: {event.get('force_stop_reason', 'unknown')}]"
                elif "result" in event:
                    stop_reason = str(event["result"].stop_reason)
                    yield f"[done: {stop_reason}]"
        except Exception as e:
            yield f"[error: {str(e)}]"

    return StreamingResponse(generate(), media_type="text/plain")

# Standalone example
async def main():
    agent = Agent(callback_handler=None)
    async for event in agent.stream_async("Explain quantum computing"):
        if "data" in event:
            print(event["data"], end="", flush=True)
        elif event.get("init_event_loop"):
            pass  # loop initialised
        elif event.get("start_event_loop"):
            pass  # new iteration

asyncio.run(main())
```

_Source: https://strandsagents.com/docs/user-guide/concepts/streaming/async-iterators/index.md_

---

### Synchronous callback handler for non-async apps (Python-only)

```python
from strands import Agent
from strands_tools import calculator

# Note: the callback handler is Python-only.
# TypeScript uses exclusively the async iterator pattern (agent.stream())

def my_callback(**kwargs):
    """Synchronous callback — kwargs contains all events."""
    if "data" in kwargs:
        print(kwargs["data"], end="", flush=True)
    elif "current_tool_use" in kwargs and kwargs["current_tool_use"].get("name"):
        print(f"\n[Calling tool: {kwargs['current_tool_use']['name']}]")
    elif "message" in kwargs:
        msg = kwargs["message"]
        if msg.get("role") == "assistant":
            pass  # complete message available
    elif kwargs.get("init_event_loop"):
        pass   # loop initialised
    elif kwargs.get("start_event_loop"):
        pass   # new loop iteration
    elif kwargs.get("force_stop"):
        print(f"\n[Force stopped: {kwargs.get('force_stop_reason')}]")
    elif "result" in kwargs:
        print(f"\n[Done: {kwargs['result'].stop_reason}]")

agent = Agent(tools=[calculator], callback_handler=my_callback)
agent("What is 922 + 5321?")
```

_Source: https://strandsagents.com/docs/user-guide/concepts/streaming/callback-handlers/index.md_

---

### Structured output with Pydantic BaseModel

```python
from pydantic import BaseModel, Field
from strands import Agent
from strands.types.exceptions import StructuredOutputException

class ProductInfo(BaseModel):
    """Extract product information from text."""
    name: str = Field(description="Product name")
    price: float = Field(description="Price in USD")
    category: str = Field(description="Product category")
    in_stock: bool = Field(description="Whether the product is in stock")

agent = Agent()

try:
    result = agent(
        "The Blue Widget X200 costs $29.99, is in the electronics category, and is currently available.",
        structured_output_model=ProductInfo,
    )
    product: ProductInfo = result.structured_output
    print(f"Name: {product.name}, Price: ${product.price}")
except StructuredOutputException as e:
    print(f"Structured output failed: {e}")

# Async variant
import asyncio
async def get_structured():
    result = await agent.invoke_async(
        "The Red Gadget costs $49.99, is in toys, and is out of stock.",
        structured_output_model=ProductInfo,
    )
    return result.structured_output

product = asyncio.run(get_structured())

# Structured output + streaming: the object appears in the 'result' event
async def stream_structured():
    async for event in agent.stream_async(
        "A laptop costs $999, electronics, in stock",
        structured_output_model=ProductInfo,
    ):
        if "data" in event:
            print(event["data"], end="", flush=True)
        elif "result" in event:
            product = event["result"].structured_output
            if product:
                print(f"\nParsed: {product.name} — ${product.price}")

asyncio.run(stream_structured())
```

_Source: https://strandsagents.com/docs/user-guide/concepts/agents/structured-output/index.md_

---

### Hooks — registration with type hints, Plugin pattern and HookProvider

```python
from strands import Agent
from strands.hooks import (
    BeforeInvocationEvent,
    AfterInvocationEvent,
    BeforeModelCallEvent,
    AfterModelCallEvent,
    BeforeToolCallEvent,
    AfterToolCallEvent,
    MessageAddedEvent,
)
from strands.plugins import Plugin, hook
from strands.hooks import HookProvider, HookRegistry

agent = Agent()

# Registration with type hint inference (recommended approach)
def log_before_tool(event: BeforeToolCallEvent) -> None:
    print(f"Tool called: {event.tool_use['name']}")
    # Modify tool parameters:
    # event.tool_use["input"]["param"] = "forced_value"
    # Cancel the tool (Python uses cancel_tool, TypeScript uses cancel):
    # event.cancel_tool = "Tool not allowed"

def handle_after_tool(event: AfterToolCallEvent) -> None:
    print(f"Tool result status: {event.result.get('status')}")
    # event.result["content"] = [{"text": "modified result"}]
    # event.retry = True  # retry the tool

async def on_after_invocation(event: AfterInvocationEvent) -> None:
    """Async hooks are supported."""
    if event.result:
        print(f"Invocation ended: {event.result.stop_reason}")
    # event.resume = "Please summarize what you just did."  # automatic follow-up

agent.add_hook(log_before_tool)      # type inferred from type hint
agent.add_hook(handle_after_tool)    # type inferred from type hint
agent.add_hook(on_after_invocation)  # async hook supported

# Explicit registration on multiple event types
def multi_handler(event) -> None:
    print(f"Event: {type(event).__name__}")
agent.add_hook(multi_handler, [BeforeModelCallEvent, AfterModelCallEvent])


# Plugin: groups multiple hooks with state and configuration
class AuditPlugin(Plugin):
    name = "audit-plugin"

    def __init__(self, max_tool_calls: int = 20):
        self._max = max_tool_calls
        self._count = 0

    @hook
    def reset_on_start(self, event: BeforeInvocationEvent) -> None:
        self._count = 0

    @hook
    def check_limit(self, event: BeforeToolCallEvent) -> None:
        self._count += 1
        if self._count > self._max:
            event.cancel_tool = f"Tool limit of {self._max} reached"

    @hook
    def log_completion(self, event: AfterToolCallEvent) -> None:
        print(f"Tool '{event.tool_use['name']}' done ({self._count}/{self._max})")


# HookProvider: reusable collections without a full Plugin
class RequestLogger(HookProvider):
    def register_hooks(self, registry: HookRegistry) -> None:
        registry.add_callback(BeforeToolCallEvent, self._log)

    def _log(self, event: BeforeToolCallEvent) -> None:
        print(f"[LOG] tool={event.tool_use['name']}")


agent_with_plugins = Agent(plugins=[AuditPlugin(max_tool_calls=10)])
```

_Source: https://strandsagents.com/docs/user-guide/concepts/agents/hooks/index.md_

---

### Snapshots — manual save/restore of state

```python
from strands import Agent
from strands_tools import calculator

agent = Agent(
    tools=[calculator],
    system_prompt="You are a helpful assistant.",
    state={"user_id": "alice", "step": 0},
)

agent("Remember that my name is Alice")

# Capture snapshot (in-memory, manual control)
# preset='session' includes: messages, state, conversation_manager_state,
#                            interrupt_state
# Note: system_prompt is NOT included by default in Python.
# To include it: agent.take_snapshot(preset="session", include=["system_prompt"])
snapshot = agent.take_snapshot(preset="session")

# With custom app_data — Strands does not read it, passes through verbatim
snapshot_with_meta = agent.take_snapshot(
    preset="session",
    app_data={"checkpoint_label": "after_greeting", "workflow_step": 1},
)

# Capture only specific fields
messages_only = agent.take_snapshot(include=["messages", "state"])

# Selective exclusion
no_system = agent.take_snapshot(preset="session", exclude=["system_prompt"])

agent("Do something that changes state...")

# Restore: only fields present in the snapshot are updated
agent.load_snapshot(snapshot)
print(agent.state.get("user_id"))  # 'alice'

# Difference from session management:
# - snapshot: manual, in-memory, precise control of the moment
# - session_manager: automatic, persistent to disk/S3, managed by SDK
```

_Source: https://strandsagents.com/docs/user-guide/concepts/agents/snapshots/index.md_

---

### Session Management with FileSessionManager (dev) and S3SessionManager (prod)

```python
from strands import Agent
from strands.session.file_session_manager import FileSessionManager
from strands.session.s3_session_manager import S3SessionManager

# === DEV: local filesystem ===
file_session = FileSessionManager(
    session_id="user-123",
    storage_dir="./agent_sessions",  # default: tmpdir
)
agent = Agent(
    agent_id="support-bot",  # used as directory key
    session_manager=file_session,
)
agent("Hello! I'm John.")  # automatically persisted
# On next execution with same session_id: conversation resumed

# === PROD: Amazon S3 ===
import boto3
boto_session = boto3.Session(region_name="us-east-1")
s3_session = S3SessionManager(
    session_id="user-123",
    bucket="my-agent-sessions",
    prefix="prod/",
    boto_session=boto_session,
    # Required IAM permissions:
    # s3:GetObject, s3:PutObject, s3:DeleteObject, s3:ListBucket
    # (s3:ListBucket added compared to the previous version of the docs)
)
agent_prod = Agent(
    agent_id="support-bot",
    session_manager=s3_session,
)
agent_prod("Hello!")

# THIRD PARTY: Amazon Bedrock AgentCore memory (short-term + long-term)
# from amazon_agentcore import AgentCoreMemorySessionManager
# manager = AgentCoreMemorySessionManager(session_id="...", ...)

# CRITICAL RULE: in Graph/Swarm, session_manager ONLY on the orchestrator
# Agent with session_manager inside Graph/Swarm raises ValueError
```

_Source: https://strandsagents.com/docs/user-guide/concepts/agents/session-management/index.md_

---

### Agent State — persistable key-value store with ToolContext

```python
from strands import Agent, tool, ToolContext
from strands.session.file_session_manager import FileSessionManager

@tool(context=True)
def increment_counter(tool_context: ToolContext) -> str:
    """Increment the request counter."""
    # Note: state.get() without arguments returns the complete dict
    count = tool_context.agent.state.get("request_count") or 0
    tool_context.agent.state.set("request_count", count + 1)
    return f"Request count: {count + 1}"

@tool(context=True)
def get_user_info(tool_context: ToolContext) -> str:
    """Get current user information from agent state."""
    user_id = tool_context.agent.state.get("user_id")
    return f"User ID: {user_id}"

# Initialisation with initial state (must be JSON-serialisable)
# Non-serialisable values (e.g. functions) raise ValueError
agent = Agent(
    tools=[increment_counter, get_user_info],
    state={"user_id": "abc123", "request_count": 0},
)

agent("Increment the counter")
agent("Increment it again")

# Direct state access
print(agent.state.get("request_count"))  # 2
print(agent.state.get("user_id"))         # 'abc123'
print(agent.state.get())                  # complete dict

agent.state.set("last_seen", "2026-06-03")
agent.state.delete("last_seen")

# Direct tool calls (not recorded in conversation history)
# agent.tool.increment_counter()  # use record_direct_tool_call=False to exclude them
```

_Source: https://strandsagents.com/docs/user-guide/concepts/agents/state/index.md_

---

### ContextOffloader plugin — preventing context window overflow

```python
from strands import Agent
from strands.vended_plugins.context_offloader import (
    ContextOffloader,
    InMemoryStorage,
    FileStorage,
)
from strands_tools import file_read, http_request

# In-memory storage (for testing / single-process sessions)
agent_mem = Agent(
    tools=[file_read, http_request],
    plugins=[
        ContextOffloader(storage=InMemoryStorage())
    ],
)

# File storage with custom thresholds and retrieval tool
# include_retrieval_tool=True automatically adds a tool for
# on-demand retrieval of offloaded blocks
agent_file = Agent(
    tools=[file_read, http_request],
    plugins=[
        ContextOffloader(
            storage=FileStorage("./artifacts"),
            max_result_tokens=5_000,   # offloading threshold (default: 2500)
            preview_tokens=2_000,      # preview kept in context (default: 1000)
            include_retrieval_tool=True,
        )
    ],
)

# When a tool returns >max_result_tokens tokens:
# 1. Complete content is saved to storage
# 2. Only preview + reference to the block remains in context
# 3. The model can use the retrieval tool to read specific blocks
# This is proactive vs SlidingWindowConversationManager which is reactive
```

_Source: https://strandsagents.com/docs/user-guide/concepts/plugins/context-offloader/index.md_

---

### Cancellation with async watchdog timeout

```python
import asyncio
from strands import Agent
from strands.types.agent import Limits

agent = Agent()

# Option 1: cancel() from a separate task (watchdog pattern)
async def run_with_timeout(prompt: str, timeout_seconds: float):
    task = asyncio.create_task(agent.invoke_async(prompt))

    async def watchdog():
        await asyncio.sleep(timeout_seconds)
        agent.cancel()  # thread-safe, idempotent

    watchdog_task = asyncio.create_task(watchdog())
    result = await task
    watchdog_task.cancel()

    if result.stop_reason == "cancelled":
        print(f"Agent cancelled after timeout ({timeout_seconds}s)")
        # Signal resets automatically: agent immediately reusable
    return result

# Option 2: Limits for soft budget cap (no separate thread required)
async def run_with_budget():
    result = await agent.invoke_async(
        "Analyze this large dataset step by step",
        limits=Limits(turns=15, total_tokens=50000),
    )
    if result.stop_reason in ("limit_turns", "limit_total_tokens"):
        print(f"Budget cap hit: {result.stop_reason}")
        # agent.messages is in reinvocable state
    return result

result = asyncio.run(run_with_timeout("Analyze this large dataset", timeout_seconds=30.0))
```

_Source: https://strandsagents.com/docs/api/python/strands.agent.agent/_

---

## Configuration reference

| Name | Description | Default / example |
|---|---|---|
| `AWS_ACCESS_KEY_ID` | AWS key for BedrockModel authentication. Alternative to IAM role or `aws configure`. | `export AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE` |
| `AWS_SECRET_ACCESS_KEY` | AWS secret for authentication. Use together with `AWS_ACCESS_KEY_ID`. | `export AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY` |
| `AWS_SESSION_TOKEN` | Temporary session token (STS assume-role). Optional; required only for temporary credentials. | `export AWS_SESSION_TOKEN=AQoXnyc4lcK4w...` |
| `AWS_DEFAULT_REGION` | Preferred AWS region. HIGH priority in boto3 resolution, more reliable than `AWS_REGION`. Use this, not `AWS_REGION`. | `export AWS_DEFAULT_REGION=us-east-1` |
| `AWS_REGION` | AWS region. Lowest-priority fallback in boto3 resolution chain for BedrockModel (priority 3 of 4, just above the hardcoded default us-west-2). Do not rely on it as the sole region mechanism. | Lowest priority — prefer `AWS_DEFAULT_REGION` or `BedrockModel(region_name=...)` |
| `AWS_BEARER_TOKEN_BEDROCK` | Bearer token for alternative authentication to Bedrock (not SigV4). Alternative to IAM keys. | `export AWS_BEARER_TOKEN_BEDROCK=<token>` |
| `ANTHROPIC_API_KEY` | API key for `AnthropicModel` (direct access, not via Bedrock). Required when using `strands.models.anthropic`. | `export ANTHROPIC_API_KEY=sk-ant-...` |
| `OPENAI_API_KEY` | API key for `OpenAIModel`. Can also be passed via `client_args={'api_key': ...}`. | `export OPENAI_API_KEY=sk-...` |
| `BedrockModel.model_id` | Bedrock model ID. Default: Claude Sonnet 4.6. Cross-region inference requires geo prefix. | `anthropic.claude-sonnet-4-6` \| `us.anthropic.claude-sonnet-4-6` |
| `BedrockModel.region_name` | Bedrock region. Highest priority in resolution after BedrockModel constructor. Default: `us-west-2`. | `us-east-1` |
| `BedrockModel.temperature` | Model output randomness (0.0–1.0). Lower values = more deterministic. | `0.3` |
| `BedrockModel.max_tokens` | Maximum number of tokens to generate in the response. | `4096` |
| `BedrockModel.cache_config` | Enables prompt caching for Claude models. `strategy='auto'` for automatic cache point management (Claude-only). Amazon Nova supports caching but does not accept checkpoints in the `tools` field. | `CacheConfig(strategy='auto')` — only Claude on Bedrock |
| `BedrockModel.cache_tools` | Enables caching of tool definitions. Accepts string `'default'` (TTL 5 min) or `CacheToolsConfig(type=..., ttl='1h')`. | `cache_tools='default'` |
| `BedrockModel.service_tier` | Service tier to balance latency vs cost (introduced v1.35+). `ValidationException` if model/region does not support the tier. | `'default'` \| `'priority'` \| `'flex'` |
| `BedrockModel.additional_request_fields` | Model-specific parameters not normalised in the common interface. Used for reasoning/thinking and beta features. | `{'thinking': {'type': 'enabled', 'budget_tokens': 4096}}` |
| `Agent.agent_id` | Unique agent identifier, used for session management and multi-agent. Default: `'default'`. | `support-bot-v2` |
| `Agent.concurrent_invocation_mode` | Behaviour in case of concurrent invocations. Default: `ConcurrentInvocationMode.THROW` (`ConcurrencyException`). `UNSAFE_REENTRANT` to skip the lock (no behavioural guarantees). | `ConcurrentInvocationMode.THROW` |
| `Agent.retry_strategy` | Retry strategy for throttling or transient errors. Default: `max_attempts=6`, `initial_delay=4s`, `max_delay=240s`. | `ModelRetryStrategy(max_attempts=6, initial_delay=4, max_delay=240)` |
| `Limits.turns` | Max loop iterations per single invocation (`stop_reason='limit_turns'`). Positive int, optional. Highest priority among the three caps. | `15` |
| `Limits.output_tokens` | Max cumulative generated tokens (soft cap, `stop_reason='limit_output_tokens'`). Lowest priority among the three caps. | `8000` |
| `Limits.total_tokens` | Max cumulative input+output tokens (soft cap, `stop_reason='limit_total_tokens'`). Medium priority among the three caps. | `50000` |
| `SlidingWindowConversationManager.window_size` | Maximum number of messages in the conversation window. Older messages are removed. | `40` |
| `SlidingWindowConversationManager.per_turn` | `False` (default): applies management only after the loop. `True`: before each model call. `int N`: every N model calls. | `False` \| `True` \| `3` |
| `SlidingWindowConversationManager.should_truncate_results` | Truncates large tool results keeping head/tail (200 chars default). Proactive alternative: `ContextOffloader` plugin. | `True` (default) |
| `S3SessionManager` — required IAM permissions | S3 permissions needed for session persistence. `s3:ListBucket` is required in addition to the three CRUD operations. | `s3:GetObject, s3:PutObject, s3:DeleteObject, s3:ListBucket` on the sessions bucket |
| `bedrock:InvokeModelWithResponseStream` (IAM) | IAM permission for `BedrockModel` in streaming mode (default). Mandatory. `BedrockModel` uses Converse API streaming. | `{"Effect": "Allow", "Action": ["bedrock:InvokeModelWithResponseStream"], "Resource": "*"}` |
| `bedrock:InvokeModel` (IAM) | IAM permission for `BedrockModel` in non-streaming mode (`streaming=False`). | `{"Effect": "Allow", "Action": ["bedrock:InvokeModel"], "Resource": "*"}` |

---

## Gotchas

- `AWS_REGION` is the lowest-priority fallback in the boto3 resolution chain for `BedrockModel`. The full chain is: `BedrockModel(region_name=...)` > boto3 session region (AWS_DEFAULT_REGION or profile) > `AWS_REGION` > default `us-west-2`. If your agent uses an unexpected region, check the profile first and then use `BedrockModel(region_name=...)` or `AWS_DEFAULT_REGION`. _Source: https://strandsagents.com/docs/user-guide/concepts/model-providers/amazon-bedrock/index.md_

- `BedrockModel` uses the Bedrock Converse API internally, NOT the legacy InvokeModel API. Do not try to configure `InvokeModel` — use `BedrockModel` parameters that map onto Converse (`model_id`, `max_tokens`, `temperature`, `stop_sequences`, `guardrail_*`, `cache_config`, `additional_request_fields`).

- Do not use the callback handler (default `PrintingCallbackHandler`) together with `stream_async()`: it will cause double output. Set `callback_handler=None` when using the async iterator pattern. The callback handler is Python-only: TypeScript uses exclusively the async iterator pattern.

- Cancellation via `agent.cancel()` is **cooperative** for tools: if a tool is already executing, it continues until completion. Only tools can respect cancellation internally. TypeScript also supports external `AbortSignal` for framework-driven cancellation.

- Agents inside a Graph or Swarm must NOT have their own `session_manager` — Python raises `ValueError`. Only the orchestrator (Graph/Swarm) should have the `session_manager`.

- `MaxTokensReachedException` / `stop_reason='max_tokens'` is NOT recoverable within the current loop. The loop ends immediately. `Limits` (`limit_turns`, `limit_total_tokens`, `limit_output_tokens`) are different: they terminate gracefully and leave `agent.messages` in a reinvocable state.

- `Agent` constructor with `model=None` uses `BedrockModel` as default. Passing `model='model-id-string'` automatically creates a `BedrockModel` with that `model_id`. These two patterns are equivalent: `Agent()` and `Agent(model='anthropic.claude-sonnet-4-6')`.

- `invocation_state` is a dictionary **shared by reference** between all hooks and tools during the same invocation. Changes in one hook are visible to subsequent hooks and tools. Not thread-safe if using `UNSAFE_REENTRANT`.

- For non-Bedrock providers (Anthropic, OpenAI, LiteLLM, Ollama, Gemini, etc.) the corresponding extra package MUST be installed separately: `pip install 'strands-agents[anthropic]'`. Importing without the package raises `ModuleNotFoundError`.

- `SlidingWindowConversationManager` by default applies window management AFTER the full loop (`per_turn=False`). For long-running agents with many tool calls use `per_turn=True` or the `ContextOffloader` plugin, otherwise `ContextWindowOverflowException` may occur during the loop.

- `BedrockModel` requires the model to be enabled in the Bedrock console for the target region (Model Access). Without enablement you get `AccessDeniedException` even with a correct IAM policy.

- `cleanup()` must be called explicitly when using tools with MCP clients or external resources. The `__del__` finalizer is only a fallback and is not guaranteed in all runtimes.

- `cache_config` with `strategy='auto'` is ONLY for Claude models on Bedrock. Amazon Nova supports caching but does not accept cache checkpoints in the `tools` field — use cache points in `messages` instead. Minimum tokens: Claude Sonnet 1024, Claude Haiku 4096. Expiry: 5 minutes of inactivity.

- `service_tier` is available from approximately v1.35. If the model or region does not support the specified tier, Bedrock returns `ValidationException`. Verify https://docs.aws.amazon.com/bedrock/latest/userguide/service-tiers-inference.html for the support matrix.

- Snapshots (`take_snapshot`/`load_snapshot`) are in-memory and manual — they are NOT automatic persistence. For automatic persistence use `session_manager`. The two mechanisms are complementary: snapshots for precise save-points in the same process, `session_manager` for cross-session persistence.

- `S3SessionManager` requires `s3:ListBucket` IN ADDITION TO `s3:GetObject`, `s3:PutObject`, `s3:DeleteObject`. Previous versions of the documentation omitted this permission.

- `BidiAgent` is in the `strands.experimental.bidi` namespace with explicitly experimental status ("may change in future versions"). Do not use in production without a migration plan. Pip extras: `strands-agents[bidi]`, `strands-agents[bidi-all]`, `strands-agents[bidi-gemini]`, `strands-agents[bidi-openai]`.

- `LiteLLMModel` caching via `SystemContentBlock` is documented as "provider-agnostic" but the actual behaviour depends entirely on the underlying provider. The documentation does not guarantee which providers actually support caching through the LiteLLM proxy in production.

---

## Official sources

- [Strands Agents SDK — User Guide: Agent Loop](https://strandsagents.com/docs/user-guide/concepts/agents/agent-loop/index.md) — Complete agent cycle: stop reasons, cooperative cancellation, context window management, lifecycle
- [Strands Agents SDK — API Reference: Agent class (Python)](https://strandsagents.com/docs/api/python/strands.agent.agent/) — All Agent constructor parameters, `__call__`, `invoke_async`, `stream_async`, `structured_output`, `add_hook`, `as_tool`, `take_snapshot`, `load_snapshot`, `cleanup`, `cancel`
- [Strands Agents SDK — Python Quickstart](https://strandsagents.com/docs/user-guide/quickstart/python/index.md) — Installation, credentials, `AgentResult.metrics`, model providers, streaming with async iterator and callback handler, debug logging
- [Strands Agents SDK — Model Providers Overview](https://strandsagents.com/docs/user-guide/concepts/model-providers/index.md) — Complete table of supported Python/TypeScript providers, pip install commands, community vs official providers
- [Strands Agents SDK — Amazon Bedrock Provider](https://strandsagents.com/docs/user-guide/concepts/model-providers/amazon-bedrock/index.md) — IAM permissions, boto3 credentials, all `BedrockModel` parameters, caching (`cache_config`/`cache_tools`), `service_tier`, reasoning via `additional_request_fields`, guardrails, Converse API
- [Strands Agents SDK — API Reference: BedrockModel (Python)](https://strandsagents.com/docs/api/python/strands.models.bedrock/) — Complete `BedrockConfig`: `service_tier`, `cache_tools`, `cache_config`, `guardrail_*` parameters with all possible values
- [Strands Agents SDK — Anthropic Provider](https://strandsagents.com/docs/user-guide/concepts/model-providers/anthropic/index.md) — `AnthropicModel` with `client_args`, `model_id`, `max_tokens`, `params`, `use_native_token_count`
- [Strands Agents SDK — OpenAI Provider](https://strandsagents.com/docs/user-guide/concepts/model-providers/openai/index.md) — `OpenAIModel` and OpenAI Responses API, `client_args`/`params` parameters, stop token for GPT-OSS
- [Strands Agents SDK — LiteLLM Provider](https://strandsagents.com/docs/user-guide/concepts/model-providers/litellm/index.md) — `LiteLLMModel` with proxy support, caching via `SystemContentBlock` (behaviour depends on underlying provider)
- [Strands Agents SDK — Ollama Provider](https://strandsagents.com/docs/user-guide/concepts/model-providers/ollama/index.md) — `OllamaModel`, Python-only, complete parameters including `keep_alive` and `update_config` at runtime
- [Strands Agents SDK — llama.cpp Provider](https://strandsagents.com/docs/user-guide/concepts/model-providers/llamacpp/) — `LlamaCppModel`, official provider (not community), Python-only, multimodal, GBNF grammar, native token counting
- [Strands Agents SDK — Streaming Events](https://strandsagents.com/docs/user-guide/concepts/streaming/index.md) — All Python and TypeScript event types: lifecycle, model stream, tool, multi-agent; differences between the two SDKs
- [Strands Agents SDK — Async Iterators](https://strandsagents.com/docs/user-guide/concepts/streaming/async-iterators/index.md) — `stream_async()` with FastAPI `StreamingResponse`, mandatory `callback_handler=None`, event inspection
- [Strands Agents SDK — Callback Handlers (Python)](https://strandsagents.com/docs/user-guide/concepts/streaming/callback-handlers/index.md) — Synchronous Python-only callback, `PrintingCallbackHandler`, events: `init_event_loop`, `start_event_loop`, `data`, `current_tool_use`, `message`, `result`, `force_stop`
- [Strands Agents SDK — Hooks](https://strandsagents.com/docs/user-guide/concepts/agents/hooks/index.md) — All hook events (Python and TypeScript), modifiable properties, Plugin pattern, `HookProvider` protocol, `HookOrder` for TypeScript
- [Strands Agents SDK — Structured Output](https://strandsagents.com/docs/user-guide/concepts/agents/structured-output/index.md) — Pydantic `BaseModel` via `structured_output_model`, `StructuredOutputException`, streaming + SO, all supported providers
- [Strands Agents SDK — Conversation Management](https://strandsagents.com/docs/user-guide/concepts/agents/conversation-management/index.md) — `NullConversationManager`, `SlidingWindowConversationManager` (`window_size`, `per_turn`, `proactiveCompression`, `shouldTruncateResults`), `SummarizingConversationManager`
- [Strands Agents SDK — Agent State & Session](https://strandsagents.com/docs/user-guide/concepts/agents/state/index.md) — Conversation history, `AgentState` (`get`/`set`/`delete`), `invocation_state`, `ToolContext`, `record_direct_tool_call`
- [Strands Agents SDK — Session Management](https://strandsagents.com/docs/user-guide/concepts/agents/session-management/index.md) — `FileSessionManager`, `S3SessionManager`, directory structure, IAM permissions (includes `s3:ListBucket`), third parties (`AgentCoreMemorySessionManager`), Graph/Swarm rule
- [Strands Agents SDK — Snapshots](https://strandsagents.com/docs/user-guide/concepts/agents/snapshots/index.md) — `take_snapshot`/`load_snapshot`, preset `'session'`, `include`/`exclude` fields, `app_data`, difference from session management
- [Strands Agents SDK — API Reference: Limits TypedDict](https://strandsagents.com/docs/api/python/strands.types.agent/index.md) — `Limits` TypedDict: `turns`, `output_tokens`, `total_tokens`; `ConcurrentInvocationMode` enum; `stop_reason` values for each limit
- [Strands Agents SDK — Context Offloader Plugin](https://strandsagents.com/docs/user-guide/concepts/plugins/context-offloader/index.md) — `ContextOffloader` plugin for managing large tool results; `InMemoryStorage`, `FileStorage`, `max_result_tokens` and `preview_tokens` parameters
- [Strands Agents SDK — BidiAgent (Experimental)](https://strandsagents.com/docs/user-guide/concepts/bidirectional-streaming/agent/) — Namespace `strands.experimental.bidi`, experimental status, providers: Nova Sonic, OpenAI Realtime, Google Gemini Live
- [AWS Open Source Blog — Introducing Strands Agents 1.0](https://aws.amazon.com/blogs/opensource/introducing-strands-agents-1-0-production-ready-multi-agent-orchestration-made-simple/) — 1.0 GA announcement with session management, structured output, async, multi-agent primitives
- [strands-agents — PyPI](https://pypi.org/project/strands-agents/) — Current version 1.42.0 (1 June 2026), extras: `a2a`, `all`, `anthropic`, `bidi`, `bidi-all`, `bidi-gemini`, `bidi-io`, `bidi-openai`, `dev`, `docs`, `gemini`, `litellm`, `llamaapi`, `mistral`, `ollama`, `openai`, `otel`, `sagemaker`, `writer`; Python >=3.10
- [strands-agents/sdk-python — GitHub](https://github.com/strands-agents/sdk-python) — Source code, release changelog (v1.42.0 latest)
- [Strands Agents SDK — Blog: Interleaved Thinking with Claude 4](https://strandsagents.com/blog/interleaved-thinking-claude-4/index.md) — Interleaved thinking configuration via `additional_request_fields` for `BedrockModel` and `AnthropicModel`
