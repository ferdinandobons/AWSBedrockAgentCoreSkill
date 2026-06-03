<!-- Asset of the aws-ai-agent-architect skill. See ../SKILL.md and ../references/ for detail and official sources. -->

# Model & inference selection guide

> **Verify live** — exact model IDs, per-token prices, TPM/TPD quota defaults, and regional availability change frequently. Always cross-check against the [Bedrock model catalog / model cards](https://docs.aws.amazon.com/bedrock/latest/userguide/model-cards.html), the [Bedrock pricing page](https://aws.amazon.com/bedrock/pricing/), and the [Service Quotas console](https://console.aws.amazon.com/servicequotas/) before hard-coding anything.

---

## 1. Choosing an inference profile

| Profile type | `modelId` prefix | Use when |
|---|---|---|
| **Geo cross-region** | `us.` / `eu.` / `au.` / `jp.` | Data-residency requirements — traffic stays within the named geography |
| **Global cross-region** | `global.` | Max throughput + ~10 % cost saving vs geo; no residency constraint |
| **Application inference profile** | `arn:aws:bedrock:…:inference-profile/…` | Cost attribution per team / env / project via AWS Cost Allocation Tags |
| **Base model ID** | `anthropic.…` | Dev/test only — no burst buffering, no cross-region failover |

**Decision tree:**

```
Has data-residency requirement?
  Yes → geo profile (us. / eu. / au. / jp.)
  No  → Does request carry any EU/regulated data tag?
          Yes → geo profile matching regulation
          No  → global profile (cheapest, most headroom)

Need cost split by team/env/experiment?
  Yes → wrap the chosen geo or global profile in an Application Inference Profile (CreateInferenceProfile + tags)
```

**IAM notes for global routing:**
- Requires a **three-statement** IAM policy: (1) inference-profile ARN in source region, (2) FM ARN in-region, (3) FM ARN without region/account (global).
- SCPs must explicitly allow `aws:RequestedRegion = "unspecified"` or global routing is silently blocked.

**Gotcha:** geo profiles require `bedrock:InvokeModel` in **all** destination regions listed on the model card. A single blocked destination region fails all requests to that profile.

---

## 2. Prompt caching — when and how

### Enable caching when

- System prompt or tool definitions exceed the minimum-token threshold **and** will be reused across multiple calls (same session or same batch).
- RAG documents are prepended to many user turns.
- ROI rule: **cache hit saves more than the cache-write surcharge**. Cache-write tokens are priced above standard input tokens; cache-read tokens are priced well below. Break-even is typically reached after ~2 hits within the TTL window.

### Cache point placement order (mandatory)

```
tools  →  system  →  messages
  ↑            ↑            ↑
 cachePoint  cachePoint   cachePoint   (up to 4 total per request)
```

Modifying any upstream section invalidates **all downstream checkpoints**. Keep tool definitions and system prompt fully static; put the user query after the last checkpoint.

### Minimum token thresholds per model

| Models | Min tokens per checkpoint |
|---|---|
| Claude 3.7 Sonnet, Sonnet 4.6, Opus 4, Opus 4.1 | 1 024 |
| Claude Opus 4.5 / 4.6, Sonnet 4.5, Haiku 4.5 | 4 096 |

Max 4 checkpoints per request on all supported models.

### TTL options

| TTL | Supported models |
|---|---|
| 5 min (default) | All cache-capable models |
| 1 hour | Claude Opus 4.5, Haiku 4.5, Sonnet 4.5 |

If 1h TTL is specified on an unsupported model it is **silently ignored** — verify via the model card.

### Billing & quota impact

| Token type | Counts against TPM quota? | Billed at |
|---|---|---|
| `inputTokens` (non-cached) | Yes | Standard input rate |
| `cacheWriteInputTokens` | **Yes** | Cache-write rate (higher than standard) |
| `cacheReadInputTokens` | **No** | Cache-read rate (lower than standard) |
| `outputTokens` | Yes (× burndown) | Output rate |

Simplified Cache Management: place **one** `cachePoint` after the static block; Bedrock searches up to ~20 content blocks backward for the best match.

---

## 3. Service tiers

| Tier | `service_tier` value | Price vs Standard | SLA / notes | Use when |
|---|---|---|---|---|
| **Standard** | `"default"` (or omit) | 1× | On-demand, best-effort | Default; interactive workloads with moderate concurrency |
| **Priority** | `"priority"` | +75 % | No reservation; lower latency headroom | Customer-facing, latency-sensitive, no need for Reserved commitment |
| **Flex** | `"flex"` | −50 % | Higher latency variance | Non-interactive: batch processing, offline RAG, agentic pipelines, summarization |
| **Reserved** | `"reserved"` | Contact AWS | 99.5 % uptime target; 1- or 3-month commitment | Predictable high-volume production; min 100 K input TPM + 10 K output TPM |

**Notes:**
- On-demand quota is **shared** across Standard, Priority, and Flex; Reserved has its own capacity pool.
- Reserved tier sizing: include `InputTokenCount + CacheWriteInputTokens` — not just input tokens — or you'll overflow to Standard.
- Flex is incompatible with batch inference (use batch inference instead for ~50 % off on true async jobs).

---

## 4. Reasoning / extended thinking

### Which models, which mode

| Model | Supported mode | Notes |
|---|---|---|
| Claude 3.7 Sonnet | `type: "enabled"` + `budget_tokens` | Fixed budget; min 1 024 tokens |
| Claude Opus 4.5, Sonnet 4.5, Haiku 4.5 | `type: "enabled"` + `budget_tokens` | Fixed budget; min 4 096 tokens for cache |
| Claude Opus 4.6, Sonnet 4.6 | `type: "adaptive"` + `effort` | `"enabled"` is deprecated on these models |
| **Claude Opus 4.7** | `type: "adaptive"` **only** | `"enabled"` returns HTTP 400 |
| Claude Mythos (Gated Preview) | `type: "adaptive"` **only** | Gated research preview; us-east-1 only |

`effort` levels (adaptive): `max` (Opus 4.6 only) / `high` (default) / `medium` / `low` — pass in `output_config`, not inside `thinking`.

Claude 4 models return **summarized** thinking content, not the full chain-of-thought.

### Incompatibilities

- `temperature`, `topP`, `top_k` — **not compatible** with any thinking mode; omit them.
- `toolChoice: any` or `toolChoice: tool` (forced tool use) — not compatible; only `auto` is allowed.
- Streaming is **required** if `max_tokens > 21 333`.
- Batch inference — thinking modes not supported.

---

## 5. The 5× token burndown rule & sizing `max_tokens`

**Applies to:** Claude 3.7 Sonnet and all Claude 4.x models.

```
Quota consumed = inputTokens + cacheWriteInputTokens + (max_tokens × 5)
                                                          ↑
                           deducted from TPM at request start, before generation
```

- `max_tokens` is reserved upfront against the TPM quota; unused tokens are returned at completion.
- Billing is on **actual** tokens generated, not on `max_tokens`.
- Setting `max_tokens = 32 768` "for safety" on a 200-token response wastes 163 360 quota tokens per call.

**How to size `max_tokens`:**
1. Run a representative sample; inspect `outputTokens` in `usage`.
2. Set `max_tokens` ≈ p95 of observed output + 20 % headroom.
3. Monitor `stopReason = "max_tokens"` (output truncated) in CloudWatch — raise only if it fires.
4. Use `requestMetadata` tags (`team`, `env`) to segment CloudWatch metrics per workload.

**For models with 1:1 burndown** (all non-Claude-3.7+ models): quota consumed = input + output; `max_tokens` is not deducted upfront.

---

## Sources (official)

- Model cards (IDs, inference profiles, caching limits, service tiers): `https://docs.aws.amazon.com/bedrock/latest/userguide/model-cards.html`
- Inference profiles: `https://docs.aws.amazon.com/bedrock/latest/userguide/inference-profiles-support.html`
- Global cross-region inference: `https://docs.aws.amazon.com/bedrock/latest/userguide/global-cross-region-inference.html`
- Prompt caching: `https://docs.aws.amazon.com/bedrock/latest/userguide/prompt-caching.html`
- Service tiers: `https://docs.aws.amazon.com/bedrock/latest/userguide/service-tiers-inference.html`
- Token burndown / quota: `https://docs.aws.amazon.com/bedrock/latest/userguide/quotas-token-burndown.html`
- Extended thinking: `https://docs.aws.amazon.com/bedrock/latest/userguide/claude-messages-extended-thinking.html`
- Adaptive thinking: `https://docs.aws.amazon.com/bedrock/latest/userguide/claude-messages-adaptive-thinking.html`
- Pricing: `https://aws.amazon.com/bedrock/pricing/`
