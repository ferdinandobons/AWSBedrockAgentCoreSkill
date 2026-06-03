# Amazon Bedrock AgentCore Memory

> Part of the **aws-bedrock-agentcore-skill** skill. See [SKILL.md](../SKILL.md) for the decision tree. Every source below is official — re-open it to verify details.

## Table of contents

- [Overview](#overview)
- [Key concepts](#key-concepts)
  - [Memory Resource](#memory-resource-agentcore-memory)
  - [Short-term Memory (STM)](#short-term-memory-stm)
  - [Long-term Memory (LTM)](#long-term-memory-ltm)
  - [Actor and Session](#actor-and-session)
  - [Memory Strategies](#memory-strategy)
  - [Built-in Strategies](#built-in-strategies)
  - [Namespace](#namespace)
  - [Event Metadata](#event-metadata)
  - [LTM Metadata and Indexed Keys](#ltm-metadata-and-indexed-keys)
  - [Two Boto3 Clients](#two-boto3-clients)
  - [AgentCoreMemorySessionManager (Strands)](#agentcorememorysessionmanager-strands-integration)
  - [LangChain/LangGraph Integration](#langchainlanggraph-integration)
  - [Memory Record Streaming](#memory-record-streaming)
  - [Self-managed Strategy Triggers](#self-managed-strategy-triggers)
- [Best practices](#best-practices)
- [Code](#code)
  - [Create memory with 3 built-in strategies + poll ACTIVE](#create-memory-resource-with-all-3-common-built-in-strategies-boto3-control-plane----poll-until-active)
  - [Write conversational events to STM](#write-conversational-events-to-short-term-memory-createevent-data-plane)
  - [Retrieve short-term memory](#retrieve-short-term-memory-conversation-history-for-a-session)
  - [Semantic search on LTM records](#semantic-search-on-long-term-memory-records-retrievememoryrecords----exact-namespace-and-prefix-search)
  - [Add a strategy to existing memory](#add-a-strategy-to-an-existing-memory-resource-updatememory)
  - [Strands Agent with STM only](#strands-agent-with-short-term-memory-stm-only----no-retrieval-config)
  - [Strands Agent with LTM + RetrievalConfig](#strands-agent-with-full-ltm-strategies--retrievalconfig-per-namespace-and-batch_size-context-manager)
  - [Episodic memory strategy configuration](#episodic-memory-strategy-configuration-boto3----requires-separate-reflection-namespacetemplates)
  - [Built-in with overrides: custom extraction instructions](#built-in-with-overrides-custom-extraction-instructions-for-domain-specific-semantic-extraction)
  - [Self-managed strategy configuration (CLI)](#self-managed-strategy-trigger-conditions-and-snss3-delivery-configuration-cli)
  - [LTM metadata with indexed keys (CLI)](#ltm-metadata-create-memory-with-indexed-keys-and-metadata-schema-cli-for-filterable-llm-extraction)
  - [CDK Memory construct (TypeScript)](#cdk-memory-construct-with-custom-execution-role-and-grantwritegrantreadlongtermmemory-typescript)
  - [IAM policy for agent data plane](#iam-policy-for-agent-data-plane----create-events-and-retrieve-ltm-records-with-namespace-restriction)
  - [LangGraph AgentCoreMemorySaver + AgentCoreMemoryStore](#langchainlanggraph-integration-agentcorememorysaver-stm-checkpointer--agentcorememorystore-ltm)
  - [AgentCore SDK MemoryClient](#agentcore-sdk-bedrock-agentcore----memoryclient-and-memorysessionmanager-for-pure-python-agents)
- [Configuration reference](#configuration-reference)
- [Gotchas](#gotchas)
- [Official sources](#official-sources)

---

## Overview

Amazon Bedrock AgentCore Memory is a fully managed, stateful memory service for AI agents, offering two complementary memory types: **short-term memory** (raw immutable events per session, stored via `CreateEvent`) and **long-term memory** (structured insights extracted asynchronously using configurable strategies). It integrates natively with the Strands Agents SDK via `AgentCoreMemorySessionManager`, with LangChain/LangGraph via `AgentCoreMemorySaver` and `AgentCoreMemoryStore` (package `langgraph-checkpoint-aws`), and with boto3 through two separate clients: `bedrock-agentcore-control` (control plane, resource lifecycle) and `bedrock-agentcore` (data plane, event and record operations). Memory strategies — Semantic, User Preference, Summary/Summarization, and Episodic — drive LTM extraction; each strategy writes records into namespaces you define using template variables like `{actorId}`, `{sessionId}`, and `{memoryStrategyId}`. Pricing is consumption-based: $0.25 per 1,000 create events (STM), $0.75/$0.25 per 1,000 records stored per month for built-in/custom strategies (LTM), and $0.50 per 1,000 retrieve calls.

**Maturity:** Generally Available (GA). Preview began July 2025, full GA in early 2026. Memory Record Streaming GA March 2026. LTM metadata/filtering GA May 2026. LangChain/LangGraph integration GA (package: `langgraph-checkpoint-aws`). LangGraph agent framework integration uses Converse API via `bedrock_converse` model provider. AgentCore Optimization and AWS Agent Registry are still in public **Preview** as of June 2026 — do not treat them as production defaults.

---

## Key concepts

### Memory Resource (AgentCore Memory)

Top-level container for an agent's memory. Created once via `bedrock-agentcore-control` `CreateMemory` API (or via AgentCore CLI: `agentcore add memory --name X --strategies Y && agentcore deploy`). Holds all short-term events and long-term records for a given application or agent. Has a status lifecycle: `CREATING` → `ACTIVE | FAILED`. The memory ID is the primary handle for all data plane operations. Maximum 150 memory resources per region per account (adjustable).

### Short-term Memory (STM)

Raw, immutable, timestamped events stored per `(actorId, sessionId)` pair via the `CreateEvent` API. Supports two payload types:

- **`conversational`** — role + text content; the **only** payload type that flows into LTM extraction.
- **`blob`** — binary/JSON data for custom use such as LangGraph checkpoints; stored in STM only, never extracted to LTM.

Events are retained up to the configured expiration (7–365 days, default 90). Supports event branching via `branch.rootEventId` and `branch.name` for conversation editing. Hard limits: max 100 messages per `CreateEvent` call, max 100 KB per message, max 10 MB per event.

### Long-term Memory (LTM)

Structured insights **asynchronously extracted** from conversational STM events by memory strategies. Stored as memory records in namespaces. Extraction runs after `CreateEvent` completes — typically 60+ seconds later. Only events created **after** a strategy becomes `ACTIVE` are processed. LTM enables semantic search via `RetrieveMemoryRecords` (cosine similarity) and metadata-filtered listing via `ListMemoryRecords`.

### Actor and Session

- **Actor** — entity interacting with the agent (user, another agent, system). Identified by `actorId`. Template variable: `{actorId}`.
- **Session** — a single continuous conversation grouped by `sessionId`. All `CreateEvent` calls within a session share the same `sessionId`. In LangGraph, `thread_id` maps to `sessionId`. Template variable: `{sessionId}`.

### Memory Strategy

Configuration on the memory resource that defines **how** to extract LTM records from STM events. Three flavors:

| Flavor | Infrastructure | Cost (LTM storage) | Customization |
|---|---|---|---|
| Built-in | Fully managed, no extra infra | $0.75/1,000 records/month | None |
| Built-in with overrides | Uses your Bedrock account for inference | $0.25/1,000 records/month | `appendToPrompt` (≤30 KB, **replaces** default prompt — see best practices), model override |
| Self-managed | SNS + S3 + Lambda (yours) | $0.25/1,000 records/month | Full custom pipeline |

Maximum **6 strategies per memory resource** (not adjustable).

### Built-in Strategies

| Strategy | Description | Stages | CLI flag |
|---|---|---|---|
| `SemanticMemoryStrategy` | Extracts factual information, entities, key details; builds persistent knowledge base | Extraction + Consolidation | `SEMANTIC` |
| `UserPreferenceMemoryStrategy` | Identifies and persists user preferences, choices, styles across sessions | Extraction + Consolidation | `USER_PREFERENCE` |
| `SummaryMemoryStrategy` / `SUMMARIZATION` | Creates condensed running summaries within a session for quick context recall | Consolidation only | `SUMMARIZATION` |
| `EpisodicStrategy` | Captures structured episodes (scenario, intent, actions, outcomes, artifacts) + cross-episode reflection | Extraction + Consolidation + Reflection | No CLI shorthand; configure via SDK/boto3 |

The Episodic strategy's Reflection step requires a **separate** `namespaceTemplates` under a `reflection` key (see [code example](#episodic-memory-strategy-configuration-boto3----requires-separate-reflection-namespacetemplates)).

### Namespace

Hierarchical path string used to organize LTM records. Rules:

- Defined in `namespaceTemplates` when creating a strategy.
- **Must start and end with `/`** — e.g., `/users/{actorId}/preferences/`.
- Supported template variables: `{actorId}`, `{sessionId}`, `{memoryStrategyId}`.
- `RetrieveMemoryRecords` supports exact `namespace` or hierarchical `namespacePath` (prefix match).
- **IAM condition keys** express paths **without** a leading slash — e.g., `summaries/agent1/*`.

Granularity options:

| Granularity | Template example |
|---|---|
| Global | `/` |
| Per-strategy | `/strategy/{memoryStrategyId}/` |
| Per-actor | `/users/{actorId}/` |
| Per-session | `/summaries/{actorId}/{sessionId}/` |

### Event Metadata

Optional key-value string pairs attached to STM events at `CreateEvent` time. Used for filtering via `ListEvents`. **Not encrypted** with customer-managed KMS. Does not flow to LTM unless also declared in the strategy `metadataSchema`.

### LTM Metadata and Indexed Keys

Structured attributes on LTM records:

- Up to **10 indexed keys** per memory resource (declared at `CreateMemory`/`UpdateMemory` time). Types: `STRING`, `NUMBER`, `STRINGLIST`.
- Keys in the strategy's `metadataSchema` are **auto-extracted by the LLM**.
- Indexed keys are filterable via `metadataFilters` (up to 5 AND-combined filters) on `RetrieveMemoryRecords` and `ListMemoryRecords`.
- System fields `x-amz-agentcore-memory-createdAt` / `x-amz-agentcore-memory-updatedAt` (dateTimeValue, supports `BEFORE`/`AFTER` operators) are **always available** without declaring an indexed key.
- Once added, indexed keys **cannot be removed** and **do not backfill** existing records.

### Two Boto3 Clients

AgentCore Memory requires **two separate** Boto3 clients:

| Client | Service name | Operations |
|---|---|---|
| Control plane | `bedrock-agentcore-control` | `CreateMemory`, `UpdateMemory`, `GetMemory`, `DeleteMemory`, `ListMemories` |
| Data plane | `bedrock-agentcore` | `CreateEvent`, `GetEvent`, `ListEvents`, `ListSessions`, `RetrieveMemoryRecords`, `ListMemoryRecords`, `GetMemoryRecord`, `BatchCreateMemoryRecords`, `BatchUpdateMemoryRecords`, `BatchDeleteMemoryRecords` |

Using the wrong client will cause `Unknown service` errors.

### AgentCoreMemorySessionManager (Strands integration)

Class from `bedrock_agentcore.memory.integrations.strands.session_manager`. Takes `AgentCoreMemoryConfig` and `region_name`. Implements the Strands `session_manager` interface — passed directly to the `Agent()` constructor. Key parameters:

- `retrieval_config` — dict mapping namespace paths to `RetrievalConfig` objects defining `top_k` (default 10, max 1000) and `relevance_score` (default 0.2, range 0.0–1.0) for LTM retrieval at agent startup.
- `batch_size` — messages to buffer before sending (default 1). When `> 1`, **must use context manager or `close()`** or buffered messages are permanently lost.
- Only **one Strands agent per session** is supported.

### LangChain/LangGraph Integration

Package: `langgraph-checkpoint-aws`. Two classes:

- **`AgentCoreMemorySaver`** — LangGraph checkpointer for STM persistence using blob payloads. Saves/loads full graph state. **Does not trigger LTM extraction** (blob payload).
- **`AgentCoreMemoryStore`** — LTM store for saving conversational messages and performing async extraction + semantic search.

Both require only a `memory_id` and `region_name`. Runtime config must supply `actor_id` and `thread_id` (maps to `actorId` and `sessionId` respectively). Models are invoked via `bedrock_converse` model provider (Converse API).

### Memory Record Streaming

Real-time push delivery of LTM record lifecycle events (`MemoryRecordCreated`, `MemoryRecordUpdated`, `MemoryRecordDeleted`) to a Kinesis Data Stream in your account. Eliminates polling. GA March 2026.

- For built-in strategies: requires `kinesis:PutRecords` + `kinesis:DescribeStream` in `memoryExecutionRoleArn`.
- For custom strategies: additionally requires `bedrock:InvokeModel`.
- Supports `METADATA_ONLY` or `FULL_CONTENT` level (Deleted events always contain only identifiers).
- A `StreamingEnabled` validation event is published to the Kinesis stream on successful setup.

### Self-managed Strategy Triggers

Three trigger types for self-managed strategies (first to fire wins):

| Trigger | Config key | Description |
|---|---|---|
| `messageBasedTrigger` | `messageCount` | Fires after N conversational turns |
| `tokenBasedTrigger` | `tokenCount` | Fires after N tokens in the window |
| `timeBasedTrigger` | `idleSessionTimeout` | Fires after N minutes of session inactivity |

When triggered, AgentCore puts the conversation payload to S3 and publishes a JSON notification to SNS. The SNS message contains: `jobId`, `s3PayloadLocation`, `memoryId`, `strategyId`. Use FIFO SNS for ordering-sensitive use cases such as summarization.

---

## Best practices

- **Use trailing slashes in all namespace paths and prefer hierarchical namespaces** — The trailing slash prevents prefix collisions in multi-tenant apps — `/actors/Alice/` will not accidentally match `/actors/AliceBob/`. Use the most granular namespace when storing and `namespacePath` for broad retrieval across multiple sessions. _Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory-organization.html_

- **Poll for `ACTIVE` status after `CreateMemory` before writing events or starting agents** — Memory creation is async (2–3 min). If you call `CreateEvent` before the resource is `ACTIVE` or before a new strategy is `ACTIVE`, those events will NOT be processed for LTM extraction. Use a polling loop checking `GetMemory` status, or use the SDK helper `create_memory_and_wait()`. _Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/long-term-enabling-long-term-memory.html_

- **Account for LTM extraction latency — do not read LTM immediately after writing** — LTM extraction is asynchronous and can take 60+ seconds after `CreateEvent`. The official customer scenario example uses an explicit `time.sleep(60)` before querying LTM. In production, retrieve LTM at the start of a new session (for context from prior sessions), not immediately after writing. _Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory-customer-scenario.html_

- **Combine multiple strategies on a single memory resource to capture complementary memory types** — A single memory can have `SEMANTIC` + `SUMMARIZATION` + `USER_PREFERENCE` strategies simultaneously (max 6). This gives agents facts, conversation condensations, and personalization data without managing separate memory resources. CLI: `agentcore add memory --name X --strategies SEMANTIC,SUMMARIZATION,USER_PREFERENCE`. _Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/strands-sdk-memory.html_

- **Use customer-managed KMS keys for sensitive workloads** — All data is always encrypted at rest, but a customer-managed KMS key (`encryptionKeyArn` in `CreateMemory` / `kmsKey` in CDK) gives you full audit and revocation control. Event metadata is NOT encrypted with customer KMS — avoid storing sensitive content in event metadata. _Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/best-practices.html_

- **Sanitize and validate all user input before writing it to memory via `CreateEvent`** — LTM extraction uses an LLM on the conversational payload. Malicious users can embed prompt injection instructions to corrupt memory stores or escalate privilege. Apply Amazon Bedrock Guardrails before persisting events. AWS secures infrastructure; you are responsible for input validation. _Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/best-practices.html_

- **Use IAM condition keys (`namespace`, `namespacePath`, `actorId`, `sessionId`) for least-privilege access control** — Scope IAM policies to specific namespaces using `bedrock-agentcore:namespace` (exact match with `StringEquals`) or `bedrock-agentcore:namespacePath` (prefix match via `StringLike`). Note: IAM condition values are expressed **without** a leading slash (e.g., `summaries/agent1/*`). This enables multi-tenant isolation so Agent A cannot read Actor B's memories. _Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory-organization.html_

- **Always use a context manager (`with` block) or call `close()` when using `batch_size > 1` with `AgentCoreMemorySessionManager`** — When `batch_size > 1`, messages are buffered. If the session ends without flush, buffered messages are permanently lost. The context manager guarantees flush on exit, including on exceptions. Alternatively, wrap in `try/finally` with `session_manager.close()`. _Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/strands-sdk-memory.html_

- **Use built-in with overrides (not full self-managed) when you only need to customize extraction domain or language** — Built-in with overrides lets you replace the extraction/consolidation system prompt via `appendToPrompt` (up to 30 KB; despite the name, it replaces the default — see the best practice below) and change the Bedrock model without building SNS/S3/Lambda infrastructure. Full self-managed is only needed when you require a custom output schema, non-Bedrock models, or external database integration. Overrides also cost less per stored record ($0.25 vs $0.75). _Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory-custom-strategy.html_

- **`appendToPrompt` REPLACES the default system prompt entirely — always copy the full base prompt, then append your domain lines** — Despite the parameter name, the official docs state: "The content of `appendToPrompt` replaces the default instructions in the system prompt." The base extraction/consolidation prompts contain critical logic (schema definitions, role instructions, output constraints). To customise safely: retrieve the full base prompt text for your strategy type (see the system-prompt pages linked from the official docs), append your domain-specific lines, and pass the complete combined text as `appendToPrompt`. Never pass only your new lines — this discards the base logic and will silently corrupt the LTM pipeline. Also never rename consolidation operations (`AddMemory`, `UpdateMemory`) or attempt to modify the output schema. _Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory-custom-strategy.html_

- **Use validation constraints on LTM metadata schema keys for consistent filter matching** — Without `allowedValues`, the LLM may produce `'High'`, `'high'`, `'HIGH'` for the same concept, breaking filter equality checks. Define `stringValidation.allowedValues` for `STRING` keys (max 10 values, each max 256 chars), `stringListValidation` for `STRINGLIST`, and `numberValidation.minValue/maxValue` for `NUMBER`. The `definition` field should be specific and descriptive. _Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/long-term-memory-metadata.html_

- **Use `RetrieveMemoryRecords` (semantic search) for context injection; use `ListMemoryRecords` for browse/audit; optionally filter by `memoryStrategyId`** — `RetrieveMemoryRecords` performs vector similarity search, ideal for finding top-K most relevant facts at inference time. You can scope it to a specific strategy with the optional `memoryStrategyId` parameter. `ListMemoryRecords` does no semantic ranking — use it for auditing or backfill. `topK` default is 10, max 100; note that `topK` is a **per-page limit** — paginate through all results using `nextToken` when you need more than one page. _Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/long-term-retrieve-records.html_

- **Use Memory Record Streaming instead of polling when building downstream workflows triggered by LTM changes** — Polling `ListMemoryRecords` is expensive and introduces latency. Kinesis streaming delivers push events in real time, enabling event-driven pipelines, data lake ingestion, and audit trails. Verify the `StreamingEnabled` test event is received after creating the memory. _Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory-record-streaming.html_

- **Use LTM for personal user context and RAG (Bedrock Knowledge Bases) for authoritative factual content — they are complementary** — LTM answers "who is the user and what happened before". RAG answers "what do trusted sources say now". Mixing them gives agents both personalization and factual grounding. _Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory-ltm-rag.html_

- **Set event expiration to match your compliance requirements, not the maximum** — Raw STM events can be retained from 7 to 365 days (default 90). Storing raw conversations longer than needed increases cost and attack surface. Once LTM records are extracted, the full event history is often not needed for agent personalization. The official example uses 30 days. _Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory-create-a-memory-store.html_

- **Monitor token quota for built-in strategy LTM extraction; request increases before going to production** — Built-in strategies have a quota of 150,000 tokens/min for LTM extraction (adjustable). Episodic strategies have an additional per-session limit of 50,000 tokens/min (not adjustable). For built-in with overrides, your Bedrock account quotas apply — throttling causes ingestion failures. Monitor the `TokenCount` CloudWatch metric in the `Bedrock-AgentCore` namespace. _Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/bedrock-agentcore-limits.html_

- **Plan your indexed key budget carefully before creating the memory** — A memory resource supports up to 10 indexed keys total; they cannot be removed once added, and adding a new key does not backfill existing records. Declare at most the 3–5 filter dimensions you truly need. Keys in the `metadataSchema` but not in `indexedKeys` are visible on records but cannot be used in filter expressions. _Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/long-term-memory-metadata.html_

---

## Code

### Create memory resource with all 3 common built-in strategies (Boto3 control plane) — poll until ACTIVE

```python
import boto3
import time

# Control plane client (resource lifecycle)
control_client = boto3.client('bedrock-agentcore-control', region_name='us-east-1')
# Data plane client (events and records) — separate client required
data_client = boto3.client('bedrock-agentcore', region_name='us-east-1')

# Create the memory resource with defined strategies
response = control_client.create_memory(
    name='ShoppingSupportAgentMemory',
    description='Memory for a customer support agent.',
    eventExpiryDuration=90,  # days; range 7–365, default 90
    memoryStrategies=[
        {
            'summaryMemoryStrategy': {
                'name': 'SessionSummarizer',
                'namespaceTemplates': ['/summaries/{actorId}/{sessionId}/']
            }
        },
        {
            'userPreferenceMemoryStrategy': {
                'name': 'UserPreferenceExtractor',
                'namespaceTemplates': ['/users/{actorId}/preferences/']
            }
        },
        {
            'semanticMemoryStrategy': {
                'name': 'FactExtractor',
                'namespaceTemplates': ['/facts/{actorId}/']
            }
        }
    ]
)

memory_id = response['memory']['id']
print(f'Memory ID: {memory_id}')

# Poll for ACTIVE status before writing any events (typically 2-3 minutes)
while True:
    mem_status = control_client.get_memory(memoryId=memory_id)
    status = mem_status.get('memory', {}).get('status')
    if status == 'ACTIVE':
        print('Memory ACTIVE')
        break
    elif status == 'FAILED':
        raise Exception(f"Memory creation FAILED: {mem_status['memory'].get('failureReason')}")
    print(f'Status: {status} — waiting...')
    time.sleep(10)
```

_Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory-create-a-memory-store.html_

---

### Write conversational events to short-term memory (CreateEvent data plane)

```python
import boto3
from datetime import datetime

# Data plane client (events and records)
data_client = boto3.client('bedrock-agentcore', region_name='us-east-1')

memory_id = 'mem-xxxxxxxxxxxx'  # from CreateMemory response
actor_id = 'user-sarah-123'
session_id = 'support-session-001'

# Store a multi-turn conversation as a single event
# NOTE: Only 'conversational' payload type flows into LTM extraction.
# 'blob' payloads are stored in STM only.
data_client.create_event(
    memoryId=memory_id,
    actorId=actor_id,
    sessionId=session_id,
    eventTimestamp=datetime.now(),
    payload=[
        {
            'conversational': {
                'role': 'USER',
                'content': {'text': 'Hi, my order #ABC-456 is delayed.'}
            }
        },
        {
            'conversational': {
                'role': 'ASSISTANT',
                'content': {'text': "I'm sorry about that, Sarah. Let me check the status."}
            }
        },
        {
            'conversational': {
                'role': 'USER',
                'content': {'text': 'For future orders please always use FedEx.'}
            }
        },
        {
            'conversational': {
                'role': 'ASSISTANT',
                'content': {'text': 'Noted — I will remember your preference for FedEx.'}
            }
        }
    ]
    # Optional: metadata for STM filtering (NOT encrypted with KMS, NOT sent to LTM)
    # metadata parameter name is 'metadata' (NOT 'eventMetadata'); value shape is {key: {stringValue: str}}
    # metadata={'ticketType': {'stringValue': 'shipping'}}
)
```

_Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory-customer-scenario.html_

---

### Retrieve short-term memory (conversation history) for a session

```python
import boto3

data_client = boto3.client('bedrock-agentcore', region_name='us-east-1')

memory_id = 'mem-xxxxxxxxxxxx'
actor_id = 'user-sarah-123'
session_id = 'support-session-001'

# List sessions for an actor
sessions_response = data_client.list_sessions(
    memoryId=memory_id,
    actorId=actor_id
)

# List events for a specific session (paginated, most-recent first)
events_response = data_client.list_events(
    memoryId=memory_id,
    actorId=actor_id,
    sessionId=session_id,
    maxResults=10  # use nextToken for pagination
)

# Display in chronological order (list_events returns most-recent first)
for event in reversed(events_response.get('events', [])):
    print(event)
```

_Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory-customer-scenario.html_

---

### Semantic search on long-term memory records (RetrieveMemoryRecords) — exact namespace and prefix search

```python
import boto3
import time

data_client = boto3.client('bedrock-agentcore', region_name='us-east-1')

memory_id = 'mem-xxxxxxxxxxxx'
actor_id = 'user-sarah-123'
session_id = 'support-session-001'

# Wait for async extraction (typically 60+ seconds after CreateEvent)
time.sleep(60)

# Example 1: Retrieve from an exact namespace (user preferences)
pref_response = data_client.retrieve_memory_records(
    memoryId=memory_id,
    namespace=f'/users/{actor_id}/preferences/',  # exact match
    searchCriteria={
        'searchQuery': 'Does the user have a preferred shipping carrier?',
        'topK': 5  # default 10, max 100
        # 'memoryStrategyId': 'strategy-xxx'  # optional: scope to one strategy
    }
)
for record in pref_response.get('memoryRecordSummaries', []):
    # score is cosine similarity (NOT a percentage) — field name is 'score' per MemoryRecordSummary API
    print(f"Score: {record.get('score')} | {record.get('content')}")

# Example 2: Retrieve across all sessions for an actor (namespacePath prefix search)
issue_response = data_client.retrieve_memory_records(
    memoryId=memory_id,
    namespacePath=f'/summaries/{actor_id}/',  # prefix match — all sessions
    searchCriteria={
        'searchQuery': 'What problems did the user report with their orders?',
        'topK': 10
    }
)
for record in issue_response.get('memoryRecordSummaries', []):
    print(record)
```

_Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory-customer-scenario.html_

---

### Add a strategy to an existing memory resource (UpdateMemory)

```python
import boto3

control_client = boto3.client('bedrock-agentcore-control', region_name='us-east-1')
memory_id = 'mem-xxxxxxxxxxxx'

response = control_client.update_memory(
    memoryId=memory_id,
    # memoryStrategies for UpdateMemory is a ModifyMemoryStrategies object, NOT a plain array.
    # Use addMemoryStrategies / deleteMemoryStrategies / modifyMemoryStrategies keys.
    memoryStrategies={
        'addMemoryStrategies': [
            {
                'summaryMemoryStrategy': {
                    'name': 'SessionSummarizer',
                    'description': 'Summarizes conversation sessions for context',
                    'namespaceTemplates': ['/summaries/{actorId}/{sessionId}/']
                }
            }
        ]
    }
)

# NOTE: Only events created AFTER the new strategy becomes ACTIVE will be processed.
# Historical events are NOT retroactively processed.
mem_response = control_client.get_memory(memoryId=memory_id)
strategies = mem_response.get('memory', {}).get('strategies', [])
print(f'Strategies: {strategies}')
```

_Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/long-term-enabling-long-term-memory.html_

---

### Strands Agent with short-term memory (STM only) — no retrieval config

```python
# pip install bedrock-agentcore strands-agents
from datetime import datetime
from strands import Agent
from bedrock_agentcore.memory import MemoryClient
from bedrock_agentcore.memory.integrations.strands.config import AgentCoreMemoryConfig
from bedrock_agentcore.memory.integrations.strands.session_manager import AgentCoreMemorySessionManager

# One-time: create the memory resource (or read memory_id from env: MEMORY_BASICAGENTMEMORY_ID)
client = MemoryClient(region_name='us-east-1')
basic_memory = client.create_memory(
    name='BasicTestMemory',
    description='Basic memory for testing short-term functionality'
)
memory_id = basic_memory.get('id')

# Per-conversation: configure and create session manager
ACTOR_ID = 'actor_id_test_%s' % datetime.now().strftime('%Y%m%d%H%M%S')
SESSION_ID = 'testing_session_id_%s' % datetime.now().strftime('%Y%m%d%H%M%S')

config = AgentCoreMemoryConfig(
    memory_id=memory_id,
    session_id=SESSION_ID,
    actor_id=ACTOR_ID
)

session_manager = AgentCoreMemorySessionManager(
    agentcore_memory_config=config,
    region_name='us-east-1'
)

agent = Agent(
    system_prompt='You are a helpful assistant. Use all you know about the user to provide helpful responses.',
    session_manager=session_manager,
)

agent('I like sushi with tuna.')
agent('I like pizza.')
agent('What should I have for lunch today?')  # agent recalls sushi + pizza preferences
```

_Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/strands-sdk-memory.html_

---

### Strands Agent with full LTM strategies + RetrievalConfig per namespace and batch_size context manager

```python
# pip install bedrock-agentcore strands-agents
from datetime import datetime
from strands import Agent
from bedrock_agentcore.memory import MemoryClient
from bedrock_agentcore.memory.integrations.strands.config import AgentCoreMemoryConfig, RetrievalConfig
from bedrock_agentcore.memory.integrations.strands.session_manager import AgentCoreMemorySessionManager

# One-time: create memory with all 3 strategies and wait for ACTIVE
client = MemoryClient(region_name='us-east-1')
comprehensive_memory = client.create_memory_and_wait(
    name='ComprehensiveAgentMemory',
    description='Full-featured memory with all built-in strategies',
    strategies=[
        {'summaryMemoryStrategy': {'name': 'SessionSummarizer',
                                   'namespaceTemplates': ['/summaries/{actorId}/{sessionId}/']}},
        {'userPreferenceMemoryStrategy': {'name': 'PreferenceLearner',
                                          'namespaceTemplates': ['/preferences/{actorId}/']}},
        {'semanticMemoryStrategy': {'name': 'FactExtractor',
                                    'namespaceTemplates': ['/facts/{actorId}/']}}
    ]
)
memory_id = comprehensive_memory.get('id')

# Per-conversation setup with LTM retrieval configuration
ACTOR_ID = 'actor_id_test_%s' % datetime.now().strftime('%Y%m%d%H%M%S')
SESSION_ID = 'testing_session_id_%s' % datetime.now().strftime('%Y%m%d%H%M%S')

# retrieval_config: dict mapping namespace path -> RetrievalConfig
# relevance_score default 0.2, range 0.0–1.0; top_k default 10, range 1–1000
retrieval_config = {
    f'/preferences/{ACTOR_ID}/': RetrievalConfig(top_k=5, relevance_score=0.7),
    f'/facts/{ACTOR_ID}/': RetrievalConfig(top_k=10, relevance_score=0.3),
    f'/summaries/{ACTOR_ID}/{SESSION_ID}/': RetrievalConfig(top_k=3, relevance_score=0.5),
}

config = AgentCoreMemoryConfig(
    memory_id=memory_id,
    session_id=SESSION_ID,
    actor_id=ACTOR_ID,
    retrieval_config=retrieval_config,
    batch_size=10  # buffer up to 10 messages; MUST use context manager or close()
)

# Use context manager to guarantee flush of buffered messages on exit (even on exception)
with AgentCoreMemorySessionManager(config, region_name='us-east-1') as session_manager:
    agent = Agent(
        system_prompt='You are a helpful assistant.',
        session_manager=session_manager,
    )
    agent('My favourite airline is Lufthansa.')
    agent('Book me a window seat on my next flight.')
# STM events flushed here; LTM extraction starts async in background
```

_Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/strands-sdk-memory.html_

---

### Episodic memory strategy configuration (Boto3) — requires separate reflection namespaceTemplates

```python
import boto3

control_client = boto3.client('bedrock-agentcore-control', region_name='us-east-1')

response = control_client.create_memory(
    name='EpisodicSupportMemory',
    memoryStrategies=[
        {
            'episodicMemoryStrategy': {
                'name': 'EpisodicStrategy',
                'namespaceTemplates': [
                    '/strategy/{memoryStrategyId}/actors/{actorId}/sessions/{sessionId}/'
                ],
                # Reflection step requires its own namespace (cross-episode insights).
                # Note: official AWS docs omit the leading slash on the reflection
                # namespaceTemplate (e.g. 'strategy/.../actors/{actorId}/'); use the
                # exact form from your AWS console/docs to ensure matching.
                # The file's general rule requires leading + trailing slash, so
                # '/strategy/{memoryStrategyId}/actors/{actorId}/' is the safe form.
                'reflection': {
                    'namespaceTemplates': [
                        '/strategy/{memoryStrategyId}/actors/{actorId}/'
                    ]
                }
            }
        }
    ]
)
print(response['memory']['id'])
```

_Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/long-term-configuring-built-in-strategies.html_

---

### Built-in with overrides: custom extraction instructions for domain-specific semantic extraction

```python
import boto3

control_client = boto3.client('bedrock-agentcore-control', region_name='us-east-1')
execution_role_arn = 'arn:aws:iam::123456789012:role/AgentCoreMemoryExecutionRole'
# NOTE: memoryExecutionRoleArn is REQUIRED for built-in with overrides.
# Bedrock inference will be charged to YOUR account separately.

response = control_client.create_memory(
    name='TravelDomainMemory',
    memoryExecutionRoleArn=execution_role_arn,
    memoryStrategies=[
        {
            'semanticMemoryStrategy': {
                'name': 'TravelFactExtractor',
                'namespaceTemplates': ['/travel/{actorId}/facts/'],
                'configuration': {
                    'builtInWithOverrideConfiguration': {
                        'extraction': {
                            # appendToPrompt REPLACES the default system prompt entirely (despite the name).
                            # Best practice: copy the full base extraction prompt for your strategy type,
                            # then append your domain lines, and pass the complete combined text here.
                            # Passing only new lines discards all base logic and silently corrupts LTM.
                            'appendToPrompt': '<full base extraction prompt text here>\n- Focus exclusively on extracting facts related to travel and booking preferences.',
                            'modelId': 'anthropic.claude-3-5-haiku-20241022-v1:0'  # override model
                        }
                        # consolidation can also be overridden similarly
                        # WARNING: Do NOT rename AddMemory or UpdateMemory operations
                    }
                }
            }
        }
    ]
)
```

_Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory-custom-strategy.html_

---

### Self-managed strategy: trigger conditions and SNS/S3 delivery configuration (CLI)

```bash
# Create memory with self-managed strategy via AWS CLI
# IAM role requires: s3:GetBucketLocation, s3:PutObject, sns:GetTopicAttributes, sns:Publish
aws bedrock-agentcore-control create-memory \
  --name 'MyCustomMemory' \
  --description 'Memory with self-managed extraction strategy' \
  --memory-execution-role-arn 'arn:aws:iam::123456789012:role/AgentCoreMemoryRole' \
  --event-expiry-duration 90 \
  --memory-strategies '[
    {
      "customMemoryStrategy": {
        "name": "SelfManagedExtraction",
        "description": "Custom extraction strategy",
        "configuration": {
          "selfManagedConfiguration": {
            "triggerConditions": [
              {"messageBasedTrigger": {"messageCount": 6}},
              {"tokenBasedTrigger": {"tokenCount": 1000}},
              {"timeBasedTrigger": {"idleSessionTimeout": 30}}
            ],
            "historicalContextWindowSize": 2,
            "invocationConfiguration": {
              "payloadDeliveryBucketName": "my-agentcore-payloads",
              "topicArn": "arn:aws:sns:us-east-1:123456789012:agentcore-memory-jobs"
            }
          }
        }
      }
    }
  ]'
```

_Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory-self-managed-strategies.html_

---

### LTM metadata: create memory with indexed keys and metadata schema (CLI) for filterable LLM extraction

```bash
# Up to 10 indexed keys per memory; cannot be removed once added; does not backfill existing records.
# Keys in metadataSchema but NOT in indexedKeys are still stored but NOT filterable.
# System fields x-amz-agentcore-memory-createdAt/updatedAt always available (no declaration needed).
# Up to 5 AND-combined metadataFilters on RetrieveMemoryRecords and ListMemoryRecords.
aws bedrock-agentcore-control create-memory \
  --name 'CustomerSupportMemory' \
  --event-expiry-duration 30 \
  --indexed-keys '[
    {"key": "priority",   "type": "STRING"},
    {"key": "agent_type", "type": "STRING"},
    {"key": "tags",       "type": "STRINGLIST"},
    {"key": "channel",    "type": "STRING"},
    {"key": "ticket_id",  "type": "STRING"}
  ]' \
  --memory-strategies '[
    {
      "semanticMemoryStrategy": {
        "name": "SupportSemanticStrategy",
        "namespaceTemplates": ["/support/{actorId}/"],
        "memoryRecordSchema": {
          "metadataSchema": [
            {
              "key": "priority",
              "type": "STRING",
              "extractionConfig": {
                "llmExtractionConfig": {
                  "definition": "Issue priority level based on customer impact. Values range from critical (most severe) to low (least severe).",
                  "llmExtractionInstruction": "LATEST_VALUE",
                  "validation": {
                    "stringValidation": {
                      "allowedValues": ["critical", "high", "medium", "low"]
                    }
                  }
                }
              }
            }
          ]
        }
      }
    }
  ]'
```

_Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/long-term-memory-metadata.html_

---

### CDK Memory construct with custom execution role and grantWrite/grantReadLongTermMemory (TypeScript)

```typescript
import * as cdk from 'aws-cdk-lib';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as agentcore from 'aws-cdk-lib/aws-bedrockagentcore';

// Execution role needed for built-in with overrides strategies (Bedrock inference)
const executionRole = new iam.Role(this, 'MemoryExecutionRole', {
  assumedBy: new iam.ServicePrincipal('bedrock-agentcore.amazonaws.com'),
  managedPolicies: [
    iam.ManagedPolicy.fromAwsManagedPolicyName(
      'AmazonBedrockAgentCoreMemoryBedrockModelInferenceExecutionRolePolicy'
    ),
  ],
});

const memory = new agentcore.Memory(this, 'MyMemory', {
  memoryName: 'my_agent_memory',
  description: 'Production memory with custom execution role',
  expirationDuration: cdk.Duration.days(90),
  executionRole: executionRole,
  // memoryStrategies: [...]  // IMemoryStrategy[]
});

// Grant agent lambda write (CreateEvent) permissions
memory.grantWrite(agentLambda);
// Grant read of LTM records only
memory.grantReadLongTermMemory(agentLambda);

// CloudWatch metrics (namespace: Bedrock-AgentCore)
const eventCount = memory.metricEventCreationCount();
const recordCount = memory.metricMemoryRecordCreationCount();
```

_Source: https://docs.aws.amazon.com/cdk/api/v2/docs/aws-cdk-lib.aws_bedrockagentcore.Memory.html_

---

### IAM policy for agent data plane — create events and retrieve LTM records with namespace restriction

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "STMWriteForThisActor",
      "Effect": "Allow",
      "Action": ["bedrock-agentcore:CreateEvent"],
      "Resource": "arn:aws:bedrock-agentcore:us-east-1:123456789012:memory/mem-xxxx",
      "Condition": {
        "StringEquals": {
          "bedrock-agentcore:actorId": "${aws:PrincipalTag/userId}"
        }
      }
    },
    {
      "Sid": "LTMSemanticSearchOwnNamespace",
      "Effect": "Allow",
      "Action": ["bedrock-agentcore:RetrieveMemoryRecords"],
      "Resource": "arn:aws:bedrock-agentcore:us-east-1:123456789012:memory/mem-xxxx",
      "Condition": {
        "StringLike": {
          "bedrock-agentcore:namespacePath": "summaries/${aws:PrincipalTag/userId}/*"
        }
      }
    },
    {
      "Sid": "SpecificNamespaceExactAccess",
      "Effect": "Allow",
      "Action": ["bedrock-agentcore:RetrieveMemoryRecords"],
      "Resource": "arn:aws:bedrock-agentcore:us-east-1:123456789012:memory/mem-xxxx",
      "Condition": {
        "StringEquals": {
          "bedrock-agentcore:namespace": "summaries/agent1/"
        }
      }
    },
    {
      "Sid": "STMReadOwnSessions",
      "Effect": "Allow",
      "Action": [
        "bedrock-agentcore:ListEvents",
        "bedrock-agentcore:GetEvent",
        "bedrock-agentcore:ListSessions"
      ],
      "Resource": "arn:aws:bedrock-agentcore:us-east-1:123456789012:memory/mem-xxxx"
    }
  ]
}
```

_Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory-organization.html_

---

### LangChain/LangGraph integration: AgentCoreMemorySaver (STM checkpointer) + AgentCoreMemoryStore (LTM)

```python
# pip install langgraph-checkpoint-aws langchain-aws langgraph
from langchain.chat_models import init_chat_model
from langgraph.prebuilt import create_react_agent
from langgraph.store.base import BaseStore
from langchain_core.runnables import RunnableConfig
from langchain_core.messages import HumanMessage
from langgraph_checkpoint_aws import AgentCoreMemorySaver, AgentCoreMemoryStore
import uuid

REGION = 'us-west-2'
MEMORY_ID = 'YOUR_MEMORY_ID'  # from CreateMemory
MODEL_ID = 'us.anthropic.claude-3-7-sonnet-20250219-v1:0'

# STM persistence: saves/loads full LangGraph graph state via AgentCore blob payloads
checkpointer = AgentCoreMemorySaver(MEMORY_ID, region_name=REGION)

# LTM store: saves conversational messages; async extraction by AgentCore strategies
store = AgentCoreMemoryStore(MEMORY_ID, region_name=REGION)

# Pre-model hook: save human messages to AgentCore for async LTM extraction
def pre_model_hook(state, config: RunnableConfig, *, store: BaseStore):
    actor_id = config['configurable']['actor_id']
    thread_id = config['configurable']['thread_id']
    namespace = (actor_id, thread_id)
    messages = state.get('messages', [])
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            store.put(namespace, str(uuid.uuid4()), {'message': msg})
            break
    return {'llm_input_messages': messages}

# Uses bedrock_converse model provider (Converse API)
llm = init_chat_model(MODEL_ID, model_provider='bedrock_converse', region_name=REGION)

graph = create_react_agent(
    model=llm,
    tools=[],  # add your tools here
    checkpointer=checkpointer,
    store=store,
    pre_model_hook=pre_model_hook,
)

# actor_id maps to AgentCore actorId; thread_id maps to AgentCore sessionId
config = {
    'configurable': {
        'thread_id': 'session-1',
        'actor_id': 'react-agent-1',
    }
}

response = graph.invoke(
    {'messages': [('human', 'I like sushi with tuna. In general seafood is great.')]},
    config=config
)
# In a new session, LTM retrieval brings back preferences from session-1
config['configurable']['thread_id'] = 'session-2'
response = graph.invoke(
    {'messages': [('human', 'Lets make a meal tonight, what should I cook?')]},
    config=config
)
```

_Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory-integrate-lang.html_

---

### AgentCore SDK (bedrock-agentcore) — MemoryClient and MemorySessionManager for pure Python agents

```python
from bedrock_agentcore.memory import MemoryClient
from bedrock_agentcore.memory.session import MemorySessionManager
from bedrock_agentcore.memory.constants import ConversationalMessage, MessageRole
import time

# Higher-level SDK client
client = MemoryClient(region_name='us-east-1')

# create_memory_and_wait blocks until ACTIVE
memory = client.create_memory_and_wait(
    name='MyAgentMemory',
    strategies=[{
        'summaryMemoryStrategy': {
            'name': 'SessionSummarizer',
            'namespaceTemplates': ['/summaries/{actorId}/{sessionId}/']
        }
    }]
)

# create_event accepts messages as list of (text, role) tuples
client.create_event(
    memory_id=memory.get('id'),
    actor_id='User84',
    session_id='OrderSupportSession1',
    messages=[
        ('Hi, my order #12345 is delayed.', 'USER'),
        ("I'm sorry to hear that. Let me look up your order.", 'ASSISTANT'),
        ('The package arrived damaged.', 'USER'),
    ],
)

# Wait for async LTM extraction
time.sleep(60)

# Semantic search (retrieve_memories) — namespace must match strategy template
memories = client.retrieve_memories(
    memory_id=memory.get('id'),
    namespace='/summaries/User84/OrderSupportSession1/',
    query='can you summarize the support issue'
)

# Low-level session manager (for multi-turn incremental writes)
# MemorySessionManager takes memory_id; actor_id/session_id are passed to each method call.
# There is no create_memory_session factory — methods are invoked directly on the manager.
session_mgr = MemorySessionManager(memory_id=memory.get('id'), region_name='us-east-1')

# Add turns individually
session_mgr.add_turns(
    actor_id='User84',
    session_id='Session2',
    messages=[
        ConversationalMessage('Hello!', MessageRole.USER),
        ConversationalMessage('Hi, how can I help?', MessageRole.ASSISTANT),
    ],
)

# Retrieve last N turns from STM
turns = session_mgr.get_last_k_turns(actor_id='User84', session_id='Session2', k=5)

# Semantic search on LTM
results = session_mgr.search_long_term_memories(
    query='What topics were discussed?',
    namespace='/summaries/User84/Session2/',
    top_k=3
)

# List LTM records under namespace hierarchy
all_records = session_mgr.list_long_term_memory_records(namespace_path='/')
```

_Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agentcore-sdk-memory.html_

---

## Configuration reference

| Name | Description | Default / example |
|---|---|---|
| `eventExpiryDuration` (CreateMemory) | How long raw STM events are retained (short-term memory retention). Integer, in days. | Default: 90 days. Min: 7, Max: 365 |
| `memoryExecutionRoleArn` (CreateMemory) | ARN of the IAM role AgentCore assumes to call Bedrock models (built-in with overrides) or to publish to SNS/S3 (self-managed) or Kinesis (streaming). Trust principal: `bedrock-agentcore.amazonaws.com`. Required when using built-in with overrides, self-managed, or streaming strategies. | `arn:aws:iam::123456789012:role/AgentCoreMemoryExecutionRole` |
| `encryptionKeyArn` / `kmsKey` (CreateMemory / CDK MemoryProps) | ARN of a customer-managed KMS key for data encryption at rest. Event metadata is NOT encrypted with customer KMS regardless. | Optional. Default: AWS-owned key |
| `namespaceTemplates` (strategy config) | List of namespace path templates for a strategy. Must start and end with `/`. Supported variables: `{actorId}`, `{sessionId}`, `{memoryStrategyId}`. In IAM condition keys, paths are expressed WITHOUT a leading slash. | `['/users/{actorId}/preferences/']` |
| `MEMORY_<NAME>_ID` (environment variable) | After `agentcore deploy`, each memory resource automatically injects this env var into the agent runtime. `<NAME>` is the memory name uppercased with underscores. Strands and AgentCore SDK integrations should read this variable instead of hardcoding the ID. | `MEMORY_MYAGENTMEMORY_ID=mem-xxxxxxxxxx` |
| `topK` (RetrieveMemoryRecords `searchCriteria`) | Per-page limit on semantically relevant LTM records returned. `topK` is a **per-page limit** (max 100); use `nextToken` in the response to paginate through additional pages. | Default: 10. Max: 100 |
| `top_k` / `relevance_score` (RetrievalConfig — Strands) | Per-namespace retrieval settings in `AgentCoreMemoryConfig`. `relevance_score` is the minimum cosine similarity threshold; records below this score are filtered out. | `top_k` default: 10 (range 1–1000). `relevance_score` default: 0.2 (range 0.0–1.0) |
| `batch_size` (AgentCoreMemoryConfig — Strands) | Number of Strands messages to buffer before sending to AgentCore. `batch_size=1` sends immediately; `batch_size>1` buffers. Always use context manager or `close()` with `batch_size>1`. | Default: 1. Max: 100 |
| `indexedKeys` (CreateMemory) | Indexed metadata keys for LTM record filtering. Types: `STRING`, `NUMBER`, `STRINGLIST`. Key pattern: `^[a-zA-Z0-9\s._:/=+@-]*$` (max 128 chars). Max 10 indexed keys per memory. Cannot be removed once added. Does not backfill existing records. | `[{"key": "priority", "type": "STRING"}, {"key": "tags", "type": "STRINGLIST"}]` |
| `metadataFilters` (RetrieveMemoryRecords / ListMemoryRecords) | Up to 5 AND-combined filter expressions on indexed keys. `STRING` supports `StringEquals`/`StringNotEquals`; `STRINGLIST` supports `ContainsAny`/`ContainsAll`; `NUMBER` supports `NumberGreaterThan`/`LessThan` etc.; `dateTimeValue` system fields support `BEFORE`/`AFTER`. | max 5 filters, AND logic only |
| `messageCount` / `tokenCount` / `idleSessionTimeout` (self-managed `triggerConditions`) | Trigger conditions for self-managed strategies. First to fire wins. `messageCount`: N conversational turns. `tokenCount`: N tokens in the window. `idleSessionTimeout`: minutes of inactivity. | `messageCount: 6, tokenCount: 1000, idleSessionTimeout: 30` |
| `historicalContextWindowSize` (self-managed) | Number of prior extraction batches to include as historical context in the S3 payload delivered to your processing pipeline. | Example: 2 |
| `contentConfigurations.level` (streaming) | Controls data included in Kinesis stream events. `METADATA_ONLY` includes IDs, timestamps, strategyId, namespaces. `FULL_CONTENT` adds `memoryRecordText`. `MemoryRecordDeleted` events contain only identifiers regardless of this setting. | `METADATA_ONLY` or `FULL_CONTENT` |
| Maximum strategies per memory resource | Hard limit on how many memory strategies a single memory resource can have. Not adjustable. | 6 (not adjustable) |
| Maximum memories per region per account | Soft limit on AgentCore Memory resources per AWS Region. Adjustable via Service Quotas. | 150 (adjustable) |
| CreateEvent TPS limits | Account-wide: 10 TPS. Per-actor/per-session with conversational payloads: 5 TPS (not adjustable). Per-actor/per-session without conversational payloads: 10 TPS (not adjustable). Max 100 messages per call, max 100 KB per message, max 10 MB per event. | 10 TPS account-wide (adjustable); 5 TPS per-actor/session with conversational payload (not adjustable) |
| RetrieveMemoryRecords / ListMemoryRecords TPS | Both operations have a default quota of 30 TPS per account per region. Adjustable via Service Quotas. | 30 TPS (adjustable) |
| LTM extraction token quota (built-in strategies) | Maximum tokens per minute for LTM extraction using built-in strategies. Monitor via `TokenCount` CloudWatch metric in `Bedrock-AgentCore` namespace. Episodic strategy has an additional fixed 50,000 tokens/min per-session limit. | 150,000 tokens/min (adjustable). Episodic per-session: 50,000 tokens/min (not adjustable) |
| IAM Actions — control plane | `CreateMemory` (requires `iam:PassRole` when using execution roles), `UpdateMemory`, `GetMemory`, `DeleteMemory`, `ListMemories`. In IAM policy Action field the prefix is `bedrock-agentcore` even for control-plane operations. | `bedrock-agentcore:CreateMemory, bedrock-agentcore:GetMemory` |
| IAM Actions — data plane | `bedrock-agentcore` prefix actions: `CreateEvent` (condition keys: `sessionId`, `actorId`), `RetrieveMemoryRecords` (condition keys: `namespace`, `namespacePath`), `ListMemoryRecords`, `GetMemoryRecord`, `ListEvents`, `GetEvent`, `ListSessions`, `BatchCreateMemoryRecords`, `BatchUpdateMemoryRecords`, `BatchDeleteMemoryRecords`. | `bedrock-agentcore:CreateEvent, bedrock-agentcore:RetrieveMemoryRecords` |
| IAM Condition Keys (memory-specific) | `bedrock-agentcore:namespace` (`StringEquals`, exact match — WITHOUT leading slash in IAM), `bedrock-agentcore:namespacePath` (`StringLike`, prefix match — WITHOUT leading slash, e.g., `summaries/agent1/*`), `bedrock-agentcore:actorId` (`StringEquals`), `bedrock-agentcore:sessionId` (`StringEquals`), `bedrock-agentcore:KmsKeyArn` (on `CreateMemory`). | `"bedrock-agentcore:namespacePath": "summaries/alice/*"` |
| CloudWatch namespace for metrics | AgentCore Memory emits metrics under the `Bedrock-AgentCore` CloudWatch namespace. Key metrics: `CreateEvent` Invocations/Latency/Errors, `RetrieveMemoryRecord` Invocations/Latency/Errors, `TokenCount` (extraction token usage), extraction/consolidation `NumberOfMemoryRecords` per strategy. | Namespace: `Bedrock-AgentCore` |
| Memory resource ARN format | Resource ARN pattern for IAM policies targeting a specific memory. | `arn:aws:bedrock-agentcore:{region}:{account-id}:memory/{memory-id}` |
| Memory pricing | STM: $0.25/1,000 create event requests. LTM storage: $0.75/1,000 records stored/month (built-in); $0.25/1,000 records stored/month (built-in with overrides or self-managed). LTM retrieval: $0.50/1,000 retrieve memory record requests. For built-in with overrides, additional Bedrock model inference charges apply. Billed hourly assuming a 31-day month for storage. | STM: $0.25/1K events; LTM storage: $0.75/$0.25 per 1K records/month; LTM retrieval: $0.50/1K requests |

---

## Gotchas

- **Two separate Boto3 clients are required**: `bedrock-agentcore-control` for resource management (`CreateMemory`, `UpdateMemory`) and `bedrock-agentcore` for data operations (`CreateEvent`, `RetrieveMemoryRecords`). Using the wrong client will result in `Unknown service` errors.

- **LTM extraction is asynchronous** — events written via `CreateEvent` are NOT immediately available in `RetrieveMemoryRecords`. The official example uses `time.sleep(60)` before querying. Do not write and immediately read LTM in the same code path.

- **Only events created AFTER a strategy becomes `ACTIVE` are processed for LTM**. If you add a strategy to an existing memory via `UpdateMemory`, all historical events are ignored — only new events trigger extraction.

- **Memory creation itself is asynchronous** — you must poll `GetMemory` until `status == 'ACTIVE'` (2–3 minutes) before writing events or the memory may silently ignore events or return errors. Use the SDK helper `create_memory_and_wait()` to avoid polling boilerplate.

- **Only `conversational` payload type flows into LTM extraction**. `blob` payloads are stored in STM but are never processed by memory strategies. LangGraph `AgentCoreMemorySaver` uses blob payloads for state persistence — so checkpointed state does NOT trigger LTM extraction.

- **Event metadata (attached to STM events) is NOT encrypted** with customer-managed KMS. Do not store sensitive PII or secrets in event metadata fields.

- **Indexed metadata keys on a memory resource CANNOT be removed once added**, and adding a new key does NOT backfill existing records. Plan your 10-key budget carefully before creating the memory.

- **When using `AgentCoreMemorySessionManager` with `batch_size > 1`**, buffered messages are permanently lost if the session ends without calling `close()` or exiting a `with` block. Use `try/finally` with `close()` if a context manager is not possible.

- **Only one Strands agent per session is supported** with `AgentCoreMemorySessionManager`. Running two agents with the same `session_id` against the same memory is not supported.

- **`appendToPrompt` REPLACES (not appends to) the default system prompt** — despite the parameter name, the official docs confirm it replaces the default instructions entirely. Always pass the complete combined text (base prompt + your domain additions). Also NEVER rename the consolidation operations `AddMemory` or `UpdateMemory` — this silently breaks the LTM pipeline. The output schema is also not editable in built-in with overrides mode.

- **The relevance score returned by `RetrieveMemoryRecords` is a cosine similarity value, NOT a percentage**. The field is named `score` on each `MemoryRecordSummary` object (per the API type definition — not `relevanceScore`). Values near 0.2 are often already highly relevant for well-formed queries.

- **Namespace templates must start AND end with `/`**. However, IAM condition key values for `bedrock-agentcore:namespace` and `bedrock-agentcore:namespacePath` are expressed WITHOUT a leading slash (official docs show `summaries/agent1/` and `summaries/agent1/*`).

- **Built-in with overrides strategies require a `memoryExecutionRoleArn`**. Bedrock model inference charges apply to your account separately; throttling of your Bedrock quotas can cause memory ingestion failures. Monitor and request quota increases before going to production.

- **Self-managed strategy SLA is shared between AgentCore and your custom pipeline**. Use FIFO SNS topics when session ordering matters (e.g., for summarization). Set S3 lifecycle policies to auto-delete processed payloads.

- **Memory Record Streaming requires a `memoryExecutionRoleArn`** with `kinesis:PutRecords` + `kinesis:DescribeStream`. For custom strategies also add `bedrock:InvokeModel`. A `StreamingEnabled` validation event is published on memory creation — if your consumer does not receive it, permissions are wrong.

- **The per-actor/per-session limit for `CreateEvent` with conversational payloads is 5 TPS and is NOT adjustable**. For high-frequency, concurrent multi-user agents, design your session architecture to stay within this limit.

- **`appendToPrompt` for custom strategies is limited to 30 KB**. Do not attempt to embed large domain corpora directly in the prompt override.

- **Built-in strategies cost 3x more for LTM storage than built-in with overrides or self-managed** ($0.75 vs $0.25 per 1,000 records/month). For high-volume production workloads where customization is needed, built-in with overrides provides cost savings alongside flexibility.

---

## Official sources

- [AgentCore Memory — Developer Guide (root)](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory.html) — Primary entry point; links to all sub-topics on memory types, strategies, and examples
- [Memory Types (Short-term and Long-term)](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory-types.html) — Explains STM (raw events per session) vs LTM (asynchronously extracted insights); includes API names
- [Get Started with AgentCore Memory](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory-get-started.html) — Step-by-step quickstart: AgentCore CLI, Boto3, AgentCore SDK; installs, create memory, write events, retrieve records
- [Memory Strategies Overview](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory-strategies.html) — Compares built-in (higher cost, no infra), built-in with overrides (customized prompts/model, lower cost), and self-managed (full custom, lowest cost) strategies
- [Built-in Memory Strategies](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/built-in-strategies.html) — Describes the 4 built-in strategies: Semantic, UserPreference, Summary, Episodic; extraction/consolidation/reflection steps
- [Configure Built-in Strategies (with Boto3 examples)](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/long-term-configuring-built-in-strategies.html) — Full Boto3 create_memory code for each of the 4 built-in strategies with namespaceTemplates
- [Memory Organization — Namespaces, Actors, Sessions](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory-organization.html) — Namespace templates, hierarchy levels, IAM condition-key based access restriction per namespace
- [Create an AgentCore Memory](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory-create-a-memory-store.html) — Console, CLI, and SDK creation paths; event retention, KMS, strategies
- [Use Short-term Memory](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/using-memory-short-term.html) — Links to CreateEvent, GetEvent, ListEvents, DeleteEvent operations
- [Create an Event (STM)](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/short-term-create-event.html) — Payload types (conversational, blob), event branching with branch.rootEventId and branch.name
- [Enable Long-term Memory](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/long-term-enabling-long-term-memory.html) — Creating new memory with strategies and adding strategies to existing memory via update_memory
- [Save and Retrieve Insights (LTM)](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/long-term-saving-and-retrieving-insights.html) — Full AgentCore SDK example: add_turns, search_long_term_memories with namespace and namespace_path
- [Retrieve Memory Records (RetrieveMemoryRecords API)](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/long-term-retrieve-records.html) — Required params: memoryId, namespace/namespacePath, searchCriteria; response: relevance score (cosine similarity). Optional param: memoryStrategyId for strategy-scoped search
- [Customize a Built-in Strategy or Create Your Own](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory-custom-strategy.html) — Built-in with overrides: appendToPrompt, model selection, which steps are overridable per strategy; do not rename AddMemory/UpdateMemory consolidation operations
- [Self-managed Strategy](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory-self-managed-strategies.html) — SNS + S3 trigger architecture, trigger conditions (message count, token count, idle timeout), BatchCreateMemoryRecords; IAM role requires s3:PutObject + sns:Publish
- [Structured Metadata for Long-term Memories](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/long-term-memory-metadata.html) — Indexed keys (up to 10 per memory), metadata schema per strategy, LLM extraction, filter operators (up to 5 AND-combined), quotas; system fields x-amz-agentcore-memory-createdAt/updatedAt always available
- [Memory Record Streaming (Kinesis)](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory-record-streaming.html) — Push-based Kinesis delivery for LTM record lifecycle events: MemoryRecordCreated/Updated/Deleted schemas; METADATA_ONLY or FULL_CONTENT level
- [Best Practices (official)](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/best-practices.html) — Encryption (KMS), memory poisoning / prompt injection threats, least-privilege IAM; input validation with guardrails is customer responsibility
- [Customer Support Scenario (full end-to-end code)](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory-customer-scenario.html) — 6-step walkthrough with all Boto3 code: create, start session, capture events, retrieve STM and LTM; includes 60-second wait for async extraction
- [Strands Agents SDK Memory Integration (official docs)](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/strands-sdk-memory.html) — AgentCoreMemoryConfig, AgentCoreMemorySessionManager, MemoryClient, batch_size, context manager usage; pip install bedrock-agentcore strands-agents
- [LangChain / LangGraph Integration](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory-integrate-lang.html) — AgentCoreMemorySaver (checkpointer, STM via blob) and AgentCoreMemoryStore (LTM search); package langgraph-checkpoint-aws; uses actor_id + thread_id in RunnableConfig
- [Amazon Bedrock AgentCore SDK (Python) Memory](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agentcore-sdk-memory.html) — MemoryClient higher-level API: create_memory, create_memory_and_wait, create_event (takes messages as list of tuples), retrieve_memories
- [IAM Actions, Resources, and Condition Keys for Amazon Bedrock AgentCore](https://docs.aws.amazon.com/service-authorization/latest/reference/list_amazonbedrockagentcore.html) — Full IAM action list with service prefix bedrock-agentcore; condition keys sessionId, actorId, namespace, KmsKeyArn
- [CDK Memory Construct (aws-cdk-lib.aws_bedrockagentcore.Memory)](https://docs.aws.amazon.com/cdk/api/v2/docs/aws-cdk-lib.aws_bedrockagentcore.Memory.html) — TypeScript/Python CDK construct; grant* methods, metric* methods, MemoryProps, addMemoryStrategy
- [Compare LTM with RAG](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory-ltm-rag.html) — When to use LTM vs Knowledge Bases (RAG): personal context vs authoritative current facts
- [Boto3 bedrock-agentcore-control client reference](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/bedrock-agentcore-control.html) — Control plane: CreateMemory, UpdateMemory, GetMemory, DeleteMemory, ListMemories
- [Boto3 bedrock-agentcore client reference](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/bedrock-agentcore.html) — Data plane: CreateEvent, GetEvent, ListEvents, ListSessions, RetrieveMemoryRecords, ListMemoryRecords, GetMemoryRecord, BatchCreateMemoryRecords, BatchUpdateMemoryRecords, BatchDeleteMemoryRecords
- [AgentCore Memory Service Quotas](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/bedrock-agentcore-limits.html) — All TPS limits: CreateEvent 10 TPS (account), 5 TPS per-actor/session; RetrieveMemoryRecords 30 TPS; ListMemoryRecords 30 TPS; max 6 strategies per memory; max 150 memories per region; max 100 messages per CreateEvent
- [AgentCore Memory Pricing](https://aws.amazon.com/bedrock/agentcore/pricing/) — STM $0.25/1,000 events; LTM storage $0.75/1,000 records/month (built-in), $0.25/1,000 records/month (built-in with overrides or self-managed); LTM retrieval $0.50/1,000 requests
- [Amazon Bedrock Capacity for Built-in with Overrides Strategies](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/bedrock-capacity.html) — Bedrock model usage for custom strategies is attributed to and billed in your own account; throttling from Bedrock quotas can cause ingestion failures
- [AgentCore Samples Repository (GitHub)](https://github.com/awslabs/amazon-bedrock-agentcore-samples/tree/main/01-tutorials) — Runnable tutorial notebooks for memory quickstart and end-to-end scenarios
- [bedrock-agentcore-sdk-python (Strands integration source)](https://github.com/aws/bedrock-agentcore-sdk-python/tree/main/src/bedrock_agentcore/memory/integrations/strands) — Source for AgentCoreMemorySessionManager, AgentCoreMemoryConfig, RetrievalConfig classes
