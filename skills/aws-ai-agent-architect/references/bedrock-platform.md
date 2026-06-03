# Bedrock Platform Features for Cost, Scale & Quality (Intelligent Prompt Router, Batch, Fine-tuning, Data Residency)

> Part of the **aws-ai-agent-architect** skill. See [SKILL.md](../SKILL.md) for the decision tree. Every source below is official — re-open it to verify details.

## Table of contents

- [Overview](#overview)
- [Key concepts](#key-concepts)
- [1. Intelligent Prompt Router](#1-intelligent-prompt-router)
  - [When to use](#when-to-use)
  - [Best practices](#best-practices-prompt-router)
  - [Code](#code-prompt-router)
  - [Configuration reference](#configuration-reference-prompt-router)
  - [Gotchas](#gotchas-prompt-router)
- [2. Batch Inference](#2-batch-inference)
  - [When to use](#when-to-use-batch)
  - [Best practices](#best-practices-batch)
  - [Code](#code-batch)
  - [Configuration reference](#configuration-reference-batch)
  - [Gotchas](#gotchas-batch)
- [3. Fine-tuning and Custom Models](#3-fine-tuning-and-custom-models)
  - [When to use](#when-to-use-fine-tuning)
  - [Best practices](#best-practices-fine-tuning)
  - [Configuration reference](#configuration-reference-fine-tuning)
  - [Gotchas](#gotchas-fine-tuning)
- [4. Data Residency Checklist](#4-data-residency-checklist)
  - [Best practices](#best-practices-data-residency)
  - [Code](#code-data-residency)
  - [Configuration reference](#configuration-reference-data-residency)
  - [Gotchas](#gotchas-data-residency)
- [Official sources](#official-sources)

---

## Overview

This file covers four Bedrock platform capabilities that span cost, scale, and compliance. They are mostly **independent of one another** — choose based on workload shape:

| Feature | Primary driver | Maturity |
|---|---|---|
| Intelligent Prompt Router | Reduce cost without sacrificing quality on mixed-complexity workloads | **GA** (April 2025) |
| Batch Inference | Process large offline datasets asynchronously at ~50% lower cost | **GA** |
| Fine-tuning / Custom Models | Improve task-specific accuracy; Provisioned Throughput required for inference | **GA** |
| Data Residency (geo profiles + KMS + PrivateLink) | Keep data within a geographic boundary and private network | **GA** |

For agent-level IAM, tagging, cost allocation, and quota governance, see [`security-iam-cost.md`](./security-iam-cost.md). For CDK/IaC for Provisioned Throughput, see [`deployment-iac.md`](./deployment-iac.md). For foundational Bedrock concepts (Converse API, model IDs, Knowledge Bases, Guardrails), see [`bedrock.md`](./bedrock.md).

---

## Key concepts

- **Model Unit (MU):** The billing and capacity unit for Provisioned Throughput. One MU delivers a fixed number of input/output tokens per minute. Needed for any custom model, and optionally for base models at scale.
- **Inference Profile:** An ARN (system-defined or application-defined) that abstracts one or more regional model endpoints. Geo profiles pin requests within a geographic boundary; Global profiles span all commercial regions. Use as `modelId` in any API call.
- **Batch job:** An asynchronous `CreateModelInvocationJob` request that reads JSONL from S3 and writes JSONL responses back to S3. Not connected to interactive agent sessions.
- **Prompt Router:** A Bedrock resource (ARN) that dynamically selects between two models in the same family per request based on predicted response quality. You invoke it exactly like a model ID.
- **CMK:** AWS KMS Customer Managed Key. Provides a second encryption layer with customer-controlled key policy, rotation, and audit trail.

---

## 1. Intelligent Prompt Router

**Maturity: GA** — became generally available in April 2025.

_Source: [Amazon Bedrock Intelligent Prompt Routing is now generally available](https://aws.amazon.com/about-aws/whats-new/2025/04/amazon-bedrock-intelligent-prompt-routing-generally-available/)_

Intelligent Prompt Router provides a **single serverless endpoint** that dynamically routes each request between two foundation models in the same family. Bedrock predicts which model will deliver the best response quality for each specific prompt, then routes accordingly. No orchestration code required.

### Supported model families (GA)

| Provider | Models in family |
|---|---|
| Amazon | Nova Lite, Nova Pro |
| Anthropic | Claude 3 Haiku, Claude 3.5 Haiku, Claude 3.5 Sonnet v1, Claude 3.5 Sonnet v2 |
| Meta | Llama 3.1 8B/70B, Llama 3.2 11B/90B, Llama 3.3 70B |

_Source: [Understanding intelligent prompt routing in Amazon Bedrock](https://docs.aws.amazon.com/bedrock/latest/userguide/prompt-routing.html)_

You can use each model either as a **single-region model** (direct model ID) or as a **cross-region inference profile** (prefixed ID, e.g., `us.anthropic.claude-3-5-sonnet-20241022-v2:0`). The table of supported regions per model is maintained in the official docs — defer to the console or `GetInferenceProfile` for the current list.

### When to use

- Workload has a **wide range of prompt complexity** — some simple/short prompts naturally suit a cheaper model (e.g., Haiku) while complex reasoning benefits from a larger one (e.g., Sonnet).
- You want **automatic cost reduction** without manually classifying prompts or maintaining routing code.
- You are already using on-demand inference (pay-per-token) and do not require Provisioned Throughput.
- You are calling the Converse API or InvokeModel — prompt routing is invoked as a `modelId`.

Do **not** use Intelligent Prompt Router when:
- You need deterministic routing (e.g., always use the cheaper model for latency SLAs or compliance auditing).
- Your prompts are in a language other than English (routing is optimized for English only).
- You require tool calling / function calling in every request — confirm tool support on the specific family.

### Best practices (Prompt Router) {#best-practices-prompt-router}

- **Start with default routers** before creating configured routers. Default routers require zero setup and work with Anthropic and Meta families out of the box.
  _Source: [Understanding intelligent prompt routing in Amazon Bedrock](https://docs.aws.amazon.com/bedrock/latest/userguide/prompt-routing.html)_

- **Set the fallback model** to the higher-capability (more expensive) model. The router only deviates to the cheaper model when predicted quality is within your `responseQualityDifference` threshold. This ensures quality degrades gracefully, not silently.
  _Source: [Understanding intelligent prompt routing in Amazon Bedrock](https://docs.aws.amazon.com/bedrock/latest/userguide/prompt-routing.html)_

- **Monitor routing decisions** using CloudWatch — the response payload includes the `modelId` that was actually invoked. Track the fraction routed to each model to calibrate cost savings versus quality regression.
  _Source: [Understanding intelligent prompt routing in Amazon Bedrock](https://docs.aws.amazon.com/bedrock/latest/userguide/prompt-routing.html)_

- **Use cross-region inference profiles** as inputs to the router to combine routing with geographic throughput scaling. Both `modelA` and `modelB` ARNs can be inference profile ARNs.
  _Source: [Understanding intelligent prompt routing in Amazon Bedrock](https://docs.aws.amazon.com/bedrock/latest/userguide/prompt-routing.html)_

- **Review and refresh** the router configuration when new models join the family. Intelligent Prompt Router is designed to incorporate new models, but configured routers reference specific model ARNs — update them when upgrading model generations.
  _Source: [Understanding intelligent prompt routing in Amazon Bedrock](https://docs.aws.amazon.com/bedrock/latest/userguide/prompt-routing.html)_

### Code (Prompt Router) {#code-prompt-router}

**Create a configured prompt router (AWS CLI):**

```bash
aws bedrock create-prompt-router \
    --prompt-router-name my-claude-router \
    --models '[{"modelArn": "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-3-5-sonnet-20241022-v2:0"}]' \
    --fallback-model '{"modelArn": "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-3-5-haiku-20241022-v1:0"}' \
    --routing-criteria '{"responseQualityDifference": 0.5}'
```
_Source: [Understanding intelligent prompt routing in Amazon Bedrock](https://docs.aws.amazon.com/bedrock/latest/userguide/prompt-routing.html)_

**Invoke via Converse API (Python / boto3) — use the router ARN as `modelId`:**

```python
import boto3

bedrock = boto3.client("bedrock-runtime", region_name="us-east-1")

# Use the prompt router ARN as the modelId
router_arn = "arn:aws:bedrock:us-east-1:123456789012:default-prompt-router/anthropic.claude:1"

response = bedrock.converse(
    modelId=router_arn,
    messages=[{"role": "user", "content": [{"text": "Summarize this paragraph in one sentence."}]}]
)

# The response includes the actual model used
print(response["output"]["message"]["content"][0]["text"])
# response["trace"]["promptRouter"]["invokedModelId"] holds the ARN of the model actually invoked
```
_Source: [Understanding intelligent prompt routing in Amazon Bedrock](https://docs.aws.amazon.com/bedrock/latest/userguide/prompt-routing.html)_

### Configuration reference (Prompt Router) {#configuration-reference-prompt-router}

| Field | Type | Description |
|---|---|---|
| `promptRouterName` | string | Unique name for the router resource |
| `models[].modelArn` | string | ARN of the secondary model (cheaper / faster) |
| `fallbackModel[].modelArn` | string | ARN of the primary (higher-quality) model; used when routing criteria not met |
| `routingCriteria.responseQualityDifference` | float (0–100) | Threshold: how much better the fallback model must be for requests to stay on it. Lower = route to cheaper model more aggressively. The value is a percentage: 0.5 means 0.5%, 50 means 50% |
| `description` | string (optional) | Human-readable description |

_Source: [CreatePromptRouter API Reference](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_CreatePromptRouter.html)_

### Gotchas (Prompt Router) {#gotchas-prompt-router}

- **English-only optimization.** Routing quality degrades for non-English prompts — the router was trained on English data. For multilingual agents, test routing quality or disable the router.
- **No application-specific feedback loop.** The router cannot learn from your application's production quality signals. It uses Bedrock's general-purpose quality prediction model.
- **Exactly two models per router.** You must specify exactly two models from the same family. You cannot mix families (e.g., Claude + Llama).
- **Default routers are read-only.** You cannot delete or modify Bedrock's default prompt routers; only configured routers are user-managed.
- **Preview note.** The GA announcement lists Anthropic Claude (Haiku, Haiku 3.5, Sonnet 3.5 v1, Sonnet 3.5 v2) and Meta Llama and Amazon Nova families. Verify support for newer model generations (Claude 3.7+, Claude 4.x) in the console before relying on routing.

---

## 2. Batch Inference

**Maturity: GA**

_Source: [Process multiple prompts with batch inference](https://docs.aws.amazon.com/bedrock/latest/userguide/batch-inference.html)_

Batch inference lets you submit large sets of prompts as **JSONL files in S3**, run them asynchronously as a `ModelInvocationJob`, and retrieve results from S3 when the job completes. AWS pricing documentation states up to **~50% cost savings** compared to on-demand inference pricing.

_Source: [What's New — Batch inference for Anthropic Claude Sonnet 4 and OpenAI GPT-OSS models](https://aws.amazon.com/about-aws/whats-new/2025/08/amazon-bedrock-batch-inference-anthropic-claude-sonnet-4-openai-gpt-oss-models/)_

### When to use (Batch) {#when-to-use-batch}

Batch inference is the right choice when:
- You are running **offline, non-interactive jobs** — document classification, evaluation pipelines, bulk summarization, content generation at scale, dataset annotation.
- Latency is not a constraint — jobs run asynchronously with no SLA guarantee on completion time.
- Request volume is large enough that 50% cost savings justify the asynchronous model.

Do **not** use batch inference for:
- **Interactive agents** or any user-facing response path — there is no way to stream or return results synchronously.
- **Tool calling / function calling** — not supported (each JSONL record is processed independently with no multi-turn back-and-forth).
- **Structured output (`response_format`)** — not supported.
- **Provisioned Throughput models** — batch inference only works with on-demand model IDs or cross-region inference profiles.
- **Prompt caching** — prompt caching is not supported in batch inference jobs.

### Best practices (Batch) {#best-practices-batch}

- **Use the Converse API format in JSONL** when inputs are mixed-model or when you expect to swap models later — it decouples your data format from model-specific schemas.
  _Source: [Create a batch inference job](https://docs.aws.amazon.com/bedrock/latest/userguide/batch-inference-create.html)_

- **Encrypt S3 output with a KMS CMK** for compliance-sensitive workloads. Specify the key in the Bedrock console output settings or via the API's `outputDataConfig`.
  _Source: [Create a batch inference job](https://docs.aws.amazon.com/bedrock/latest/userguide/batch-inference-create.html)_

- **Use EventBridge notifications** instead of polling `GetModelInvocationJob`. Register an EventBridge rule on `aws.bedrock` events (`ModelInvocationJobStateChange`) to trigger downstream processing as soon as the job completes.
  _Source: [Process multiple prompts with batch inference](https://docs.aws.amazon.com/bedrock/latest/userguide/batch-inference.html)_

- **Run batch jobs inside a VPC** for data-sensitive workloads. VPC configuration is only available via the API (`vpcConfig` field), not through the console.
  _Source: [Create a batch inference job](https://docs.aws.amazon.com/bedrock/latest/userguide/batch-inference-create.html)_

- **Use cross-region inference profiles** as the `modelId` to benefit from multi-region compute capacity and faster processing of large batch jobs.
  _Source: [Geographic cross-Region inference](https://docs.aws.amazon.com/bedrock/latest/userguide/geographic-cross-region-inference.html)_

- **Set a `timeoutDurationInHours`** on long jobs to avoid runaway charges if the job stalls. The enforced range is Minimum 24 hours / Maximum 168 hours.
  _Source: [Create a batch inference job](https://docs.aws.amazon.com/bedrock/latest/userguide/batch-inference-create.html)_

- **Tag batch jobs** for cost attribution (`bedrock:TagResource`). Verify your tagging taxonomy from [`security-iam-cost.md`](./security-iam-cost.md).

### Code (Batch) {#code-batch}

**Create a batch inference job (Python / boto3):**

```python
import boto3

bedrock = boto3.client("bedrock", region_name="us-east-1")

response = bedrock.create_model_invocation_job(
    jobName="bulk-summarization-2026-06",
    roleArn="arn:aws:iam::123456789012:role/BedrockBatchRole",
    modelId="us.anthropic.claude-3-5-sonnet-20241022-v2:0",  # cross-region inference profile
    modelInvocationType="Converse",  # use Converse format in JSONL
    inputDataConfig={
        "s3InputDataConfig": {
            "s3Uri": "s3://my-bucket/batch-input/"
        }
    },
    outputDataConfig={
        "s3OutputDataConfig": {
            "s3Uri": "s3://my-bucket/batch-output/",
            "s3EncryptionKmsKeyId": "arn:aws:kms:us-east-1:123456789012:key/my-cmk-id"
        }
    },
    timeoutDurationInHours=24,
    # Optional: VPC isolation (API-only, not available in console)
    vpcConfig={
        "subnetIds": ["subnet-abc123"],
        "securityGroupIds": ["sg-xyz789"]
    }
)

job_arn = response["jobArn"]
print(f"Batch job submitted: {job_arn}")
```
_Source: [Create a batch inference job](https://docs.aws.amazon.com/bedrock/latest/userguide/batch-inference-create.html) | [CreateModelInvocationJob API](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_CreateModelInvocationJob.html)_

**Minimal JSONL record (Converse format):**

```jsonl
{"recordId": "rec-001", "modelInput": {"messages": [{"role": "user", "content": [{"text": "Summarize: The quick brown fox..."}]}]}}
{"recordId": "rec-002", "modelInput": {"messages": [{"role": "user", "content": [{"text": "Classify the sentiment of: I love this product!"}]}]}}
```
_Source: [Process multiple prompts with batch inference](https://docs.aws.amazon.com/bedrock/latest/userguide/batch-inference.html)_

### Configuration reference (Batch) {#configuration-reference-batch}

| Field | Required | Description |
|---|---|---|
| `jobName` | Yes | Name for the batch job |
| `roleArn` | Yes | IAM service role ARN with S3 read/write and `bedrock:InvokeModel` permissions |
| `modelId` | Yes | Model ID, cross-region inference profile ID, or foundation model ARN |
| `modelInvocationType` | No | `InvokeModel` (default) or `Converse` |
| `inputDataConfig.s3InputDataConfig.s3Uri` | Yes | S3 prefix or file path to JSONL input |
| `outputDataConfig.s3OutputDataConfig.s3Uri` | Yes | S3 prefix for output files |
| `outputDataConfig.s3OutputDataConfig.s3EncryptionKmsKeyId` | No | KMS CMK ARN for output encryption |
| `timeoutDurationInHours` | No | Abort the job after this many hours. Enforced range: Minimum 24, Maximum 168 |
| `vpcConfig.subnetIds` | No | VPC subnets for network isolation (API-only) |
| `vpcConfig.securityGroupIds` | No | Security groups for VPC isolation (API-only) |
| `clientRequestToken` | No | Idempotency token |

_Source: [CreateModelInvocationJob API Reference](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_CreateModelInvocationJob.html)_

### Gotchas (Batch) {#gotchas-batch}

- **No tool calling or structured output.** Each JSONL record is fully self-contained — there is no back-and-forth between the model and the calling application. Any agent logic that relies on tool invocations cannot be expressed in a batch job.
- **Prompt caching is not supported.** Do not attempt to embed cache checkpoints in batch JSONL records — they will be ignored or cause errors. If prompt caching is important for your offline pipeline, consider using streaming inference in a worker fleet instead.
- **Not for provisioned models.** The `modelId` must be a foundation model ID or a cross-region inference profile. Custom models with Provisioned Throughput cannot be used for batch inference.
- **Cross-account S3 buckets require API submission.** You cannot submit a batch job via the console if the input or output S3 bucket belongs to a different AWS account.
- **VPC configuration is API-only.** The console does not expose `vpcConfig`. Use boto3, the AWS CLI, or CloudFormation/CDK to set it.
- **EventBridge, not polling.** Polling `GetModelInvocationJob` in a loop wastes resources and can hit API rate limits. Use EventBridge events for job completion notifications.

---

## 3. Fine-tuning and Custom Models

**Maturity: GA**

_Source: [Customize your model to improve its performance for your use case](https://docs.aws.amazon.com/bedrock/latest/userguide/custom-models.html)_

Amazon Bedrock supports four model customization methods:

| Method | Data type | Use case |
|---|---|---|
| **Supervised fine-tuning** | Labeled input-output pairs (JSONL) | Improve task-specific accuracy (classification, extraction, custom tone) |
| **Continued pre-training** | Unlabeled domain text | Inject domain vocabulary and knowledge |
| **Distillation** | Prompts (teacher generates responses) | Transfer large-model quality to a smaller, cheaper student model |
| **Reinforcement fine-tuning** | Prompts + Lambda reward functions | Align model behavior via iterative feedback |

_Source: [Customize your model to improve its performance for your use case](https://docs.aws.amazon.com/bedrock/latest/userguide/custom-models.html)_

**Critical constraint:** To run inference on any custom model, you **must purchase Provisioned Throughput**. On-demand pricing is not available for custom models.

_Source: [Custom models](https://docs.aws.amazon.com/help-panel/bedrock/latest/console/hp-custom-models.html) | [Purchase Provisioned Throughput for a custom model](https://docs.aws.amazon.com/bedrock/latest/userguide/custom-model-use-pt.html)_

### When to use (Fine-tuning) {#when-to-use-fine-tuning}

Fine-tuning is appropriate when:
- The base model does not achieve acceptable accuracy on your specific task despite prompt engineering.
- You have a sufficient volume of high-quality labeled examples (typically hundreds to thousands of pairs).
- You are willing to pay the one-time training cost and ongoing Provisioned Throughput hourly commitment.

Prefer prompt engineering, few-shot examples, or RAG (see [`bedrock.md`](./bedrock.md)) before committing to fine-tuning. Use Distillation when you want a smaller/cheaper model but have a larger model that already performs well.

For Provisioned Throughput IaC, see [`deployment-iac.md`](./deployment-iac.md). For cost governance of Provisioned Throughput commitments, see [`security-iam-cost.md`](./security-iam-cost.md).

### Best practices (Fine-tuning) {#best-practices-fine-tuning}

- **Encrypt custom model artifacts with a KMS CMK.** Specify `customModelKmsKeyId` in `CreateModelCustomizationJob`. Training data is not stored by Bedrock after the job completes and is never used for other purposes.
  _Source: [Encryption of custom models](https://docs.aws.amazon.com/bedrock/latest/userguide/encryption-custom-job.html)_

- **Store training data in S3 with SSE-KMS** to maintain an encrypted chain from training data through the custom model artifact.
  _Source: [Data encryption](https://docs.aws.amazon.com/bedrock/latest/userguide/data-encryption.html)_

- **Use validation data** (`validationDataConfig`) in `CreateModelCustomizationJob`. Bedrock returns validation loss metrics after the job completes, which you should track to detect overfitting.
  _Source: [create_model_customization_job](https://docs.aws.amazon.com/boto3/latest/reference/services/bedrock/client/create_model_customization_job.html)_

- **Evaluate cost before committing to a term.** Provisioned Throughput offers no-commitment, 1-month, and 6-month tiers — longer commitments reduce the hourly price. Contact your AWS account manager for exact MU pricing, as it varies by model and is not published in the public pricing page.
  _Source: [Increase model invocation capacity with Provisioned Throughput in Amazon Bedrock](https://docs.aws.amazon.com/bedrock/latest/userguide/prov-throughput.html)_

- **Purchase Provisioned Throughput via `CreateProvisionedModelThroughput`** with the custom model ARN as `modelId`. The response returns a `provisionedModelArn` — use this as the `modelId` in `InvokeModel` / `Converse` requests.
  _Source: [Purchase Provisioned Throughput for a custom model](https://docs.aws.amazon.com/bedrock/latest/userguide/custom-model-use-pt.html)_

- **Consider distillation** when cost is the primary driver. Use a large capable teacher model (e.g., Claude Sonnet) to generate synthetic training data for a student model (e.g., Claude Haiku). Bedrock automates the synthesis — you provide prompts.
  _Source: [Customize a model with distillation in Amazon Bedrock](https://docs.aws.amazon.com/bedrock/latest/userguide/model-distillation.html)_

### Configuration reference (Fine-tuning) {#configuration-reference-fine-tuning}

| Field | Description |
|---|---|
| `baseModelIdentifier` | Foundation model ARN to fine-tune from |
| `customizationType` | `FINE_TUNING`, `CONTINUED_PRE_TRAINING`, `DISTILLATION`, or `REINFORCED_FINE_TUNING` |
| `trainingDataConfig.s3Uri` | S3 path to training JSONL |
| `validationDataConfig.validators[].s3Uri` | S3 path to validation JSONL (recommended) |
| `outputDataConfig.s3Uri` | S3 path for output custom model artifacts |
| `roleArn` | IAM role with S3 and KMS permissions |
| `customModelKmsKeyId` | KMS CMK ARN to encrypt the custom model at rest |
| `hyperParameters` | Training hyperparameters (epochs, learning rate, batch size) — model-specific |
| `vpcConfig` | Optional VPC subnets and security groups for isolation |

_Source: [create_model_customization_job](https://docs.aws.amazon.com/boto3/latest/reference/services/bedrock/client/create_model_customization_job.html)_

**Provisioned Throughput fields:**

| Field | Description |
|---|---|
| `modelUnits` | Number of MUs to purchase |
| `modelId` | Custom model name or ARN |
| `provisionedModelName` | Name for the provisioned throughput resource |
| `commitmentDuration` | `OneMonth` \| `SixMonths`. Omit this field entirely for no-commitment Provisioned Throughput |

_Source: [CreateProvisionedModelThroughput API](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_CreateProvisionedModelThroughput.html)_

### Gotchas (Fine-tuning) {#gotchas-fine-tuning}

- **Provisioned Throughput billing continues until you explicitly delete it** — even if you make zero inference calls. Set a budget alarm on the Provisioned Throughput resource. See [`security-iam-cost.md`](./security-iam-cost.md).
- **No-commitment PT can be deleted anytime but costs more per hour.** Commit terms lock you in — estimate your inference volume carefully before selecting a term.
- **Distillation incurs teacher model inference charges** in addition to the training job cost — Bedrock calls the teacher model to generate synthetic data from your prompts.
  _Source: [Customize a model with distillation in Amazon Bedrock](https://docs.aws.amazon.com/bedrock/latest/userguide/model-distillation.html)_
- **Batch inference does not support custom models** via on-demand paths. If you have a custom model, use Provisioned Throughput for online inference only.
- **Model training cost = tokens × epochs.** Large training sets with many epochs can produce unexpectedly large training bills. Always validate hyperparameters on a small subset first.

---

## 4. Data Residency Checklist

**Maturity: GA**

Data residency on Bedrock is achieved through a combination of four controls: geo-scoped inference profiles, KMS CMKs, VPC PrivateLink, and service control policies. This section is a concise checklist — for IAM/SCP details, see [`security-iam-cost.md`](./security-iam-cost.md).

### Geo-scoped inference profiles

Geographic cross-Region inference routes requests across AWS Regions **within a defined geographic boundary** (US, EU, APAC) while keeping data stored only in the source Region. Input prompts and output results may traverse Regions within the geography over Amazon's encrypted network.

_Source: [Geographic cross-Region inference](https://docs.aws.amazon.com/bedrock/latest/userguide/geographic-cross-region-inference.html)_

Three profile scopes are available:

| Scope | Geo boundary | ID prefix example | Notes |
|---|---|---|---|
| Geographic (US) | US Regions only | `us.anthropic.claude-...` | Available for all current Claude models |
| Geographic (EU) | EU Regions only | `eu.anthropic.claude-...` | Available for all current Claude models |
| Geographic (APAC) | APAC Regions only | `apac.anthropic.claude-...` | Used by Claude Sonnet 4; superseded by `au.` and `jp.` for Claude 4.5+ |
| Geographic (AU) | Australia/Pacific Regions | `au.anthropic.claude-...` | Claude 4.5 and newer; separate boundary from `apac.` |
| Geographic (JP) | Japan Regions | `jp.anthropic.claude-...` | Claude 4.5 and newer; separate boundary from `apac.` |
| Global | All commercial Regions | `global.anthropic.claude-...` | Currently Claude Sonnet 4/4.5+ in select source Regions; destination Regions can expand |

_Source: [Supported Regions and models for inference profiles](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-profiles-support.html)_

> Use **Geo profiles** (not Global) when you have a data residency requirement. Global profiles may route to any commercial Region.

### Best practices (Data Residency) {#best-practices-data-residency}

- **Use Geo inference profiles for data-residency compliance.** The destination Region list of a Geo profile is fixed and never changes. Global inference profiles can have their destination Regions expanded by AWS.
  _Source: [Supported Regions and models for inference profiles](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-profiles-support.html)_

- **Check model-region availability before designing your architecture.** Not every model is available in every geo profile. Visit the model's detail page in the Bedrock console or use `GetInferenceProfile` — do not rely on static lists in docs as model availability changes.
  _Source: [Supported Regions and models for inference profiles](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-profiles-support.html)_

- **Update SCPs to allow all destination Regions in the Geo profile.** If an SCP restricts unused Regions, it must explicitly allow all Regions in the inference profile's destination list — blocking even one destination Region causes cross-Region inference to fail.
  _Source: [Geographic cross-Region inference](https://docs.aws.amazon.com/bedrock/latest/userguide/geographic-cross-region-inference.html)_

- **Encrypt data at rest with a KMS CMK.** Apply CMK encryption to:
  - Custom model artifacts via `customModelKmsKeyId` in `CreateModelCustomizationJob`
  - Bedrock Agents via `customerEncryptionKeyArn` in `CreateAgent`
  - Knowledge Base data sources via `kmsKeyArn` in `CreateDataSource`
  - Batch inference S3 output via `s3EncryptionKmsKeyId`
  - S3 training/validation data via SSE-KMS on the bucket

  _Source: [Data encryption](https://docs.aws.amazon.com/bedrock/latest/userguide/data-encryption.html)_

- **Deploy VPC PrivateLink endpoints** to eliminate internet exposure for all Bedrock API calls. Five endpoint service names are required for full coverage: `bedrock`, `bedrock-runtime`, `bedrock-mantle`, `bedrock-agent`, and `bedrock-agent-runtime`.
  _Source: [Use interface VPC endpoints (AWS PrivateLink) to create a private connection between your VPC and Amazon Bedrock](https://docs.aws.amazon.com/bedrock/latest/userguide/vpc-interface-endpoints.html)_

- **Enable private DNS** on all VPC endpoints. With private DNS enabled, standard SDK/CLI calls (e.g., `bedrock-runtime.us-east-1.amazonaws.com`) automatically route through the VPC endpoint — no code changes required.
  _Source: [Use interface VPC endpoints (AWS PrivateLink) to create a private connection between your VPC and Amazon Bedrock](https://docs.aws.amazon.com/bedrock/latest/userguide/vpc-interface-endpoints.html)_

- **Use FIPS endpoints** if your workload requires FIPS 140-2 compliance. FIPS endpoint services (`bedrock-fips`, `bedrock-runtime-fips`) are available in us-east-1, us-east-2, us-west-2, ca-central-1, us-gov-east-1, and us-gov-west-1.
  _Source: [Use interface VPC endpoints (AWS PrivateLink) to create a private connection between your VPC and Amazon Bedrock](https://docs.aws.amazon.com/bedrock/latest/userguide/vpc-interface-endpoints.html)_

- **Use `bedrock:InferenceProfileArn` condition in IAM policies** to restrict which inference profiles a principal can use. This prevents accidentally using a Global profile when only a Geo profile is allowed.
  _Source: [Geographic cross-Region inference](https://docs.aws.amazon.com/bedrock/latest/userguide/geographic-cross-region-inference.html)_

### Code (Data Residency) {#code-data-residency}

**IAM policy for Geo cross-Region inference (EU boundary example):**

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowEUGeoInferenceProfile",
      "Effect": "Allow",
      "Action": "bedrock:InvokeModel",
      "Resource": "arn:aws:bedrock:eu-west-1:123456789012:inference-profile/eu.anthropic.claude-3-5-sonnet-20241022-v2:0"
    },
    {
      "Sid": "AllowFoundationModelInEURegions",
      "Effect": "Allow",
      "Action": "bedrock:InvokeModel",
      "Resource": [
        "arn:aws:bedrock:eu-west-1::foundation-model/anthropic.claude-3-5-sonnet-20241022-v2:0",
        "arn:aws:bedrock:eu-central-1::foundation-model/anthropic.claude-3-5-sonnet-20241022-v2:0",
        "arn:aws:bedrock:eu-west-3::foundation-model/anthropic.claude-3-5-sonnet-20241022-v2:0"
      ],
      "Condition": {
        "StringEquals": {
          "bedrock:InferenceProfileArn": "arn:aws:bedrock:eu-west-1:123456789012:inference-profile/eu.anthropic.claude-3-5-sonnet-20241022-v2:0"
        }
      }
    }
  ]
}
```
_Source: [Geographic cross-Region inference](https://docs.aws.amazon.com/bedrock/latest/userguide/geographic-cross-region-inference.html)_

**Python: Invoke with private DNS VPC endpoint (boto3):**

```python
import boto3

# With private DNS enabled — no endpoint_url override needed
# All traffic stays within VPC automatically
client = boto3.client("bedrock-runtime", region_name="eu-west-1")

response = client.converse(
    modelId="eu.anthropic.claude-3-5-sonnet-20241022-v2:0",  # EU Geo profile
    messages=[{"role": "user", "content": [{"text": "Hello from EU VPC"}]}]
)
```
_Source: [Use interface VPC endpoints (AWS PrivateLink)](https://docs.aws.amazon.com/bedrock/latest/userguide/vpc-interface-endpoints.html) | [Geographic cross-Region inference](https://docs.aws.amazon.com/bedrock/latest/userguide/geographic-cross-region-inference.html)_

**Python: Explicit VPC endpoint URL (private DNS not enabled):**

```python
import boto3

client = boto3.client(
    "bedrock-runtime",
    region_name="eu-west-1",
    endpoint_url="https://vpce-0abc123.bedrock-runtime.eu-west-1.vpce.amazonaws.com"
)
```
_Source: [Use interface VPC endpoints (AWS PrivateLink)](https://docs.aws.amazon.com/bedrock/latest/userguide/vpc-interface-endpoints.html)_

### Configuration reference (Data Residency) {#configuration-reference-data-residency}

| Control | How to configure | Notes |
|---|---|---|
| **Geo inference profile** | Use `us.*`, `eu.*`, `apac.*` (Claude Sonnet 4), `au.*`, or `jp.*` (Claude 4.5+) prefixed model ID as `modelId` | Fixed destination Regions; preferred over Global for residency. Check each model's detail page for supported prefixes |
| **Global inference profile** | Use `global.*` prefixed model ID | Currently available for Claude Sonnet 4 and Claude 4.5+; destination Regions can expand |
| **VPC PrivateLink — bedrock** | Create VPC interface endpoint: `com.amazonaws.{region}.bedrock` | Control plane API (CreateAgent, etc.) |
| **VPC PrivateLink — bedrock-runtime** | `com.amazonaws.{region}.bedrock-runtime` | InvokeModel, Converse |
| **VPC PrivateLink — bedrock-agent** | `com.amazonaws.{region}.bedrock-agent` | Agents build-time API |
| **VPC PrivateLink — bedrock-agent-runtime** | `com.amazonaws.{region}.bedrock-agent-runtime` | Agents runtime API |
| **VPC PrivateLink — bedrock-mantle** | `com.amazonaws.{region}.bedrock-mantle` | Project Mantle / OpenAI-compatible endpoints |
| **FIPS endpoints** | `com.amazonaws.{region}.bedrock-fips` / `bedrock-runtime-fips` | Only available in 6 Regions (see above) |
| **KMS CMK — custom models** | `customModelKmsKeyId` in `CreateModelCustomizationJob` | Encrypts model artifacts at rest |
| **KMS CMK — agents** | `customerEncryptionKeyArn` in `CreateAgent` | Encrypts agent configuration |
| **KMS CMK — knowledge bases** | `kmsKeyArn` in `CreateDataSource` | Encrypts data source ingestion jobs |
| **KMS CMK — batch output** | `s3EncryptionKmsKeyId` in batch `outputDataConfig` | Encrypts batch inference S3 output |
| **IAM condition** | `bedrock:InferenceProfileArn` in `Condition` block | Prevents use of unintended profile types |

_Source: [Data encryption](https://docs.aws.amazon.com/bedrock/latest/userguide/data-encryption.html) | [Use interface VPC endpoints](https://docs.aws.amazon.com/bedrock/latest/userguide/vpc-interface-endpoints.html) | [Geographic cross-Region inference](https://docs.aws.amazon.com/bedrock/latest/userguide/geographic-cross-region-inference.html)_

### Gotchas (Data Residency) {#gotchas-data-residency}

- **Prompts and outputs may cross Regions within a geo boundary.** Data is not pinned to a single Region during inference — it can traverse any Region within the Geo profile's destination list. If you require single-Region inference, use a base model ID (not an inference profile) and deploy in that Region only.
- **SCP misconfiguration is the most common failure mode.** If your SCP blocks `us-east-2` or `us-west-2` while you're using the US Geo profile from `us-east-1`, the cross-Region inference will fail. Test with a non-restricted IAM principal first.
- **Global inference profile destination Regions can expand.** If residency requires a fixed boundary, never use a Global inference profile — use a named Geo profile whose destination list is guaranteed not to change.
- **VPC PrivateLink does not prevent data from traversing Regions at the Bedrock layer.** PrivateLink keeps traffic off the public internet between your VPC and the Bedrock service endpoint, but cross-Region routing within Bedrock's internal network is a separate concern governed by the inference profile scope.
- **Missing one VPC endpoint breaks a specific API category.** For example, if you create `bedrock-runtime` but forget `bedrock-agent-runtime`, agent invocations will fail even though direct model invocations succeed. Create all five endpoints for full coverage.
- **Encryption at rest does not cover data in-transit between Regions.** All inter-Region transit is TLS 1.2 encrypted over Amazon's network, but you do not control the keys for in-transit data.

---

## Official sources

- [Understanding intelligent prompt routing in Amazon Bedrock](https://docs.aws.amazon.com/bedrock/latest/userguide/prompt-routing.html)
- [Amazon Bedrock Intelligent Prompt Routing is now generally available (April 2025)](https://aws.amazon.com/about-aws/whats-new/2025/04/amazon-bedrock-intelligent-prompt-routing-generally-available/)
- [CreatePromptRouter API Reference](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_CreatePromptRouter.html)
- [Process multiple prompts with batch inference](https://docs.aws.amazon.com/bedrock/latest/userguide/batch-inference.html)
- [Create a batch inference job](https://docs.aws.amazon.com/bedrock/latest/userguide/batch-inference-create.html)
- [Supported Regions and models for batch inference](https://docs.aws.amazon.com/bedrock/latest/userguide/batch-inference-supported.html)
- [CreateModelInvocationJob API Reference](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_CreateModelInvocationJob.html)
- [What's New — Batch inference for Claude Sonnet 4 and OpenAI GPT-OSS (August 2025)](https://aws.amazon.com/about-aws/whats-new/2025/08/amazon-bedrock-batch-inference-anthropic-claude-sonnet-4-openai-gpt-oss-models/)
- [Customize your model to improve its performance for your use case](https://docs.aws.amazon.com/bedrock/latest/userguide/custom-models.html)
- [Purchase Provisioned Throughput for a custom model](https://docs.aws.amazon.com/bedrock/latest/userguide/custom-model-use-pt.html)
- [Increase model invocation capacity with Provisioned Throughput in Amazon Bedrock](https://docs.aws.amazon.com/bedrock/latest/userguide/prov-throughput.html)
- [CreateProvisionedModelThroughput API Reference](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_CreateProvisionedModelThroughput.html)
- [Customize a model with distillation in Amazon Bedrock](https://docs.aws.amazon.com/bedrock/latest/userguide/model-distillation.html)
- [Encryption of custom models](https://docs.aws.amazon.com/bedrock/latest/userguide/encryption-custom-job.html)
- [create_model_customization_job (boto3)](https://docs.aws.amazon.com/boto3/latest/reference/services/bedrock/client/create_model_customization_job.html)
- [Geographic cross-Region inference](https://docs.aws.amazon.com/bedrock/latest/userguide/geographic-cross-region-inference.html)
- [Supported Regions and models for inference profiles](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-profiles-support.html)
- [Use interface VPC endpoints (AWS PrivateLink) to create a private connection between your VPC and Amazon Bedrock](https://docs.aws.amazon.com/bedrock/latest/userguide/vpc-interface-endpoints.html)
- [Data encryption](https://docs.aws.amazon.com/bedrock/latest/userguide/data-encryption.html)
- [Amazon Bedrock expands support for AWS PrivateLink — bedrock-mantle endpoint (February 2026)](https://aws.amazon.com/about-aws/whats-new/2026/02/amazon-bedrock-expands-aws-privatelink-support-openai-api-endpoints/)
