# AWSBedrockAgentCoreSkill

[![version](https://img.shields.io/badge/version-0.1.0-blue)](.claude-plugin/plugin.json) [![license](https://img.shields.io/badge/license-MIT-green)](LICENSE) [![Claude Code plugin](https://img.shields.io/badge/Claude%20Code-plugin-orange)](https://code.claude.com/docs/en/plugins)

> **Your coding agent already "knows" AWS agents. That is the problem.**

Ask a generic LLM to build an agent on AWS and it will confidently write code from stale training data: `InvokeModel` where the Converse API is required, a bare-string `serviceTier` that throws `ParamValidationError`, a deprecated `structured_output()`, an `agentRuntimeVersion="v2"` the API rejects, a 1-hour prompt-cache TTL on a model that only supports 5 minutes. It reads fine in review. It breaks on deploy, and you lose the afternoon finding out why.

**AWSBedrockAgentCoreSkill** is a Claude Code plugin that hands the agent the *current, official* answer for each of those, with the source URL attached, so it builds the right agent the first time instead of guessing.

It is not a single template. It is a **decision engine plus a reference library**: a routing `SKILL.md` that maps a use case to the right stack and the exact files to open, 20 deep reference files, copy-paste assets, and a 369-URL official source index. Every recommendation is traceable to an official AWS source the agent can re-open.

Scope: **Strands Agents**, **Amazon Bedrock** (Converse, Guardrails, Knowledge Bases), and **Amazon Bedrock AgentCore** (Runtime, Memory, Gateway, Identity, Browser/Code Interpreter), with Terraform-first IaC and CloudWatch/OpenTelemetry observability.

## Quickstart

```text
/plugin marketplace add ferdinandobons/AWSBedrockAgentCoreSkill
/plugin install aws-bedrock-agentcore-skill@aws-agent-skills
```

Then just describe the agent you want ("build a support agent on AWS that answers from our PDFs and remembers each customer"). The skill triggers automatically and routes the agent to the right pattern. Detailed install options are [below](#install-options).

> The repository is currently **private**. Run `gh repo edit ferdinandobons/AWSBedrockAgentCoreSkill --visibility public` to let others install it.

---

## Why it is different from "just ask the model"

- **Every claim cites an official source.** 636 inline `_Source:` citations across 20 reference files, indexed in [`sources.md`](skills/aws-bedrock-agentcore-skill/references/sources.md) (369 unique official URLs). When the agent recommends something, it can show you the page it came from, and re-open it when it needs more.
- **It chooses the pattern, not just the API.** A decision tree routes the use case (chatbot, tool-using agent, RAG, multi-agent, serverless production, memory, auth, guardrails, observability, IaC) to a recommended stack and the exact reference files to open. No dumping 19,000 lines into context: it opens only what the task needs.
- **Built to be correct, then adversarially checked.** Researched from official docs, then run through a build-simulation audit ("could an agent build this use case from the skill alone?"), a full cross-file review, and a pass that verified **292 code snippets piece by piece against official documentation** (by reading the docs, not executing code). That pass alone caught real runtime bugs: wrong `serviceTier` shape, deprecated `structured_output`, `response['body']` vs `response['response']`, list-vs-dict configuration bundles, `agentRuntimeVersion` format.
- **Maturity-aware.** Every feature is labelled **GA** or **Preview**, and Preview is never proposed as a production default.
- **Honest on purpose.** Volatile facts (live prices, default quotas, current model IDs and regions) are deferred to the AWS console instead of being hard-coded to rot. Anything no official page could confirm is flagged "verify live" rather than asserted as fact.

These are exactly the version-specific traps that cost hours when an agent gets them wrong, and the reason a source-cited skill beats generic model knowledge for this domain.

---

## What you type, what it does

The skill is description-driven: Claude consults it automatically whenever a task involves building, configuring, deploying, securing, monitoring, or debugging an AI agent on AWS, even if the specific service is not named. You can also invoke it explicitly with `/aws-bedrock-agentcore-skill:aws-bedrock-agentcore-skill`.

Prompts that activate it:

- "Build a customer-support agent on AWS that answers from our PDFs and remembers each customer across sessions."
- "Productionize my Strands agent on AgentCore Runtime with guardrails and observability, deployed with Terraform."
- "I need 3 specialist agents with conditional routing. Which Strands pattern, and how do I stop it looping forever?"
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

**At a glance:** 1 router + **20 reference files** (~19,000 lines), **14 assets**, **636 inline source citations**, **369 unique official source URLs**.

---

## How it was built and verified

This is not a one-shot generation. The content was researched from official documentation, then put through several adversarial passes, each one fixing real defects:

1. **Build-simulation audit:** an agent tried to build each use case using only the skill, and logged every point where it had to guess or leave the skill.
2. **Full cross-file review:** per-file checks for bugs, contradictions, unverified sources, and coverage gaps, plus cross-file consistency.
3. **Snippet verification:** 292 code snippets checked one by one against the official API references, SDK docs, and provider registries (no code executed).

Source claims were checked against live AWS and Strands docs throughout. See [`sources.md`](skills/aws-bedrock-agentcore-skill/references/sources.md) for the full topic to official-URL map and the provenance policy (AWS service docs, the Strands SDK site, the official Terraform registry, and AWS GitHub orgs; the two non-AWS sources, the cross-vendor A2A protocol spec and an optional Langfuse OTEL backend, are explicitly labelled; third-party blogs are excluded).

## What it does not do (so you can trust what it does)

- **It does not execute code against a live account.** Snippets are verified against official docs, which catches API-shape and naming errors but not account-specific issues. Validate the generated config on a real account before production (IAM actually attaches, quotas, region availability, cost).
- **It does not freeze AWS in time.** AgentCore ships features monthly. Treat maturity labels and version-specific facts as suspect after roughly 3 to 6 months and re-verify via the cited sources. Maintenance guidance lives in [`CLAUDE.md`](CLAUDE.md).
- **It is not an official AWS distribution.** It is an independent, source-cited best-practices skill.

---

## Install options

This repo is both a **plugin** and a single-plugin **marketplace** (`aws-agent-skills`).

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

---

## Versioning

Semantic versioning in [`.claude-plugin/plugin.json`](.claude-plugin/plugin.json). Current: **0.1.0** (initial release). Bump on every change you ship to installers.

## License

[MIT](LICENSE) © 2026 Ferdinando Bons.

> Strands Agents, Amazon Bedrock, and Amazon Bedrock AgentCore are products of Amazon Web Services. This is an independent, source-cited best-practices skill, not an official AWS distribution.
