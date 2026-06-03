# Security, IAM, Cost & Quotas for AWS AI Agents

> Part of the **aws-bedrock-agentcore-skill** skill. See [SKILL.md](../SKILL.md) for the decision tree. Every source below is official - re-open it to verify details.

## Table of contents

- [Overview](#overview)
- [Key concepts](#key-concepts)
  - [Execution Role (AgentCore Runtime)](#execution-role-agentcore-runtime)
  - [Execution Role (Bedrock Agents classic)](#execution-role-bedrock-agents-classic)
  - [BedrockAgentCoreFullAccess managed policy](#bedrockagentcorefullaccessmanaged-policy)
  - [Token Burndown Rate](#token-burndown-rate)
  - [Prompt Caching and Cache Checkpoints](#prompt-caching-and-cache-checkpoints)
  - [Intelligent Prompt Routing](#intelligent-prompt-routing)
  - [Cross-Region Inference Profiles](#cross-region-inference-profiles)
  - [VPC Interface Endpoints (PrivateLink) for Bedrock](#vpc-interface-endpoints-privatelink-for-bedrock)
  - [VPC Interface Endpoints (PrivateLink) for AgentCore](#vpc-interface-endpoints-privatelink-for-agentcore)
  - [KMS Customer Managed Key for Bedrock](#kms-customer-managed-key-for-bedrock)
  - [MMDS in AgentCore](#mmds-in-agentcore)
  - [AgentCore Runtime Quotas](#agentcore-runtime-quotas)
  - [Service Tiers](#service-tiers)
  - [Provisioned Throughput vs Batch Inference](#provisioned-throughput-vs-batch-inference)
- [Best practices](#best-practices)
- [Code](#code)
  - [AgentCore Runtime execution role (container deploy)](#agentcore-runtime-execution-role-container-deploy)
  - [Bedrock Agents service role](#bedrock-agents-service-role)
  - [VPC endpoint for Bedrock Runtime](#vpc-endpoint-for-bedrock-runtime)
  - [AgentCore PrivateLink - three required endpoints](#agentcore-privatelink--three-required-endpoints)
  - [VPC endpoint policy for AgentCore (SigV4 + OAuth)](#vpc-endpoint-policy-for-agentcore-sigv4--oauth)
  - [VPC endpoint policy for Bedrock Runtime](#vpc-endpoint-policy-for-bedrock-runtime)
  - [Prompt caching with Converse API (Python)](#prompt-caching-with-converse-api-python)
  - [Prompt caching with InvokeModel API (Python)](#prompt-caching-with-invokemodel-api-python)
  - [IAM policy for Global cross-region inference](#iam-policy-for-global-cross-region-inference)
  - [SCP for data residency](#scp-for-data-residency)
  - [Deny GetWorkloadAccessTokenForUserId in production](#deny-getworkloadaccesstokenforuserid-in-production)
  - [Create Bedrock Agent with KMS CMK (Python)](#create-bedrock-agent-with-kms-cmk-python)
  - [Request TPM quota increase via AWS CLI](#request-tpm-quota-increase-via-aws-cli)
  - [Use service tiers in Converse API (Python)](#use-service-tiers-in-converse-api-python)
- [Configuration reference](#configuration-reference)
- [Gotchas](#gotchas)
- [Official sources](#official-sources)
- [Verify live (open questions)](#verify-live-open-questions)

---

## Overview

Complete operational guide for configuring least-privilege IAM, KMS encryption, VPC/PrivateLink, data privacy, and cost optimization for AI agents on Amazon Bedrock and Amazon Bedrock AgentCore Runtime. Covers the real execution roles for both Bedrock Agents and AgentCore Runtime, `bedrock:InvokeModel` / `bedrock-agentcore:*` permissions, token-based quotas (TPM/TPD with 5x burndown rate for Claude 3.7+), cost-saving strategies via prompt caching, intelligent prompt routing, cross-region inference, batch inference, and Provisioned Throughput. Includes the three specific AgentCore PrivateLink endpoints and AgentCore Runtime quotas (active sessions, TPS, hardware allocation).

**Maturity note:** All features covered are **GA** as of June 2026, with the following exceptions: Claude 3.5 Sonnet v2 prompt caching is listed as "Preview" in the official `prompt-caching.html` table. **AgentCore Harness and AgentCore Payments are still in Preview** (4–5 regions) - do not use for production without verifying regional availability. Agent Registry is in Preview in 5 regions. Claude Mythos is in Gated Research Preview in us-east-1 only.

---

## Key concepts

### Execution Role (AgentCore Runtime)

IAM role assumed by the service principal `bedrock-agentcore.amazonaws.com` to run an agent. Requires permissions on ECR (image pull), CloudWatch Logs, X-Ray, CloudWatch metrics (namespace `bedrock-agentcore`), `bedrock:InvokeModel` / `bedrock:InvokeModelWithResponseStream`, and `bedrock-agentcore:GetWorkloadAccessToken*`. The trust policy **must** use `aws:SourceAccount` + `aws:SourceArn` to prevent confused deputy attacks.

### Execution Role (Bedrock Agents classic)

IAM service role assumed by `bedrock.amazonaws.com` to orchestrate traditional agents. Minimum permissions: `bedrock:InvokeModel` on specific foundation model ARNs, `s3:GetObject` for OpenAPI schemas, `bedrock:Retrieve` for knowledge bases. Optional: `bedrock:InvokeAgent` (multi-agent), `bedrock:ApplyGuardrail`, `bedrock:GetProvisionedModelThroughput`.

### BedrockAgentCoreFullAccess managed policy

AWS managed policy for dev/quick-start covering `bedrock-agentcore:*`, `iam` (PassRole scoped to `*BedrockAgentCore*`), `secretsmanager` (prefix `bedrock-agentcore`), `kms` (decrypt same-account), `s3`, `lambda`, `logs`, `xray`, `ecr`, `cloudwatch`. **Does NOT include `iam:CreateRole`.** In production replace with a custom least-privilege policy - the managed policy includes `GetWorkloadAccessTokenForUserId` which is unsafe in production.

ARN: `arn:aws:iam::aws:policy/BedrockAgentCoreFullAccess`

### Token Burndown Rate

Multiplicative factor with which output tokens consume TPM/TPD quota. For Claude 3.7 Sonnet and all later models (all Claude 4.x): **1 output token = 5 quota tokens**. For all other models: 1:1.

`max_tokens` is deducted from the TPM quota at request start (before generation completes); excess is returned at completion. Billing is on actual use only.

**Formula - initial quota reservation (at request start):**
```
InputTokenCount + CacheWriteInputTokens + (max_tokens × burndown_rate)
```
**Formula - final quota consumed (after completion):**
```
InputTokenCount + CacheWriteInputTokens + (OutputTokenCount × burndown_rate)
```
**Formula - billing:**
```
inputTokens (standard rate) + cacheWriteInputTokens (cache-write rate)
  + cacheReadInputTokens (reduced cache-read rate) + outputTokens (output rate)
```

### Prompt Caching and Cache Checkpoints

Optional feature that saves repeated prompt prefixes in cache (TTL 5 min or 1 hour for selected models). Defined via `cachePoint` (Converse API) or `cache_control` (InvokeModel Anthropic format).

- `CacheReadInputTokens` do **not** consume TPM quota.
- `CacheWriteInputTokens` **do** consume quota (together with `InputTokenCount`).
- `inputTokens` in the response represents only tokens that were neither cached nor written to cache.

**Models supporting TTL 1 hour:** Claude Opus 4.5, Haiku 4.5, Sonnet 4.5 **only**. Claude Sonnet 4.6 and Claude Opus 4.6 support **5 minutes only**. _Source: https://docs.aws.amazon.com/bedrock/latest/userguide/prompt-caching.html (supported models table)_

**Minimum tokens before a cache checkpoint:**
- Claude 3.7, Sonnet 4.6, Opus 4, Opus 4.1: **1024 tokens**
- Claude Opus 4.5, Opus 4.6, Haiku 4.5, Sonnet 4.5: **4096 tokens**

**Maximum cache checkpoints per request:** 4 for all supported Claude models.

### Intelligent Prompt Routing

Single serverless endpoint that predicts per-request which model in the same family (Anthropic, Meta, Amazon Nova) will yield the best quality/cost ratio. Used via a Prompt Router ARN. Supports default routers (pre-configured by AWS) and configured routers (customizable criteria). English prompts only.

### Cross-Region Inference Profiles

Two variants:
- **Geographic profiles** (`us.`, `eu.`, `au.`, `jp.` prefix) - routing stays within the specified geography, for data residency requirements. _Source: https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-sonnet-4-6.html (Geo inference IDs listed as `us.`, `eu.`, `au.`, `jp.` - `apac.` is not a valid prefix)_
- **Global profiles** (`global.` prefix) - routes worldwide on the AWS backbone; ~10% cost saving confirmed for Claude Sonnet 4.5. No additional routing cost.

Data stays on the AWS network, encrypted in transit. Requests are logged in CloudTrail in the source region with `additionalEventData.inferenceRegion`.

Global inference uses `aws:RequestedRegion = 'unspecified'` for cross-region routing. The IAM policy for Global CRIS requires **three separate statements** (see [Code](#iam-policy-for-global-cross-region-inference)).

Available Global CRIS source regions (Claude Sonnet 4.x): `us-west-2`, `us-east-1`, `us-east-2`, `eu-west-1`, `ap-northeast-1`.

Global inference profile ID pattern: `global.anthropic.claude-sonnet-4-6`

### VPC Interface Endpoints (PrivateLink) for Bedrock

Five separate service endpoints plus two FIPS variants:

| Service name | Plane |
|---|---|
| `com.amazonaws.{region}.bedrock` | Control plane |
| `com.amazonaws.{region}.bedrock-runtime` | Runtime (inference) |
| `com.amazonaws.{region}.bedrock-mantle` | Mantle |
| `com.amazonaws.{region}.bedrock-agent` | Agent control plane |
| `com.amazonaws.{region}.bedrock-agent-runtime` | Agent runtime |
| `com.amazonaws.{region}.bedrock-fips` | Control plane (FIPS) |
| `com.amazonaws.{region}.bedrock-runtime-fips` | Runtime (FIPS) |

With private DNS enabled, no code changes are needed. Without private DNS, pass `endpoint_url` to the boto3 client.

### VPC Interface Endpoints (PrivateLink) for AgentCore

Three distinct endpoints:

| Service name | Covers |
|---|---|
| `com.amazonaws.{region}.bedrock-agentcore` | Data plane: Runtime, Memory, Built-in Tools, Identity, Gateway, Policy |
| `com.amazonaws.{region}.bedrock-agentcore-control` | Control plane: Runtime and Memory management |
| `com.amazonaws.{region}.bedrock-agentcore.gateway` | AgentCore Gateway (MCP tools) |

**Critical:** VPC endpoint policies cannot restrict OAuth callers - only SigV4. For OAuth callers the `Principal` must be `"*"` in the endpoint policy.

### KMS Customer Managed Key for Bedrock

The following artifacts support CMK encryption:

| Artifact | API parameter |
|---|---|
| Bedrock Agent | `customerEncryptionKeyArn` in `CreateAgent` |
| Knowledge base data source | `kmsKeyArn` in `CreateDataSource` |
| Custom model / fine-tuning job | `customModelKmsKeyId` in `CreateModelCustomizationJob` |
| Model evaluation job | `customerEncryptionKeyId` in `CreateEvaluationJob` |
| Vector stores (OpenSearch) | KMS key configured at vector store level |

Training/validation data on S3 uses SSE-KMS. Default encryption uses AWS-owned keys at no additional cost.

### MMDS in AgentCore

Analogous to EC2 IMDS. Any code running in the AgentCore microVM can read the execution role's temporary credentials from the MMDS endpoint. Therefore the execution role **must** be scoped to the strict minimum. Any tool code, prompt injection, or compromised dependency executing inside the microVM can exfiltrate these credentials.

### AgentCore Runtime Quotas

| Quota | Value | Adjustable |
|---|---|---|
| Active session workloads (US East N. Virginia / US West Oregon) | 1000 | Yes |
| Active session workloads (other regions) | 500 | Yes |
| Agent runtimes per account | 1000 | Yes |
| InvokeAgentRuntime TPS per agent | 25 | Yes |
| Hardware per session | 2 vCPU / 8 GB RAM | **No** |
| Sync request timeout | 15 minutes | **No** |
| Streaming request timeout | 60 minutes | No |
| Async job timeout | 8 hours | Configurable via `LifecycleConfiguration.maxLifetime` |
| Max payload | 100 MB | No |
| Max Docker image | 2 GB | No |
| Max direct-code package (compressed) | 250 MB | No |
| Max direct-code package (uncompressed) | 750 MB | No |

Supported regions: 16 regions including GovCloud (GA for Runtime, Memory, Gateway, Identity, Built-in Tools, Observability, Policy).

### Service Tiers

Four tiers available via the `serviceTier` parameter in runtime API calls:

| Tier | API value | Cost vs Standard | Notes |
|---|---|---|---|
| Reserved | `reserved` | Committed capacity pricing | Min 100K input TPM + 10K output TPM; 1 or 3 month commitment; 99.5% uptime target; contact AWS team |
| Priority | `priority` | Price premium - see the [Bedrock pricing page](https://aws.amazon.com/bedrock/pricing/) | No reservation needed |
| Standard | `default` | Baseline | Default if `serviceTier` is omitted |
| Flex | `flex` | Price discount - see the [Bedrock pricing page](https://aws.amazon.com/bedrock/pricing/) | Higher latency variability; on-demand quota shared with Priority/Standard |

On-demand quota is shared across Priority, Standard, and Flex. Reserved has a separate quota pool.

### Provisioned Throughput vs Batch Inference

**Provisioned Throughput:** Reserved capacity by the hour; required for custom models; no throttling within purchased Model Units. Pricing requires contacting the AWS team or querying the pricing API (not documented statically).

**Batch Inference:** Async job over S3; up to 10,000 records / 200 MB input file; 24-hour processing window; ~50% discount vs on-demand. **Does NOT support:** prompt caching, tool use, structured output, or multi-turn conversations. Not suitable for agentic workflows.

---

## Best practices

- **Use the trust policy with `aws:SourceAccount` + `aws:SourceArn` on ALL Bedrock and AgentCore execution roles** - Prevents the confused deputy attack: without these conditions, a malicious service could impersonate `bedrock.amazonaws.com` or `bedrock-agentcore.amazonaws.com` and assume your role with elevated privileges. _Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-security-best-practices.html_

- **Do not use AgentCore CLI-generated policies in production** - CLI policies have broad scope (`resource: *`) for prototyping convenience. In production every statement must reference specific runtime ARNs, not wildcards. _Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-security-best-practices.html_

- **In production (JWT always available): use `GetWorkloadAccessTokenForJWT` and explicitly deny `GetWorkloadAccessTokenForUserId`** - `GetWorkloadAccessTokenForUserId` accepts any opaque string without IdP verification, exposing the runtime to user impersonation. `GetWorkloadAccessTokenForJWT` validates the JWT signature, issuer, and expiry. _Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-permissions.html_

- **Restrict `bedrock:InvokeModel` to the exact model ARN(s) required, never use `arn:aws:bedrock:*::foundation-model/*`** - The wildcard grants invocation of any model (including the most expensive ones). Specific ARNs prevent accidental cost escalation and block data exfiltration to unapproved models. _Source: https://docs.aws.amazon.com/bedrock/latest/userguide/security_iam_id-based-policy-examples.html_

- **Enable private DNS on Bedrock and AgentCore VPC endpoints; do NOT hardcode `endpoint_url` in code** - With private DNS enabled, code uses standard DNS names with no modifications. Hardcoding the `vpce-id`-based endpoint URL creates a runtime dependency that breaks portability. _Source: https://docs.aws.amazon.com/bedrock/latest/userguide/vpc-interface-endpoints.html_

- **For AgentCore VPC endpoints with OAuth: set `Principal: "*"` in the endpoint policy for actions that use Bearer Tokens** - VPC endpoint policies can only restrict SigV4 callers via IAM principals. OAuth calls only pass through if `Principal = "*"`. Without this, OAuth callers receive 403. _Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/vpc-interface-endpoints.html_

- **Reduce `max_tokens` to the approximate real completion size - never set 32768 "to be safe"** - `max_tokens` is deducted from the TPM quota at request start before any response is generated. An excessively high value reduces concurrent request capacity even if actual completions use few tokens. Calibrate using the CloudWatch `OutputTokenCount` metric. _Source: https://docs.aws.amazon.com/bedrock/latest/userguide/quotas-token-burndown.html_

- **Place cache checkpoints after static content (tools → system → messages) and before variable content** - Sections are processed in order: tools → system → messages. Modifying an upstream section invalidates the cache for all downstream sections. Variable content (user queries) must come AFTER the last checkpoint. _Source: https://docs.aws.amazon.com/bedrock/latest/userguide/prompt-caching.html_

- **Monitor `CacheReadInputTokens` and `CacheWriteInputTokens` via CloudWatch to measure prompt caching ROI** - Cache writes can cost more than standard input tokens on some models. Real savings depend on the read/write ratio. Without monitoring you may pay more rather than less. For Reserved tier, sum `InputTokenCount + CacheWriteInputTokens` to estimate capacity to reserve. _Source: https://docs.aws.amazon.com/bedrock/latest/userguide/quotas-token-burndown.html_

- **Use geographic inference profiles (`us.`, `eu.`, `au.`, `jp.`) when data residency is required; use global profiles for maximum throughput and ~10% cost reduction** - Geographic profiles guarantee data stays within the specified geography. Global profiles route across any AWS commercial region but only on the AWS backbone (never public internet) and offer ~10% savings (confirmed for Claude Sonnet 4.5). _Source: https://docs.aws.amazon.com/bedrock/latest/userguide/cross-region-inference.html; geo prefixes confirmed at https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-sonnet-4-6.html_

- **For Global cross-region inference IAM policy: include ALL THREE required statements** - Global CRIS requires three distinct resource ARNs: inference profile in the source region, FM in-region, and FM global (ARN without region or account). Missing even one causes `AccessDeniedException`. _Source: https://docs.aws.amazon.com/bedrock/latest/userguide/global-cross-region-inference.html_

- **Apply SCP at the Organization/OU level to restrict `bedrock:*` to approved regions, explicitly allowing `"unspecified"` for Global inference** - Without SCP, users/roles can invoke Bedrock models in non-compliant regions. SCPs are the only control that applies to child accounts. Global CRIS requests use `aws:RequestedRegion = "unspecified"` - an SCP blocking all unlisted regions must include `"unspecified"` in the exception or it blocks Global routing. _Source: https://docs.aws.amazon.com/prescriptive-guidance/latest/data-perimeter-for-amazon-bedrock/regional-boundary-enforcement.html_

- **Start with `BedrockAgentCoreFullAccess` as a baseline, then create a customer-managed policy removing unused actions** - The managed policy is immediately available and reduces early errors, but it includes broad permissions (`GetWorkloadAccessTokenForUserId`, `iam:PassRole` on `*BedrockAgentCore*`). For production, copy only the needed statements. _Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/security-iam-awsmanpol.html_

- **For VPC-mode agents, configure VPC endpoints for ECR (`dkr` + `api`), S3 (gateway), and CloudWatch Logs; restrict the S3 gateway policy to the ECR layer bucket only** - Without the S3 gateway endpoint, ECR image pulls transit through the NAT gateway incurring per-GB cost. The restricted policy prevents the endpoint from allowing access to any arbitrary S3 bucket. _Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-security-best-practices.html_

- **For non-time-sensitive batch workloads, use batch inference instead of on-demand** - Batch inference costs approximately 50% less than on-demand and processes up to 10,000 records per job on S3. No throttling or quota management needed. _Source: https://docs.aws.amazon.com/bedrock/latest/userguide/capacity-limits-cost-optimization.html_

- **Use IAM Access Analyzer to validate policies before deploying to production** - Access Analyzer runs over 100 automatic checks on policy JSON and flags excessive permissions, unnecessary resource wildcards, and insecure patterns. _Source: https://docs.aws.amazon.com/bedrock/latest/userguide/security_iam_id-based-policy-examples.html_

- **For Reserved tier capacity planning, sum `InputTokenCount + CacheWriteInputTokens` (not just `InputTokenCount`) to estimate capacity to reserve** - The service-tiers documentation explicitly confirms that Reserved tier consumes both `InputTokenCount` and `CacheWriteInputTokens`. Underestimating leads to frequent overflow onto the Standard tier. _Source: https://docs.aws.amazon.com/bedrock/latest/userguide/service-tiers-inference.html_

---

## Code

### AgentCore Runtime execution role (container deploy)

Trust policy and minimum permission policy for a container-based AgentCore Runtime agent.

```json
// TRUST POLICY - attach to the IAM role
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AssumeRolePolicy",
      "Effect": "Allow",
      "Principal": { "Service": "bedrock-agentcore.amazonaws.com" },
      "Action": "sts:AssumeRole",
      "Condition": {
        "StringEquals": { "aws:SourceAccount": "123456789012" },
        "ArnLike":     { "aws:SourceArn": "arn:aws:bedrock-agentcore:us-east-1:123456789012:*" }
      }
    }
  ]
}

// PERMISSION POLICY - attach as inline or customer-managed policy
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ECRImageAccess",
      "Effect": "Allow",
      "Action": ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"],
      "Resource": ["arn:aws:ecr:us-east-1:123456789012:repository/*"]
    },
    {
      "Effect": "Allow",
      "Action": ["logs:DescribeLogStreams", "logs:CreateLogGroup"],
      "Resource": ["arn:aws:logs:us-east-1:123456789012:log-group:/aws/bedrock-agentcore/runtimes/*"]
    },
    {
      "Effect": "Allow",
      "Action": ["logs:DescribeLogGroups"],
      "Resource": ["arn:aws:logs:us-east-1:123456789012:log-group:*"]
    },
    {
      "Effect": "Allow",
      "Action": ["logs:CreateLogStream", "logs:PutLogEvents"],
      "Resource": ["arn:aws:logs:us-east-1:123456789012:log-group:/aws/bedrock-agentcore/runtimes/*:log-stream:*"]
    },
    {
      "Sid": "ECRTokenAccess",
      "Effect": "Allow",
      "Action": ["ecr:GetAuthorizationToken"],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": ["xray:PutTraceSegments", "xray:PutTelemetryRecords", "xray:GetSamplingRules", "xray:GetSamplingTargets"],
      "Resource": ["*"]
    },
    {
      "Effect": "Allow",
      "Resource": "*",
      "Action": "cloudwatch:PutMetricData",
      "Condition": { "StringEquals": { "cloudwatch:namespace": "bedrock-agentcore" } }
    },
    {
      "Sid": "GetAgentAccessToken",
      "Effect": "Allow",
      "Action": [
        "bedrock-agentcore:GetWorkloadAccessToken",
        "bedrock-agentcore:GetWorkloadAccessTokenForJWT"
      ],
      "Resource": [
        "arn:aws:bedrock-agentcore:us-east-1:123456789012:workload-identity-directory/default",
        "arn:aws:bedrock-agentcore:us-east-1:123456789012:workload-identity-directory/default/workload-identity/agentName-*"
      ]
    },
    {
      "Sid": "BedrockModelInvocation",
      "Effect": "Allow",
      "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
      "Resource": [
        "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-sonnet-4-6"
      ]
    }
  ]
}
```

_Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-permissions.html_

---

### Bedrock Agents service role

Trust policy and minimum permission policy for a classic Bedrock Agent (foundation model, S3 schema, knowledge base, guardrail).

```json
// TRUST POLICY
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": { "Service": "bedrock.amazonaws.com" },
      "Action": "sts:AssumeRole",
      "Condition": {
        "StringEquals": { "aws:SourceAccount": "123456789012" },
        "ArnLike":       { "AWS:SourceArn": "arn:aws:bedrock:us-east-1:123456789012:agent/*" }
      }
    }
  ]
}

// PERMISSION POLICY
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AgentModelInvocationPermissions",
      "Effect": "Allow",
      "Action": ["bedrock:InvokeModel"],
      "Resource": [
        "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-3-7-sonnet-20250219-v1:0"
      ]
    },
    {
      "Sid": "AgentActionGroupS3",
      "Effect": "Allow",
      "Action": ["s3:GetObject"],
      "Resource": ["arn:aws:s3:::my-bucket/openapi-schema.json"],
      "Condition": { "StringEquals": { "aws:ResourceAccount": "123456789012" } }
    },
    {
      "Sid": "AgentKnowledgeBaseQuery",
      "Effect": "Allow",
      "Action": ["bedrock:Retrieve", "bedrock:RetrieveAndGenerate"],
      "Resource": ["arn:aws:bedrock:us-east-1:123456789012:knowledge-base/KB12345678"]
    },
    {
      "Sid": "ApplyGuardrail",
      "Effect": "Allow",
      "Action": "bedrock:ApplyGuardrail",
      "Resource": ["arn:aws:bedrock:us-east-1:123456789012:guardrail/GUARDRAIL_ID"]
    }
  ]
}
```

_Source: https://docs.aws.amazon.com/bedrock/latest/userguide/agents-permissions.html_

---

### VPC endpoint for Bedrock Runtime

Create the endpoint via AWS CLI and use it with boto3.

```bash
# Create the endpoint (private DNS enabled - recommended)
aws ec2 create-vpc-endpoint \
  --vpc-id vpc-0abcdef1234567890 \
  --service-name com.amazonaws.us-east-1.bedrock-runtime \
  --vpc-endpoint-type Interface \
  --subnet-ids subnet-0111aaa2222bbb333 \
  --security-group-ids sg-0aaabbbccc1111222 \
  --private-dns-enabled \
  --region us-east-1

# Repeat for other Bedrock service names if needed:
# com.amazonaws.us-east-1.bedrock
# com.amazonaws.us-east-1.bedrock-agent
# com.amazonaws.us-east-1.bedrock-agent-runtime

# boto3 with private DNS (no code change needed):
# import boto3
# client = boto3.client("bedrock-runtime", region_name="us-east-1")
# Automatically uses the VPC endpoint via private DNS

# boto3 WITHOUT private DNS (explicit endpoint_url):
python3 -c "
import boto3
client = boto3.client(
    'bedrock-runtime',
    region_name='us-east-1',
    endpoint_url='https://vpce-029dea71225152fde.bedrock-runtime.us-east-1.vpce.amazonaws.com'
)
response = client.converse(
    modelId='anthropic.claude-sonnet-4-6',
    messages=[{'role': 'user', 'content': [{'text': 'Hello'}]}]
)
print(response)
"
```

_Source: https://docs.aws.amazon.com/bedrock/latest/userguide/vpc-interface-endpoints.html_

---

### AgentCore PrivateLink - three required endpoints

```bash
# Data plane endpoint (Runtime, Memory, Built-in Tools, Identity, Gateway, Policy)
aws ec2 create-vpc-endpoint \
  --vpc-id vpc-0abcdef1234567890 \
  --service-name com.amazonaws.us-east-1.bedrock-agentcore \
  --vpc-endpoint-type Interface \
  --subnet-ids subnet-0111aaa2222bbb333 \
  --security-group-ids sg-0aaabbbccc1111222 \
  --private-dns-enabled \
  --region us-east-1

# Control plane endpoint (CreateAgentRuntime, UpdateAgentRuntime, ...)
aws ec2 create-vpc-endpoint \
  --vpc-id vpc-0abcdef1234567890 \
  --service-name com.amazonaws.us-east-1.bedrock-agentcore-control \
  --vpc-endpoint-type Interface \
  --subnet-ids subnet-0111aaa2222bbb333 \
  --security-group-ids sg-0aaabbbccc1111222 \
  --private-dns-enabled \
  --region us-east-1

# Gateway endpoint (AgentCore Gateway MCP tools)
aws ec2 create-vpc-endpoint \
  --vpc-id vpc-0abcdef1234567890 \
  --service-name com.amazonaws.us-east-1.bedrock-agentcore.gateway \
  --vpc-endpoint-type Interface \
  --subnet-ids subnet-0111aaa2222bbb333 \
  --security-group-ids sg-0aaabbbccc1111222 \
  --private-dns-enabled \
  --region us-east-1
```

_Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/vpc-interface-endpoints.html_

---

### VPC endpoint policy for AgentCore (SigV4 + OAuth)

Mixed policy supporting both IAM SigV4 callers (restricted Principal) and OAuth callers (Principal `"*"` required).

```json
{
  "Statement": [
    {
      "Sid": "AllowPRMDiscovery",
      "Effect": "Allow",
      "Principal": "*",
      "Action": ["bedrock-agentcore:GetRuntimeProtectedResourceMetadata"],
      "Resource": "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/*"
    },
    {
      "Sid": "AllowIAMInvoke",
      "Effect": "Allow",
      "Principal": {
        "AWS": "arn:aws:iam::123456789012:role/MyAppRole"
      },
      "Action": ["bedrock-agentcore:InvokeAgentRuntime"],
      "Resource": "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/customAgent1"
    },
    {
      "Sid": "AllowOAuthAndIAMInvoke",
      "Effect": "Allow",
      "Principal": "*",
      "Action": ["bedrock-agentcore:InvokeAgentRuntime"],
      "Resource": "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/customAgent2"
    }
  ]
}
```

_Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/vpc-interface-endpoints.html_

---

### VPC endpoint policy for Bedrock Runtime

Restrict which actions and models are allowed through the endpoint.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Principal": "*",
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream"
      ],
      "Resource": "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-sonnet-4-6"
    }
  ]
}
```

_Source: https://docs.aws.amazon.com/bedrock/latest/userguide/vpc-interface-endpoints.html_

---

### Prompt caching with Converse API (Python)

Cache checkpoint on `system` with explicit TTL. Includes the quota and billing formulas in comments.

```python
import boto3

client = boto3.client("bedrock-runtime", region_name="us-east-1")

# Example with system cache checkpoint (TTL 5 min default)
response = client.converse(
    modelId="anthropic.claude-sonnet-4-6",  # min 1024 tokens before checkpoint
    system=[
        {
            "text": "You are a helpful assistant. " + LONG_STATIC_DOCUMENT  # > 1024 tokens
        },
        {
            "cachePoint": {
                "type": "default"
                # ttl omitted = 5 minutes default
                # NOTE: Sonnet 4.6 supports 5m ONLY. "ttl": "1h" is valid only on
                # Claude Opus 4.5 / Haiku 4.5 / Sonnet 4.5 (silently ignored elsewhere).
            }
        }
    ],
    messages=[
        {
            "role": "user",
            "content": [{"text": "What is the main topic of chapter 3?"}]
        }
    ],
    inferenceConfig={"maxTokens": 512}
)

# Read caching metrics from the response
usage = response["usage"]
print(f"Input tokens (non-cached, non-write): {usage.get('inputTokens', 0)}")
print(f"Cache read tokens (do NOT consume TPM quota): {usage.get('cacheReadInputTokens', 0)}")
print(f"Cache write tokens (consume TPM quota):       {usage.get('cacheWriteInputTokens', 0)}")
print(f"Output tokens:                                {usage.get('outputTokens', 0)}")

# FORMULA quota consumed (models with 5x burndown, e.g. Claude Sonnet 4.6):
# = inputTokens + cacheWriteInputTokens + (outputTokens x 5)
# FORMULA billing:
# = inputTokens (standard rate) + cacheWriteInputTokens (cache write rate)
#   + cacheReadInputTokens (cache read rate, reduced) + outputTokens (output rate)
# FORMULA total input tokens in prompt:
# = inputTokens + cacheReadInputTokens + cacheWriteInputTokens
```

_Source: https://docs.aws.amazon.com/bedrock/latest/userguide/prompt-caching.html_

---

### Prompt caching with InvokeModel API (Python)

Native Anthropic `cache_control` format inside the InvokeModel body.

```python
import boto3
import json

client = boto3.client("bedrock-runtime", region_name="us-east-1")

body = {
    "anthropic_version": "bedrock-2023-05-31",
    "system": "Reply concisely.",
    "messages": [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": LONG_STATIC_CONTEXT  # must exceed 1024 tokens for Claude Sonnet 4.6/3.7/Opus 4
                                                  # must exceed 4096 tokens for Claude Opus 4.5/4.6/Haiku 4.5/Sonnet 4.5
                },
                {
                    "type": "text",
                    "text": "Summarize the above.",
                    "cache_control": {
                        "type": "ephemeral"
                        # ttl omitted = 5 minutes default
                        # for TTL 1 hour (supported models only): "ttl": "1h"
                    }
                }
            ]
        }
    ],
    "max_tokens": 512
}

response = client.invoke_model(
    modelId="anthropic.claude-sonnet-4-6",
    body=json.dumps(body),
    contentType="application/json",
    accept="application/json"
)
result = json.loads(response["body"].read())
print(result)
```

_Source: https://docs.aws.amazon.com/bedrock/latest/userguide/prompt-caching.html_

---

### IAM policy for Global cross-region inference

Three mandatory statements for Global CRIS. All three must be present or `AccessDeniedException` is raised.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "GrantGlobalCrisInferenceProfileRegionAccess",
      "Effect": "Allow",
      "Action": "bedrock:InvokeModel",
      "Resource": [
        "arn:aws:bedrock:us-east-1:123456789012:inference-profile/global.anthropic.claude-sonnet-4-6"
      ],
      "Condition": {
        "StringEquals": { "aws:RequestedRegion": "us-east-1" }
      }
    },
    {
      "Sid": "GrantGlobalCrisInferenceProfileInRegionModelAccess",
      "Effect": "Allow",
      "Action": "bedrock:InvokeModel",
      "Resource": [
        "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-sonnet-4-6"
      ],
      "Condition": {
        "StringEquals": {
          "aws:RequestedRegion": "us-east-1",
          "bedrock:InferenceProfileArn": "arn:aws:bedrock:us-east-1:123456789012:inference-profile/global.anthropic.claude-sonnet-4-6"
        }
      }
    },
    {
      "Sid": "GrantGlobalCrisInferenceProfileGlobalModelAccess",
      "Effect": "Allow",
      "Action": "bedrock:InvokeModel",
      "Resource": [
        "arn:aws:bedrock:::foundation-model/anthropic.claude-sonnet-4-6"
      ],
      "Condition": {
        "StringEquals": {
          "aws:RequestedRegion": "unspecified",
          "bedrock:InferenceProfileArn": "arn:aws:bedrock:us-east-1:123456789012:inference-profile/global.anthropic.claude-sonnet-4-6"
        }
      }
    }
  ]
}
```

_Source: https://docs.aws.amazon.com/bedrock/latest/userguide/global-cross-region-inference.html_

---

### SCP for data residency

Restricts `bedrock:*` to approved regions, explicitly permits `"unspecified"` for Global CRIS.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "RestrictToApprovedRegions",
      "Effect": "Deny",
      "Action": "bedrock:*",
      "Resource": "*",
      "Condition": {
        "StringNotEquals": {
          "aws:RequestedRegion": [
            "us-east-1",
            "us-west-2",
            "eu-west-1",
            "unspecified"
          ]
        }
      }
    },
    {
      "Sid": "DataResidencyCompliance",
      "Effect": "Deny",
      "Action": ["bedrock:InvokeModel", "bedrock:CreateCustomModel"],
      "Resource": "*",
      "Condition": {
        "StringEquals":    { "aws:RequestTag/DataResidency": "EU" },
        "StringNotEquals": { "aws:RequestedRegion": ["eu-west-1", "eu-central-1"] }
      }
    }
  ]
}
```

_Source: https://docs.aws.amazon.com/prescriptive-guidance/latest/data-perimeter-for-amazon-bedrock/regional-boundary-enforcement.html_

---

### Deny GetWorkloadAccessTokenForUserId in production

When JWTs are always available, explicitly deny the unsafe `UserId` variant.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DenyUserIdDelegation",
      "Effect": "Deny",
      "Action": [
        "bedrock-agentcore:GetWorkloadAccessTokenForUserId",
        "bedrock-agentcore:InvokeAgentRuntimeForUser"
      ],
      "Resource": "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/*"
    },
    {
      "Sid": "AllowJWTBasedTokenOnly",
      "Effect": "Allow",
      "Action": ["bedrock-agentcore:GetWorkloadAccessTokenForJWT"],
      "Resource": [
        "arn:aws:bedrock-agentcore:us-east-1:123456789012:workload-identity-directory/default"
      ]
    }
  ]
}
```

_Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-security-best-practices.html_

---

### Create Bedrock Agent with KMS CMK (Python)

```python
import boto3

bedrock_agent = boto3.client("bedrock-agent", region_name="us-east-1")

response = bedrock_agent.create_agent(
    agentName="my-secure-agent",
    agentResourceRoleArn="arn:aws:iam::123456789012:role/MyBedrockAgentRole",
    foundationModel="anthropic.claude-3-7-sonnet-20250219-v1:0",
    description="Production agent with CMK encryption",
    idleSessionTTLInSeconds=600,
    customerEncryptionKeyArn="arn:aws:kms:us-east-1:123456789012:key/mrk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
    instruction="You are a helpful assistant."
)
agent_id = response["agent"]["agentId"]
print(f"Agent created: {agent_id}")

# For knowledge base with KMS:
bedrock_agent.create_data_source(
    knowledgeBaseId="KB12345678",
    name="my-datasource",
    dataSourceConfiguration={
        "type": "S3",
        "s3Configuration": {"bucketArn": "arn:aws:s3:::my-kb-bucket"}
    },
    serverSideEncryptionConfiguration={
        "kmsKeyArn": "arn:aws:kms:us-east-1:123456789012:key/mrk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    }
)
```

_Source: https://docs.aws.amazon.com/bedrock/latest/userguide/data-encryption.html_

---

### Request TPM quota increase via AWS CLI

```bash
# List current quotas for Bedrock
aws service-quotas list-service-quotas \
  --service-code bedrock \
  --region us-east-1 \
  --query "Quotas[?contains(QuotaName, 'claude-sonnet-4-6')]"

# Request quota increase.
# NOTE: request the increase for 'Cross-Region InvokeModel tokens per minute'.
# The support team will also offer to increase On-demand TPM and TPD in the same request.
aws service-quotas request-service-quota-increase \
  --service-code bedrock \
  --quota-code L-XXXXXXXX \
  --desired-value 2000000 \
  --region us-east-1

# NOTE: new AWS accounts have reduced quotas compared to documented defaults.
# AWS prioritizes quota increase requests from customers with real traffic
# already consuming existing quota.
```

_Source: https://docs.aws.amazon.com/bedrock/latest/userguide/quotas-runtime.html_

---

### Use service tiers in Converse API (Python)

```python
import boto3

client = boto3.client("bedrock-runtime", region_name="us-east-1")

# Standard tier (default) - same as not specifying serviceTier at all.
# serviceTier is a TOP-LEVEL Converse request parameter (not inside additionalModelRequestFields).
response = client.converse(
    modelId="anthropic.claude-sonnet-4-6",
    messages=[{"role": "user", "content": [{"text": "Hello"}]}],
    serviceTier={"type": "default"}  # Standard
)

# Flex tier - -50% vs Standard price, higher latency variability
response_flex = client.converse(
    modelId="anthropic.claude-sonnet-4-6",
    messages=[{"role": "user", "content": [{"text": "Batch summarize this document"}]}],
    serviceTier={"type": "flex"}
)

# Verify which tier actually served the request (ResolvedServiceTier)
# available via CloudWatch Metrics under ModelId and ServiceTier/ResolvedServiceTier
print(response["output"]["message"]["content"][0]["text"])
```

_Source: https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_Converse.html - `serviceTier` is a top-level JSON body field (type: ServiceTier object with required `type` string); valid values: `priority | default | flex | reserved`. It is NOT passed inside `additionalModelRequestFields`._

---

## Configuration reference

| Name | Description | Default / example |
|---|---|---|
| `customerEncryptionKeyArn` (CreateAgent) | ARN of the KMS CMK used to encrypt the Bedrock agent at rest. | `arn:aws:kms:us-east-1:123456789012:key/mrk-abc123` |
| `customModelKmsKeyId` (CreateModelCustomizationJob) | ARN of the KMS CMK to encrypt the custom model and fine-tuning job output. | `arn:aws:kms:us-east-1:123456789012:key/mrk-abc123` |
| `kmsKeyArn` (CreateDataSource / UpdateDataSource) | ARN of the KMS CMK to encrypt a Bedrock knowledge base data source. | `arn:aws:kms:us-east-1:123456789012:key/mrk-abc123` |
| `cachePoint.type` (Converse API) | Defines a cache checkpoint in the Converse request. Fixed value: `"default"`. | `{"type": "default"}` or `{"type": "default", "ttl": "1h"}` |
| `cachePoint.ttl` (Converse API) | TTL for the cache checkpoint. `"5m"` (default for all) or `"1h"` (supported: Claude Opus 4.5, Haiku 4.5, Sonnet 4.5 only - Sonnet 4.6 and Opus 4.6 support 5m only). If `"1h"` is specified on an unsupported model, it is silently ignored. _Source: https://docs.aws.amazon.com/bedrock/latest/userguide/prompt-caching.html_ | `"5m"` or `"1h"` |
| `cache_control.type` (InvokeModel Anthropic) | Enables caching in the native Anthropic format inside the InvokeModel body. Fixed value: `"ephemeral"`. | `{"type": "ephemeral"}` or `{"type": "ephemeral", "ttl": "5m"}` |
| Token burndown rate - Claude 3.7+ and Claude 4.x | 1 output token = 5 quota tokens (TPM/TPD) for Claude 3.7 Sonnet and all later models. All other models: 1:1. Initial quota deducted = InputTokens + CacheWriteInputTokens + max_tokens × burndown. Final quota = InputTokens + CacheWriteInputTokens + (OutputTokens × burndown). | `5x` for Claude 3.7, Sonnet 4.6, Opus 4, Opus 4.6 and later; `1x` for other models |
| Minimum tokens per cache checkpoint | Min tokens required before a cache checkpoint. | `1024` (Claude 3.7, Sonnet 4.6, Opus 4, Opus 4.1); `4096` (Opus 4.5, Opus 4.6, Haiku 4.5, Sonnet 4.5) |
| Max cache checkpoints per request | Maximum cache checkpoints per single request for all supported Claude models. | `4` for all supported Claude models |
| Service endpoint names - VPC PrivateLink Bedrock | Names of the 5 (+2 FIPS) Bedrock services for interface VPC endpoints. | `com.amazonaws.{region}.bedrock` \| `bedrock-runtime` \| `bedrock-mantle` \| `bedrock-agent` \| `bedrock-agent-runtime` \| `bedrock-fips` \| `bedrock-runtime-fips` |
| Service endpoint names - VPC PrivateLink AgentCore | Names of the 3 AgentCore services for interface VPC endpoints. | `com.amazonaws.{region}.bedrock-agentcore` (data plane) \| `bedrock-agentcore-control` (control plane) \| `bedrock-agentcore.gateway` (Gateway) |
| `BedrockAgentCoreFullAccess` | AWS managed policy for AgentCore. Does NOT include `iam:CreateRole`. `iam:PassRole` scoped to `*BedrockAgentCore*`. Contains `GetWorkloadAccessTokenForUserId` (dev only). | `arn:aws:iam::aws:policy/BedrockAgentCoreFullAccess` |
| Batch inference limits | Max records, input file size, processing window, discount. Does NOT support: prompt caching, tool use, structured output, multi-turn. | `10,000 records / 200 MB / 24 h / ~50% discount vs on-demand` |
| AgentCore Runtime active sessions | Default quota for simultaneous active workload sessions per account. Adjustable via Service Quotas. | `1000` (US East N. Virginia / US West Oregon); `500` (other regions) |
| AgentCore Runtime max hardware per session | Maximum hardware allocation per AgentCore Runtime session. Not adjustable. | `2 vCPU / 8 GB RAM per session` |
| AgentCore InvokeAgentRuntime TPS | Maximum transactions per second per agent per account for `InvokeAgentRuntime`. Adjustable. | `25 TPS per agent` |
| AgentCore sync request timeout | Maximum timeout for synchronous Runtime requests. Not adjustable. | `15 minutes` |
| AgentCore async job timeout | Maximum duration for async AgentCore Runtime jobs. Configurable via `maxLifetime` in `LifecycleConfiguration`. | `8 hours` (default idle timeout: 15 minutes of inactivity, configurable) |
| `aws:RequestedRegion` for Global CRIS | The value `aws:RequestedRegion` takes when a request is routed globally. SCPs must explicitly include this value in permitted-regions exceptions. | `"unspecified"` |
| Global inference ID pattern | Inference profile ID for Global cross-region inference. Source regions: `us-west-2`, `us-east-1`, `us-east-2`, `eu-west-1`, `ap-northeast-1`. | `global.anthropic.claude-sonnet-4-6` |
| Claude 3.5 Sonnet v2 pricing (extended access, us-east-1) | Only pair of prices confirmed statically in public docs. For Claude 4.x models consult the AWS console pricing page directly. | Input: $6.00/1M \| Output: $30.00/1M \| Batch input: $3.00/1M \| Batch output: $15.00/1M \| Cache write: $7.50/1M \| Cache read: $0.60/1M |
| `serviceTier` parameter (runtime API) | Optional parameter in runtime calls to select the service tier. Pass as a dict: `{"type": "..."}`. | `serviceTier={"type": "default"}` \| `{"type": "priority"}` \| `{"type": "flex"}` \| `{"type": "reserved"}` |
| Reserved tier minimum capacity | Minimum reservable capacity in the Reserved tier. Requires contacting the AWS team. | Min 100,000 input TPM + 10,000 output TPM for 1 or 3 months |

---

## Gotchas

- **BURNDOWN RATE 5x FOR CLAUDE 3.7+ AND ALL CLAUDE 4.x:** 1 output token consumes 5 tokens from the TPM/TPD quota. A prompt with `max_tokens=32768` deducts 32,768 tokens from the TPM quota at the START of the request, even if the real response is 200 tokens. Overestimating `max_tokens` is the primary cause of premature throttling. Example: 1000 input + 100 output on Claude Sonnet 4.6 = 1,500 tokens consumed from quota (1000 + 100×5), but only 1,100 tokens are billed.

- **`CacheReadInputTokens` do NOT consume quota, but `CacheWriteInputTokens` DO:** Quota formula = `InputTokenCount + CacheWriteInputTokens + (OutputTokenCount × burndown)`. Tokens read from cache (`CacheReadInputTokens`) are not counted against TPM/TPD quotas. If the TTL expires frequently (continuous cache misses) you pay more than without caching because cache-write cost on some models is higher than the standard input token rate.

- **Bedrock does not support resource-based policies:** Unlike S3 or Lambda, `bedrock:InvokeModel` cannot be controlled via a resource policy on the model. All access logic is identity-based (policy on the caller) or via VPC endpoint policy.

- **`GetWorkloadAccessTokenForUserId` is dangerous in production:** It accepts any string as user-id without verifying identity with an IdP. A malicious actor with access to the runtime can impersonate any user-id. Use only in development; in production use `GetWorkloadAccessTokenForJWT`.

- **AgentCore CLI policies are for dev/test ONLY:** Permissions generated by the CLI have `"Resource": "*"` on many actions. Using them in production violates least-privilege and can expose the account to escalation.

- **MMDS exposes execution role credentials to any code in the microVM:** Any tool code, prompt injection, or compromised dependency running in the AgentCore microVM can call the MMDS endpoint and obtain the execution role's temporary credentials. Mitigation: keep the role scope at the strict minimum.

- **Changing tools invalidates ALL downstream cache:** Cache checkpoints in the Converse API are processed in order: tools → system → messages. Modifying a tool definition invalidates checkpoints for system and messages. Structure tools as static and user messages AFTER the last checkpoint.

- **Cross-region inference and SCPs:** Global inference profiles send requests with `aws:RequestedRegion = "unspecified"`. The SCP must explicitly allow `"unspecified"` in the list of permitted regions; otherwise Global CRIS requests are blocked even if the source region is whitelisted.

- **Batch inference does not support prompt caching, tool use, structured output, or multi-turn:** Do not use batch for agentic workflows that require these features.

- **Quota increases:** AWS prioritizes customers already consuming existing quotas. Requesting large increases before having real traffic may be rejected.

- **`iam:PassRole` in `BedrockAgentCoreFullAccess` is scoped to `*BedrockAgentCore*`:** If execution roles are named with a different pattern (e.g., `MyAgentRole`), `iam:PassRole` will fail silently. Use names containing `BedrockAgentCore` or create a custom policy with your own pattern.

- **TTL 1 hour is limited to Claude Opus 4.5, Haiku 4.5, and Sonnet 4.5.** The official `prompt-caching.html` supported-models table lists Claude **Sonnet 4.6 and Opus 4.6 as `5 minutes` only** (not 1 hour). Specifying `"ttl": "1h"` on an unsupported model is silently ignored (inference still succeeds at 5m). _Source: https://docs.aws.amazon.com/bedrock/latest/userguide/prompt-caching.html_

- **CORRECTION - AgentCore VPC endpoint is NOT a single endpoint:** You need THREE separate endpoints: `bedrock-agentcore` (data plane), `bedrock-agentcore-control` (control plane), `bedrock-agentcore.gateway` (Gateway). Create only the ones relevant to the operations you intend to perform.

- **RPM (requests per minute) is no longer enforced:** The RPM quota on `bedrock-runtime` has been officially deprecated. Throttling is governed ONLY by token-based quotas (TPM and TPD). Do not request RPM increases for `bedrock-runtime`.

- **AgentCore Harness and AgentCore Payments are still in Preview (not GA)** with reduced availability (4–5 regions). Do not use for production workloads without verifying regional availability.

- **Global cross-region inference for Bedrock requires an IAM policy with THREE statements:** One for the inference profile in the source region, one for the FM in-region, one for the FM global (ARN without region or account). Missing even one causes `AccessDeniedException`.

- **For Reserved tier, include `CacheWriteInputTokens` in capacity estimation:** The Reserved tier consumes `InputTokenCount + CacheWriteInputTokens`. Sizing only on `InputTokenCount` leads to frequent overflow onto the Standard tier.

---

## Official sources

- [IAM Permissions for AgentCore Runtime](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-permissions.html) - Execution role for AgentCore Runtime (direct and container), trust policy, `bedrock-agentcore:GetWorkloadAccessToken*` permissions
- [Security best practices for AgentCore Runtime](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-security-best-practices.html) - 12 security domains: session isolation, IAM least-privilege, confused deputy, network, encryption, auditing, MMDS credential exposure
- [AWS managed policies for Amazon Bedrock AgentCore](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/security-iam-awsmanpol.html) - `BedrockAgentCoreFullAccess` and the 3 service managed policies (network, identity, memory)
- [Use interface VPC endpoints (AWS PrivateLink) for AgentCore](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/vpc-interface-endpoints.html) - Three AgentCore PrivateLink endpoints: data plane (bedrock-agentcore), control plane (bedrock-agentcore-control), gateway (bedrock-agentcore.gateway). Notes on OAuth vs SigV4 policy.
- [Quotas for Amazon Bedrock AgentCore](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/bedrock-agentcore-limits.html) - Runtime quotas: 1000 active sessions (US-E1/US-W2), 500 elsewhere; 25 TPS invocation; 2 vCPU/8 GB per session; 15 min sync timeout; 8 h async; 1 GB storage/session
- [Create a service role for Amazon Bedrock Agents](https://docs.aws.amazon.com/bedrock/latest/userguide/agents-permissions.html) - Trust policy and identity-based permissions for classic Bedrock Agents (InvokeModel, Retrieve, guardrails, multi-agent, Provisioned Throughput)
- [Identity-based policy examples for Amazon Bedrock](https://docs.aws.amazon.com/bedrock/latest/userguide/security_iam_id-based-policy-examples.html) - Policies for console, deny inference, provisioned model, minimal playground policy
- [How Amazon Bedrock works with IAM](https://docs.aws.amazon.com/bedrock/latest/userguide/security_iam_service-with-iam.html) - Overview of IAM features supported by Bedrock: identity-based, condition keys, ABAC, temporary credentials
- [Use interface VPC endpoints (AWS PrivateLink) for Amazon Bedrock](https://docs.aws.amazon.com/bedrock/latest/userguide/vpc-interface-endpoints.html) - Service names for all Bedrock endpoints, endpoint policies, boto3/CLI examples, FIPS endpoint
- [Data encryption](https://docs.aws.amazon.com/bedrock/latest/userguide/data-encryption.html) - KMS for agents (`customerEncryptionKeyArn`), knowledge bases (`kmsKeyArn`), custom models (`customModelKmsKeyId`), S3, Secrets Manager
- [Data protection](https://docs.aws.amazon.com/bedrock/latest/userguide/data-protection.html) - Shared responsibility model, no training on customer data, TLS 1.2+, FIPS 140-3, model providers have no access to customer data
- [Prompt caching for faster model inference](https://docs.aws.amazon.com/bedrock/latest/userguide/prompt-caching.html) - How caching works, TTL (5 min / 1 hour), supported models, Converse API and InvokeModel API code examples. Claude Sonnet 4.6 supports TTL 5m only with min 1024 tokens; Claude Opus 4.6 supports 5m only with min 4096 tokens; Claude Opus 4.5, Haiku 4.5, Sonnet 4.5 support 5m and 1h with min 4096 tokens.
- [Quotas for the bedrock-runtime endpoint](https://docs.aws.amazon.com/bedrock/latest/userguide/quotas-runtime.html) - TPM and TPD quotas per model, confirmed RPM deprecation, how to request quota increases. Default TPD = TPM × 24 × 60.
- [How tokens are counted in Amazon Bedrock](https://docs.aws.amazon.com/bedrock/latest/userguide/quotas-token-burndown.html) - 5x burndown rate for Claude 3.7+, impact of max_tokens, `CacheReadInputTokens` do not count against quota.
- [Understanding intelligent prompt routing in Amazon Bedrock](https://docs.aws.amazon.com/bedrock/latest/userguide/prompt-routing.html) - Automatic routing between models in the same family, configurable criteria, supported models (Anthropic, Meta, Amazon Nova)
- [Increase throughput with cross-Region inference](https://docs.aws.amazon.com/bedrock/latest/userguide/cross-region-inference.html) - Geographic vs Global inference profiles, ~10% savings with global (confirmed for Claude Sonnet 4.5), data residency, CloudTrail in source region
- [Global cross-Region inference](https://docs.aws.amazon.com/bedrock/latest/userguide/global-cross-region-inference.html) - Three-statement IAM policy required for Global CRIS; `aws:RequestedRegion='unspecified'` for global routing; SCP must explicitly allow `"unspecified"`
- [Service tiers for optimizing performance and cost](https://docs.aws.amazon.com/bedrock/latest/userguide/service-tiers-inference.html) - Four tiers: Reserved (99.5% uptime, min 100K input TPM + 10K output TPM), Priority (price premium), Standard (default), Flex (price discount). `serviceTier` parameter in runtime APIs - exact percentages vary; see the [Bedrock pricing page](https://aws.amazon.com/bedrock/pricing/).
- [GENCOST03-BP03 Implement prompt caching to reduce token costs (Well-Architected Generative AI Lens)](https://docs.aws.amazon.com/wellarchitected/latest/generative-ai-lens/gencost03-bp03.html) - Official Well-Architected best practice for prompt caching, implementation steps
- [Regional boundary enforcement (Data Perimeter for Amazon Bedrock)](https://docs.aws.amazon.com/prescriptive-guidance/latest/data-perimeter-for-amazon-bedrock/regional-boundary-enforcement.html) - SCP for data residency/region restriction, S3 bucket policy anti-cross-region replication
- [Claude Sonnet 4.6 model card](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-sonnet-4-6.html) - ID: `anthropic.claude-sonnet-4-6`; context 1M; max output 64K; TTL caching 5m only (per official prompt-caching table); Geo IDs: `us./eu./au./jp.anthropic.claude-sonnet-4-6`; Global ID: `global.anthropic.claude-sonnet-4-6`. Launch: Feb 17, 2026.
- [Claude Opus 4.6 model card](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-opus-4-6.html) - ID: `anthropic.claude-opus-4-6-v1`; context 1M; max output 128K; TTL caching 5m only (not 1h per official prompt-caching table), min 4096 tokens; Geo IDs: `us./eu./au.anthropic.claude-opus-4-6-v1`. Launch: Feb 5, 2026.
- [Amazon Bedrock pricing](https://aws.amazon.com/bedrock/pricing/) - Official pricing page. Claude 4.x prices are shown in the AWS console and accessible via `bedrock:GetFoundationModelAvailability`. Claude 3.5 Sonnet v2 (extended access): input $6.00, output $30.00, cache write $7.50, cache read $0.60 per 1M tokens.
- [Supported AWS Regions for AgentCore](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agentcore-regions.html) - AgentCore Runtime GA in 16 regions including GovCloud. AgentCore Harness and Payments still in Preview with reduced availability.

---

## Verify live (open questions)

Re-check the following in the live console or docs before relying on them in production code:

1. **Exact prices ($/MTok) for cache read vs cache write vs standard input for Claude 4.x models** (Sonnet 4.6, Opus 4.6, Opus 4.5, Haiku 4.5, Sonnet 4.5, Opus 4, etc.): The [Amazon Bedrock pricing page](https://aws.amazon.com/bedrock/pricing/) renders these only via interactive JavaScript - they cannot be extracted statically. The only statically confirmed price pair is Claude 3.5 Sonnet v2 (extended access): input $6.00, output $30.00, cache write $7.50, cache read $0.60 per 1M tokens. For all current Anthropic models consult the pricing section in the AWS console directly.

2. **Exact default quota values per model** (e.g., default TPM for Claude Sonnet 4.6 in us-east-1): These change frequently and are not documented statically. Verify in the [Service Quotas console](https://console.aws.amazon.com/servicequotas/home/services/bedrock/quotas) or via `aws service-quotas list-service-quotas --service-code bedrock`.

3. **Provisioned Throughput pricing per model** (cost per Model Unit per hour): Requires contacting the AWS team or querying the pricing API. Not available in static documentation.
