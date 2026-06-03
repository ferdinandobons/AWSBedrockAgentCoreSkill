# Managed & Complementary AWS Agent Surfaces

> Part of the **aws-bedrock-agentcore-skill** skill. See [SKILL.md](../SKILL.md) for the decision tree. Every source below is official - re-open it to verify details.

This skill defaults to the **code-first path** (Strands Agents + Amazon Bedrock + AgentCore). That is the right default for custom, dynamic agents - but it is **not always the best tool**. Before building, decide whether a **managed / lower-code** AWS service fits better, and remember the **complementary** capabilities that strengthen *any* agent (including a Strands one). Everything here is GA unless noted, and all are official AWS surfaces.

## Table of contents
- [When to leave the code-first default](#when-to-leave-the-code-first-default)
- [Part 1 - Managed / alternative agent-building services](#part-1--managed--alternative-agent-building-services)
- [Part 2 - Complementary capabilities (use WITH your agent)](#part-2--complementary-capabilities-use-with-your-agent)
- [Official sources](#official-sources)

## When to leave the code-first default

Pick the building approach **first**, then walk the SKILL.md decision tree for the chosen approach:

- **Strands + AgentCore (code-first)** - default in this skill. Choose for custom orchestration, dynamic multi-step reasoning, bespoke tool logic, and full control over the agent loop.
- **Managed Bedrock Agents** - choose for low-code, AWS-managed, durable agent definitions (action groups, versioned aliases, console wiring) when you don't want to run/host orchestration code yourself.
- **Bedrock Flows** - choose when the work is a fixed, deterministic, versioned workflow graph (supports conditions and loops via DoWhile/Iterator nodes) of Bedrock resources you want to assemble visually and version as an immutable artifact (not an open-ended agent loop).
- **Bedrock Responses API (bedrock-mantle)** - choose when migrating an existing **OpenAI SDK** codebase to Bedrock with minimal change, or when you want managed stateful multi-turn + server-side built-in tools without building session state yourself.

## Part 1 - Managed / alternative agent-building services

### Amazon Bedrock managed Agents (InvokeAgent / InvokeInlineAgent)
**Maturity:** GA. A fully managed agent service: agent definitions live in Bedrock with versioned aliases, action groups (Lambda or OpenAPI), Knowledge Base wiring, and a managed control plane. `InvokeAgent` calls a pre-created agent; `InvokeInlineAgent` supplies the agent config at request time.
**Choose it over Strands+AgentCore when:** you want AWS to host and manage the orchestration (durable, versioned, console-buildable) rather than running agent logic in your own compute, and your flow fits the managed action-group/KB model.
**Don't choose it when:** you need custom orchestration, dynamic graphs/swarms, or tool logic beyond action groups - use Strands + AgentCore Runtime.
_Source: https://docs.aws.amazon.com/bedrock/latest/userguide/agents.html_

### Amazon Bedrock Flows
**Maturity:** GA (the visual DAG builder is GA; *persistent long-running execution* and the *inline-code node* are in Preview - label them as such if proposed).
**What it is:** a visual builder that links Bedrock resources - prompts, Knowledge Bases, Lambda functions, agents, iterators, conditions - into a deterministic, versioned workflow graph (supports conditions and loops via DoWhile/Iterator nodes) you version as an artifact.
**Choose it over Strands+AgentCore when:** the workload is a fixed, repeatable pipeline of Bedrock steps you want assembled visually and governed as an immutable, versioned artifact.
**Don't choose it when:** you need open-ended, dynamic agent loops or business logic beyond the supported node types.
_Source: https://docs.aws.amazon.com/bedrock/latest/userguide/flows.html_

### Amazon Bedrock Responses API (bedrock-mantle endpoint)
**Maturity:** GA (launched December 2025; documented as recommended for stateful/agentic apps, no preview label).
**What it is:** an **OpenAI-protocol-compatible** API on the `bedrock-mantle` endpoint with stateful multi-turn conversation management, server-side built-in tools, and asynchronous long-running inference. Migration is largely a base-URL + API-key swap from an OpenAI SDK app.
**Choose it when:** migrating an existing OpenAI SDK codebase to Bedrock with minimal code change, or when you want managed conversation state + server-side tools without building session logic.
**Don't choose it when:** building greenfield AWS-native agents where Strands + AgentCore gives you more control and tighter AWS integration.
_Source: https://docs.aws.amazon.com/bedrock/latest/userguide/bedrock-mantle.html_

## Part 2 - Complementary capabilities (use WITH your agent)

These are **not** alternatives - they strengthen an agent built on *any* framework (including Strands).

### Amazon Bedrock AgentCore Policy (Cedar-based gateway authorization)
**Maturity:** GA (March 2026). A Cedar-language policy engine inside AgentCore Gateway that enforces fine-grained, **code-independent** authorization over which tools an agent may call and with what inputs - before tool traffic reaches the backend.
**Use it when:** a security/compliance team needs deterministic, auditable access control over tool calls (regulated or multi-tenant scenarios). Add it to a Gateway-based agent (see [gateway-identity.md](gateway-identity.md)).
_Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy.html_

### Amazon Bedrock AgentCore Evaluations
**Maturity:** GA (March 31, 2026). Continuous, automated quality scoring for agents: online evaluation of production traffic, on-demand/CI regression testing, with built-in LLM-as-a-Judge evaluators plus custom Lambda-based scorers. Integrates with Strands and LangGraph via OpenTelemetry.
**Use it when:** you need to measure and regression-test agent quality (not just collect traces). Pairs with [observability.md](observability.md).
_Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/evaluations.html_

### Amazon Bedrock Prompt Management
**Maturity:** GA. A centralized, versioned catalog of prompts integrated into applications by referencing a prompt version ARN in the Converse API or by adding a prompt node to a Bedrock Flow, with lifecycle governance (versions, rollback, A/B testing, metadata).
**Use it when:** you want to externalize and version prompts independently of agent/application code, instead of hard-coding system prompts.
_Source: https://docs.aws.amazon.com/bedrock/latest/userguide/prompt-management.html_

## Official sources

- [Amazon Bedrock Agents (managed)](https://docs.aws.amazon.com/bedrock/latest/userguide/agents.html) - managed agent service: action groups, aliases, InvokeAgent / InvokeInlineAgent.
- [Amazon Bedrock Flows](https://docs.aws.amazon.com/bedrock/latest/userguide/flows.html) - visual GenAI DAG pipelines (core GA; persistent execution + inline-code node Preview).
- [Amazon Bedrock Responses API (bedrock-mantle)](https://docs.aws.amazon.com/bedrock/latest/userguide/bedrock-mantle.html) - OpenAI-compatible, stateful, server-side tools; GA Dec 2025.
- [Amazon Bedrock AgentCore Policy (Cedar)](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy.html) - deterministic tool-call authorization in Gateway; GA Mar 2026.
- [Amazon Bedrock AgentCore Evaluations](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/evaluations.html) - automated agent quality scoring; GA Mar 31 2026.
- [Amazon Bedrock Prompt Management](https://docs.aws.amazon.com/bedrock/latest/userguide/prompt-management.html) - versioned prompt catalog; integrate via Converse API (prompt version ARN) or Flows prompt node; GA.
