# Changelog

All notable changes to this project are documented here. This project follows
[Semantic Versioning](https://semver.org/).

## v0.1.1 — 2026-06-04

Initial public release of the **AWSBedrockAgentCoreSkill** Claude Code plugin (and agent skill).

### Added
- Routing `SKILL.md`: decision tree + use-case playbooks + 12 cross-cutting rules.
- 20 source-cited reference files (~19,000 lines) covering Strands Agents; Amazon Bedrock
  (Converse, Guardrails, Knowledge Bases/RAG, prompt caching, inference profiles); Amazon
  Bedrock AgentCore (Runtime, Memory, Gateway, Identity, Browser/Code Interpreter);
  observability; security/IAM/cost; managed alternatives; testing & rollout; and
  Terraform-first IaC (CDK secondary).
- 14 assets: service-selection matrix, model-selection guide, deployment checklist,
  ready-to-adapt IAM policies, and copy-paste starter snippets.
- Central official-source index (`references/sources.md`): 369 unique official URLs and
  636 inline citations.
- Plugin packaging: `.claude-plugin/plugin.json` + single-plugin marketplace
  (`aws-agent-skills`). `claude plugin validate` passes.

### Verified
- Built and QA'd with Claude Code multi-agent workflows (~140 subagents): a build-simulation
  audit, a full cross-file review, and a pass that verified 292 code snippets one by one
  against the official documentation (no code executed).

### Notes
- Maturity labels and version-specific facts reflect AWS state as of mid-2026; re-verify via
  the cited sources after ~3 to 6 months (see `CLAUDE.md`).
- Snippets are verified against official docs, not executed against a live account: validate
  IAM, quotas, and region availability before production.
