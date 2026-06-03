# AWS AI Agent Architect

[![version](https://img.shields.io/badge/version-0.1.0-blue)](.claude-plugin/plugin.json) [![license](https://img.shields.io/badge/license-MIT-green)](LICENSE) [![Claude Code plugin](https://img.shields.io/badge/Claude%20Code-plugin-orange)](https://code.claude.com/docs/en/plugins)

> The **definitive, source-cited playbook** that lets a coding agent (especially Claude) **autonomously design, configure, deploy, and troubleshoot production-grade AI agents on AWS** — with every recommendation traceable to an official AWS source it can re-open.

This repository is a **Claude Code plugin** that bundles the `aws-ai-agent-architect` skill. Hand it to a coding agent and, knowing nothing about AWS agents up front, it can stand up the *right* agent for the user's use case — applying official AWS best practices instead of guessing.

It is **not** a single template. It is a decision engine + reference library: a routing `SKILL.md`, 20 deep reference files, ready-to-adapt assets, and a 369-URL official source index.

---

## Why this exists

AWS agent APIs are full of version-specific gotchas that generic model knowledge gets wrong — Converse vs the legacy `InvokeModel`, the 5× token burndown, the boto3 region-resolution order, the ARM64 AgentCore runtime contract, asynchronous long-term memory, prompt-cache TTL support per model. This skill encodes the **current, official** answers and, crucially, **cites the source for each one** so the agent (and you) can verify and re-read it.

Design principles baked in:

- **Official sources only.** Every best practice and code snippet carries an inline `_Source:_` URL. Provenance is tiered (AWS service docs, the Strands SDK site, the official Terraform registry, AWS GitHub orgs); the two non-AWS sources (the cross-vendor A2A protocol spec and an optional Langfuse OTEL backend) are explicitly labelled, and third-party blogs are excluded.
- **Autonomous building.** A primary decision tree maps a use case → recommended stack → exactly which reference files to open (progressive disclosure).
- **Maturity-aware.** Every feature is labelled **GA / Preview**; Preview is never proposed as a production default.
- **Data-aware.** Volatile facts (live prices, default quotas, current model IDs/regions) are deliberately deferred to the AWS console / model cards instead of being hard-coded to rot.
- **Conflict rule.** If two parts disagree, the detailed `references/` file wins over the summary/matrices; when unsure, re-verify the official URL in `references/sources.md`.

---

## Install

This repo is both a **plugin** and a single-plugin **marketplace** (`aws-agent-skills`).

### From a Git host (recommended)

```text
# 1) Add this repo as a marketplace (replace with your fork/remote)
/plugin marketplace add <your-username>/aws-ai-agent-architect

# 2) Install the plugin
/plugin install aws-ai-agent-architect@aws-agent-skills

# 3) Confirm
/plugin list
```

> `/plugin marketplace add` also accepts a full Git URL (`https://github.com/<you>/aws-ai-agent-architect.git`) or a `owner/repo@ref` form.

### Try it locally (no install)

```bash
# From the repository root
claude --plugin-dir "/path/to/aws-ai-agent-architect"
# After edits, inside the session:
/reload-plugins
```

### Validate the plugin

```bash
claude plugin validate .
```

### Use it as a plain skill (without the plugin system)

Copy the skill directory into your skills folder:

```bash
cp -r skills/aws-ai-agent-architect ~/.claude/skills/
```

### Uninstall

```text
/plugin uninstall aws-ai-agent-architect@aws-agent-skills
# or temporarily:
/plugin disable aws-ai-agent-architect
```

---

## How it triggers

The skill is description-driven: Claude consults it automatically whenever a task involves building, configuring, deploying, securing, monitoring, or debugging an AI agent on AWS — even if the specific service isn't named. You can also invoke it explicitly with `/aws-ai-agent-architect:aws-ai-agent-architect`.

**Example prompts that activate it:**

- "Build a customer-support agent on AWS that answers from our PDFs and remembers each customer across sessions."
- "Productionize my Strands agent on AgentCore Runtime with guardrails and observability, deployed with Terraform."
- "I need 3 specialist agents with conditional routing — which Strands pattern, and how do I stop it looping forever?"
- "Which inference profile and model should I use on Bedrock to control cost?"
- "Write least-privilege IAM for a Bedrock agent."

---

## What it covers

The `SKILL.md` decision tree routes across the full realistic use-case space:

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
| Infrastructure as Code | **Terraform-first** (`hashicorp/aws` + `awscc`); CDK secondary |
| Host any framework on AgentCore | LangGraph · CrewAI · LlamaIndex · Google ADK · Strands (framework-agnostic Runtime) |
| Test & safe rollout | Local testing · unit tests · AgentCore Evaluations in CI · versioned endpoints + canary |
| Batch · cost-routing · custom models | Batch inference · Intelligent Prompt Router · fine-tuning + Provisioned Throughput |
| Security · IAM · cost · quotas | Least-privilege IAM, KMS, VPC PrivateLink, token burndown, prompt caching |

---

## What's inside

```
.
├── .claude-plugin/
│   ├── plugin.json              # Plugin manifest
│   └── marketplace.json         # Single-plugin marketplace (aws-agent-skills)
├── skills/
│   └── aws-ai-agent-architect/
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

**At a glance:** 1 router + **20 reference files** (~19,000 lines), **14 assets**, **636 inline source citations**, **369 unique official source URLs**.

---

## Provenance & maintenance

- **Provenance:** see [`skills/aws-ai-agent-architect/references/sources.md`](skills/aws-ai-agent-architect/references/sources.md) for the full topic → official-URL map and the source policy.
- **Built and audited with multi-agent workflows:** the content was researched from official docs, then put through a build-simulation audit (can an agent build autonomously from it alone?), a full cross-file review (bugs, contradictions, unverified sources, coverage), and a verified fix pass. Source claims were checked against live AWS docs.
- **Data-aware:** model IDs, prices, and quotas change — the skill points to the live model cards, Bedrock pricing page, and Service Quotas console for exact numbers. Re-verify time-sensitive facts before relying on them.
- **Maturity labels** track AWS GA/Preview status as of mid-2026; re-check the cited page for the current state.

## Versioning

Semantic versioning in [`.claude-plugin/plugin.json`](.claude-plugin/plugin.json). Current: **0.1.0** (initial release). Bump on every change you want to ship to installers.

## License

[MIT](LICENSE) © 2026 Ferdinando Bons.

> Strands Agents, Amazon Bedrock, and Amazon Bedrock AgentCore are products of Amazon Web Services. This is an independent, source-cited best-practices skill and is not an official AWS distribution.
