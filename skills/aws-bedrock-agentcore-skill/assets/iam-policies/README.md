<!-- Asset of the aws-bedrock-agentcore-skill skill. See ../SKILL.md and ../references/ for detail and official sources. -->

# IAM Policy Files — AWSBedrockAgentCoreSkill

Ready-to-adapt IAM JSON policy files for Amazon Bedrock and Amazon Bedrock AgentCore Runtime.
All shapes and permissions are derived from official AWS documentation; see
`../../references/security-iam-cost.md` for rationale, sources, and gotchas.

---

## Files

### `agentcore-runtime-execution-role-trust.json`

**What it is:** Trust policy for the IAM role assumed by the AgentCore Runtime service
(`bedrock-agentcore.amazonaws.com`) when executing a containerized agent.

**Why the conditions are non-negotiable:** The `aws:SourceAccount` + `aws:SourceArn`
confused-deputy guards are required. Without them, any service that can act as
`bedrock-agentcore.amazonaws.com` could assume this role with elevated privileges.
This is documented explicitly in the AgentCore security best-practices guide.

**Placeholders:**

| Placeholder | Replace with |
|---|---|
| `<ACCOUNT_ID>` | Your 12-digit AWS account ID |
| `<REGION>` | AWS region (e.g. `us-east-1`) |

**Source:** https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-security-best-practices.html

---

### `agentcore-runtime-execution-role-permissions.json`

**What it is:** Least-privilege permission policy for the same AgentCore Runtime execution
role (container deploy). Covers ECR image pull, CloudWatch Logs (scoped to
`/aws/bedrock-agentcore/runtimes/*`), X-Ray tracing, CloudWatch metrics scoped to the
`bedrock-agentcore` namespace, workload access tokens via JWT, and
`bedrock:InvokeModel` / `bedrock:InvokeModelWithResponseStream` scoped to a specific
model ARN.

**Key security decisions encoded in this file:**

- `GetWorkloadAccessTokenForJWT` is allowed; `GetWorkloadAccessTokenForUserId` is
  **explicitly denied**. The `ForUserId` action accepts any opaque string without IdP
  verification — enabling user impersonation. Use only in non-production environments.
- `bedrock:InvokeModel` is scoped to `<MODEL_ARN>` — not the wildcard
  `arn:aws:bedrock:*::foundation-model/*`. The wildcard grants invocation of every
  model (including expensive ones) and should never be used in production.
- CloudWatch `PutMetricData` is constrained by `cloudwatch:namespace` condition to
  prevent writing to arbitrary namespaces.
- `ecr:GetAuthorizationToken` and X-Ray actions use `Resource: *` only where AWS does
  not support resource-level conditions for those specific actions.
- MMDS (the AgentCore microVM metadata endpoint) exposes execution role credentials to
  all code running in the microVM. Keep this role's scope minimal.

**Placeholders:**

| Placeholder | Replace with |
|---|---|
| `<ACCOUNT_ID>` | Your 12-digit AWS account ID |
| `<REGION>` | AWS region (e.g. `us-east-1`) |
| `<ECR_REPOSITORY_NAME>` | Name of the ECR repository holding your agent image |
| `<AGENT_NAME>` | Agent name prefix used in workload identity ARNs |
| `<MODEL_ARN>` | Full foundation-model or inference-profile ARN, e.g. `arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-sonnet-4-6` |

**Source:** https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-permissions.html

---

### `bedrock-agents-service-role-trust.json`

**What it is:** Trust policy for the Bedrock Agents classic service role — the role
assumed by `bedrock.amazonaws.com` to orchestrate traditional Bedrock Agents (not
AgentCore Runtime).

**Important naming constraint:** The IAM role name **must** start with
`AmazonBedrockExecutionRoleForAgents_`. This prefix is enforced by the Bedrock service
trust evaluation. If you name the role differently, assume-role will fail.

**After agent creation:** Replace the `agent/*` wildcard in `AWS:SourceArn` with the
specific agent ARN. The wildcard is acceptable only before the agent ID is known
(initial creation).

**Permissions not included here:** Pair this trust policy with a separate inline or
managed permissions policy. At minimum you need `bedrock:InvokeModel` on the specific
model ARN. Add `bedrock:Retrieve` + `bedrock:RetrieveAndGenerate` for knowledge bases,
`bedrock:ApplyGuardrail` for guardrails, `s3:GetObject` for action group OpenAPI
schemas, and `bedrock:InvokeAgent` for multi-agent collaboration. See
`bedrock-invoke-least-privilege.json` for those statement shapes.

**Placeholders:**

| Placeholder | Replace with |
|---|---|
| `<ACCOUNT_ID>` | Your 12-digit AWS account ID |
| `<REGION>` | AWS region (e.g. `us-east-1`) |

**Source:** https://docs.aws.amazon.com/bedrock/latest/userguide/agents-permissions.html

---

### `bedrock-invoke-least-privilege.json`

**What it is:** A composite permissions policy with multiple selectable statement blocks
covering:

1. **Standard on-demand invocation** — `bedrock:InvokeModel` +
   `bedrock:InvokeModelWithResponseStream` scoped to an exact model ARN.
2. **Global cross-region inference (CRIS) — three mandatory statements.** Global CRIS
   requires three distinct resource ARN forms in three separate statements. Missing even
   one causes `AccessDeniedException`:
   - Inference profile ARN in source region (with `aws:RequestedRegion` condition)
   - Foundation model ARN in source region (with `bedrock:InferenceProfileArn` condition)
   - Global foundation model ARN — **no region, no account** — with
     `aws:RequestedRegion: "unspecified"` condition
3. **Bedrock Agents service role permissions** — `bedrock:InvokeModel` for agent
   orchestration, plus optional `bedrock:Retrieve`, `bedrock:ApplyGuardrail`, and
   `s3:GetObject` statements to include as needed.

**SCP note for Global CRIS:** If your AWS Organization uses SCPs to restrict Bedrock to
approved regions, you must explicitly include `"unspecified"` in the allowed region list.
Global routing sets `aws:RequestedRegion` to `"unspecified"` — an SCP that does not
allow it will block all global inference even if the source region is whitelisted.

**Adapt this file:** Remove statement blocks you do not need. Do not deploy all
statements as-is — the file intentionally contains optional sections for different use
cases.

**Placeholders:**

| Placeholder | Replace with |
|---|---|
| `<ACCOUNT_ID>` | Your 12-digit AWS account ID |
| `<REGION>` | Source region for inference (e.g. `us-east-1`) |
| `<MODEL_ID>` | Model identifier, e.g. `anthropic.claude-sonnet-4-6` |
| `<MODEL_ARN>` | Full model ARN for the direct on-demand statement |
| `<KNOWLEDGE_BASE_ID>` | Bedrock Knowledge Base ID (optional statement) |
| `<GUARDRAIL_ID>` | Bedrock Guardrail ID (optional statement) |
| `<S3_BUCKET_NAME>` | S3 bucket holding the OpenAPI schema (optional statement) |
| `<OPENAPI_SCHEMA_KEY>` | S3 object key for the OpenAPI schema file |
| `<AGENT_NAME>` | Agent name for role-naming convention |

**Source:** https://docs.aws.amazon.com/bedrock/latest/userguide/global-cross-region-inference.html

---

## General guidance

- Run all policies through **IAM Access Analyzer** before deploying to production.
  Access Analyzer performs 100+ automated checks and flags wildcards, overly broad
  resources, and insecure patterns.
- The CLI-generated AgentCore policies use `Resource: *` on many actions. Do not use
  them in production — they are development scaffolding only.
- After any role policy update, allow 15–60 seconds for IAM propagation before
  creating Bedrock resources that depend on it (Terraform: use `time_sleep`).
- For the full rationale behind every decision in these files, see
  `../../references/security-iam-cost.md`.
