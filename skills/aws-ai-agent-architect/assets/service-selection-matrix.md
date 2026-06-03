<!-- Asset of the aws-ai-agent-architect skill. See ../SKILL.md and ../references/ for detail and official sources. -->

# Service selection matrix

## Use-case → recommended stack

| Use case | Recommended stack | Key AWS services | Maturity | When NOT to use it / cheaper alternative |
|---|---|---|---|---|
| **Simple chatbot** (no tools, single or multi-turn) | `Strands Agent` + `BedrockModel` (Converse API) | Amazon Bedrock Converse API, boto3 | GA | Skip Strands entirely and call `boto3.client("bedrock-runtime").converse()` directly if you need no agent loop and want fewer moving parts. |
| **Tool-using agent** (function calling, APIs, databases) | `Strands Agent` + `@tool` functions and/or MCP client | Amazon Bedrock Converse API, Strands SDK, optional AgentCore MCP Gateway | GA | Do not reach for AgentCore Browser/Code Interpreter unless you need a sandboxed environment — they cost extra and bill until explicitly stopped. |
| **Sandboxed web browser / code execution** | `Strands Agent` + AgentCore built-in Browser or Code Interpreter tools | AgentCore Browser Tool, AgentCore Code Interpreter | GA (Oct 2025, 16 regions; Web Bot Auth still Preview) | If you only need to run lightweight Python, a regular `@tool` wrapping a subprocess is free and fully GA. |
| **RAG over private documents** | `Bedrock Knowledge Base` (`RetrieveAndGenerate` managed, or `Retrieve` + custom Converse call) | Bedrock Knowledge Bases, OpenSearch Serverless or Aurora pgvector | GA | Do not hand-roll a vector pipeline unless you need features KB doesn't support — it adds ops burden. For small corpora, pass documents directly in the prompt with prompt caching instead. |
| **Multi-agent — deterministic / conditional routing** | `Strands GraphBuilder` (DAG with explicit edges) | Strands multi-agent, Bedrock Converse | GA | Avoid if the routing logic is trivial (two steps) — a simple `if/else` + sequential calls is clearer. Do not use the deprecated `agent_graph`. |
| **Multi-agent — emergent / handoff-based** | `Strands Swarm` | Strands multi-agent, Bedrock Converse | GA | Avoid in regulated environments where every decision must be auditable — Graph gives more determinism. |
| **Multi-agent — repeatable task DAG** | `Strands Workflow` | Strands multi-agent, Bedrock Converse | GA | Prefer Graph when routing depends on runtime conditions rather than a fixed order. |
| **Multi-agent — supervisor calls specialist agents** | `Agents-as-Tools` pattern (supervisor treats sub-agents as Strands tools) | Strands multi-agent, Bedrock Converse | GA | Overkill for two cooperating agents — wire them directly with a handoff instead. |
| **Multi-agent — network-exposed agents** | `A2A` (Agent-to-Agent protocol, agents exposed over HTTP) | Strands A2A, Amazon ECS/Fargate or AgentCore Runtime | GA (Strands SDK 1.0; AgentCore Runtime A2A support GA Oct 2025) | For fully in-process orchestration, prefer Graph/Swarm/Workflow — A2A adds network hops and auth complexity. |
| **Serverless production agent** | `BedrockAgentCoreApp` on **AgentCore Runtime** (ARM64, `/invocations` + `/ping` on 8080) | AgentCore Runtime, Amazon ECR, IAM execution role | GA | Lambda is cheaper for short, stateless invocations (no streaming, no session state). Fargate/ECS is better when you need HTTP response streaming outside AgentCore. |
| **Agent with persistent memory** | `AgentCore Memory` (STM events + LTM strategies) wired via `AgentCoreMemorySessionManager`; or `Strands SessionManager` (S3/file) for simpler needs | AgentCore Memory, Amazon S3 | AgentCore Memory: GA (Oct 2025); Strands SessionManager: GA | Do not use LTM if you cannot tolerate asynchronous extraction (no read-after-write guarantee). For simple single-session context, a `SlidingWindowConversationManager` in Strands is GA and free. |
| **Agent with user auth / OAuth / token vault** | `AgentCore Identity` (inbound JWT/IAM; outbound OAuth credential providers) + `AgentCore Gateway` | AgentCore Identity, AgentCore Gateway, IAM | GA (Oct 2025) | If you only need IAM-based caller identity and no user-delegated OAuth flows, skip Identity and use the standard IAM execution role. |
| **Expose external APIs / Lambda as MCP tools** | `AgentCore Gateway` (turn REST APIs, Lambda functions, OpenAPI specs into MCP endpoints) | AgentCore Gateway, AWS Lambda, IAM | GA (Oct 2025) | If the tools are only ever called by a single in-process agent, define them as `@tool` functions directly — no gateway needed. |
| **Safety, content filtering, compliance** | `Amazon Bedrock Guardrails` (content filters, denied topics, PII masking, contextual grounding) | Bedrock Guardrails | GA | Do not use `DRAFT` version in production — always deploy a numbered version. For minimal filtering needs, system-prompt instructions are simpler, but offer no PII detection or audit trail. |
| **Monitoring / debugging in production** | `AgentCore Observability` + `CloudWatch GenAI Observability` (Transaction Search) + OpenTelemetry/ADOT | CloudWatch, AgentCore Observability, AWS Distro for OpenTelemetry | AgentCore Observability: GA (Oct 2025); CloudWatch Transaction Search: GA | Enable Transaction Search **before** deploy — it is not retroactive. For local development, console logging + Strands hooks is sufficient. |
| **Low-code / managed agent** (no custom orchestration code) | **Amazon Bedrock managed Agents** (`InvokeAgent` / `InvokeInlineAgent`, action groups, KB wiring) | Bedrock Agents, AWS Lambda (action groups), Bedrock Knowledge Bases | GA | Choose Strands + AgentCore instead when you need custom/dynamic orchestration, graphs/swarms, or tool logic beyond action groups. See [managed-alternatives.md](../references/managed-alternatives.md). |
| **Fixed visual GenAI pipeline** (deterministic DAG) | **Amazon Bedrock Flows** (visual builder, versioned artifact) | Bedrock Flows, prompts, Knowledge Bases, Lambda | GA (persistent long-running exec + inline-code node: Preview) | Not for open-ended agent loops or logic beyond supported node types — use Strands. See [managed-alternatives.md](../references/managed-alternatives.md). |
| **Migrating an OpenAI-SDK app to Bedrock** | **Amazon Bedrock Responses API** (`bedrock-mantle`, OpenAI-compatible, stateful) | Bedrock Responses API | GA (Dec 2025) | For greenfield AWS-native agents prefer Strands + AgentCore for tighter control/integration. See [managed-alternatives.md](../references/managed-alternatives.md). |
| **Deterministic tool-call authorization** (regulated / multi-tenant) | **AgentCore Policy** (Cedar) on top of AgentCore Gateway — complements any framework | AgentCore Policy, AgentCore Gateway | GA (Mar 2026) | If app-level checks suffice and you have no compliance mandate, the Gateway's standard auth may be enough. See [managed-alternatives.md](../references/managed-alternatives.md). |
| **Automated agent quality scoring / eval** | **AgentCore Evaluations** (online + CI regression, built-in + custom evaluators) — complements any framework | AgentCore Evaluations, OpenTelemetry | GA (Mar 2026) | For traces alone (no scoring) plain Observability suffices. See [managed-alternatives.md](../references/managed-alternatives.md). |
| **Host a non-Strands framework** (LangGraph, CrewAI, LlamaIndex, Google ADK) | Wrap it in `BedrockAgentCoreApp` (or any server meeting the contract) on **AgentCore Runtime** (framework-agnostic) | AgentCore Runtime, AgentCore CLI | GA | If the framework needs no AWS-managed hosting, run it on your own Fargate/EKS instead. See [frameworks-on-agentcore.md](../references/frameworks-on-agentcore.md). |
| **Test before deploy + safe rollout** | Local test (AgentCore CLI) → unit tests / Strands Evals → AgentCore Evaluations in CI → versioned endpoints + canary | AgentCore Runtime versions/endpoints, AgentCore Evaluations | GA (Gateway A/B + bundle rollback: Preview) | Don't pin prod traffic to the auto-updating DEFAULT endpoint. See [testing-and-rollout.md](../references/testing-and-rollout.md). |
| **Large offline / batch jobs** | **Bedrock Batch inference** (asynchronous, ~50% cheaper) | Bedrock batch inference, S3 | GA | Not for interactive agents; no tool calling, structured output, or prompt caching in batch. See [bedrock-platform.md](../references/bedrock-platform.md). |
| **Auto-route across models for cost/quality** | **Bedrock Intelligent Prompt Router** (two models, same family) | Bedrock Intelligent Prompt Router | GA (Apr 2025) | English-optimized; for a single fixed model just call it directly. See [bedrock-platform.md](../references/bedrock-platform.md). |
| **Fine-tuned / custom model** | Custom model + **Provisioned Throughput** (required for custom-model inference) | Bedrock custom models, Provisioned Throughput | GA | Custom models have no on-demand path — Provisioned Throughput is mandatory and costs per model-unit/hour. See [bedrock-platform.md](../references/bedrock-platform.md). |

---

## Need → which reference file to open

| I need to… | Open this reference |
|---|---|
| Build any Strands agent (agent loop, streaming, hooks, structured output, conversation manager) | [`references/strands.md`](../references/strands.md) |
| Choose a model, use the Converse API, set inference profiles, cache prompts, enable reasoning, do RAG | [`references/bedrock.md`](../references/bedrock.md) |
| Deploy an agent as a managed serverless service (AgentCore Runtime, sessions, versioning) | [`references/agentcore-runtime.md`](../references/agentcore-runtime.md) |
| Add short-term or long-term memory (AgentCore Memory or Strands SessionManager) | [`references/memory.md`](../references/memory.md) |
| Turn APIs / Lambda / OpenAPI specs into MCP tools, or handle OAuth / user auth | [`references/gateway-identity.md`](../references/gateway-identity.md) |
| Define Strands tools (`@tool`, `TOOL_SPEC`, MCP integration, human-in-the-loop) | [`references/tools.md`](../references/tools.md) |
| Use sandboxed Browser or Code Interpreter (AgentCore built-in tools) | [`references/agentcore-tools.md`](../references/agentcore-tools.md) |
| Orchestrate multiple agents (Graph, Swarm, Workflow, Agents-as-Tools, A2A) | [`references/multi-agent.md`](../references/multi-agent.md) |
| Set up tracing, metrics, logging (CloudWatch GenAI, OTEL, Transaction Search) | [`references/observability.md`](../references/observability.md) |
| Configure IAM least-privilege, KMS, VPC PrivateLink, quotas, token burndown, prompt caching cost | [`references/security-iam-cost.md`](../references/security-iam-cost.md) |
| Add content filters, denied topics, PII masking, contextual grounding (Guardrails) | [`references/guardrails.md`](../references/guardrails.md) |
| Choose a managed/low-code path (Bedrock managed Agents, Flows, Responses API) or complementary capabilities (Policy/Cedar, Evaluations, Prompt Management) | [`references/managed-alternatives.md`](../references/managed-alternatives.md) |
| Write Terraform IaC for Bedrock and AgentCore resources | [`references/deployment-iac.md`](../references/deployment-iac.md) |
| Apply IaC best practices (remote state, least-priv IAM via Terraform, ARM64 build, CI/CD) | [`references/deployment-best-practices.md`](../references/deployment-best-practices.md) |
| Use AWS CDK (secondary IaC option) with L2/alpha constructs | [`references/deployment-cdk.md`](../references/deployment-cdk.md) |
| Deploy a Strands agent to Lambda, Fargate-ECS, or EKS (non-AgentCore hosting) | [`references/deployment-frameworks.md`](../references/deployment-frameworks.md) |
| Host any framework (LangGraph/CrewAI/LlamaIndex/Google ADK) on AgentCore, or check Python vs TypeScript SDK differences | [`references/frameworks-on-agentcore.md`](../references/frameworks-on-agentcore.md) |
| Test an agent before deploy (local, unit tests, Evaluations in CI) and roll it out safely (versioned endpoints, canary) | [`references/testing-and-rollout.md`](../references/testing-and-rollout.md) |
| Use Intelligent Prompt Router, batch inference, fine-tuning/custom models, or check a data-residency checklist | [`references/bedrock-platform.md`](../references/bedrock-platform.md) |
| Re-read or verify any official source URL | [`references/sources.md`](../references/sources.md) |

---

> This matrix mirrors the primary decision tree in [SKILL.md](../SKILL.md). For detailed gotchas, build order, and critical warnings for each pattern, follow the decision tree there and open the matching reference files listed above.
