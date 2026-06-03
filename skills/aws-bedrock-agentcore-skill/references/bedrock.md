# Amazon Bedrock — Models, Converse API & Knowledge Bases (RAG)

> Part of the **aws-bedrock-agentcore-skill** skill. See [SKILL.md](../SKILL.md) for the decision tree. Every source below is official — re-open it to verify details.

## Table of contents

- [Part 1 — Models & Converse API](#part-1--models--converse-api)
  - [Overview (Part 1)](#overview-part-1)
  - [Key concepts (Part 1)](#key-concepts-part-1)
  - [Best practices (Part 1)](#best-practices-part-1)
  - [Code (Part 1)](#code-part-1)
  - [Configuration reference (Part 1)](#configuration-reference-part-1)
  - [Gotchas (Part 1)](#gotchas-part-1)
  - [Official sources (Part 1)](#official-sources-part-1)
- [Part 2 — Knowledge Bases & RAG](#part-2--knowledge-bases--rag)
  - [Overview (Part 2)](#overview-part-2)
  - [Key concepts (Part 2)](#key-concepts-part-2)
  - [Best practices (Part 2)](#best-practices-part-2)
  - [Code (Part 2)](#code-part-2)
  - [Configuration reference (Part 2)](#configuration-reference-part-2)
  - [Gotchas (Part 2)](#gotchas-part-2)
  - [Official sources (Part 2)](#official-sources-part-2)

---

## Part 1 — Models & Converse API

### Overview (Part 1)

Amazon Bedrock exposes two families of inference APIs on the `bedrock-runtime` service: the **Converse/ConverseStream API** (unified interface, identical across all message-capable models) and the **Invoke API** (`InvokeModel` / `InvokeModelWithResponseStream`, with a model-specific body). For conversational agents, Converse is always recommended.

The `modelId` field accepts: base model IDs, inference profile IDs/ARNs (cross-region geo or global), application inference profile ARNs, provisioned throughput ARNs, and Prompt Management prompt ARNs. Anthropic models require a one-time FTU form (`PutUseCaseForModelAccess`). Prompt caching, tool use (function calling), extended/adaptive thinking, guardrails, and streaming are all supported by the Converse API. From November 2025, four service tiers are available: Standard, Priority, Flex, and Reserved.

**Maturity:** GA for Converse, ConverseStream, InvokeModel, InvokeModelWithResponseStream, inference profiles, prompt caching (all major Anthropic Claude and Amazon Nova models). Global cross-region inference: documented GA for Claude Sonnet 4.5 (`global.anthropic.claude-sonnet-4-5-20250929-v1:0`); verify current Global-inference source regions and supported models per individual model card. Service tiers Priority and Flex: GA November 2025. Reserved tier: GA November 2025. Adaptive thinking (Claude Opus 4.6, Sonnet 4.6, Opus 4.7, Claude Mythos Preview): GA 2026. `InvokeModelWithBidirectionalStream` (Nova Sonic speech-to-speech): GA March 2025, model in **Legacy lifecycle with EOL September 2026**. Server-side tool use (Responses API via bedrock-mantle): GA, currently supports GPT OSS 20B/120B, Claude Opus 4.7, Claude Haiku 4.5. Batch inference with Converse format: GA February 2026.

---

### Key concepts (Part 1)

- **Converse API** — `bedrock-runtime` operation providing a unified interface for all message-capable models. HTTP endpoint: `POST /model/{modelId}/converse`. Required IAM permission: `bedrock:InvokeModel`. Handles multi-turn conversations, tool use, guardrails, prompt caching, images, documents, video, and audio. Application logic does NOT change when switching models — only `modelId` changes.

- **ConverseStream API** — Streaming variant of Converse. HTTP endpoint: `POST /model/{modelId}/converse-stream`. IAM permission: `bedrock:InvokeModelWithResponseStream`. Returns a typed event stream: `messageStart`, `contentBlockStart`, `contentBlockDelta`, `contentBlockStop`, `messageStop`, `metadata`. **AWS CLI does NOT support this endpoint.** Check streaming support via `GetFoundationModel` (`responseStreamingSupported` field).

- **InvokeModel API** — Low-level single-inference API. Request body is model-specific (model-native JSON). Requires `bedrock:InvokeModel`. Use for: embeddings, image generation, models that don't support Converse, model-specific parameters not available in Converse. For streaming: `InvokeModelWithResponseStream`. For async jobs (e.g., video): `StartAsyncInvoke`. For real-time speech (Amazon Nova Sonic): `InvokeModelWithBidirectionalStream`.

- **modelId field** — Required field in URI (Converse) or header. Accepts: (1) base model ID e.g. `anthropic.claude-sonnet-4-6`; (2) geo cross-region profile ID e.g. `us.anthropic.claude-sonnet-4-6`; (3) global inference profile ID e.g. `global.anthropic.claude-sonnet-4-6`; (4) application inference profile ARN; (5) provisioned throughput ARN; (6) Prompt Management prompt ARN; (7) marketplace endpoint ARN. Length: 1–2048 characters.

- **inferenceConfig** — Common inference parameters for all models in Converse API: `maxTokens` (integer, output token limit), `temperature` (0–1, randomness), `topP` (0–1, nucleus sampling), `stopSequences` (array of strings that stop generation). For model-specific parameters (e.g., `top_k`, `thinking`), use `additionalModelRequestFields`.

- **Cross-Region Inference Profile (Geo)** — System-defined profiles that route requests across multiple regions within the same geography to handle traffic bursts. Prefixes: `us.` (US), `eu.` (Europe), `au.` (Australia), `jp.` (Japan). Source region = the region you call; destination regions = other regions in the same geography. SCPs and IAM policies must allow `bedrock:InvokeModel` in ALL destination regions of the chosen profile. Per-model details (inference profile IDs and destination regions) are found on each individual model card.

- **Global Cross-Region Inference Profile** — Routes requests to any commercial region worldwide, optimizing throughput without data residency constraints. Prefix: `global.` (e.g., `global.anthropic.claude-sonnet-4-5-20250929-v1:0`). Documented for Claude Sonnet 4.5; verify current supported models and source regions per individual model card. Offers ~10% cost savings vs geo profiles. Requires a three-statement IAM policy with condition `aws:RequestedRegion='unspecified'` for global routing. SCPs must allow `aws:RequestedRegion='unspecified'`. To disable, add a Deny on `RequestedRegion='unspecified'`. _Source: https://docs.aws.amazon.com/bedrock/latest/userguide/global-cross-region-inference.html_

- **Application Inference Profile** — User-created profile via `CreateInferenceProfile` to track costs and usage per team/environment/project. Can be based on: (1) a single foundation model to track a single region; (2) a cross-region system profile to track multi-region costs. Use the returned ARN as `modelId` in any inference operation.

- **Tool Use (Function Calling) — client-side** — The model does NOT directly call tools. Flow: (1) define tools in `toolConfig.tools[].toolSpec`; (2) model responds with `stopReason='tool_use'` and content with `toolUse` blocks; (3) application executes the tool; (4) send result back to model as `toolResult` content with status `'success'` or `'error'`; (5) model generates final response. `toolChoice` supports: `auto`, `any`, `tool`. With extended/adaptive thinking, `toolChoice` supports only `auto` or `none`.

- **Server-side tool use (Responses API)** — Available via the `bedrock-mantle` endpoint with the Responses API (OpenAI compatibility). Amazon Bedrock executes Lambda functions that implement tools (MCP JSON-RPC protocol) using the same IAM credentials as the calling application. Currently supported on GPT OSS 20B/120B; Claude support coming. Includes AWS built-in tools (`notes`, `tasks`) on `openai.gpt-oss-20b` and `openai.gpt-oss-120b`.

- **stopReason** — Field in Converse response indicating why the model stopped generating. Values: `end_turn` (normal completion), `tool_use` (tool execution required), `max_tokens` (token limit reached), `stop_sequence` (stop string found), `guardrail_intervened` (guardrail triggered), `content_filtered`, `malformed_model_output`, `malformed_tool_use`, `model_context_window_exceeded`.

- **Prompt Caching** — Optional feature that reduces latency and cost by caching static portions of the prompt (system, messages, tools). Implemented by inserting `cachePoint` blocks in content. Default TTL: 5 minutes; extended TTL of 1 hour supported **only** on: Claude Opus 4.5, Haiku 4.5, Sonnet 4.5 (Claude Opus 4.6 and Sonnet 4.6 support 5-minute TTL only; Claude Opus 4.7 is not in the supported-models table for prompt caching). Cache checkpoints processed in order: `tools` → `system` → `messages`. Cache read has reduced cost; cache write may cost more than uncached tokens. **Not supported with batch inference.** Simplified Cache Management: place a single `cachePoint` at the end of static content and the system automatically finds the best match up to ~20 content blocks back.

- **Extended Thinking / Adaptive Thinking** — Extended thinking: `thinking` parameter with `type='enabled'` and `budget_tokens` (minimum 1024 tokens) in `additionalModelRequestFields` (Converse) or native body (InvokeModel). Supported by Claude 3.7 Sonnet, Claude 4 (Opus, Sonnet, Haiku various). Claude 4 returns summarized thinking, not the full text. Streaming required if `max_tokens > 21333`. When `type='enabled'`: not compatible with `temperature`, `top_p`, `top_k`, forced tool use. Adaptive thinking: `type='adaptive'` with `effort` (`max`/`high`/`medium`/`low`) in `output_config`. Recommended for Claude Opus 4.6 and Sonnet 4.6; **mandatory for Claude Opus 4.7 and Claude Mythos Preview** (`thinking.type='enabled'` returns 400 on these models). Adaptive thinking automatically enables interleaved thinking with tool use.

- **Service Tiers** — `Standard` (default, `'default'` or omitted): consistent performance, pay-per-token. `Priority` (`'priority'`): +75% vs Standard, no reservation, better latency for customer-facing workloads. `Flex` (`'flex'`): -50% vs Standard, for non-interactive workloads (batch, summarization, agentic). `Reserved` (`'reserved'`): 99.5% uptime guaranteed, 1 or 3-month reservation, minimum 100K input TPM + 10K output TPM, requires contact with AWS account team. On-demand quota is shared among Standard, Priority, and Flex. Tier is visible in the response and in CloudTrail.

- **InvokeModelWithBidirectionalStream (Nova Sonic)** — API for real-time speech-to-speech voice conversations. Uses HTTP/2 for a persistent full-duplex channel (max 8 minutes per session). Currently supported only by Amazon Nova Sonic (`amazon.nova-sonic-v1:0`), a model in **Legacy lifecycle with EOL September 2026**. Input: Speech; Output: Speech + Text. Supports user interruptions mid-response. Does not support the Converse API (InvokeModel family only).

- **Models and Model Access** — Automatic access to all serverless models in all commercial regions with correct AWS Marketplace permissions. Exception: Anthropic requires a one-time FTU form (`PutUseCaseForModelAccess`) per account or per management account of an Org. Providers without an AWS Marketplace product key (Amazon, DeepSeek, Mistral, Meta, Qwen, OpenAI) cannot be blocked via subscription, but you can deny `bedrock:InvokeModel` on specific resources. Anthropic models on `bedrock-mantle` do NOT require the FTU form.

- **bedrock-mantle endpoint** — Distinct endpoint from `bedrock-runtime` for open-weight third-party models and APIs compatible with OpenAI/Anthropic. Supports: Chat Completions API, Messages API (native Anthropic for Claude Haiku 4.5, Opus 4.7, etc.), Responses API (server-side tool use with Lambda). URL: `bedrock-mantle.{region}.api.aws/v1` (OpenAI compat) or `bedrock-mantle.{region}.api.aws/anthropic/v1/messages` (Messages API). Anthropic models on `bedrock-mantle` do NOT require the Marketplace FTU form.

---

### Best practices (Part 1)

- **Always use Converse/ConverseStream instead of InvokeModel for conversational applications** — The interface is identical for all models: only `modelId` changes without rewriting logic. InvokeModel is required only for models that don't support messages (embeddings, image gen, Nova Sonic speech-to-speech) or to access model-specific parameters not available in Converse. _Source: https://docs.aws.amazon.com/bedrock/latest/userguide/conversation-inference.html_

- **Use geo inference profiles (e.g., `us.anthropic.claude-sonnet-4-6`) or global profiles (`global.anthropic.claude-sonnet-4-6`) in production instead of direct model IDs** — Automatically distributes traffic across multiple regions to handle bursts and reduce `ThrottlingException`. The global profile also offers ~10% cost savings vs geo. Update SCPs with condition `aws:RequestedRegion='unspecified'` to enable global routing. Updated model IDs and inference profile IDs are found on each individual model card. _Source: https://docs.aws.amazon.com/bedrock/latest/userguide/inference-profiles-support.html_

- **Create application inference profiles with tags for each environment/team for cost tracking** — The `tags` field in `CreateInferenceProfile` enables use of AWS Cost Allocation Tags to attribute inference costs to specific cost centers without modifying application code. Use the control plane client `bedrock` (not `bedrock-runtime`) for creation. _Source: https://docs.aws.amazon.com/bedrock/latest/userguide/inference-profiles-create.html_

- **Handle the tool_use cycle with a loop WHILE `stopReason == 'tool_use'`; exit on `end_turn` or any other terminal stop reason** — The model may request multiple consecutive tool uses in a single conversation. Continue sending `toolResult` blocks and re-invoking Converse as long as `stopReason == 'tool_use'`. Exit the loop when `stopReason` is `end_turn`, `max_tokens`, `stop_sequence`, `guardrail_intervened`, or any other non-tool stop reason. Always pass `status` (`'success'` or `'error'`) in the `toolResult`. _Source: https://docs.aws.amazon.com/bedrock/latest/userguide/tool-use-client-side.html_

- **Add `cachePoint` at the end of the system prompt and static documents to enable prompt caching** — Reduces latency and cost for workloads with long static contexts (RAG docs, long system prompts). Cache hits are not counted against the TPM quota. Use Simplified Cache Management for simplicity: place a single `cachePoint` after static content. Cache checkpoints are processed in `tools` → `system` → `messages` order: altering an upstream section invalidates downstream checkpoints. _Source: https://docs.aws.amazon.com/bedrock/latest/userguide/prompt-caching.html_

- **Use adaptive thinking (`thinking.type='adaptive'`) for Claude Opus 4.6, Sonnet 4.6, and Opus 4.7 instead of extended thinking with a fixed `budget_tokens`** — Adaptive thinking lets the model autonomously decide when and how much to think based on request complexity, yielding better performance than a fixed budget. It is the **only mode supported on Claude Opus 4.7** (`budget_tokens` returns 400). On Claude Opus 4.6 and Sonnet 4.6, `thinking.type='enabled'` is deprecated. Pass `thinking` and `effort` (optional) in `additionalModelRequestFields` when using the Converse API. _Source: https://docs.aws.amazon.com/bedrock/latest/userguide/claude-messages-adaptive-thinking.html_

- **Use `requestMetadata` to tag each call with business attributes (team, env, experiment)** — Key-value pairs in `requestMetadata` (max 16 pairs, key and value max 256 chars) are written to model invocation logs and can be filtered for usage analysis and debugging, with no billing impact. _Source: https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_Converse.html_

- **Implement retry with exponential backoff for `ThrottlingException` (HTTP 429)** — `bedrock-runtime` no longer exposes RPM (requests-per-minute) quotas; throttling is governed by TPM (tokens per minute, input+output combined). `ThrottlingException` indicates account quota exceeded. Implement custom backoff or request a quota increase via the Service Quotas console. Before requesting an increase, verify the model is not in Legacy or Deprecated state. _Source: https://docs.aws.amazon.com/bedrock/latest/userguide/quotas-runtime.html_

- **Verify model access prerequisites BEFORE invoking in production, not during** — The first invocation of a third-party model initiates the Marketplace subscription in the background (up to 15 min). If prerequisites are missing, the subscription fails and subsequent calls return `AccessDeniedException` for up to 2 minutes. Pre-verify during setup/bootstrap. _Source: https://docs.aws.amazon.com/bedrock/latest/userguide/model-access.html_

- **Do not include `additionalModelRequestFields`, `inferenceConfig`, `system`, or `toolConfig` when using a Prompt Management prompt** — The Converse API ignores/rejects these fields when `modelId` points to a Prompt Management prompt version ARN. These parameters must be defined directly in the prompt resource. If `messages` are included, they are appended after those defined in the prompt. _Source: https://docs.aws.amazon.com/bedrock/latest/userguide/conversation-inference.html_

- **To completely block access to a model, deny BOTH `bedrock:InvokeModel` AND `bedrock:InvokeModelWithResponseStream`** — Denying only one of the two does not block access via Converse. Both actions must be denied because Converse uses `bedrock:InvokeModel` and ConverseStream uses `bedrock:InvokeModelWithResponseStream`. _Source: https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_Converse.html_

- **Use the Flex service tier for asynchronous and non-interactive workloads (batch processing, summarization, long agentic workflows)** — The Flex tier offers 50% savings vs Standard tier for workloads that can tolerate higher latencies. Ideal for background processing, offline RAG pipelines, model evaluations. Set `service_tier='flex'` in the Converse request. _Source: https://docs.aws.amazon.com/bedrock/latest/userguide/service-tiers-inference.html_

---

### Code (Part 1)

#### Converse API — basic call with system prompt and inferenceConfig (Python boto3)

```python
import boto3
import json
from botocore.exceptions import ClientError

client = boto3.client("bedrock-runtime", region_name="us-east-1")

try:
    response = client.converse(
        # modelId: base model, geo cross-region profile, global profile, app profile ARN, provisioned ARN
        modelId="us.anthropic.claude-sonnet-4-6",  # Geo cross-region profile (US)
        # Alternative: "global.anthropic.claude-sonnet-4-6" for global routing (~10% cheaper vs geo)
        system=[
            {"text": "You are a helpful technical assistant. Be concise."}
        ],
        messages=[
            {
                "role": "user",
                "content": [{"text": "Explain what an inference profile is in Amazon Bedrock."}]
            }
        ],
        inferenceConfig={
            "maxTokens": 512,
            "temperature": 0.7,
            "topP": 0.9,
            "stopSequences": ["\n\nHuman:"]
        },
        # Optional: model-specific parameters not in inferenceConfig
        additionalModelRequestFields={
            "top_k": 200  # Claude-specific
        },
        # Optional: metadata for invocation logs filtering (max 16 pairs, key/value max 256 chars)
        requestMetadata={
            "team": "ai-platform",
            "env": "production"
        },
        # Optional: service tier — value must be a dict, not a bare string
        # serviceTier={"type": "flex"}  # use for non-interactive workloads, 50% cheaper
    )
except client.exceptions.ThrottlingException as e:
    print(f"Rate limit exceeded (TPM quota): {e}")
    raise
except client.exceptions.AccessDeniedException as e:
    print(f"Access denied — check IAM permissions and FTU form: {e}")
    raise
except ClientError as e:
    print(f"AWS error: {e.response['Error']['Code']} — {e.response['Error']['Message']}")
    raise

# Parse response
stop_reason = response["stopReason"]  # 'end_turn' | 'tool_use' | 'max_tokens' | ...
output_text = response["output"]["message"]["content"][0]["text"]
usage = response["usage"]  # {inputTokens, outputTokens, totalTokens, cacheReadInputTokens, cacheWriteInputTokens}
latency_ms = response["metrics"]["latencyMs"]

print(f"stopReason: {stop_reason}")
print(f"Response: {output_text}")
print(f"Tokens — in: {usage['inputTokens']}, out: {usage['outputTokens']}, total: {usage['totalTokens']}")
print(f"Latency: {latency_ms}ms")
```

_Source: https://docs.aws.amazon.com/bedrock/latest/userguide/conversation-inference.html_

#### ConverseStream API — streaming response with event stream handling (Python boto3)

```python
import boto3

client = boto3.client("bedrock-runtime", region_name="us-east-1")

# NOTE: AWS CLI does NOT support ConverseStream — SDK only
# Requires: bedrock:InvokeModelWithResponseStream permission
response = client.converse_stream(
    modelId="us.anthropic.claude-sonnet-4-6",
    messages=[
        {"role": "user", "content": [{"text": "Write a short poem about APIs."}]}
    ],
    inferenceConfig={"maxTokens": 256, "temperature": 0.7}
)

# Iterate over the EventStream
stream = response["stream"]
full_text = ""
for event in stream:
    # Text delta events
    if "contentBlockDelta" in event:
        delta = event["contentBlockDelta"]["delta"]
        if "text" in delta:
            chunk = delta["text"]
            full_text += chunk
            print(chunk, end="", flush=True)

    # Message stop — contains stopReason
    elif "messageStop" in event:
        stop_reason = event["messageStop"]["stopReason"]
        print(f"\n\nStop reason: {stop_reason}")

    # Token usage (at end of stream)
    elif "metadata" in event:
        usage = event["metadata"].get("usage", {})
        print(f"Tokens — in: {usage.get('inputTokens')}, out: {usage.get('outputTokens')}")
```

_Source: https://docs.aws.amazon.com/boto3/latest/reference/services/bedrock-runtime/client/converse_stream.html_

#### Tool Use (Function Calling) with Converse API — complete cycle with status and error handling (Python boto3)

```python
import boto3
import logging
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)
client = boto3.client("bedrock-runtime", region_name="us-east-1")

# --- Tool implementation ---
def get_top_song(call_sign: str) -> dict:
    songs = {"WZPZ": {"song": "Elemental Hotel", "artist": "8 Storey Hike"}}
    if call_sign not in songs:
        raise ValueError(f"Station {call_sign} not found")
    return songs[call_sign]

# --- Tool config (passed to every Converse call) ---
tool_config = {
    "tools": [
        {
            "toolSpec": {
                "name": "top_song",
                "description": "Get the most popular song on a radio station.",
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "sign": {
                                "type": "string",
                                "description": "Radio station call sign, e.g. WZPZ, WKRP."
                            }
                        },
                        "required": ["sign"]
                    }
                }
            }
        }
    ],
    # toolChoice options: {"auto": {}} | {"any": {}} | {"tool": {"name": "top_song"}}
    # NOTE: when using extended/adaptive thinking, only "auto" or "none" are supported
    "toolChoice": {"auto": {}}
}

def run_with_tools(user_input: str, model_id: str = "us.anthropic.claude-sonnet-4-6"):
    messages = [{"role": "user", "content": [{"text": user_input}]}]

    while True:  # Loop until end_turn or non-tool stop
        response = client.converse(
            modelId=model_id,
            messages=messages,
            toolConfig=tool_config
        )

        output_message = response["output"]["message"]
        messages.append(output_message)  # Keep conversation history
        stop_reason = response["stopReason"]

        if stop_reason == "tool_use":
            tool_results = []
            for block in output_message["content"]:
                if "toolUse" not in block:
                    continue
                tool = block["toolUse"]
                logger.info("Tool requested: %s (id=%s)", tool["name"], tool["toolUseId"])

                try:
                    if tool["name"] == "top_song":
                        result = get_top_song(tool["input"]["sign"])
                        tool_results.append({
                            "toolUseId": tool["toolUseId"],
                            "content": [{"json": result}],
                            "status": "success"  # 'success' | 'error'
                        })
                    else:
                        tool_results.append({
                            "toolUseId": tool["toolUseId"],
                            "content": [{"text": f"Unknown tool: {tool['name']}"}],
                            "status": "error"
                        })
                except Exception as e:
                    tool_results.append({
                        "toolUseId": tool["toolUseId"],
                        "content": [{"text": str(e)}],
                        "status": "error"
                    })

            # Append all tool results as a single user message
            messages.append({
                "role": "user",
                "content": [{"toolResult": tr} for tr in tool_results]
            })

        else:  # end_turn, max_tokens, stop_sequence, guardrail_intervened, etc.
            final_text = ""
            for block in output_message["content"]:
                if "text" in block:
                    final_text += block["text"]
            print(final_text)
            break

    return messages

if __name__ == "__main__":
    run_with_tools("What is the most popular song on WZPZ?")
```

_Source: https://docs.aws.amazon.com/bedrock/latest/userguide/tool-use-client-side.html_

#### Prompt Caching — cachePoint in system and messages with optional TTL (Python boto3)

```python
import boto3

client = boto3.client("bedrock-runtime", region_name="us-east-1")

# Cache checkpoint token minimums per model:
# - Claude Sonnet 4.6, Opus 4, Claude 3.7 Sonnet: min 1,024 tokens per checkpoint
# - Claude Opus 4.5, Opus 4.6, Sonnet 4.5, Haiku 4.5: min 4,096 tokens per checkpoint
# All: max 4 checkpoints per request
# 1-hour TTL supported ONLY on: Claude Opus 4.5, Haiku 4.5, Sonnet 4.5
# (Claude Opus 4.6, Sonnet 4.6, and all others: 5-minute TTL only)
# Cache checkpoints processed in order: tools -> system -> messages
# Altering content before a cachePoint invalidates that and all subsequent checkpoints

large_document_text = "..." * 500  # Replace with real static content (must meet min token count)

response = client.converse(
    modelId="anthropic.claude-sonnet-4-6",  # 1,024 token minimum, 5-min TTL
    system=[
        {"text": "You are a document analysis assistant. Answer questions based only on the provided document."},
        # cachePoint marks end of the prefix to cache.
        # Everything BEFORE this point (in the tools->system->messages order) is cached.
        {"cachePoint": {"type": "default"}}  # default TTL: 5 min
        # For 1-hour TTL (only on: Claude Opus 4.5, Haiku 4.5, Sonnet 4.5 — NOT Opus 4.6 or Sonnet 4.6):
        # {"cachePoint": {"type": "default", "ttl": "1h"}}
        # IMPORTANT: 1-hour entries must appear BEFORE 5-minute entries in the same request
    ],
    messages=[
        {
            "role": "user",
            "content": [
                {"text": "Please analyze this document:"},
                {
                    "document": {
                        "format": "txt",
                        "name": "AnalysisDocument",  # neutral name — vulnerable to prompt injection
                        "source": {"text": large_document_text}
                    }
                },
                # Cache the document content for subsequent questions
                {"cachePoint": {"type": "default"}},
                {"text": "What are the main themes?"}
            ]
        }
    ],
    inferenceConfig={"maxTokens": 512}
)

usage = response["usage"]
print(f"Input tokens: {usage['inputTokens']}")
print(f"Cache write tokens: {usage.get('cacheWriteInputTokens', 0)}")
print(f"Cache read tokens: {usage.get('cacheReadInputTokens', 0)}")
```

_Source: https://docs.aws.amazon.com/bedrock/latest/userguide/prompt-caching.html_

#### Adaptive Thinking with Converse API — Claude Opus 4.6 / Sonnet 4.6 (Python boto3)

```python
import boto3
import json

bedrock_runtime = boto3.client(service_name="bedrock-runtime", region_name="us-east-1")

# Adaptive thinking: Claude autonomously decides when/how much to think
# Supported: Claude Opus 4.6, Sonnet 4.6, Opus 4.7, Claude Mythos Preview
# NOTE: Claude Opus 4.7 ONLY supports adaptive thinking.
#       thinking.type='enabled' with budget_tokens returns 400 on Opus 4.7.
#       thinking.type='enabled' is DEPRECATED on Opus 4.6 and Sonnet 4.6.

response = bedrock_runtime.converse(
    modelId="us.anthropic.claude-opus-4-6-v1",  # or "us.anthropic.claude-opus-4-7" for Opus 4.7
    messages=[{
        "role": "user",
        "content": [{"text": "Analyze the trade-offs between microservices and monolithic architectures."}]
    }],
    additionalModelRequestFields={
        "thinking": {
            "type": "adaptive"  # Claude decides when to think based on complexity
        },
        # effort controls thinking depth — place in output_config, NOT inside thinking
        # Effort levels: "max" (Opus 4.6 only), "high" (default), "medium", "low"
        "output_config": {
            "effort": "high"  # Claude always thinks; deep reasoning on complex tasks
        }
    },
    inferenceConfig={"maxTokens": 8192}
)

output_message = response["output"]["message"]
for block in output_message["content"]:
    if "reasoningContent" in block:
        # Summarized thinking (Claude 4 models return summarized thinking, not full text)
        print(f"Thinking summary: {block['reasoningContent']}")
    elif "text" in block:
        print(f"Response: {block['text']}")
```

_Source: https://docs.aws.amazon.com/bedrock/latest/userguide/claude-messages-adaptive-thinking.html_

#### Extended Thinking (fixed budget_tokens) with InvokeModel — Claude Sonnet 4.5 / Opus 4.5 (Python boto3)

```python
import boto3
import json

client = boto3.client("bedrock-runtime", region_name="us-east-1")

# Fixed budget_tokens extended thinking: required for Claude Sonnet 4.5, Haiku 4.5, Opus 4.5
# DEPRECATED on Claude Opus 4.6 and Sonnet 4.6 (use adaptive instead)
# NOT supported (returns 400) on Claude Opus 4.7 and Claude Mythos Preview
# Minimum budget_tokens: 1024
# budget_tokens must be < max_tokens
# Streaming required if max_tokens > 21333

request_body = {
    "anthropic_version": "bedrock-2023-05-31",
    "max_tokens": 10000,
    "thinking": {
        "type": "enabled",
        "budget_tokens": 5000  # max tokens Claude can use for internal reasoning
    },
    "messages": [
        {
            "role": "user",
            "content": "What is the probability that a prime number between 1 and 100 is greater than 50?"
        }
    ]
}

response = client.invoke_model(
    modelId="anthropic.claude-sonnet-4-5-20250929-v1:0",
    body=json.dumps(request_body),
    contentType="application/json",
    accept="application/json"
)

response_body = json.loads(response["body"].read())
for block in response_body["content"]:
    if block["type"] == "thinking":
        print(f"Thinking: {block['thinking'][:200]}...")  # truncated for display
    elif block["type"] == "text":
        print(f"Answer: {block['text']}")
```

_Source: https://docs.aws.amazon.com/bedrock/latest/userguide/claude-messages-extended-thinking.html_

#### Create Application Inference Profile for cost tracking (Python boto3)

```python
import boto3

# NOTE: Uses bedrock control plane client (bedrock), NOT bedrock-runtime
bedrock = boto3.client("bedrock", region_name="us-east-1")

# Create an application inference profile from a geo cross-region system profile
# to enable cost tracking WITH cross-region routing.
# Supported regions for application profiles: ap-northeast-1, ap-northeast-2, ap-south-1,
# ap-southeast-1, ap-southeast-2, ca-central-1, eu-central-1, eu-west-1, eu-west-2,
# eu-west-3, sa-east-1, us-east-1, us-east-2, us-gov-east-1, us-west-2
response = bedrock.create_inference_profile(
    inferenceProfileName="prod-claude-sonnet-46-us",
    description="Production US inference profile for Claude Sonnet 4.6",
    modelSource={
        # Can be: ARN of a foundation model OR ARN of a system-defined cross-region profile
        "copyFrom": "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-sonnet-4-6"
    },
    tags=[
        {"key": "team", "value": "platform"},
        {"key": "environment", "value": "production"},
        {"key": "cost-center", "value": "ai-123"}
    ]
)

profile_arn = response["inferenceProfileArn"]
print(f"Created inference profile ARN: {profile_arn}")
# Use this ARN as modelId in converse(), invoke_model(), etc.
```

_Source: https://docs.aws.amazon.com/bedrock/latest/userguide/inference-profiles-create.html_

#### InvokeModel API — call with native payload (Python boto3, Amazon Titan)

```python
import boto3
import json
from botocore.exceptions import ClientError

client = boto3.client("bedrock-runtime", region_name="us-east-1")

# InvokeModel: body is model-specific (unlike Converse which is unified)
# Required permission: bedrock:InvokeModel
# Use for: embeddings, image gen, models not supporting Converse, model-specific params
model_id = "amazon.titan-text-premier-v1:0"

native_request = {
    "inputText": "Describe the purpose of a hello world program in one line.",
    "textGenerationConfig": {
        "maxTokenCount": 512,
        "temperature": 0.5,
        "topP": 0.9
    }
}

try:
    response = client.invoke_model(
        modelId=model_id,
        body=json.dumps(native_request),
        contentType="application/json",
        accept="application/json"
    )
except ClientError as e:
    print(f"Error: {e.response['Error']['Code']}")
    raise

model_response = json.loads(response["body"].read())
response_text = model_response["results"][0]["outputText"]
print(response_text)
```

_Source: https://docs.aws.amazon.com/bedrock/latest/userguide/inference-api.html_

#### Converse API — multi-turn conversation with history maintenance (Python boto3)

```python
import boto3

client = boto3.client("bedrock-runtime", region_name="us-east-1")

model_id = "us.anthropic.claude-sonnet-4-6"
system = [{"text": "You are a helpful assistant."}]
messages = []

def chat(user_input: str) -> str:
    """Send a message and maintain conversation history."""
    messages.append({
        "role": "user",
        "content": [{"text": user_input}]
    })

    response = client.converse(
        modelId=model_id,
        system=system,
        messages=messages,
        inferenceConfig={"maxTokens": 1024, "temperature": 0.7}
    )

    # Add the assistant response to history for next turn
    assistant_message = response["output"]["message"]
    messages.append(assistant_message)

    return assistant_message["content"][0]["text"]

# Multi-turn conversation
print(chat("What is Amazon Bedrock?"))
print(chat("What APIs does it offer for inference?"))
print(chat("Which one should I use for an AI agent?"))
```

_Source: https://docs.aws.amazon.com/bedrock/latest/userguide/conversation-inference.html_

#### Multimodal — sending image from S3 and inline document with Converse API (Python boto3)

```python
import boto3

client = boto3.client("bedrock-runtime", region_name="us-east-1")

response = client.converse(
    modelId="us.anthropic.claude-sonnet-4-6",
    messages=[
        {
            "role": "user",
            "content": [
                {"text": "Analyze this diagram and the accompanying specification document."},
                # Image from S3 (role must have s3:GetObject)
                {
                    "image": {
                        "format": "png",  # png | jpeg | gif | webp
                        "source": {
                            "s3Location": {
                                "uri": "s3://my-bucket/architecture-diagram.png",
                                "bucketOwner": "123456789012"  # required if cross-account
                            }
                        }
                    }
                },
                # Document inline (bytes or s3Location)
                {
                    "document": {
                        "format": "pdf",  # pdf|csv|doc|docx|xls|xlsx|html|txt|md
                        "name": "SpecificationDoc",  # alphanumeric + whitespace + hyphens
                        "source": {
                            "bytes": open("spec.pdf", "rb").read()
                            # or: "s3Location": {"uri": "s3://...", "bucketOwner": "..."}
                        },
                        "citations": {"enabled": True}  # get document citations in response
                    }
                }
            ]
        }
    ],
    inferenceConfig={"maxTokens": 1024}
)
```

_Source: https://docs.aws.amazon.com/bedrock/latest/userguide/conversation-inference.html_

---

### Configuration reference (Part 1)

| Name | Description | Default / example |
|------|-------------|-------------------|
| `bedrock:InvokeModel` | IAM action required for Converse and InvokeModel. To deny access to a specific model, use it with the model's resource ARN. | `arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-sonnet-4-6` |
| `bedrock:InvokeModelWithResponseStream` | IAM action required for ConverseStream and InvokeModelWithResponseStream. MUST be denied alongside `bedrock:InvokeModel` to fully block access. | Add to Deny together with `bedrock:InvokeModel` |
| `aws-marketplace:Subscribe` | IAM action required for auto-enabling third-party serverless models on first use. Not needed for subsequent invocations. Does not apply to Amazon, DeepSeek, Mistral, Meta, Qwen, OpenAI. | `Condition: {"ForAnyValue:StringEquals": {"aws-marketplace:ProductId": ["prod-..."]}}` |
| `inferenceConfig.maxTokens` | Maximum number of tokens to generate in the response. Depends on the model's context window. If reached, `stopReason = 'max_tokens'`. Claude Sonnet 4.6 and Opus 4.6: max 64K. Claude Opus 4.7: max 128K. | `512` (default varies by model) |
| `inferenceConfig.temperature` | Controls output randomness. Value between 0 and 1. 0 = deterministic, 1 = maximum variability. Not compatible with extended thinking when `thinking.type='enabled'`; the `'adaptive'` thinking type does not document this restriction. | `0.7` |
| `inferenceConfig.topP` | Nucleus sampling: considers only tokens whose cumulative probability is <= topP. Alternative to temperature; usually not used together. Not compatible with extended/adaptive thinking. | `0.9` |
| `inferenceConfig.stopSequences` | Array of strings that stop generation. Stop text is not included in the output. | `["\n\nHuman:", "</response>"]` |
| `additionalModelRequestFields` | Model-specific parameters not supported by `inferenceConfig`. For Claude: `top_k` (integer); `thinking` object (`type='enabled'`+`budget_tokens` for older models, `type='adaptive'` for Opus 4.6/Sonnet 4.6/Opus 4.7); `output_config.effort` for adaptive thinking. Format: JSON object. | `{"thinking": {"type": "adaptive"}, "output_config": {"effort": "high"}}` |
| `bedrock-runtime endpoint` | Regional endpoint for Converse, ConverseStream, InvokeModel. Format: `bedrock-runtime.{region}.amazonaws.com`. FIPS available for us-east-1, us-east-2, us-west-2, ca-central-1, us-gov-east-1, us-gov-west-1. | `bedrock-runtime.us-east-1.amazonaws.com` |
| `bedrock endpoint (control plane)` | Endpoint for management APIs: `CreateInferenceProfile`, `ListFoundationModels`, `GetFoundationModel`, `PutUseCaseForModelAccess`, etc. NOT for inference. | `bedrock.us-east-1.amazonaws.com` |
| `bedrock-mantle endpoint` | Endpoint for native Anthropic Messages API and Responses API (OpenAI compat). Used by Claude Haiku 4.5, Opus 4.7 on bedrock-mantle for Messages API. URL: `bedrock-mantle.{region}.api.aws/anthropic/v1/messages` (Messages) or `/v1` (OpenAI compat). | `bedrock-mantle.us-east-1.api.aws/anthropic/v1/messages` |
| `Cross-region profile ID prefix (Geo)` | Prefix of the geo-specific profile ID: `us.` (US), `eu.` (Europe), `au.` (Australia), `jp.` (Japan). Destination regions are fixed and do not change over time. | `us.anthropic.claude-sonnet-4-6` |
| `Cross-region profile ID prefix (Global)` | `global.` prefix for routing across all commercial regions worldwide. Destination regions expand as new commercial regions are added. Requires a three-statement IAM policy. | `global.anthropic.claude-sonnet-4-6` |
| `requestMetadata` | Map string-string (max 16 pairs, key max 256 chars, value max 256 chars) for tagging calls in logs. Key pattern: `[a-zA-Z0-9\s:_@$#=/+,-.]+` | `{"team": "ai-platform", "env": "prod"}` |
| `cachePoint.ttl` | Cache TTL. Values: `'5m'` (default, all supported models) or `'1h'` (only Claude Opus 4.5, Haiku 4.5, Sonnet 4.5; Opus 4.6 and Sonnet 4.6 support 5-minute TTL only). Note: 1h entries must precede 5m entries in the same request. | `"5m"` (implicit default if omitted) |
| `service_tier` | Optional Converse/InvokeModel parameter to choose the tier. Values: `'default'` (Standard), `'priority'` (+75% vs Standard, no reservation, better latency), `'flex'` (-50% vs Standard, for non-interactive workloads), `'reserved'` (reserved capacity, only if configured). On-demand quota shared among priority/default/flex. | `"default"` (implicit if omitted) |
| `TPM Quota (bedrock-runtime)` | Token-per-minute quotas on bedrock-runtime count input+output combined per individual model. RPM (requests-per-minute) is no longer enforced. Separate quotas for On-demand vs Cross-Region InvokeModel. Max tokens per day = TPM * 24 * 60 by default. | Verify in Service Quotas console: Amazon Bedrock > On-demand InvokeModel tokens per minute for {model} |
| `additionalModelRequestFields.thinking.budget_tokens` | Maximum tokens Claude can use for internal reasoning (extended thinking). Minimum: 1024. Must be < `max_tokens`. The model may use fewer. Above 32K, batch processing is recommended to avoid timeouts. Deprecated on Opus 4.6 and Sonnet 4.6; NOT supported on Opus 4.7 (use `type='adaptive'`). | `{"thinking": {"type": "enabled", "budget_tokens": 5000}}` |

---

### Gotchas (Part 1)

- **AWS CLI does NOT support ConverseStream** (or `InvokeModelWithResponseStream`). Always use an SDK (Python boto3, Node.js, Java, etc.) for streaming.

- **Denying only `bedrock:InvokeModel` does NOT block access via Converse**: you must deny BOTH `bedrock:InvokeModel` AND `bedrock:InvokeModelWithResponseStream`.

- **The first invocation of an Anthropic model without the FTU form fails with `AccessDeniedException`**. The form must be submitted BEFORE production deploy via the console or `PutUseCaseForModelAccess` API.

- **Cross-region inference profiles (geo): if a destination region is blocked by SCPs, ALL requests to the profile fail even if other destination regions are available.** Update SCPs to allow `bedrock:InvokeModel` in ALL destination regions of the chosen profile.

- **Global cross-region inference profile: SCPs using `StringEquals` conditions on `aws:RequestedRegion` do not capture global routing.** To enable global routing, SCPs must also allow `aws:RequestedRegion='unspecified'`. To disable it, add a Deny with `StringEquals` on `'unspecified'`.

- **When using a Prompt Management prompt as `modelId`, do NOT include `inferenceConfig`, `system`, `toolConfig`, or `additionalModelRequestFields`** — these are ignored or cause a 400 error. `messages` are appended after those defined in the prompt.

- **Claude Opus 4.7 (and Claude Mythos Preview) supports ONLY `thinking.type='adaptive'`**. Using `thinking.type='enabled'` with `budget_tokens` on these models returns HTTP 400. Migrate code from `budget_tokens` to `type='adaptive'` before updating the `modelId`.

- **`thinking.type='enabled'` with `budget_tokens` is DEPRECATED on Claude Opus 4.6 and Claude Sonnet 4.6**. Use `type='adaptive'`. Older models (Opus 4.5, Sonnet 4.5, Haiku 4.5, Claude 3.7 Sonnet) do NOT support adaptive thinking and still require `type='enabled'` with `budget_tokens`.

- **The `effort` parameter for adaptive thinking MUST be placed inside `output_config`, NOT inside the `thinking` object.** Placing `effort` inside `thinking` causes `ValidationException`.

- **Extended thinking (`thinking.type='enabled'`) is not compatible with `temperature`, `top_p`, `top_k`**. If using `type='enabled'`, remove these parameters from `inferenceConfig` and `additionalModelRequestFields`. This incompatibility is documented for `type='enabled'`; `type='adaptive'` does not carry this documented restriction.

- **Prompt caching: cache checkpoints are processed in `tools` → `system` → `messages` order**. If you alter content before a checkpoint (in an 'upstream' section), all subsequent checkpoints are also invalidated. Keep content before `cachePoint` blocks identical across requests.

- **Prompt caching does NOT work with batch inference** (`StartAsyncInvoke`). Only with on-demand (Converse, InvokeModel).

- **Cache entries with TTL `1h` must precede entries with TTL `5m` in the same request**. Mixing TTLs in the reverse order causes an error.

- **With Mistral AI and Meta models, the Converse API automatically wraps input in a model-specific prompt template**. This can affect token counts compared to using InvokeModel directly.

- **Automatic Marketplace subscription on first use takes up to 15 minutes**. During this time, API calls may temporarily succeed or return `AccessDeniedException` intermittently.

- **The `name` field in `DocumentBlock` (`document.name`) is vulnerable to prompt injection**: the model may interpret it as an instruction. Always use neutral, descriptive names — never unsanitized user input.

- **`toolConfig` CANNOT be used together with a Prompt Management prompt** (returns `ValidationException`). Tool choice with extended/adaptive thinking supports only `'auto'` or `'none'`.

- **The `bedrock-mantle` endpoint is distinct from `bedrock-runtime`** and serves both open-weight third-party models (DeepSeek, Gemma, MiniMax, etc.) with OpenAI API compat, and Anthropic models with native Messages API. Anthropic models on `bedrock-mantle` do NOT require the Marketplace FTU form.

- **`bedrock-runtime` no longer exposes RPM (requests-per-minute) quotas**: throttling is governed entirely by TPM (tokens per minute, input+output combined). `ThrottlingException` indicates TPM quota exceeded, not RPM.

- **Model IDs for newer models (Claude Sonnet 4.6: `anthropic.claude-sonnet-4-6`; Opus 4.6: `anthropic.claude-opus-4-6-v1`; Opus 4.7: `anthropic.claude-opus-4-7`) no longer follow the pattern with a date string (e.g., `-20240229-`), but use short names without an explicit version string.** Always verify on the individual model card.

- **Amazon Nova Sonic (`InvokeModelWithBidirectionalStream`) is in Legacy lifecycle with EOL September 2026**. Evaluate migration to Nova Sonic 2 or successors before deprecation.

---

### Official sources (Part 1)

- [Inference using Converse API — Amazon Bedrock User Guide](https://docs.aws.amazon.com/bedrock/latest/userguide/conversation-inference.html) — Main page: request/response structure, all fields (messages, system, inferenceConfig, toolConfig, guardrailConfig, cachePoint, reasoningContent, requestMetadata, serviceTier), examples for text, image, document, streaming.
- [Converse — Amazon Bedrock API Reference](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_Converse.html) — Official REST API reference: HTTP path, all request/response parameters, ARN patterns for modelId, errors (ThrottlingException, AccessDeniedException, ValidationException, ModelTimeoutException, ModelNotReadyException), HTTP examples with inference profile and Prompt Management.
- [Converse — boto3 Reference](https://docs.aws.amazon.com/boto3/latest/reference/services/bedrock-runtime/client/converse.html) — Complete Python syntax for `client.converse()`, all ContentBlock types (text, image, document, video, audio, toolUse, toolResult, guardContent, cachePoint, reasoningContent, citationsContent).
- [ConverseStream — boto3 Reference](https://docs.aws.amazon.com/boto3/latest/reference/services/bedrock-runtime/client/converse_stream.html) — Python syntax for `client.converse_stream()`, event stream types, note: AWS CLI does not support ConverseStream.
- [Inference using Invoke API — Amazon Bedrock User Guide](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-api.html) — InvokeModel, InvokeModelWithResponseStream, StartAsyncInvoke, InvokeModelWithBidirectionalStream; required and optional parameters (performanceConfigLatency, guardrailIdentifier, serviceTier).
- [Supported Regions and models for inference profiles](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-profiles-support.html) — List of predefined cross-region profiles (Geo: US, EU, APAC, AU, JP; Global: all commercial regions), source/destination regions, SCPs and IAM required on all destination regions. Per-model details are now on individual model cards.
- [Global cross-Region inference — Amazon Bedrock User Guide](https://docs.aws.amazon.com/bedrock/latest/userguide/global-cross-region-inference.html) — How it works, benefits (throughput, ~10% cost saving vs geo), three-statement IAM policy required, SCP with `aws:RequestedRegion=unspecified` condition, how to disable global routing.
- [Use an inference profile in model invocation](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-profiles-use.html) — How to specify the inference profile ARN or ID in the `modelId` field of Converse, InvokeModel, RetrieveAndGenerate, CreateFlow, etc.
- [Create an application inference profile](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-profiles-create.html) — `CreateInferenceProfile` API: required fields (inferenceProfileName, modelSource), response: inferenceProfileArn; use of tags for cost allocation.
- [Request access to models — Amazon Bedrock User Guide](https://docs.aws.amazon.com/bedrock/latest/userguide/model-access.html) — Automatic access to all serverless models with AWS Marketplace permissions; Anthropic FTU form (PutUseCaseForModelAccess); IAM prerequisites (aws-marketplace:Subscribe, Unsubscribe, ViewSubscriptions); auto-enablement 15 min.
- [Tool use (Function calling) — Amazon Bedrock User Guide](https://docs.aws.amazon.com/bedrock/latest/userguide/tool-use.html) — Overview of 3 modes: client-side (Converse, InvokeModel), server-side (Responses API + Lambda via MCP), native Anthropic Claude tool use.
- [Client-side tool use — Amazon Bedrock User Guide](https://docs.aws.amazon.com/bedrock/latest/userguide/tool-use-client-side.html) — Complete Python example of tool use with Converse API: toolConfig, tool_use stopReason cycle, toolResult, error handling.
- [Server-side tool use (Responses API) — Amazon Bedrock User Guide](https://docs.aws.amazon.com/bedrock/latest/userguide/tool-use-server-side.html) — Responses API with custom Lambda (MCP JSON-RPC protocol), AWS built-in tools (notes, tasks), currently supported on GPT OSS 20B/120B (bedrock-mantle endpoint).
- [Prompt caching for faster model inference — Amazon Bedrock User Guide](https://docs.aws.amazon.com/bedrock/latest/userguide/prompt-caching.html) — cachePoint in message/system/tools, TTL 5 min/1 hour, minimum token requirements per model, cost (reduced cache read, more expensive cache write), Simplified Cache Management. Updated table with all GA models.
- [Extended thinking — Amazon Bedrock User Guide](https://docs.aws.amazon.com/bedrock/latest/userguide/claude-messages-extended-thinking.html) — `thinking` parameter with `budget_tokens`, supported models, streaming limits (max_tokens > 21333 requires streaming), compatibility with tool use and prompt caching, summarized thinking for Claude 4 models.
- [Adaptive thinking — Amazon Bedrock User Guide](https://docs.aws.amazon.com/bedrock/latest/userguide/claude-messages-adaptive-thinking.html) — `thinking.type=adaptive` for Claude Opus 4.6, Sonnet 4.6, Opus 4.7, Claude Mythos Preview. `effort` parameter (max/high/medium/low) in `output_config`. Claude Opus 4.7 supports ONLY adaptive thinking.
- [Service tiers for optimizing performance and cost — Amazon Bedrock User Guide](https://docs.aws.amazon.com/bedrock/latest/userguide/service-tiers-inference.html) — Standard (default), Priority (+75% premium, no reservation), Flex (-50% discount, higher latency), Reserved (99.5% uptime, 1 or 3 months, min 100K input TPM + 10K output TPM). `service_tier` parameter in Converse.
- [Quotas for the bedrock-runtime endpoint — Amazon Bedrock User Guide](https://docs.aws.amazon.com/bedrock/latest/userguide/quotas-runtime.html) — TPM quotas (input+output combined per model): On-demand, Cross-Region, Max tokens per day. RPM no longer enforced on bedrock-runtime. Quota increases via Service Quotas console.
- [Models at a glance — Amazon Bedrock User Guide](https://docs.aws.amazon.com/bedrock/latest/userguide/model-cards.html) — Model card for each model with model ID, inference profile IDs (Geo and Global), regional availability, prompt caching limits, supported service tiers, modalities. Updated frequently.
- [Amazon Bedrock endpoints and quotas — AWS General Reference](https://docs.aws.amazon.com/general/latest/gr/bedrock.html) — All endpoints for bedrock, bedrock-runtime, bedrock-agent, bedrock-agent-runtime, bedrock-mantle per region; TPM service quotas per model.

---

## Part 2 — Knowledge Bases & RAG

### Overview (Part 2)

Amazon Bedrock Knowledge Bases is a fully managed capability that implements the entire RAG (Retrieval-Augmented Generation) workflow: document ingestion, chunking, embedding generation, vector store storage, and runtime retrieval. It exposes two main runtime APIs: **Retrieve** (returns raw chunks with relevance scores) and **RetrieveAndGenerate** (full pipeline with natural language response generation and source citations). It supports structured and unstructured data sources, multimodal content, metadata filtering, reranking, and integrates natively with Amazon Bedrock Agents via `AssociateAgentKnowledgeBase`.

Official documented quotas: max 100 KB per account, 5 concurrent ingestion jobs per account (1 per KB, 1 per data source), Retrieve/RetrieveAndGenerate at 20 rps, StartIngestionJob at 0.1 rps.

**Maturity:** GA for core features: vector KB with S3, OpenSearch Serverless, OpenSearch Managed Cluster, Aurora pgvector, MongoDB Atlas, Pinecone, Redis Enterprise Cloud, Neptune Analytics, Amazon S3 Vectors. **Preview:** Bedrock Data Automation (BDA) parser (us-west-2 only, subject to change). GA: Foundation model parser (Claude vision, Nova vision, LLama 4 vision). Reranking GA: Amazon Rerank 1.0 (ap-northeast-1, ca-central-1, eu-central-1, us-west-2), Cohere Rerank 3.5 (ap-northeast-1, ca-central-1, eu-central-1, us-east-1, us-west-2). Hybrid search GA: supported on Amazon RDS (Aurora), Amazon OpenSearch Serverless, and MongoDB Atlas. S3 Vectors: GA, available in regions where both Bedrock and S3 Vectors are available.

---

### Key concepts (Part 2)

- **Knowledge Base (KB)** — Bedrock resource that bridges data sources and RAG applications. Contains configuration for the embedding model, vector store, and data sources. Managed via `bedrock-agent` (control plane) and queried via `bedrock-agent-runtime` (runtime plane). Limit: max 100 KB per account per region.

- **Data Source** — Connector to a data source attached to a KB. GA supported sources: Amazon S3 (most common), custom API via `IngestKnowledgeBaseDocuments`. Preview: Confluence, Microsoft SharePoint, Salesforce. Structured data: Amazon Redshift (SQL KB). Configuration includes `vectorIngestionConfiguration` (parsing + chunking + Lambda transform). Limit: max 5 data sources per KB.

- **Chunking Strategy** — How documents are divided before embedding. 4 strategies: `NONE` (whole file = 1 chunk), `FIXED_SIZE` (maxTokens + overlapPercentage, default ~300 tokens with sentence boundary preservation), `HIERARCHICAL` (parent chunk + child chunk, retrieval returns the parent), `SEMANTIC` (uses an FM to understand semantic boundaries, extra cost, includes `bufferSize` and `maxTokens` plus `breakpointPercentileThreshold`). **Chunking strategy CANNOT be changed after data source creation.**

- **Vector Store** — Vector database where embeddings are stored. GA options: Amazon OpenSearch Serverless (auto-create available via console), OpenSearch Managed Cluster (Public access only, NOT VPC), Amazon Aurora PostgreSQL with pgvector, Amazon S3 Vectors (float32 only, optimized for infrequent queries), Neptune Analytics (GraphRAG), Pinecone, Redis Enterprise Cloud, MongoDB Atlas. Only OpenSearch Serverless and OpenSearch Managed support binary vectors.

- **Embedding Model** — Model that converts text into numerical vectors. Supported: `amazon.titan-embed-text-v1` (1536 dim, float32, only 4 regions), `amazon.titan-embed-text-v2:0` (256/512/1024 dim, float32 or binary, 21 regions including GovCloud), `cohere.embed-english-v3` (1024 dim, float32 or binary, 12 regions), `cohere.embed-multilingual-v3` (1024 dim, float32 or binary, 12 regions). Multimodal: `amazon.titan-multimodal-embeddings-v1` (1024 dim, float32) and Cohere embed v3 multimodal (1024 dim, float32 or binary).

- **Ingestion Job** — Asynchronous process that reads documents from the data source, parses them, chunks them, generates embeddings, and writes them to the vector store. Initiated with `StartIngestionJob` (bedrock-agent API). Sync is incremental: only documents added/modified/deleted since the last sync are reprocessed. Monitor with `GetIngestionJob` until status `COMPLETE`. Quotas: max 5 concurrent jobs per account, 1 per KB, 1 per data source, max 5M files to add/update and 5M files to delete per job, max 100 GB per job, max 50 MB per single file (text).

- **Retrieve API** — `POST /knowledgebases/{knowledgeBaseId}/retrieve` — queries the KB and returns the most relevant chunks as an array of `KnowledgeBaseRetrievalResult`, each with `content`, `location`, `metadata`, and similarity score. Supports pagination with `nextToken`, metadata filter, configurable number of results, reranking, and `overrideSearchType` (SEMANTIC/HYBRID). Quota: 20 rps.

- **RetrieveAndGenerate API** — `POST /retrieveAndGenerate` — full RAG pipeline: internally executes Retrieve + InvokeModel. Input: query text + KB configuration + `modelArn`. Output: text response with `citations` (mapping between response spans and source chunks). Maintains conversational context via `sessionId`. Supports guardrails, custom prompt template, inference profile for cross-region inference. Streaming version also available: `RetrieveAndGenerateStream`. Quota: 20 rps.

- **Metadata Filtering** — Allows filtering retrieval results based on metadata associated with documents. For S3, create `.metadata.json` files (`filename.ext.metadata.json`) in the same location as the document. Supported operators: `equals`, `notEquals`, `greaterThan`, `greaterThanOrEquals`, `lessThan`, `lessThanOrEquals`, `in`, `notIn`, `stringContains` (not in console), `listContains` (not in console), `startsWith`. Operators are combined with `andAll`/`orAll`. Note: `'in'` and `'notIn'` are optimized for OpenSearch Serverless and Neptune Analytics; `'stringContains'` optimized for OpenSearch Serverless; **S3 Vectors does NOT support `'startsWith'` and `'stringContains'`**.

- **AssociateAgentKnowledgeBase** — API to link a Knowledge Base to a Bedrock Agent. Requires `agentId`, `agentVersion` (always `'DRAFT'`), `knowledgeBaseId`, and a `description` (text that tells the agent when and how to use the KB). The `description` field is critical: it is the text the agent's orchestration system uses to decide whether to query the KB. After association, call `PrepareAgent` to make the change effective. Quota: max 2 KBs associated per agent (increasable), 6 rps.

- **Service Role (IAM)** — IAM role assumed by `bedrock.amazonaws.com` to operate on the KB. Must have: trust policy toward `bedrock.amazonaws.com` with `aws:SourceAccount` condition, policy for `bedrock:InvokeModel` on the embedding model ARN, policy for `s3:GetObject`/`s3:ListBucket` on the data source, policy for the vector store (e.g., `aoss:APIAccessAll` for OpenSearch Serverless, `rds-data:BatchExecuteStatement`/`ExecuteStatement` for Aurora, `s3vectors:*` for S3 Vectors).

- **Inference Profile (in KB context)** — Alternative resource ARN to a direct model ARN that enables cross-region inference and cost tracking. Can be used in `modelArn` of `RetrieveAndGenerate` or in `CreateDataSource` (for FM parser) to distribute requests across multiple regions and increase throughput. Data may be shared across regions: use with caution for sensitive data.

- **Reranking** — Optional post-processing of retrieved chunks that reorders results using a dedicated reranking model. GA models: `amazon.rerank-v1:0` (**NOT available in us-east-1**, available in ap-northeast-1, ca-central-1, eu-central-1, us-west-2) and `cohere.rerank-v3-5:0` (available in ap-northeast-1, ca-central-1, eu-central-1, us-east-1, us-west-2). Rerank API quota: 10 rps.

- **Hybrid Search** — Search mode that combines vector similarity (semantic) with full-text search (BM25). Supported ONLY for vector stores: Amazon RDS (Aurora pgvector), Amazon OpenSearch Serverless, and MongoDB Atlas (all require a filterable text field in the vector index). For other vector stores, search uses only SEMANTIC. Activate with `overrideSearchType: 'HYBRID'`.

---

### Best practices (Part 2)

- **Let the console automatically create the OpenSearch Serverless vector store for the first Knowledge Base** — Bedrock automatically configures the collection, index, field mapping, and data access policy with the correct parameters (faiss engine, not nmslib). Recreating it manually requires precise configuration of the faiss engine, dimension matching, and AOSS policies — a common source of errors. _Source: https://docs.aws.amazon.com/bedrock/latest/userguide/knowledge-base-create.html_

- **Choose the chunking strategy before creating the data source: it is not modifiable afterward** — Chunking configuration cannot be changed once the data source is created. To change strategy, a new data source must be created. Plan chunking in advance based on document type (long/short, technical/narrative). _Source: https://docs.aws.amazon.com/bedrock/latest/userguide/kb-data-source-customize-ingestion.html_

- **Use HIERARCHICAL chunking for long, technical documents where broad context is needed but precise search is required** — Child chunks are more precise for retrieval, but are replaced by the broader parent chunk before being passed to the LLM, providing context without degrading precision. Ideal for technical documentation, contracts, manuals. _Source: https://docs.aws.amazon.com/bedrock/latest/userguide/kb-chunking.html_

- **Use SEMANTIC chunking only if retrieval quality is critical and the extra cost is acceptable** — Semantic chunking internally uses a Foundation Model to determine semantic boundaries, incurring additional costs proportional to data volume. It offers the best quality for narrative texts but is not necessary for structured documents. _Source: https://docs.aws.amazon.com/bedrock/latest/userguide/kb-chunking.html_

- **Scope IAM permissions to the specific knowledge base ARN, do not use wildcards (`*`) in production** — Example policies use `*` for `knowledgeBaseId` because the ARN is not known before creation. After creation, update the trust policy and resource policies with the specific ARN following the principle of least privilege. _Source: https://docs.aws.amazon.com/bedrock/latest/userguide/kb-permissions.html_

- **Do not share the service role among multiple knowledge bases** — Official documentation explicitly states that a policy cannot be shared among multiple roles when using the service role. Each KB must have its own dedicated role. _Source: https://docs.aws.amazon.com/bedrock/latest/userguide/kb-permissions.html_

- **Use the Retrieve API + a separate InvokeModel call instead of RetrieveAndGenerate when you want control over the prompt** — `RetrieveAndGenerate` is convenient but offers limited customization. With `Retrieve`, you get the relevant chunks and build the prompt manually, allowing injection of system instructions, chain-of-thought, or specific business logic. _Source: https://docs.aws.amazon.com/bedrock/latest/userguide/kb-how-retrieval.html_

- **Provide a detailed, specific description when associating a KB to a Bedrock Agent** — The `description` field in `AssociateAgentKnowledgeBase` (max 200 characters) is the text the agent's orchestration system uses to autonomously decide when to query the KB. A vague description leads to under-use or over-use of the KB. Example: `'Contains product catalog with pricing, specs, and availability. Query when user asks about products, prices, or stock.'` _Source: https://docs.aws.amazon.com/bedrock/latest/APIReference/API_agent_AssociateAgentKnowledgeBase.html_

- **For Aurora pgvector, enable HNSW iterative scans (pgvector >= 0.8.0) when using metadata filtering** — Without iterative scan, selective metadata filters may return fewer results than expected because filtering occurs after the HNSW scan. With `ALTER DATABASE ... SET hnsw.iterative_scan = 'relaxed_order'`, the index continues scanning until enough filtered results are found. Settings only take effect on new sessions; if using RDS Data API, wait a few minutes for connection pool recycling. _Source: https://docs.aws.amazon.com/bedrock/latest/userguide/knowledge-base-setup.html_

- **Use `amazon.titan-embed-text-v2:0` as the default embedding model for new projects** — Titan V2 supports configurable dimensions (256/512/1024), both float32 and binary embeddings, and is available in 21 regions (including GovCloud) vs Titan V1 (only 4 regions: ap-northeast-1, eu-central-1, us-east-1, us-west-2). _Source: https://docs.aws.amazon.com/bedrock/latest/userguide/knowledge-base-supported.html_

- **Wait a few minutes after ingestion job completion before querying the KB (except Aurora)** — Documentation specifies that after ingestion job completion, you may need to wait a few minutes for vector embeddings to become available in the vector store for queries, for all vector stores except Amazon Aurora RDS. _Source: https://docs.aws.amazon.com/bedrock/latest/userguide/kb-data-source-sync-ingest.html_

- **For OpenSearch Managed Cluster, use Public access (not VPC) and configure Fine-grained access control** — Domains behind VPC are NOT supported for Knowledge Bases. Use Public access with fine-grained access control to protect data. Require Engine version >= 2.13 for knn index, >= 2.16 for binary embeddings. _Source: https://docs.aws.amazon.com/bedrock/latest/userguide/knowledge-base-setup.html_

- **Do not change the parsing strategy type after creation: create a new data source** — The parsing strategy type (`BEDROCK_FOUNDATION_MODEL` vs `BEDROCK_DATA_AUTOMATION` vs default) is not modifiable after data source creation. Only internal parameters of the same strategy can be updated (e.g., `modelArn` inside `bedrockFoundationModelConfiguration`). To change type, a new data source is needed. When updating, first retrieve the complete configuration with `GetDataSource` and pass the entire `vectorIngestionConfiguration` modifying only the specific field. _Source: https://docs.aws.amazon.com/bedrock/latest/userguide/kb-data-source-customize-ingestion.html_

- **Do not add S3 location for multimodal storage after KB creation: plan it from the start** — It is not possible to add an S3 URI for multimodal data storage (images, figures, tables) after the knowledge base is created. If you want multimodal support, it must be configured during KB creation. _Source: https://docs.aws.amazon.com/bedrock/latest/userguide/kb-data-source-customize-ingestion.html_

- **Use Cohere Rerank 3.5 (not Amazon Rerank 1.0) if operating in us-east-1** — Amazon Rerank 1.0 (`amazon.rerank-v1:0`) is NOT supported in us-east-1. In that region only Cohere Rerank 3.5 (`cohere.rerank-v3-5:0`) is available. Always verify regional availability of the reranker before use. _Source: https://docs.aws.amazon.com/bedrock/latest/userguide/rerank-supported.html_

- **Use S3 Vectors as a vector store only for workloads with infrequent queries, not for high concurrency** — S3 Vectors offers sub-second latency for infrequent queries and latency up to 100ms for more frequent queries, but is not optimized for high concurrency. It is the most economical vector store for RAG with sporadic queries. Does not support binary embeddings or hybrid search. _Source: https://docs.aws.amazon.com/bedrock/latest/userguide/knowledge-base-setup.html_

- **Handle the StartIngestionJob rate limit (0.1 rps) with exponential backoff retry** — `StartIngestionJob` has a limit of 0.1 requests per second (1 every 10 seconds) per account per region and is not increasable. In automated pipelines with many KBs, serialize calls with >= 10 second delays or implement retry with exponential backoff and jitter. _Source: https://docs.aws.amazon.com/general/latest/gr/bedrock.html_

---

### Code (Part 2)

#### Create a Knowledge Base with OpenSearch Serverless as vector store (Python boto3)

```python
import boto3

client = boto3.client('bedrock-agent', region_name='us-east-1')

response = client.create_knowledge_base(
    name='my-product-kb',
    description='Product catalog knowledge base',
    roleArn='arn:aws:iam::123456789012:role/BedrockKBServiceRole',
    knowledgeBaseConfiguration={
        'type': 'VECTOR',
        'vectorKnowledgeBaseConfiguration': {
            'embeddingModelArn': 'arn:aws:bedrock:us-east-1::foundation-model/amazon.titan-embed-text-v2:0',
            'embeddingModelConfiguration': {
                'bedrockEmbeddingModelConfiguration': {
                    'dimensions': 1024,
                    'embeddingDataType': 'FLOAT32'
                }
            }
        }
    },
    storageConfiguration={
        'type': 'OPENSEARCH_SERVERLESS',
        'opensearchServerlessConfiguration': {
            'collectionArn': 'arn:aws:aoss:us-east-1:123456789012:collection/my-collection-id',
            'vectorIndexName': 'bedrock-knowledge-base-index',
            'fieldMapping': {
                'vectorField': 'embedding',
                'textField': 'AMAZON_BEDROCK_TEXT_CHUNK',
                'metadataField': 'AMAZON_BEDROCK_METADATA'
            }
        }
    }
)

knowledge_base_id = response['knowledgeBase']['knowledgeBaseId']
print(f'Knowledge Base created: {knowledge_base_id}')
```

_Source: https://docs.aws.amazon.com/boto3/latest/reference/services/bedrock-agent/client/create_knowledge_base.html_

#### Create a Knowledge Base with Aurora pgvector as vector store (Python boto3)

```python
import boto3

client = boto3.client('bedrock-agent', region_name='us-east-1')

response = client.create_knowledge_base(
    name='my-aurora-kb',
    roleArn='arn:aws:iam::123456789012:role/BedrockKBServiceRole',
    knowledgeBaseConfiguration={
        'type': 'VECTOR',
        'vectorKnowledgeBaseConfiguration': {
            'embeddingModelArn': 'arn:aws:bedrock:us-east-1::foundation-model/amazon.titan-embed-text-v2:0',
            'embeddingModelConfiguration': {
                'bedrockEmbeddingModelConfiguration': {
                    'dimensions': 1024
                }
            }
        }
    },
    storageConfiguration={
        'type': 'RDS',
        'rdsConfiguration': {
            'resourceArn': 'arn:aws:rds:us-east-1:123456789012:cluster:my-aurora-cluster',
            'credentialsSecretArn': 'arn:aws:secretsmanager:us-east-1:123456789012:secret:bedrock-kb-db-secret',
            'databaseName': 'bedrock_kb',
            'tableName': 'bedrock_integration.bedrock_kb',
            'fieldMapping': {
                'primaryKeyField': 'id',
                'vectorField': 'embedding',
                'textField': 'chunks',
                'metadataField': 'metadata',
                # optional: customMetadataField for consolidated metadata filtering
                # 'customMetadataField': 'custom_metadata'
            }
        }
    }
)
```

_Source: https://docs.aws.amazon.com/boto3/latest/reference/services/bedrock-agent/client/create_knowledge_base.html_

#### Create an S3 Data Source with HIERARCHICAL chunking (Python boto3)

```python
import boto3

client = boto3.client('bedrock-agent', region_name='us-east-1')

response = client.create_data_source(
    knowledgeBaseId='KB12345678',
    name='product-docs-s3',
    dataSourceConfiguration={
        'type': 'S3',
        's3Configuration': {
            'bucketArn': 'arn:aws:s3:::my-knowledge-base-bucket',
            'inclusionPrefixes': ['docs/']  # optional: limit to specific prefix
        }
    },
    vectorIngestionConfiguration={
        'chunkingConfiguration': {
            'chunkingStrategy': 'HIERARCHICAL',
            'hierarchicalChunkingConfiguration': {
                'levelConfigurations': [
                    {'maxTokens': 1500},  # parent chunk (returned to LLM)
                    {'maxTokens': 300}    # child chunk (used for vector search)
                ],
                'overlapTokens': 60
            }
        }
        # Optional: add parsingConfiguration and/or customTransformationConfiguration
    }
)

data_source_id = response['dataSource']['dataSourceId']
print(f'Data Source created: {data_source_id}')
```

_Source: https://docs.aws.amazon.com/bedrock/latest/userguide/kb-data-source-customize-ingestion.html_

#### Create an S3 Data Source with SEMANTIC chunking (Python boto3)

```python
import boto3

client = boto3.client('bedrock-agent', region_name='us-east-1')

response = client.create_data_source(
    knowledgeBaseId='KB12345678',
    name='my-s3-datasource-semantic',
    dataSourceConfiguration={
        'type': 'S3',
        's3Configuration': {
            'bucketArn': 'arn:aws:s3:::my-bucket'
        }
    },
    vectorIngestionConfiguration={
        'chunkingConfiguration': {
            'chunkingStrategy': 'SEMANTIC',
            'semanticChunkingConfiguration': {
                'breakpointPercentileThreshold': 95,  # higher values = larger chunks
                'bufferSize': 0,                      # number of adjacent context sentences
                'maxTokens': 300                      # maximum chunk size
            }
        }
    }
)
```

_Source: https://docs.aws.amazon.com/bedrock/latest/userguide/kb-data-source-customize-ingestion.html_

#### Start an ingestion job and wait for completion with rate limit retry (Python boto3)

```python
import boto3
import time

client = boto3.client('bedrock-agent', region_name='us-east-1')

# StartIngestionJob has a quota of 0.1 rps (1 every 10 sec) - not increasable.
# Use retry with backoff if managing multiple KBs.
response = client.start_ingestion_job(
    knowledgeBaseId='KB12345678',
    dataSourceId='DS12345678'
)

job_id = response['ingestionJob']['ingestionJobId']
print(f'Ingestion job started: {job_id}')

# Poll until complete
while True:
    status_response = client.get_ingestion_job(
        knowledgeBaseId='KB12345678',
        dataSourceId='DS12345678',
        ingestionJobId=job_id
    )
    status = status_response['ingestionJob']['status']
    stats = status_response['ingestionJob'].get('statistics', {})
    print(f'Status: {status}, Stats: {stats}')
    
    if status in ('COMPLETE', 'FAILED', 'STOPPED'):
        break
    time.sleep(15)

if status == 'COMPLETE':
    # Wait a few minutes for OpenSearch/Pinecone/Redis before querying.
    # Aurora is immediately available.
    print('Ingestion complete. Wait ~2 min before querying (except Aurora).')
else:
    failure_reasons = status_response['ingestionJob'].get('failureReasons', [])
    print(f'Ingestion failed: {failure_reasons}')
```

_Source: https://docs.aws.amazon.com/bedrock/latest/APIReference/API_agent_StartIngestionJob.html_

#### Call RetrieveAndGenerate API (full RAG pipeline) with Python boto3

```python
import boto3

runtime_client = boto3.client('bedrock-agent-runtime', region_name='us-east-1')

# Basic call - Cohere Rerank 3.5 is the only reranker available in us-east-1
response = runtime_client.retrieve_and_generate(
    input={'text': 'What are the main features of product X?'},
    retrieveAndGenerateConfiguration={
        'type': 'KNOWLEDGE_BASE',
        'knowledgeBaseConfiguration': {
            'knowledgeBaseId': 'KB12345678',
            'modelArn': 'anthropic.claude-3-5-sonnet-20241022-v2:0',
            'retrievalConfiguration': {
                'vectorSearchConfiguration': {
                    'numberOfResults': 5,
                    # HYBRID supported only on Aurora, OpenSearch Serverless, MongoDB Atlas
                    'overrideSearchType': 'HYBRID'
                }
            },
            'generationConfiguration': {
                'inferenceConfig': {
                    'textInferenceConfig': {
                        'maxTokens': 2048,
                        'temperature': 0.0
                    }
                },
                'promptTemplate': {
                    'textPromptTemplate': (
                        'You are a helpful assistant. Answer the question '
                        'using only the provided context.\n\n'
                        'Context: $search_results$\n\nQuestion: $query$'
                    )
                }
            }
        }
    }
)

print('Answer:', response['output']['text'])
for citation in response.get('citations', []):
    for ref in citation.get('retrievedReferences', []):
        print('Source:', ref['location'].get('s3Location', {}).get('uri', 'N/A'))
        print('Chunk:', ref['content']['text'][:200])
```

_Source: https://docs.aws.amazon.com/bedrock/latest/APIReference/API_agent-runtime_RetrieveAndGenerate.html_

#### Call Retrieve API with composite metadata filtering (Python boto3)

```python
import boto3

runtime_client = boto3.client('bedrock-agent-runtime', region_name='us-east-1')

response = runtime_client.retrieve(
    knowledgeBaseId='KB12345678',
    retrievalQuery={'text': 'pricing for enterprise plan'},
    retrievalConfiguration={
        'vectorSearchConfiguration': {
            'numberOfResults': 10,
            'overrideSearchType': 'HYBRID',
            'filter': {
                'andAll': [
                    {
                        'equals': {
                            'key': 'category',
                            'value': 'pricing'
                        }
                    },
                    {
                        'greaterThan': {
                            'key': 'last_updated_year',
                            'value': 2023
                        }
                    }
                ]
            }
        }
    }
)

for result in response['retrievalResults']:
    print(f'Score: {result["score"]:.4f}')
    print(f'Text: {result["content"]["text"][:300]}')
    print(f'Location: {result["location"]}')
    print('---')

# Handle pagination
next_token = response.get('nextToken')
if next_token:
    response2 = runtime_client.retrieve(
        knowledgeBaseId='KB12345678',
        retrievalQuery={'text': 'pricing for enterprise plan'},
        nextToken=next_token
    )
```

_Source: https://docs.aws.amazon.com/bedrock/latest/APIReference/API_agent-runtime_Retrieve.html_

#### RetrieveAndGenerate with sessionId for multi-turn conversation (Python boto3)

```python
import boto3

runtime_client = boto3.client('bedrock-agent-runtime', region_name='us-east-1')

KB_CONFIG = {
    'type': 'KNOWLEDGE_BASE',
    'knowledgeBaseConfiguration': {
        'knowledgeBaseId': 'KB12345678',
        'modelArn': 'anthropic.claude-3-5-sonnet-20241022-v2:0'
    }
}

# First turn - no sessionId
response1 = runtime_client.retrieve_and_generate(
    input={'text': 'What is the refund policy?'},
    retrieveAndGenerateConfiguration=KB_CONFIG
)
session_id = response1['sessionId']  # Auto-generated: save for subsequent turns
print('Turn 1:', response1['output']['text'])

# Second turn - pass sessionId to maintain context
response2 = runtime_client.retrieve_and_generate(
    input={'text': 'How long does it take?'},  # contextual follow-up
    sessionId=session_id,  # reuse the session
    retrieveAndGenerateConfiguration=KB_CONFIG
)
print('Turn 2:', response2['output']['text'])
```

_Source: https://docs.aws.amazon.com/bedrock/latest/APIReference/API_agent-runtime_RetrieveAndGenerate.html_

#### Associate a Knowledge Base to a Bedrock Agent (Python boto3)

```python
import boto3

client = boto3.client('bedrock-agent', region_name='us-east-1')

# Associate KB to agent
response = client.associate_agent_knowledge_base(
    agentId='AGENTID12',
    agentVersion='DRAFT',  # must always be 'DRAFT' (fixed string)
    knowledgeBaseId='KB12345678',
    description=(
        'Product catalog with pricing, specifications, and availability. '
        'Query when users ask about products, prices, features, or stock levels.'
    ),
    knowledgeBaseState='ENABLED'  # ENABLED | DISABLED
)

print('Association:', response['agentKnowledgeBase'])

# IMPORTANT: after association, call PrepareAgent to make it effective
prepare_response = client.prepare_agent(
    agentId='AGENTID12'
)
print('Agent status:', prepare_response['agentStatus'])
```

_Source: https://docs.aws.amazon.com/bedrock/latest/APIReference/API_agent_AssociateAgentKnowledgeBase.html_

#### IAM Trust Policy and Permission Policy for the Knowledge Base Service Role

```json
// Trust Policy (apply to IAM role)
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {"Service": "bedrock.amazonaws.com"},
            "Action": "sts:AssumeRole",
            "Condition": {
                "StringEquals": {"aws:SourceAccount": "123456789012"},
                "ArnLike": {
                    "AWS:SourceArn": "arn:aws:bedrock:us-east-1:123456789012:knowledge-base/*"
                }
            }
        }
    ]
}

// Permission Policy: Bedrock embedding model
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": ["bedrock:ListFoundationModels", "bedrock:ListCustomModels"],
            "Resource": "*"
        },
        {
            "Effect": "Allow",
            "Action": "bedrock:InvokeModel",
            "Resource": "arn:aws:bedrock:us-east-1::foundation-model/amazon.titan-embed-text-v2:0"
        }
    ]
}

// Permission Policy: S3 data source
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": "s3:ListBucket",
            "Resource": "arn:aws:s3:::my-kb-bucket",
            "Condition": {"StringEquals": {"aws:ResourceAccount": "123456789012"}}
        },
        {
            "Effect": "Allow",
            "Action": "s3:GetObject",
            "Resource": "arn:aws:s3:::my-kb-bucket/*",
            "Condition": {"StringEquals": {"aws:ResourceAccount": "123456789012"}}
        }
    ]
}

// Permission Policy: OpenSearch Serverless vector store
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": "aoss:APIAccessAll",
            "Resource": "arn:aws:aoss:us-east-1:123456789012:collection/COLLECTION_ID"
        }
    ]
}

// Permission Policy: Aurora RDS vector store
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": "rds:DescribeDBClusters",
            "Resource": "arn:aws:rds:us-east-1:123456789012:cluster:my-aurora-cluster"
        },
        {
            "Effect": "Allow",
            "Action": [
                "rds-data:BatchExecuteStatement",
                "rds-data:ExecuteStatement"
            ],
            "Resource": "arn:aws:rds:us-east-1:123456789012:cluster:my-aurora-cluster"
        },
        {
            "Effect": "Allow",
            "Action": "secretsmanager:GetSecretValue",
            "Resource": "arn:aws:secretsmanager:us-east-1:123456789012:secret:my-db-secret*"
        }
    ]
}
```

_Source: https://docs.aws.amazon.com/bedrock/latest/userguide/kb-permissions.html_

#### Format of .metadata.json file for metadata filtering on S3

```json
// File must be named: <document_name>.<extension>.metadata.json
// Example: if document is 'product-catalog.pdf', metadata file is 'product-catalog.pdf.metadata.json'
// Must be in the same S3 folder as the document

{
    "metadataAttributes": {
        "category": "pricing",
        "product_line": "enterprise",
        "last_updated_year": 2024,
        "is_published": true,
        "author": "Product Team",
        "tags": ["pricing", "enterprise", "saas"]
    }
}

// Supported value types: string, number, boolean
// Values are used in filter operators:
// equals, notEquals, greaterThan, greaterThanOrEquals,
// lessThan, lessThanOrEquals, in, notIn, stringContains (not on S3 Vectors),
// startsWith (not on S3 Vectors), listContains
// Combine with andAll/orAll
```

_Source: https://docs.aws.amazon.com/bedrock/latest/userguide/kb-test-config.html_

#### SQL to create Aurora pgvector table for Knowledge Base (PostgreSQL)

```sql
-- Prerequisite: enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Create dedicated schema
CREATE SCHEMA IF NOT EXISTS bedrock_integration;

-- Create table with fields required by Bedrock
-- Column names are customizable, but types must match
CREATE TABLE IF NOT EXISTS bedrock_integration.bedrock_kb (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    embedding vector(1024),        -- dimension must match the model
    chunks TEXT,                   -- raw text chunk
    metadata JSON,                 -- bedrock-managed metadata
    custom_metadata JSON           -- optional: for consolidated metadata filtering
);

-- HNSW index for vector search (required)
CREATE INDEX ON bedrock_integration.bedrock_kb 
    USING hnsw (embedding vector_cosine_ops);

-- Full-text index for hybrid search (use 'english' for better accuracy on English)
CREATE INDEX ON bedrock_integration.bedrock_kb 
    USING gin (to_tsvector('english', chunks));

-- GIN index on custom_metadata if using metadata filtering
CREATE INDEX ON bedrock_integration.bedrock_kb 
    USING gin (custom_metadata);

-- Enable HNSW iterative scan (pgvector >= 0.8.0) - improves accuracy with metadata filter
-- Note: only takes effect on new sessions; with RDS Data API wait for connection pool recycling
ALTER DATABASE bedrock_kb SET hnsw.iterative_scan = 'relaxed_order';
ALTER DATABASE bedrock_kb SET hnsw.max_scan_tuples = 20000;

-- Example expression index for frequent range filter on numeric field
-- Useful if you often use filter like: lessThan: { key: 'year', value: 1989 }
CREATE INDEX ON bedrock_integration.bedrock_kb ((custom_metadata->>'year')::double precision);
```

_Source: https://docs.aws.amazon.com/bedrock/latest/userguide/knowledge-base-setup.html_

#### Knowledge Base Retrieve API wired as a Strands @tool (Python, Strands Agents)

> Note: SKILL.md playbook C points here for the canonical Retrieve-as-tool pattern.

```python
import boto3
from strands import tool

runtime_client = boto3.client("bedrock-agent-runtime", region_name="us-east-1")

KNOWLEDGE_BASE_ID = "KB12345678"   # replace with your KB ID
TOP_N = 5                          # number of chunks to return

@tool
def search_product_docs(query: str) -> str:
    """Search the product documentation knowledge base.

    Use this tool whenever the user asks about product features, pricing,
    availability, specifications, or support topics. Returns the top relevant
    passages from the knowledge base so you can ground your answer in official docs.

    Args:
        query: The natural-language question or search phrase to look up.

    Returns:
        Top matching passages with their similarity scores, formatted as text.
    """
    response = runtime_client.retrieve(
        knowledgeBaseId=KNOWLEDGE_BASE_ID,
        retrievalQuery={"text": query},
        retrievalConfiguration={
            "vectorSearchConfiguration": {
                "numberOfResults": TOP_N,
            }
        },
    )
    chunks = []
    for i, result in enumerate(response.get("retrievalResults", []), start=1):
        score = result.get("score", 0.0)
        text = result["content"]["text"]
        location = result.get("location", {})
        uri = (location.get("s3Location") or {}).get("uri", "unknown")
        chunks.append(f"[{i}] (score={score:.3f}) source={uri}\n{text}")
    return "\n\n---\n\n".join(chunks) if chunks else "No results found."
```

_Source: https://docs.aws.amazon.com/bedrock/latest/APIReference/API_agent-runtime_Retrieve.html_

#### OpenSearch Managed Cluster: create knn_vector index for Knowledge Base

```json
// PUT /<index-name> on OpenSearch REST API
// Run via OpenSearch Dashboard Dev Tools or curl
// IMPORTANT: use engine 'faiss', NOT 'nmslib' (not supported, causes silent errors in filtering)
{
    "settings": {
        "index": {
            "knn": true
        }
    },
    "mappings": {
        "properties": {
            "embedding": {
                "type": "knn_vector",
                "dimension": 1024,
                // "data_type": "binary",   // Only for binary embeddings (engine version >= 2.16)
                "space_type": "l2",         // use 'hamming' for binary embeddings
                "method": {
                    "name": "hnsw",
                    "engine": "faiss",
                    "parameters": {
                        "ef_construction": 128,
                        "m": 24
                    }
                }
            },
            "AMAZON_BEDROCK_METADATA": {
                "type": "text",
                "index": "false"
            },
            "AMAZON_BEDROCK_TEXT_CHUNK": {
                "type": "text",
                "index": "true"
            },
            // Custom metadata fields for filtering: MUST have 'keyword' type
            // Without this structure, filtering queries fail with 'Rewrite first'
            "my_custom_field": {
                "type": "text",
                "fields": {
                    "keyword": {
                        "type": "keyword"
                    }
                }
            }
        }
    }
}
```

_Source: https://docs.aws.amazon.com/bedrock/latest/userguide/knowledge-base-setup.html_

---

### Configuration reference (Part 2)

| Name | Description | Default / example |
|------|-------------|-------------------|
| `embeddingModelArn` | ARN of the Foundation Model used to generate embeddings during ingestion. Format: `arn:aws:bedrock:{region}::foundation-model/{model-id}` | `arn:aws:bedrock:us-east-1::foundation-model/amazon.titan-embed-text-v2:0` |
| `embeddingModelConfiguration.dimensions` | Number of embedding vector dimensions. Must match the vector store configuration. For titan-embed-text-v2:0: 256, 512, or 1024. For titan-embed-text-v1: fixed 1536. For cohere.embed-*-v3: fixed 1024. | `1024` |
| `embeddingModelConfiguration.embeddingDataType` | Vector type: `FLOAT32` (default, higher precision) or `BINARY` (reduces storage ~32x, lower precision). Binary supported only by Titan V2 and Cohere v3, and requires OpenSearch Serverless or Managed Cluster. S3 Vectors does NOT support binary embeddings. | `FLOAT32` |
| `chunkingStrategy` | Chunking strategy: `NONE` (whole file), `FIXED_SIZE` (fixed tokens), `HIERARCHICAL` (parent+child), `SEMANTIC` (context-aware via FM). Not modifiable after data source creation. | Default (if omitted): ~300 tokens with sentence boundary preservation |
| `fixedSizeChunkingConfiguration.maxTokens` | Maximum number of tokens per chunk in FIXED_SIZE strategy. | `300` |
| `fixedSizeChunkingConfiguration.overlapPercentage` | Percentage of overlap between consecutive chunks in FIXED_SIZE strategy. Helps maintain context between chunks. | `20` (20%) |
| `hierarchicalChunkingConfiguration.levelConfigurations[0].maxTokens` | Maximum size of the parent chunk in HIERARCHICAL chunking. The parent is returned to the LLM during retrieval. | `1500` |
| `hierarchicalChunkingConfiguration.levelConfigurations[1].maxTokens` | Maximum size of the child chunk in HIERARCHICAL chunking. Child chunks are used for vector search. | `300` |
| `semanticChunkingConfiguration.breakpointPercentileThreshold` | Percentile of distance/dissimilarity between sentences to determine breakpoints in SEMANTIC chunking. Higher values = larger chunks, fewer chunks. | `95` |
| `semanticChunkingConfiguration.bufferSize` | Number of adjacent context sentences to consider for semantic breakpoint calculation. Increase to improve coherence at the cost of more processing. | `0` |
| `semanticChunkingConfiguration.maxTokens` | Maximum size in tokens of a single semantic chunk. | `300` |
| `vectorSearchConfiguration.numberOfResults` | Number of chunks to retrieve from the vector store per query. Configurable in Retrieve and RetrieveAndGenerate. With HIERARCHICAL chunking, actual result count may be lower because child chunks with the same parent are deduplicated. | `5` |
| `vectorSearchConfiguration.overrideSearchType` | Search type: `SEMANTIC` (vector similarity only) or `HYBRID` (vector + full-text BM25). HYBRID available only for Amazon RDS (Aurora), OpenSearch Serverless, and MongoDB Atlas with filterable text field. If omitted, Bedrock chooses automatically. | `SEMANTIC` (default) |
| `knowledgeBaseId` | Unique identifier of the Knowledge Base. Pattern: `[0-9a-zA-Z]{10}`. Used as path parameter in Retrieve and as body parameter in RetrieveAndGenerate. | `KB12345678` |
| `sessionId` | Session identifier for RetrieveAndGenerate. Cannot be set manually: auto-generated on the first call. Reuse in subsequent calls to maintain conversational context. | Auto-generated, pattern: `[0-9a-zA-Z._:-]+` |
| `agentVersion` (in AssociateAgentKnowledgeBase) | Version of the agent to associate the KB to. Must always be `'DRAFT'` (fixed 5-character string). Only the DRAFT version can be modified. | `DRAFT` |
| `bedrock-agent API endpoint` | Control plane endpoint for managing KBs, data sources, ingestion jobs. boto3 service: `'bedrock-agent'`. Available in: us-east-1, us-west-2, ap-southeast-1, ap-southeast-2, ap-northeast-1, ap-northeast-2, ap-south-1, ca-central-1, eu-central-1, eu-west-1, eu-west-2, eu-west-3, sa-east-1. | `https://bedrock-agent.{region}.amazonaws.com` |
| `bedrock-agent-runtime API endpoint` | Runtime endpoint for querying KBs (Retrieve, RetrieveAndGenerate). boto3 service: `'bedrock-agent-runtime'`. Available in the same regions as bedrock-agent. | `https://bedrock-agent-runtime.{region}.amazonaws.com` |
| `Quota: max KB per account per region` | Limit of Knowledge Bases per account per region. Not increasable. | `100` |
| `Quota: concurrent ingestion jobs per account` | Maximum number of ingestion jobs running simultaneously per account per region. Not increasable. | `5` |
| `Quota: concurrent ingestion jobs per KB` | Maximum number of ingestion jobs running simultaneously for a single KB. Not increasable. | `1` |
| `Quota: concurrent ingestion jobs per data source` | Maximum number of ingestion jobs running simultaneously for a single data source. Not increasable. | `1` |
| `Quota: StartIngestionJob requests per second` | Rate limit for StartIngestionJob API. NOT increasable. Equals 1 call every 10 seconds. | `0.1 rps` (1 every 10 sec) |
| `Quota: Retrieve and RetrieveAndGenerate requests per second` | Rate limit for KB query APIs. | `20 rps each` |
| `Quota: Rerank requests per second` | Rate limit for the Rerank API. | `10 rps` |
| `Quota: Ingestion job file size (text content)` | Maximum size for a single file with text content (.txt, .pdf, .docx, etc.) in an ingestion job. | `50 MB` |
| `Quota: Ingestion job size (total)` | Maximum total size of an ingestion job. | `100 GB` |
| `Quota: User query size` | Maximum size of user query in Retrieve and RetrieveAndGenerate. | `1000 characters` |
| `Quota: Data sources per knowledge base` | Maximum number of data sources per KB. | `5` |
| `Quota: Associated KBs per Agent` | Maximum number of KBs associable to a single Bedrock Agent. Increasable on request. | `2` |
| `Quota: Files per IngestKnowledgeBaseDocuments request` | Maximum number of documents per direct `IngestKnowledgeBaseDocuments` call (direct ingest API without a job, different from `StartIngestionJob`). | `25` |

---

### Gotchas (Part 2)

- **Chunking strategy CANNOT be changed after data source creation.** To change it you must delete and recreate the data source (all documents indexed for that source are lost).

- **It is not possible to add the S3 field for multimodal storage (images, figures, tables) after the Knowledge Base is created.** If you want multimodal support, the S3 URI must be configured during KB creation.

- **The parsing strategy type (e.g., `BEDROCK_FOUNDATION_MODEL` vs `BEDROCK_DATA_AUTOMATION`) is not modifiable after data source creation.** Only internal parameters of the same strategy can be updated. To change type, a new data source is needed.

- **It is not possible to create a Knowledge Base with the AWS root user.** An IAM user with appropriate permissions must be used.

- **OpenSearch Managed Cluster requires Public access (NOT VPC).** OpenSearch domains behind VPC are not supported for Knowledge Bases.

- **For OpenSearch, use engine `'faiss'` (not `'nmslib'`): the nmslib engine causes silent failure of metadata filtering.**

- **The Aurora cluster must reside in the same AWS account as the Knowledge Base.** Cross-account Aurora is not supported.

- **After completing an ingestion job, wait a few minutes before querying the KB if using OpenSearch Serverless, OpenSearch Managed, Pinecone, or Redis.** Only Aurora RDS is immediately available after completion.

- **`AssociateAgentKnowledgeBase` requires `agentVersion='DRAFT'` (exact string).** After association, `PrepareAgent` must be called to make the change effective. Without `PrepareAgent`, the KB is not used by the agent.

- **The `description` field in `AssociateAgentKnowledgeBase` (max 200 characters) is critical for agent behavior**: it is the text the orchestration system uses to decide when to query the KB. A vague description will degrade agent behavior.

- **Do not share the IAM service role among multiple Knowledge Bases**: official documentation explicitly states that a policy cannot be shared among multiple service role roles.

- **Semantic chunking incurs additional costs for internal use of a Foundation Model during ingestion.** Do not use it for large datasets if the budget is constrained.

- **HIERARCHICAL chunking is not recommended with Amazon S3 Vectors as vector store**: with high parent chunk token counts, parent-child metadata can exceed the 1 KB metadata limit per vector imposed by S3 Vectors.

- **S3 Vectors does NOT support binary embeddings (float32 only).** Use OpenSearch Serverless or Managed Cluster for binary vectors.

- **S3 Vectors does NOT support filter operators `'startsWith'` and `'stringContains'`.** If these operators are required in metadata filtering, choose a different vector store.

- **Hybrid search (`overrideSearchType: HYBRID`) is supported ONLY for Amazon RDS (Aurora), OpenSearch Serverless, and MongoDB Atlas.** For other vector stores (Pinecone, Redis, Neptune, S3 Vectors), the search silently fails or uses only SEMANTIC.

- **Amazon Rerank 1.0 (`amazon.rerank-v1:0`) is NOT available in us-east-1.** In that region use Cohere Rerank 3.5 (`cohere.rerank-v3-5:0`).

- **For Aurora pgvector with metadata filtering, enable HNSW iterative scan (pgvector >= 0.8.0) or selective filters will return fewer results than expected.** `ALTER DATABASE` settings only take effect on new sessions; with RDS Data API, wait a few minutes for connection pool recycling.

- **Custom metadata fields in OpenSearch Managed must use `'keyword'` type (or text + keyword subfield) in the mapping.** Without this configuration, filtering queries fail with error `'Rewrite first'`.

- **The `sessionId` in `RetrieveAndGenerate` is auto-generated on the first call and cannot be set manually.** Save the value from the response and reuse it for subsequent calls in the same conversation.

- **Binary embeddings are supported only by OpenSearch Serverless and OpenSearch Managed Cluster as vector store.** With Aurora, Pinecone, Redis, S3 Vectors, etc., KB creation will fail.

- **Confluence, SharePoint, Salesforce data source connectors are in Preview and subject to changes.**

- **Cross-region inference via inference profile shares data across AWS regions.** Verify data residency requirements before using inference profiles with sensitive data.

- **`StartIngestionJob` has a rate limit of 0.1 rps (1 every 10 seconds) per account per region and is NOT increasable.** Serialize calls in automated pipelines.

- **The `'associated KBs per Agent'` quota is only 2 by default (but increasable).** Plan the multi-KB architecture for agents that must query many sources.

- **The Foundation Model parser has a limit of 100 GB total file size. The BDA parser has a limit of 1000 files.** Verify limits before using these parsers on large datasets.

- **`bedrock-agent` (control plane) and `bedrock-agent-runtime` (runtime) are available in a subset of regions compared to standard Bedrock endpoints.** Verify regional availability before deploying.

---

### Official sources (Part 2)

- [Retrieve data and generate AI responses with Amazon Bedrock Knowledge Bases](https://docs.aws.amazon.com/bedrock/latest/userguide/knowledge-base.html) — Main page: complete overview of Knowledge Bases, setup steps, and links to all sub-topics.
- [How Amazon Bedrock knowledge bases work (internal architecture)](https://docs.aws.amazon.com/bedrock/latest/userguide/kb-how-it-works.html) — Explains the pre-processing flow (chunking, embedding, indexing) and runtime (vector query, augmented prompt).
- [RetrieveAndGenerate API Reference](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_agent-runtime_RetrieveAndGenerate.html) — Complete request/response schema, examples with filter and inference profile.
- [Retrieve API Reference](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_agent-runtime_Retrieve.html) — Endpoint for raw retrieval without generation, supports pagination with nextToken.
- [Prerequisites: vector store setup (OpenSearch, Aurora, S3 Vectors, Pinecone...)](https://docs.aws.amazon.com/bedrock/latest/userguide/knowledge-base-setup.html) — All supported vector stores with field configurations, index mapping, and considerations for binary embeddings. Includes details on S3 Vectors (1 KB metadata limit per vector, 35 keys max, float32 only).
- [Create a knowledge base by connecting to a data source](https://docs.aws.amazon.com/bedrock/latest/userguide/knowledge-base-create.html) — Console and API procedure for creating a KB: required parameters, vector store options, embeddings model.
- [Customize ingestion: parsing, chunking, Lambda transform](https://docs.aws.amazon.com/bedrock/latest/userguide/kb-data-source-customize-ingestion.html) — All chunking strategies (FIXED_SIZE, HIERARCHICAL, SEMANTIC, NONE) with exact JSON format for CreateDataSource. Confirms that chunking strategy and parsing strategy type are NOT modifiable after creation.
- [How content chunking works for knowledge bases](https://docs.aws.amazon.com/bedrock/latest/userguide/kb-chunking.html) — Details on fixed-size, hierarchical, semantic chunking, and multimodal chunking.
- [Parsing options for your data source](https://docs.aws.amazon.com/bedrock/latest/userguide/kb-advanced-parsing.html) — BDA parser (preview, us-west-2 only), Foundation model parser (GA, Claude/Nova/LLama4 vision), default parser. Limit: FM parser requires total file size <= 100 GB.
- [Create a service role for Amazon Bedrock Knowledge Bases (IAM)](https://docs.aws.amazon.com/bedrock/latest/userguide/kb-permissions.html) — Trust policy, policy for S3, OpenSearch, Aurora, S3 Vectors, KMS — all ready-to-use IAM policies.
- [Sync your data with your Amazon Bedrock knowledge base](https://docs.aws.amazon.com/bedrock/latest/userguide/kb-data-source-sync-ingest.html) — StartIngestionJob, incremental sync, behavior on document modification/addition/deletion.
- [StartIngestionJob API Reference](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_agent_StartIngestionJob.html) — API to start an ingestion job: knowledgeBaseId + dataSourceId, HTTP 202 response with statistics.
- [AssociateAgentKnowledgeBase API Reference](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_agent_AssociateAgentKnowledgeBase.html) — API to link a KB to a Bedrock Agent (DRAFT version only).
- [create_knowledge_base (boto3 SDK reference)](https://docs.aws.amazon.com/boto3/latest/reference/services/bedrock-agent/client/create_knowledge_base.html) — Complete Python SDK schema with all supported storageConfiguration types.
- [Supported models and Regions for Amazon Bedrock Knowledge Bases](https://docs.aws.amazon.com/bedrock/latest/userguide/knowledge-base-supported.html) — Table of embedding models (Titan, Cohere) with vector dimensions, supported vector types, and regions. Titan V2 supported in 21 regions (including GovCloud). Titan V1 supported only in 4 regions.
- [Configure and customize queries and response generation](https://docs.aws.amazon.com/bedrock/latest/userguide/kb-test-config.html) — numberOfResults, overrideSearchType, metadata filter operators, reranking, query transformation. Hybrid search supported on RDS, OpenSearch Serverless, MongoDB Atlas.
- [Supported Regions and models for reranking in Amazon Bedrock](https://docs.aws.amazon.com/bedrock/latest/userguide/rerank-supported.html) — Amazon Rerank 1.0 (NOT available in us-east-1), Cohere Rerank 3.5 (available in us-east-1). Both GA.
- [Amazon Bedrock endpoints and quotas (official Service Quotas)](https://docs.aws.amazon.com/general/latest/gr/bedrock.html) — Complete quota table: concurrent ingestion jobs per account=5, per KB=1, per data source=1. Retrieve/RetrieveAndGenerate=20 rps. StartIngestionJob=0.1 rps. Knowledge bases per account=100. Ingestion job file size (text)=50 MB. Ingestion job size=100 GB. User query size=1000 chars.
- [Amazon S3 Vectors documentation](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-vectors.html) — S3 Vectors GA documentation: float32 only, sub-second latency for infrequent queries, native integration with Bedrock KB.
