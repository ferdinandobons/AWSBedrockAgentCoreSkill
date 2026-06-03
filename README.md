# AWSBedrockAgentCoreSkill

[![version](https://img.shields.io/badge/version-0.1.0-blue)](.claude-plugin/plugin.json) [![license](https://img.shields.io/badge/license-MIT-green)](LICENSE) [![Claude Code plugin](https://img.shields.io/badge/Claude%20Code-plugin-orange)](https://code.claude.com/docs/en/plugins)

A Claude Code plugin (and agent skill) that puts the best practices for building AI agents on AWS, with Amazon Bedrock AgentCore at the center, in one place. Instead of sending the coding agent to search across dozens of AWS docs or work things out by trial and error, it hands over a consolidated, official, source-cited playbook so the agent goes straight to the right approach and can show you the source behind every recommendation.

**Scope:** Strands Agents, Amazon Bedrock (Converse, Guardrails, Knowledge Bases), and Amazon Bedrock AgentCore (Runtime, Memory, Gateway, Identity, Browser/Code Interpreter), plus Terraform-first IaC and CloudWatch/OpenTelemetry observability.

> **Built and verified with Claude Code multi-agent workflows:** ~140 subagents, ~15M tokens, and 800+ official-documentation reads went into researching, writing, and adversarially QA-ing this skill.

## What it is

It is not a single template or a code generator. It is a routing layer plus a reference library:

- a `SKILL.md` that acts as a decision tree: it maps the user's use case to a recommended stack and to the exact reference files to open;
- **20 reference files** (~19,000 lines) covering each area in depth, with an inline `_Source:` URL on every best practice and code snippet;
- **assets**: a service-selection matrix, a model-selection guide, a pre-production checklist, ready-to-adapt IAM policies, and copy-paste starter snippets;
- a central source index ([`sources.md`](skills/aws-bedrock-agentcore-skill/references/sources.md)) mapping each topic to its official URL (**369 unique official sources**).

The agent loads only the files a task needs (progressive disclosure), so it stays useful without pulling the whole library into context.

## Why use it

Building agents on AWS (especially Bedrock AgentCore) means a lot of scattered documentation and a fast-changing API surface. Left on its own, a coding agent either crawls across many pages or proceeds by trial and error, and still gets the version-specific details wrong. This skill removes both problems:

- **The best practices are already gathered and organized.** The agent does not have to research half the internet: the relevant official guidance for each area is collected in one place and routed by use case, so it goes straight to the right approach instead of probing around.
- **It is current and source-cited.** Bedrock AgentCore is recent and changes often. The skill encodes today's official answers and attaches the documentation URL to each one, so the agent (and you) can verify a recommendation instead of trusting it blindly. There are **636 inline source citations** across the reference files.
- **It prevents the common, non-obvious mistakes.** These are the kind of errors that look correct in review and only fail at deploy: using the legacy `InvokeModel` instead of the Converse API, passing `serviceTier` as a bare string, calling a deprecated `structured_output()`, setting a 1-hour prompt-cache TTL on a model that only supports 5 minutes, ignoring the ARM64 AgentCore runtime contract, or mis-sizing `max_tokens` and hitting the 5x token burndown. The skill documents the correct form for each.
- **It picks the right pattern, not just the API.** The decision tree distinguishes a simple chatbot from a tool-using agent, RAG, a multi-agent system, a serverless production deployment, and so on, and points to the matching reference. It also covers when a managed alternative (Bedrock Agents, Flows, the Responses API) fits better than the code-first path.
- **It is maturity-aware.** Every feature is labelled GA or Preview, and Preview is never recommended as a production default.
- **It does not hard-code values that rot.** Live prices, default quotas, and current model IDs are deferred to the AWS console and model cards; the skill teaches the durable shape (how caching is billed, how burndown works) and points to the live source for the exact numbers.

## Quickstart

```text
/plugin marketplace add ferdinandobons/AWSBedrockAgentCoreSkill
/plugin install aws-bedrock-agentcore-skill@aws-agent-skills
```

Then describe the agent you want to build. The skill triggers automatically (see [How it triggers](#how-it-triggers)). Full install options, including local testing, are [below](#install-options).

## How it triggers

The skill is description-driven: Claude consults it whenever a task involves building, configuring, deploying, securing, monitoring, or debugging an AI agent on AWS, even when the specific service is not named. You can also invoke it explicitly with `/aws-bedrock-agentcore-skill:aws-bedrock-agentcore-skill`.

Prompts that activate it:

- "Build a customer-support agent on AWS that answers from our PDFs and remembers each customer across sessions."
- "Productionize my Strands agent on AgentCore Runtime with guardrails and observability, deployed with Terraform."
- "I need 3 specialist agents with conditional routing. Which Strands pattern, and how do I stop it looping forever?"
- "Which inference profile and model should I use on Bedrock to control cost?"
- "Write least-privilege IAM for a Bedrock agent."

## What it covers

The `SKILL.md` decision tree routes across the realistic use-case space:

| Use case | Recommended path |
|---|---|
| Build approach (first choice) | Code-first (Strands + AgentCore) · managed Bedrock Agents · Bedrock Flows · Responses API |
| Simple chatbot (no tools) | Bedrock Converse / minimal Strands agent |
| Tool-using agent | Strands `@tool` + MCP; AgentCore Browser / Code Interpreter |
| RAG over documents | Bedrock Knowledge Bases (Retrieve / RetrieveAndGenerate) |
| Multi-agent | Strands Graph · Swarm · Workflow · Agents-as-Tools · A2A |
| Serverless production | AgentCore Runtime (ARM64 contract) · Fargate/ECS/EKS · Lambda |
| Persistent memory | AgentCore Memory (STM/LTM) · Strands SessionManager |
| Secure tools / user auth | AgentCore Gateway + Identity (+ Policy/Cedar) |
| Safety / compliance | Bedrock Guardrails |
| Observability | AgentCore Observability · CloudWatch GenAI · OpenTelemetry · Evaluations |
| Infrastructure as Code | Terraform-first (`hashicorp/aws` + `awscc`); CDK secondary |
| Host any framework on AgentCore | LangGraph · CrewAI · LlamaIndex · Google ADK · Strands (framework-agnostic Runtime) |
| Test & safe rollout | Local testing · unit tests · AgentCore Evaluations in CI · versioned endpoints + canary |
| Batch · cost-routing · custom models | Batch inference · Intelligent Prompt Router · fine-tuning + Provisioned Throughput |
| Security · IAM · cost · quotas | Least-privilege IAM, KMS, VPC PrivateLink, token burndown, prompt caching |

## What's inside

```
.
├── .claude-plugin/
│   ├── plugin.json              # Plugin manifest
│   └── marketplace.json         # Single-plugin marketplace (aws-agent-skills)
├── skills/
│   └── aws-bedrock-agentcore-skill/
│       ├── SKILL.md             # Routing layer: decision tree + playbooks + 12 cross-cutting rules
│       ├── references/          # 20 deep, source-cited reference files
│       │   ├── strands.md
│       │   ├── bedrock.md                 # models, Converse, prompt caching + Knowledge Bases/RAG
│       │   ├── bedrock-platform.md         # Intelligent Prompt Router, batch, fine-tuning, data residency
│       │   ├── agentcore-runtime.md
│       │   ├── frameworks-on-agentcore.md  # host LangGraph/CrewAI/LlamaIndex/Google ADK/Strands
│       │   ├── memory.md
│       │   ├── gateway-identity.md
│       │   ├── tools.md                   # Strands @tool & MCP
│       │   ├── agentcore-tools.md         # Browser & Code Interpreter
│       │   ├── multi-agent.md
│       │   ├── observability.md
│       │   ├── testing-and-rollout.md      # local testing, Evaluations in CI, versioned endpoints, canary
│       │   ├── security-iam-cost.md
│       │   ├── guardrails.md
│       │   ├── managed-alternatives.md    # managed Agents, Flows, Responses API, Policy, Evaluations
│       │   ├── deployment-iac.md          # Terraform (primary)
│       │   ├── deployment-best-practices.md
│       │   ├── deployment-cdk.md          # CDK (secondary)
│       │   ├── deployment-frameworks.md   # Lambda / Fargate / EKS
│       │   └── sources.md                 # central official-source index (369 URLs)
│       ├── assets/
│       │   ├── service-selection-matrix.md
│       │   ├── model-selection-guide.md
│       │   ├── deployment-checklist.md
│       │   ├── iam-policies/              # ready-to-adapt IAM role & trust policies
│       │   └── snippets/                  # copy-paste starters per pattern
│       └── evals/evals.json               # realistic test prompts
├── README.md
└── LICENSE
```

At a glance: 1 router + 20 reference files (~19,000 lines), 14 assets, 636 inline source citations, 369 unique official source URLs.

## How it was built and verified

The content was researched from official documentation and then put through several review passes, each one correcting real defects:

1. **Build-simulation audit:** an agent attempted each use case using only the skill and logged every point where it had to guess or step outside it.
2. **Full review:** per-file checks for bugs, contradictions, unverified sources, and coverage gaps, plus cross-file consistency.
3. **Snippet verification:** 292 code snippets were checked one by one against the official API references, SDK docs, and provider registries (by reading the documentation, not by executing code).

Provenance is restricted to official sources: AWS service docs (`docs.aws.amazon.com`, AWS blogs), the Strands SDK site, the official Terraform registry, and AWS GitHub orgs. Two non-AWS sources are used and explicitly labelled (the cross-vendor A2A protocol spec, and Langfuse as an optional OpenTelemetry backend); third-party blogs are excluded. See [`sources.md`](skills/aws-bedrock-agentcore-skill/references/sources.md) for the full topic-to-URL map.

## Scope and limitations

- **It verifies code against docs, not against a live account.** Snippet checks catch API-shape and naming errors but not account-specific issues. Validate the generated configuration on a real account before production (IAM attachment, quotas, region availability, cost).
- **It has a shelf life.** AgentCore ships features frequently. Treat maturity labels and version-specific facts as suspect after roughly 3 to 6 months and re-verify via the cited sources. Maintenance guidance is in [`CLAUDE.md`](CLAUDE.md).
- **It is independent.** Not an official AWS distribution.

## Install options

This repo is both a plugin and a single-plugin marketplace (`aws-agent-skills`).

**From a Git host (recommended):**

```text
/plugin marketplace add ferdinandobons/AWSBedrockAgentCoreSkill
/plugin install aws-bedrock-agentcore-skill@aws-agent-skills
/plugin list
```

`/plugin marketplace add` also accepts a full Git URL (`https://github.com/ferdinandobons/AWSBedrockAgentCoreSkill.git`) or an `owner/repo@ref` form.

**Try it locally (no install):**

```bash
claude --plugin-dir "/path/to/AWSBedrockAgentCoreSkill"
# after edits, inside the session:
/reload-plugins
```

**Validate the plugin:** `claude plugin validate .`

**Use it as a plain skill (without the plugin system):** `cp -r skills/aws-bedrock-agentcore-skill ~/.claude/skills/`

**Uninstall:** `/plugin uninstall aws-bedrock-agentcore-skill@aws-agent-skills` (or `/plugin disable aws-bedrock-agentcore-skill` to keep it installed but off).

## Versioning

Semantic versioning in [`.claude-plugin/plugin.json`](.claude-plugin/plugin.json). Current: 0.1.0 (initial release). Bump on every change you ship to installers.

## License

[MIT](LICENSE) © 2026 Ferdinando Bons.

> Strands Agents, Amazon Bedrock, and Amazon Bedrock AgentCore are products of Amazon Web Services. This is an independent, source-cited best-practices skill, not an official AWS distribution.
