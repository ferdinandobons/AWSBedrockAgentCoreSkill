<!-- Asset of the aws-ai-agent-architect skill. See ../SKILL.md and ../references/ for detail and official sources. -->

# Pre-production deployment checklist

Use this as a gate before shipping any AWS-hosted AI agent. Every item maps to a documented gotcha from the research bundles. Tick all boxes; items marked **[BLOCKER]** will cause outages or silent failures in production.

---

## Model & region

- [ ] **[BLOCKER]** Declare an explicit AWS region in every boto3 client and CLI call — never rely on `AWS_DEFAULT_REGION` alone in deployed code.
- [ ] **[BLOCKER]** Verify model access in the target region via the Bedrock console **Model access** page before deploy — a model listed in docs may not be enabled in your account or region.
- [ ] Confirm the exact model ID matches the target region format (e.g., `anthropic.claude-sonnet-4-6` for direct access, `us.anthropic.claude-sonnet-4-6` for geographic cross-region, `global.anthropic.claude-sonnet-4-6` for global CRIS).
- [ ] If using Global cross-region inference (CRIS), include **all three** IAM statement ARNs: inference profile in source region, FM in-region ARN, and FM global ARN (no region or account in the global ARN) — missing even one causes `AccessDeniedException`.
- [ ] If using Global CRIS, ensure the SCP explicitly allows `aws:RequestedRegion = "unspecified"` — Global inference routes with that value and a blanket region-restriction SCP will silently block it.
- [ ] If data-residency rules apply, use a geographic inference profile (`us.`, `eu.`, `au.`, `jp.`) instead of global — geographic profiles guarantee in-boundary routing.
- [ ] Confirm AgentCore Runtime is GA in the target region (16 regions as of June 2026, including GovCloud); Harness and Payments are Preview-only in 4 regions — do not use them for production workloads.

---

## IAM & security

- [ ] **[BLOCKER]** Add `aws:SourceAccount` and `aws:SourceArn` conditions to **every** execution role trust policy (both `bedrock.amazonaws.com` and `bedrock-agentcore.amazonaws.com`) — without these, confused-deputy attacks are possible.
- [ ] **[BLOCKER]** Scope `bedrock:InvokeModel` to the exact foundation-model ARN(s) required — a wildcard grants access to all models including the most expensive ones.
- [ ] Replace CLI-generated IAM policies before going to production — they use `Resource: *` on most actions; production policies must reference specific runtime ARNs.
- [ ] Explicitly **Deny** `bedrock-agentcore:GetWorkloadAccessTokenForUserId` and `bedrock-agentcore:InvokeAgentRuntimeForUser` if JWT auth is available — the UserId path accepts any opaque string with no IdP verification.
- [ ] Use `GetWorkloadAccessTokenForJWT` (validates issuer, signature, expiry) for end-user-facing agents; use IAM SigV4 for service-to-service calls.
- [ ] Name execution roles to include `BedrockAgentCore` in the name, or write a custom `iam:PassRole` policy — the managed `BedrockAgentCoreFullAccess` policy scopes `iam:PassRole` to `*BedrockAgentCore*` and will silently fail for differently-named roles.
- [ ] Run IAM Access Analyzer on all policies before deploy to catch overly permissive patterns.
- [ ] Restrict `cloudwatch:PutMetricData` to the namespace `bedrock-agentcore` via condition key to prevent metric namespace escalation.
- [ ] If using VPC endpoints for AgentCore with OAuth callers, set `Principal: "*"` in the endpoint policy for OAuth actions — VPC endpoint policies can only restrict SigV4 callers by IAM principal; OAuth callers receive `403` unless Principal is wildcard.
- [ ] For VPC-mode AgentCore, create **all three** PrivateLink endpoints if needed: `bedrock-agentcore` (data plane), `bedrock-agentcore-control` (control plane), `bedrock-agentcore.gateway` (Gateway) — they are separate service names.
- [ ] Enable private DNS on all Bedrock and AgentCore VPC endpoints — avoids hardcoding vpce-IDs in code.
- [ ] For regulated environments, specify `customerEncryptionKeyArn` (agents), `kmsKeyArn` (data sources), or `customModelKmsKeyId` (custom models) to use customer-managed KMS keys.

---

## Guardrails & safety

- [ ] **[BLOCKER]** Call `CreateGuardrailVersion` and reference the resulting **numbered version** (e.g., `"1"`) in all inference calls and agent configurations — never reference `DRAFT` in production; DRAFT is mutable and any edit immediately changes behavior for all callers.
- [ ] If using the `PROMPT_ATTACK` content filter (Standard tier), enable input tagging and use a **random `tagSuffix` per request** (alphanumeric, 1–20 chars) — a static suffix is a prompt-injection vector that lets attackers close the XML tag.
- [ ] Enable Standard tier (set `tierName: "STANDARD"` and supply `crossRegionConfig.guardrailProfileIdentifier`) for multilingual applications or code-heavy prompts — Classic tier only covers English, French, and Spanish.
- [ ] If PII masking is a compliance requirement, also enable **CloudWatch log data protection** on the relevant log groups — guardrail PII masking does NOT apply to CloudWatch model-invocation logs; the raw unmasked input is always logged.
- [ ] Do not rely on Automated Reasoning checks to block content — they operate in **detect mode only** (returns VALID/INVALID/TRANSLATION_AMBIGUOUS/TOO_COMPLEX findings but never blocks). Pair with content filters and topic policies for blocking.
- [ ] Do not include `automatedReasoningPolicyConfig` in guardrails used for cross-account enforcement (AWS Organizations) — it is not supported there and causes runtime failures.
- [ ] Verify contextual grounding thresholds are in the range `0.0–0.99` — `1.0` throws `ValidationException`. Start at `0.7` and tune from test runs.
- [ ] Verify `blockedInputMessaging` and `blockedOutputsMessaging` are ≤ 500 characters each — longer values throw `ValidationException`.
- [ ] For Converse API guardrail integration, use the `qualifiers` field in `guardContent` blocks — the InvokeModel XML-tag mechanism does not work with Converse API.
- [ ] Check that `bedrock:TagResource` is in the execution role policy if tags are passed to `CreateGuardrail` — omitting it causes `AccessDeniedException` even when `bedrock:CreateGuardrail` is present.

---

## AgentCore Runtime contract

- [ ] **[BLOCKER]** Build container images as `linux/arm64` (`docker buildx build --platform linux/arm64`) — building on x86 without buildx produces `exec /bin/sh: exec format error` at runtime.
- [ ] **[BLOCKER]** Expose `POST /invocations` and `GET /ping` on **port 8080** — this is the mandatory service contract; AgentCore will not route traffic to non-compliant containers.
- [ ] **[BLOCKER]** Implement `/ping` with **both** `"status"` and `"time_of_last_update"` fields — omitting `time_of_last_update` causes premature session termination even when `HealthyBusy` is set, killing background async work after 15 minutes.
- [ ] Map exactly **one session ID per user conversation** — session IDs must be ≥ 33 characters (`uuid.uuid4()` satisfies this). Sharing a session ID across different users violates the security isolation boundary.
- [ ] Propagate the session header (`X-Amzn-Bedrock-AgentCore-Runtime-Session-Id` for HTTP/A2A/AG-UI; `Mcp-Session-Id` for MCP) in every follow-up request — without it, requests route to a new microVM and lose all in-memory state.
- [ ] Set `idleRuntimeSessionTimeout` to the minimum acceptable value — idle sessions remain billable for up to the timeout duration (default 15 minutes); call `stop_runtime_session()` explicitly when a workflow completes to avoid unnecessary charges.
- [ ] For direct-code (ZIP) deployments, use `PYTHON_3_13` or `PYTHON_3_14` as the runtime identifier — `PYTHON_3_10` and `PYTHON_3_11` deprecate on 2026-06-30.
- [ ] Verify boto3 ≥ 1.39.8 / botocore ≥ 1.33.8 is installed before using AgentCore control/data plane APIs — older versions raise `Unknown service: bedrock-agent-core-runtime`.
- [ ] If using async background tasks, use `app.add_async_task()` / `app.complete_async_task()` (SDK) or return `PingStatus.HEALTHY_BUSY` from a custom `@app.ping` handler — do NOT perform blocking calls in the `@app.entrypoint` when background tasks are running (stalls health checks).
- [ ] Pin production traffic to a named custom endpoint (e.g., `production`), not the `DEFAULT` endpoint — `DEFAULT` auto-tracks the latest version on every create/update, which can break production silently.
- [ ] If using persistent session storage (`filesystemConfigurations`), note it resets on runtime version update — do not rely on session storage for state that must survive deploys.

---

## Observability

- [ ] **[BLOCKER]** Enable CloudWatch Transaction Search **before the first deploy** — it is not retroactive; spans generated before enabling are not indexed. Verify with `aws xray get-trace-segment-destination` (expect `"Status": "ACTIVE"`) and wait 10 minutes before sending the first trace.
- [ ] Set `OTEL_RESOURCE_ATTRIBUTES` with `service.name=<agent-name>` and, for non-runtime agents, `aws.log.group.names=<log-group>` — without `aws.log.group.names`, the agent does not appear in the CloudWatch GenAI Observability dashboard.
- [ ] For agents using a third-party backend (Langfuse, Datadog, Arize Phoenix), set `DISABLE_ADOT_OBSERVABILITY=true` in the runtime's `env_vars` at launch — without this, AgentCore's default ADOT env vars silently overwrite your custom OTEL configuration.
- [ ] Set a log retention policy on `/aws/spans` — it defaults to indefinite retention; on high-volume agents this causes unbounded CloudWatch Logs costs. (`aws logs put-retention-policy --log-group-name aws/spans --retention-in-days 30`).
- [ ] Explicitly configure log destinations for Memory and Gateway resources — unlike Agent Runtime, they do not create log groups automatically.
- [ ] Use a consistent session ID across multi-turn conversations and propagate it via OTEL baggage (`baggage.set_baggage("session.id", ...)`) or `trace_attributes` in the Strands `Agent` constructor — without consistent IDs, the Session View in CloudWatch cannot reconstruct full conversation flows.
- [ ] Set alarms on `InvocationThrottles` (namespace `bedrock-agentcore`, or `AWS/Bedrock/Agents` for classic agents) and `Latency P99` before going live — throttling indicates quota headroom is exhausted; the default is 25 TPS per agent (adjustable).
- [ ] Note: `EstimatedTPMQuotaUsage` in `AWS/Bedrock` is explicitly documented as an approximation — do not rely on it alone for capacity planning.

---

## Cost & quotas

- [ ] **[BLOCKER]** Set `max_tokens` to the approximate actual completion length, not a large safety margin — for Claude 3.7+ and all Claude 4.x models, `max_tokens` is deducted from the TPM quota **upfront** at a **5× burndown rate** (1 output token = 5 quota tokens). Oversized `max_tokens` is the primary cause of premature quota exhaustion.
- [ ] Measure actual `OutputTokenCount` via CloudWatch before sizing `max_tokens` — then set `max_tokens` ≈ P99 of observed output lengths plus a small buffer.
- [ ] Position cache checkpoints **after** all static content (tools → system → messages) and **before** any variable user content — modifying anything upstream invalidates all downstream cache entries.
- [ ] Monitor `CacheReadInputTokens` vs. `CacheWriteInputTokens` to confirm prompt caching is delivering ROI — cache writes may cost more than standard input tokens; if cache hit rate is low, caching can increase cost.
- [ ] For Global cross-region inference cost savings (~10%), confirm the IAM policy has all three required statements (see Model & region section) — missing one silently falls back to single-region inference.
- [ ] If Reserved tier is used, size capacity using `InputTokenCount + CacheWriteInputTokens` (not `InputTokenCount` alone) — the Reserved tier consumes both, and undersizing causes frequent overflow to Standard tier.
- [ ] For batch workloads (non-time-sensitive, no tool use or multi-turn), use Batch Inference (~50% discount) — note it does NOT support prompt caching, tool use, structured output, or multi-turn.
- [ ] Verify current TPM/TPD quota defaults in the Service Quotas console for the exact model and region being used — defaults change frequently and are not reliably documented statically.
- [ ] RPM (requests per minute) quota on `bedrock-runtime` is officially deprecated — do not request RPM increases; throttling is governed solely by TPM and TPD.
- [ ] Stop idle AgentCore sessions explicitly with `stop_runtime_session()` after workflow completion to avoid billing for idle microVM time.

---

## Memory & state

- [ ] Enforce a user-to-session mapping in application backend code so that one user's `runtimeSessionId` is never reused by another user — AgentCore microVMs provide per-session isolation, but the routing key is the session ID; sharing IDs breaks the isolation boundary.
- [ ] If in-session persistent storage (`sessionStorage` filesystem configuration) is used, account for the 1 GB limit per session, 14-day idle expiry, and reset on runtime version update — do not treat it as a durable store.
- [ ] For shared state across sessions (e.g., multi-user memory), use AgentCore Memory with a VPC-backed S3 Files or EFS mount — shared filesystems require VPC mode and appropriate execution role permissions (`elasticfilesystem:ClientMount`, `elasticfilesystem:ClientWrite`, TCP 2049 outbound to EFS mount target security group).
- [ ] For classic Bedrock Agents, confirm `idleSessionTTLInSeconds` is tuned to match expected user session duration — the default may be too short or too long for your use case, affecting cost and user experience.
- [ ] If using AgentCore Memory or Gateway, note they are separate resources from Runtime and require their own IAM permissions, observability configuration, and version management.
