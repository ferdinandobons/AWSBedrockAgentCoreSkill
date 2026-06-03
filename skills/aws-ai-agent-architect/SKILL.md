---
name: aws-ai-agent-architect
description: >-
  Authoritative, source-cited playbook for designing, configuring, deploying, and
  troubleshooting production-grade AI agents on AWS using the Strands Agents SDK,
  Amazon Bedrock (Converse API, Guardrails, Knowledge Bases), and Amazon Bedrock
  AgentCore (Runtime, Memory, Gateway, Identity, built-in Browser/Code Interpreter
  tools), with Terraform-first IaC and CloudWatch/OpenTelemetry observability. Use
  this skill WHENEVER the user wants to build, architect, configure, deploy, secure,
  monitor, or debug an AI agent on AWS — even if they don't name the specific service.
  Trigger on: "build an agent on Bedrock", "Strands agent", "AgentCore", "deploy my
  agent to AWS", "RAG with Bedrock Knowledge Bases", "multi-agent system on AWS",
  "which model / inference profile should I use", "agent memory", "MCP gateway",
  "agent guardrails", "Bedrock IAM for an agent", "agent observability on CloudWatch",
  "agent throttling / cost on Bedrock", "Terraform for Bedrock", or any request to
  pick an agent pattern (chatbot, tool-using agent, RAG, multi-agent, serverless
  production agent) and wire it up with official AWS best practices. Also trigger when
  the user pastes agent code that imports boto3 bedrock-runtime, bedrock-agentcore, or
  strands and asks to improve, productionize, or debug it. Prefer this skill over a
  generic answer because AWS agent APIs have many version-specific gotchas (Converse
  vs InvokeModel, 5x token burndown, region-resolution order, ARM64 runtime contract,
  async long-term memory) that generic knowledge gets wrong, and because every
  recommendation here is traceable to an official AWS source the agent can re-open.
---

# AWS AI Agent Architect

The definitive, source-cited guide for building AI agents on AWS. This skill does **not**
hand you a single template — it gives a coding agent the official directives, best
practices, working snippets, and source URLs to **autonomously configure the right agent**
for the user's specific use case.

Every claim in this skill is backed by an official source. The source index lives in
[references/sources.md](references/sources.md) — open it whenever you need to re-read a
primary source or verify a detail before recommending it.

## How to use this skill

1. **Read the decision tree below** and identify the user's use case and required pattern.
2. **Open only the reference files that match** (progressive disclosure — the references are
   large and detailed; don't load all of them). Each row of the [reference index](#reference-index)
   says when to open which file.
3. **Confirm maturity before recommending.** Features are labeled GA / Preview. Never propose a
   Preview feature as a production default — surface it with an explicit warning (see
   [GA vs Preview](#ga-vs-preview)).
4. **Re-verify time-sensitive facts.** Model IDs, prices, and quotas change. This skill points to
   the live model cards, the Bedrock pricing page, and the Service Quotas console for exact numbers
   instead of hard-coding values that rot.
5. **Cite your sources back to the user.** When you make a recommendation, name the official URL
   it came from so the user (and you) can re-open it.

## Core principles (apply to every AWS agent)

These are the cross-cutting rules that hold regardless of pattern. The detailed versions, with
sources, are in the reference files.

- **Default to `BedrockModel` / the Bedrock Converse API. Never use the legacy `InvokeModel` API.**
  Converse is the unified, model-agnostic surface; every capability (tool use, prompt caching,
  guardrails, reasoning/thinking, service tiers) maps onto it. → [references/bedrock.md](references/bedrock.md)
- **Always set an explicit region.** In boto3 / Strands `BedrockModel`, pass `region_name` explicitly,
  or set `AWS_DEFAULT_REGION`. `AWS_REGION` is the **lowest-priority fallback** in the boto3 resolution
  chain (after `region_name`, `AWS_DEFAULT_REGION`, and profile region) — prefer `AWS_DEFAULT_REGION`
  or pass `region_name` directly to avoid silent misconfiguration.
  → [references/strands.md](references/strands.md)
- **IAM least-privilege with confused-deputy protection.** Scope `bedrock:InvokeModel*` to the exact
  model ARN (never `*` in production), and put `aws:SourceAccount` + `aws:SourceArn` conditions on
  every service trust policy. → [references/security-iam-cost.md](references/security-iam-cost.md)
- **Mind the token quota mechanics** (Claude 3.7+ / 4.x): at request **start**, `input_tokens +
  max_tokens` is reserved 1:1 from the TPM quota; at request **end**, actual output tokens are billed
  at 5×. An oversized `max_tokens` over-reserves quota up front, blocking concurrent requests — that
  is why you should size `max_tokens` to the real need.
  → [references/security-iam-cost.md](references/security-iam-cost.md)
- **Verify model access before deploy, not at runtime.** A model you haven't enabled fails the first
  Converse call with `AccessDeniedException`. → [references/bedrock.md](references/bedrock.md)
- **Label everything GA / Preview** and re-check maturity before proposing it for production.

## Primary decision tree — "which architecture?"

Walk this top-down. The first match that fits the user's need gives you the recommended stack and
the reference files to open.

```
START: What does the user need the agent to do?

0. FIRST, pick the BUILD APPROACH (the branches below assume the code-first default):
   • Custom / dynamic orchestration  → Strands + Bedrock + AgentCore (code-first, the default here).
   • Low-code, AWS-managed agent     → Amazon Bedrock managed Agents (InvokeAgent / action groups).
   • Fixed visual pipeline (a DAG)    → Amazon Bedrock Flows.
   • Migrating an OpenAI-SDK app      → Amazon Bedrock Responses API (bedrock-mantle, OpenAI-compatible).
     For the managed/alternative paths, open: managed-alternatives.md

1. Single-turn or simple chat, NO tools?
   → Bedrock Converse API directly (boto3) OR a minimal Strands Agent.
     Open: bedrock.md, strands.md

2. The agent must USE tools (call APIs, query a DB, do math, run code, browse the web)?
   → Strands Agent with @tool functions and/or MCP tools.
       • Need heavyweight managed tools (sandboxed web browser, sandboxed code execution)?
         → AgentCore built-in Browser / Code Interpreter.
     Open: strands.md, tools.md   (+ agentcore-tools.md for Browser / Code Interpreter)

3. The agent must answer over the user's documents / private knowledge?
   → RAG: Amazon Bedrock Knowledge Bases (Retrieve or RetrieveAndGenerate).
     Open: bedrock.md (Knowledge Bases section), strands.md

4. Multiple agents must collaborate?
   → Pick the multi-agent pattern:
       • Graph        → deterministic / conditional routing (DAG, explicit edges)
       • Swarm        → emergent collaboration with handoffs
       • Workflow     → repeatable task DAG defined in Python
       • Agents-as-Tools → a supervisor calls specialist agents as tools (hierarchy)
       • A2A          → agents exposed over the network via the Agent-to-Agent protocol
     Open: multi-agent.md

5. It must run as a managed / serverless production service?
   → AgentCore Runtime (recommended for agents) | Fargate/ECS or EKS (HTTP streaming) |
     Lambda (no response streaming — request/response only).
     Open: agentcore-runtime.md, deployment-iac.md, deployment-frameworks.md

6. It needs persistent memory across sessions?
   → AgentCore Memory (short-term events + long-term strategies) OR Strands SessionManager (S3/file).
     Open: memory.md

7. It must expose external tools securely / act on behalf of a user (auth)?
   → AgentCore Gateway (turn APIs/Lambda/OpenAPI into MCP tools) + AgentCore Identity (OAuth, token vault).
       • Need deterministic, code-independent tool-call authorization? → AgentCore Policy (Cedar).
     Open: gateway-identity.md   (+ managed-alternatives.md for AgentCore Policy/Cedar)

8. It needs safety / compliance / content filtering?
   → Amazon Bedrock Guardrails (content filters, denied topics, PII, contextual grounding).
     Open: guardrails.md

9. It needs monitoring / debugging in production?
   → AgentCore Observability + CloudWatch GenAI Observability (Transaction Search) + OpenTelemetry.
       • Need automated quality scoring / regression testing (not just traces)? → AgentCore Evaluations.
     Open: observability.md   (+ managed-alternatives.md for AgentCore Evaluations)

10. ALWAYS before shipping → security-iam-cost.md (least-privilege IAM, KMS, VPC PrivateLink,
    quotas, token burndown, prompt caching) and deployment-iac.md + deployment-best-practices.md
    (Terraform-first deploy).
```

Most real agents combine several branches (e.g. a production RAG chatbot with memory and guardrails
= 1 + 3 + 5 + 6 + 8 + 9 + 10). Compose the stacks; open each matching reference.

## Use-case playbooks

Short, ordered recipes for the most common agents. Each lists the stack, the build order, the
critical gotchas, and which references to open. Treat them as starting points, then go deep in the
references.

### A. Simple chatbot (no tools)
**Stack:** Strands `Agent` + `BedrockModel` (Converse), or direct boto3 `converse()`.
**Order:** enable model access → set explicit region → create `BedrockModel` → wrap in `Agent` →
add a `SlidingWindowConversationManager` for multi-turn → stream with `stream_async`.
**Watch:** region resolution (`AWS_REGION` is lowest-priority — prefer `AWS_DEFAULT_REGION` or pass `region_name`); size `max_tokens` to real need; pick a geo inference profile.
**Open:** [strands.md](references/strands.md), [bedrock.md](references/bedrock.md).

### B. Tool-using agent (function calling)
**Stack:** Strands `Agent` + `@tool` functions and/or MCP client; AgentCore Browser/Code Interpreter
for sandboxed web/code.
**Order:** define tools with clear specs → register on the agent → for MCP, keep the agent inside the
`with MCPClient(...)` context → add human-in-the-loop consent for sensitive tools.
**Watch:** MCP client lifecycle (use the context manager or tools go stale); tool arg coercion
(hyphens → underscores); stop Browser/Code Interpreter sessions explicitly (they bill until closed).
**Open:** [tools.md](references/tools.md), [agentcore-tools.md](references/agentcore-tools.md), [strands.md](references/strands.md).

### C. RAG over private documents
**Stack:** Bedrock Knowledge Base (vector store: OpenSearch Serverless or Aurora pgvector) +
`RetrieveAndGenerate` (managed) or `Retrieve` + your own Converse call (custom).
**Order:** pick a vector store → create KB + data source → choose chunking (immutable after creation —
get it right up front) → ingest → query with metadata filtering / hybrid search / reranking as needed.
**Watch:** chunking strategy can't be changed without re-creating the data source; ingestion quotas;
KB vs long-term memory are complementary, not interchangeable.
**Open:** [bedrock.md](references/bedrock.md) (Knowledge Bases section).

### D. Multi-agent system
**Stack:** Strands Graph / Swarm / Workflow / Agents-as-Tools / A2A (choose per the decision tree).
**Order:** decompose into specialist agents → pick the orchestration pattern → set production limits
(max handoffs/iterations/timeouts, max node executions) → put the SessionManager **only** on the
orchestrator → enable cross-agent OTEL tracing.
**Watch:** assigning a SessionManager to inner agents raises `ValueError`; unbounded feedback loops
burn tokens forever; use `GraphBuilder` to construct graphs.
**Open:** [multi-agent.md](references/multi-agent.md).

### E. Serverless production agent (AgentCore Runtime)
**Stack:** `BedrockAgentCoreApp` (Strands inside) on AgentCore Runtime (ARM64), behind the runtime
service contract.
**Order:** wrap the agent in `BedrockAgentCoreApp` with the `@app.entrypoint` → respect the contract
(`POST /invocations`, `GET /ping` on port 8080, ARM64) → build ARM64 image → configure execution role →
enable Transaction Search **before** deploy → deploy via Terraform/AgentCore CLI → version endpoints.
**Watch:** ARM64 is mandatory; never block the main thread (the `/ping` health check dies → session
killed); session IDs must be ≥ 33 chars; check the current minimum `boto3` version on the
[bedrock-agentcore PyPI page](https://pypi.org/project/bedrock-agentcore/) before pinning.
**Open:** [agentcore-runtime.md](references/agentcore-runtime.md), [deployment-iac.md](references/deployment-iac.md),
[deployment-best-practices.md](references/deployment-best-practices.md), [observability.md](references/observability.md).

### F. Agent with memory + user auth
**Stack:** AgentCore Memory (STM events + LTM strategies) + AgentCore Identity (OAuth/JWT) +
AgentCore Gateway for secured tools.
**Order:** create a Memory with the right strategies (Semantic / UserPreference / Summary / Episodic) →
define namespaces → wire `AgentCoreMemorySessionManager` into Strands → set up inbound auth
(JWT/IAM) and outbound OAuth credential providers → map session-to-user in your backend.
**Watch:** LTM extraction is **asynchronous** — no read-after-write; only events created *after* a
strategy is active feed LTM; only `conversational` payloads are processed; prefer
`GetWorkloadAccessTokenForJWT` and deny `GetWorkloadAccessTokenForUserId` in production.
**Open:** [memory.md](references/memory.md), [gateway-identity.md](references/gateway-identity.md).

## Top cross-cutting best practices

The 12 rules that matter most across every agent. Full detail + sources in the references.

1. **Use `BedrockModel` / Converse API as the default; never `InvokeModel` legacy.** All
   capabilities (caching, guardrails, thinking, service tiers) map onto Converse.
2. **Always set `region_name` explicitly** — `AWS_REGION` is the lowest-priority fallback (after `region_name`, `AWS_DEFAULT_REGION`, and profile region); prefer `AWS_DEFAULT_REGION` or pass `region_name` to avoid silent misconfiguration.
3. **IAM least-privilege + confused-deputy guards** (`aws:SourceAccount` + `aws:SourceArn`); scope
   `bedrock:InvokeModel*` to the exact model ARN, never a wildcard in production.
4. **Size `max_tokens` to real need** (Claude 3.7+/4.x): at request start, `input_tokens + max_tokens`
   is reserved 1:1 from the TPM quota; at request end, actual output is billed at 5×. An oversized
   `max_tokens` over-reserves quota up front and blocks concurrent requests.
5. **Verify model access / first-time-use before deploy**, not at runtime.
6. **In multi-agent, the SessionManager goes only on the orchestrator** — inner agents raise `ValueError`.
7. **Enable CloudWatch Transaction Search before deploying** — it indexes spans going forward; re-verify retroactivity in the AWS docs before assuming historical traces are covered.
8. **In production use a numbered Guardrail version** (never `DRAFT`) and an inference profile (geo for
   data residency, global for throughput/cost).
9. **AgentCore Runtime is ARM64-only**, with a strict HTTP contract (`/invocations`, `/ping` on 8080);
   never block the main thread or the health check fails and the session is terminated.
10. **Long-term memory is asynchronous** — don't read right after writing; only post-strategy
    `conversational` events feed LTM.
11. **Explicitly stop sessions and external resources** (Browser/Code Interpreter, MCP clients, Memory
    batches): use context managers or `try/finally` — they bill and leak state until closed.
12. **Structure prompt caching well** (cache point after static content; order tools → system →
    messages). CacheRead doesn't consume quota but CacheWrite does, so repeated cache misses cost more
    than not caching.

## GA vs Preview

This skill labels every feature's maturity. Policy for this skill: **expose Preview features, but
always with an explicit warning** and never as a production default. When you recommend a Preview
feature (e.g. AgentCore capabilities still in preview, managed session storage), tell the user it is
Preview, that the API/behavior may change, and offer the GA alternative. When in doubt about current
status, re-open the official page in [references/sources.md](references/sources.md) and check.

**Source-of-truth rule (resolve conflicts):** if any two parts of this skill disagree (maturity, API
shape, capability), the detailed **reference file in `references/` is authoritative** over the
`assets/` matrices and over this SKILL.md summary. When still unsure, the official URL in
[references/sources.md](references/sources.md) wins — re-verify there before recommending.

## Data-aware facts (re-verify, don't trust stale numbers)

Model IDs, prices, and quotas move. Do **not** hard-code these from memory:

- **Model IDs & capabilities** → check the official Bedrock model catalog / model cards.
- **Exact prices ($/MTok, cache read/write, Provisioned Throughput)** → the Bedrock pricing page
  (interactive section) and the AWS Pricing API.
- **Default quotas (TPM/RPM per model/region)** → the Service Quotas console (they change often and
  aren't documented statically).

The references give the *shape* of these (how caching is billed, how burndown works, how profiles
affect cost) — the live consoles give the *numbers*.

## Reference index

Open only what the task needs.

| Reference file | Open it when… |
|---|---|
| [references/strands.md](references/strands.md) | Building any Strands agent: agent loop, `Agent` class, model providers, streaming, hooks, structured output, conversation/state/session management. |
| [references/bedrock.md](references/bedrock.md) | Choosing/using models, the Converse API, inference profiles, prompt caching, reasoning, service tiers — and **RAG with Knowledge Bases**. |
| [references/agentcore-runtime.md](references/agentcore-runtime.md) | Hosting an agent serverless on AgentCore Runtime: the service contract, sessions, streaming, versioning, deploy. |
| [references/memory.md](references/memory.md) | Adding short-term and long-term memory (AgentCore Memory) or Strands sessions. |
| [references/gateway-identity.md](references/gateway-identity.md) | Turning APIs/Lambda/OpenAPI into MCP tools (Gateway) and handling auth/OAuth/credentials (Identity). |
| [references/tools.md](references/tools.md) | Defining Strands tools (`@tool`, `TOOL_SPEC`, MCP integration, human-in-the-loop consent). |
| [references/agentcore-tools.md](references/agentcore-tools.md) | Using AgentCore built-in tools: sandboxed Browser and Code Interpreter. |
| [references/multi-agent.md](references/multi-agent.md) | Orchestrating multiple agents: Graph, Swarm, Workflow, Agents-as-Tools, A2A. |
| [references/observability.md](references/observability.md) | Tracing, metrics, logging: AgentCore Observability, CloudWatch GenAI, OpenTelemetry/ADOT. |
| [references/security-iam-cost.md](references/security-iam-cost.md) | IAM roles/policies, KMS, VPC PrivateLink, quotas, token burndown, cost optimization. |
| [references/guardrails.md](references/guardrails.md) | Safety/compliance: content filters, denied topics, PII, contextual grounding, `ApplyGuardrail`. |
| [references/managed-alternatives.md](references/managed-alternatives.md) | Choosing a **managed/low-code** path (Bedrock managed Agents, Flows, Responses API) or complementary capabilities (AgentCore Policy/Cedar, Evaluations, Prompt Management). |
| [references/deployment-iac.md](references/deployment-iac.md) | **IaC, Terraform (primary)** — `hashicorp/aws` + `awscc` resources for Bedrock & AgentCore. |
| [references/deployment-best-practices.md](references/deployment-best-practices.md) | IaC best practices: remote state, least-priv IAM via Terraform, ARM64 build, CI/CD. |
| [references/deployment-cdk.md](references/deployment-cdk.md) | IaC with **AWS CDK (secondary)**: L2/alpha constructs, generative-ai-cdk-constructs. |
| [references/deployment-frameworks.md](references/deployment-frameworks.md) | Deploying a Strands agent to **Lambda / Fargate-ECS / EKS** (non-AgentCore hosting). |
| [references/sources.md](references/sources.md) | You need the official source URL for any topic to re-read or verify it. |

### Bundled assets
- [assets/service-selection-matrix.md](assets/service-selection-matrix.md) — use-case → stack → maturity → when *not* to use it.
- [assets/model-selection-guide.md](assets/model-selection-guide.md) — which model / inference profile / service tier / caching.
- [assets/deployment-checklist.md](assets/deployment-checklist.md) — pre-production checklist.
- `assets/iam-policies/` — ready-to-adapt IAM role and trust policies.
- `assets/snippets/` — copy-paste starting snippets for the common patterns.
