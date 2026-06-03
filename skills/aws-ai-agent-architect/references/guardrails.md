# Amazon Bedrock Guardrails

> Part of the **aws-ai-agent-architect** skill. See [SKILL.md](../SKILL.md) for the decision tree. Every source below is official — re-open it to verify details.

## Table of contents

- [Overview](#overview)
- [Key concepts](#key-concepts)
  - [Guardrail resource and versioning](#guardrail-resource-and-versioning)
  - [Content filters](#content-filters)
  - [Denied topics](#denied-topics)
  - [Word filters](#word-filters)
  - [Sensitive information filters (PII)](#sensitive-information-filters-pii)
  - [Contextual grounding check](#contextual-grounding-check)
  - [Automated reasoning checks](#automated-reasoning-checks)
  - [ApplyGuardrail API](#applyguardrail-api)
  - [Safeguard tiers (Classic vs Standard)](#safeguard-tiers-classic-vs-standard)
  - [Input tagging (InvokeModel only)](#input-tagging-invokemodel-only)
  - [DRAFT vs versioned guardrail](#draft-vs-versioned-guardrail)
  - [GuardrailConfiguration for Agents](#guardrailconfiguration-for-agents)
  - [PII in logs gotcha](#pii-in-logs-gotcha)
  - [Guardrail profiles (cross-region)](#guardrail-profiles-cross-region)
- [Best practices](#best-practices)
- [Code](#code)
  - [Create a comprehensive guardrail with all policy types (Python)](#create-a-comprehensive-guardrail-with-all-policy-types-python)
  - [ApplyGuardrail API — standalone evaluation, all outcome patterns](#applyguardrail-api--standalone-evaluation-all-outcome-patterns)
  - [Inline guardrail with Converse API](#inline-guardrail-with-converse-api)
  - [Contextual grounding check with ApplyGuardrail — RAG hallucination detection](#contextual-grounding-check-with-applyguardrail--rag-hallucination-detection)
  - [Associate guardrail with a Bedrock Agent via CreateAgent API](#associate-guardrail-with-a-bedrock-agent-via-createagent-api)
  - [IAM policy for creating and using guardrails](#iam-policy-for-creating-and-using-guardrails)
  - [CLI: apply guardrail and manage versions](#cli-apply-guardrail-and-manage-versions)
  - [Image content filter — create guardrail with inputModalities/outputModalities](#image-content-filter--create-guardrail-with-inputmodalitiesoutputmodalities)
- [Configuration reference](#configuration-reference)
- [Gotchas](#gotchas)
- [Official sources](#official-sources)

---

## Overview

Amazon Bedrock Guardrails is a GA service that lets you add customizable safeguards to any generative AI application built on Bedrock. It provides seven independently configurable policy types — content filters (text and image), denied topics, word filters, sensitive information filters (PII), contextual grounding checks, and automated reasoning checks — that evaluate both user inputs and model responses. Guardrails can be applied inline during model inference (`InvokeModel`, `Converse`) or as a standalone evaluation layer via the `ApplyGuardrail` API, decoupled from any foundation model. They integrate natively with Bedrock Agents, Knowledge Bases, and Flows by specifying a `guardrailConfiguration` field in the respective create/update API calls. Cross-region inference via named guardrail profiles (`us.guardrail.v1:0`, `eu.guardrail.v1:0`, etc.) is required for Standard tier and optional for throughput scaling.

**Maturity:** GA (Generally Available). All policy types are GA. Standard tier (higher accuracy, multilingual, code domain support) is GA and requires cross-Region inference to be enabled via a guardrail profile. Automated Reasoning checks are GA in 6 regions (us-east-1, us-west-2, us-east-2, eu-central-1, eu-west-3, eu-west-1) — English only, detect mode only (does not block content). Image content filters are GA in us-east-1, us-west-2, eu-central-1, ap-northeast-1; available in **preview** in us-east-2, ap-south-1, ap-northeast-2, ap-southeast-1, ap-southeast-2, eu-west-1, eu-west-2, and us-gov-west-1. Cross-account guardrail enforcements via AWS Organizations are GA.

---

## Key concepts

### Guardrail resource and versioning

A named resource (`guardrailId` + `guardrailArn`) containing one or more policy configurations. Always starts as a `DRAFT` version. You must call `CreateGuardrailVersion` to publish an immutable numbered version (e.g., `'1'`). During inference you reference either `'DRAFT'` or a numbered version string. A single account can have up to **100 guardrails per region**.

### Content filters

Six predefined harmful content categories: `HATE`, `INSULTS`, `SEXUAL`, `VIOLENCE`, `MISCONDUCT`, and `PROMPT_ATTACK`. Each can be configured independently for input and output with a filter strength of `NONE`, `LOW`, `MEDIUM`, or `HIGH`.

Content classification confidence levels: `NONE`, `LOW`, `MEDIUM`, `HIGH`. The filter blocks content whose confidence is >= the configured strength:
- `LOW` strength: blocks `HIGH`-confidence content only
- `MEDIUM` strength: blocks `HIGH` + `MEDIUM`-confidence content
- `HIGH` strength: blocks `HIGH` + `MEDIUM` + `LOW`-confidence content

Image content is supported via `inputModalities`/`outputModalities` fields (`['TEXT', 'IMAGE']`). `PROMPT_ATTACK` (jailbreak, prompt injection, prompt leakage) is **Standard tier only**. With Standard tier, detection extends to code elements (comments, variable names, string literals).

### Denied topics

Up to **30** custom topic definitions per guardrail. Each topic has:
- `name`: topic identifier
- `definition`: up to 200 chars (Classic tier) or up to 1,000 chars (Standard tier)
- `examples`: up to 5 representative phrases, each up to 100 chars
- `type`: must be `'DENY'` (only valid value)
- `inputAction` / `outputAction`: `BLOCK` or `NONE`, configurable independently per direction

Uses **semantic/NLU matching** — not keyword matching. In Standard tier, code-related content is also evaluated.

### Word filters

Exact-match blocking. Two sub-types:
- `managedWordListsConfig` with `type: 'PROFANITY'` — AWS-maintained, continuously updated profanity list
- `wordsConfig` — custom words/phrases; each entry limited to **3 words**; list can contain up to **10,000 entries**

Actions (`BLOCK` or `NONE`) are configurable per direction via `inputAction`/`outputAction`.

### Sensitive information filters (PII)

ML-based probabilistic detection of **30+ built-in PII entity types**:

`ADDRESS`, `AGE`, `NAME`, `EMAIL`, `PHONE`, `USERNAME`, `PASSWORD`, `DRIVER_ID`, `LICENSE_PLATE`, `VEHICLE_IDENTIFICATION_NUMBER`, `CREDIT_DEBIT_CARD_CVV`, `CREDIT_DEBIT_CARD_EXPIRY`, `CREDIT_DEBIT_CARD_NUMBER`, `PIN`, `INTERNATIONAL_BANK_ACCOUNT_NUMBER`, `SWIFT_CODE`, `IP_ADDRESS`, `MAC_ADDRESS`, `URL`, `AWS_ACCESS_KEY`, `AWS_SECRET_KEY`, `US_BANK_ACCOUNT_NUMBER`, `US_BANK_ROUTING_NUMBER`, `US_INDIVIDUAL_TAX_IDENTIFICATION_NUMBER`, `US_PASSPORT_NUMBER`, `US_SOCIAL_SECURITY_NUMBER`, `CA_HEALTH_NUMBER`, `CA_SOCIAL_INSURANCE_NUMBER`, `UK_NATIONAL_HEALTH_SERVICE_NUMBER`, `UK_NATIONAL_INSURANCE_NUMBER`, `UK_UNIQUE_TAXPAYER_REFERENCE_NUMBER`

Plus **custom regex patterns** (up to 30 per guardrail; 10 in me-central-1; max 500 chars each; no regex lookaround syntax).

Two actions per entity:
- `BLOCK` — reject the entire content block
- `ANONYMIZE` (also referred to as `MASK`) — replace detected value with a `{PII_TYPE}` token

Works in both natural language and code domains. Supports independent input/output configuration via `inputAction`/`outputAction`.

**Important:** does NOT detect PII in `tool_use` (function call) output parameters.

### Contextual grounding check

Detects hallucinations by scoring model responses for:
- **GROUNDING** — factual accuracy relative to source material
- **RELEVANCE** — whether the response answers the user query

Both scores are floats `0.0`–`1.0`. You configure a threshold (`0` to `0.99`) for each; responses with score below threshold are flagged/blocked.

Hard character limits per request:
- `grounding_source`: 100,000 chars
- `query`: 1,000 chars
- model response (content to guard): 5,000 chars

Requires three content components in the `ApplyGuardrail` call: `grounding_source`, `query`, and the unqualified response text. Supported use cases: summarization, paraphrasing, question answering. **Conversational QA/chatbot use cases are explicitly NOT supported.** When multiple `grounding_source` blocks are provided, they are combined and evaluated together.

**Important:** contextual grounding check runs ONLY on `source='OUTPUT'` — it never triggers on `source='INPUT'`.

### Automated reasoning checks

Uses formal mathematical logic to validate model responses against natural language policies you define.

- **GA regions:** us-east-1, us-west-2, us-east-2, eu-central-1, eu-west-3 (Paris), eu-west-1 (Ireland)
- **Language:** English (US) only
- **Mode:** DETECT ONLY — returns structured findings (`VALID`, `INVALID`, `TRANSLATION_AMBIGUOUS`, `TOO_COMPLEX`) and explanations but **never blocks content**
- Must be combined with other blocking policies for full protection
- Not supported in guardrail enforcements (cross-account via AWS Organizations)
- Requires 1–2 Automated Reasoning policy ARNs in `automatedReasoningPolicyConfig`
- No streaming support (`InvokeModelWithResponseStream`, `ConverseStream`)
- Supports: `Converse`, `InvokeModel`, `InvokeAgent`, `RetrieveAndGenerate`, and `ApplyGuardrail` APIs

### ApplyGuardrail API

Standalone guardrail evaluation endpoint (`bedrock-runtime` service):

```
POST /guardrail/{guardrailIdentifier}/version/{guardrailVersion}/apply
```

Decoupled from foundation model calls — useful for third-party LLMs, pre-processing pipelines, or when you want to evaluate content without invoking Bedrock FMs.

- `source` parameter: `INPUT` (user content) or `OUTPUT` (model response)
- Returns: `action` (`NONE` or `GUARDRAIL_INTERVENED`), `outputs` array, and detailed `assessments` per policy
- **When `action=NONE`, the `outputs` array is empty** — not a copy of the input

### Safeguard tiers (Classic vs Standard)

| Feature | Classic | Standard |
|---|---|---|
| Languages | English, French, Spanish | Extensive multilingual |
| Topic definition max | 200 chars | 1,000 chars |
| Code domain detection | No | Yes |
| Prompt leakage detection | No | Yes |
| PROMPT_ATTACK filter | No | Yes |
| Cross-region inference | Not required | **Required** |
| Accuracy | Baseline | Higher |

Standard tier requires `crossRegionConfig.guardrailProfileIdentifier` to be set.

### Input tagging (InvokeModel only)

For `InvokeModel` and `InvokeModelWithResponseStream` APIs **only**: use XML tags with pattern:

```
<amazon-bedrock-guardrails-guardContent_SUFFIX>...</amazon-bedrock-guardrails-guardContent_SUFFIX>
```

Set `tagSuffix` in the `amazon-bedrock-guardrailConfig` payload to evaluate only tagged sections. `PROMPT_ATTACK` filter **requires** input tags to be present to function.

Security note: always use a **random `tagSuffix` per request** to prevent prompt injection attacks (alphanumeric only, 1–20 chars).

For the Converse API, use the `qualifiers` field in `guardContent` blocks instead — the two mechanisms are not interchangeable.

### DRAFT vs versioned guardrail

Every guardrail starts as `DRAFT`. `DRAFT` can be modified at any time but is **mutable** — any change immediately affects all callers referencing it. Calling `CreateGuardrailVersion` publishes an **immutable** numbered version. Maximum **20 versions per guardrail**.

**In production: always reference a numbered version, never `DRAFT`.**

### GuardrailConfiguration for Agents

A two-field object included in `CreateAgent` / `UpdateAgent` request body:

```json
{
  "guardrailIdentifier": "abc123xyz",
  "guardrailVersion": "1"
}
```

The agent runtime applies the guardrail to user messages sent to the agent and responses returned from the agent. The guardrail is applied to user-facing input and output — **not** to intermediate internal orchestration steps.

### PII in logs gotcha

PII masking applies to API inputs/outputs only. If model invocation logging is enabled in CloudWatch, the `input` field in the logs **always contains the original unmasked request**. The trace object's `match` field in `GuardrailPiiEntityFilter` also returns the original PII value. Protect logs separately with CloudWatch log data protection.

### Guardrail profiles (cross-region)

System-defined resources that define geographic routing for guardrail inference. Data stays within the declared geographic boundary.

| Profile ID | Geographic boundary |
|---|---|
| `us.guardrail.v1:0` | US regions |
| `eu.guardrail.v1:0` | EU regions |
| `uk.guardrail.v1:0` | eu-west-2 only |
| `au.guardrail.v1:0` | ap-southeast-2 only |
| `ca.guardrail.v1:0` | ca-central-1, ca-west-1 |
| `apac.guardrail.v1:0` | APAC regions |
| `us-gov.guardrail.v1:0` | GovCloud |

Full ARN format (standard regions): `arn:aws:bedrock:{source-region}:{account-id}:guardrail-profile/{profile-id}`

Full ARN format (GovCloud): `arn:aws-us-gov:bedrock:{source-region}:{account-id}:guardrail-profile/us-gov.guardrail.v1:0`

_Source: https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-cross-region-support.html_

---

## Best practices

- **Use a numbered guardrail version in production, never DRAFT** — DRAFT is mutable; any edit immediately changes behavior for all callers. A numbered version (`CreateGuardrailVersion`) is immutable and provides stable, auditable behavior. Reference the version in all inference calls and agent configurations.
  _Source: https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-components.html_

- **Evaluate inputs early with ApplyGuardrail in RAG pipelines before retrieval** — checking user input before retrieval prevents wasted compute (and cost) on retrieval and generation for blocked queries. `ApplyGuardrail` is decoupled from FMs so it can be called independently at any point in the pipeline.
  _Source: https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-use-independent-api.html_

- **Use `inputEnabled`/`outputEnabled` and `inputAction`/`outputAction` independently for each policy** — different policies are appropriate for different directions (e.g., PII masking on output but blocking on input; prompt attack detection on input only). Fine-grained direction control reduces false positives and avoids over-blocking.
  _Source: https://docs.aws.amazon.com/bedrock/latest/APIReference/API_CreateGuardrail.html_

- **Set `outputScope=FULL` during development and testing** — by default `ApplyGuardrail` returns only detected (intervened) entries. With `FULL` scope you also receive non-detected entries, making it far easier to debug threshold calibration and confirm which categories are being evaluated.
  _Source: https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-use-independent-api.html_

- **Use random `tagSuffix` per request when using InvokeModel input tagging** — a static tag suffix allows a malicious user to close the XML tag via prompt injection and append content outside the guarded region. A random alphanumeric suffix (1–20 chars) per request makes the tag structure unpredictable.
  _Source: https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-tagging.html_

- **Use contextual grounding check thresholds between 0.5 and 0.8 as starting points, then tune** — a threshold of `0.99` blocks almost everything; `0.0` blocks nothing. The valid range is `0` to `0.99` (1.0 is invalid). Start at `0.7` for grounding and `0.5` for relevance in RAG applications, then adjust based on false positive rates from test runs.
  _Source: https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-contextual-grounding-check.html_

- **Do not use denied topics for individual word or entity blocking** — denied topics use NLU-based thematic matching, not keyword matching. Trying to block specific words or entities via topic definitions will be unreliable. Use word filters for exact-match terms and sensitive information filters for entity types.
  _Source: https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-denied-topics.html_

- **Use Standard tier for multilingual applications or code-heavy prompts** — Classic tier only supports English, French, and Spanish. Standard tier provides broader language coverage, better accuracy for prompt attack detection, support for code domain (comments, variable names), and prompt leakage detection. Requires cross-region inference configuration via a guardrail profile (e.g., `us.guardrail.v1:0`).
  _Source: https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-tiers.html_

- **Encrypt guardrails with a customer-managed KMS key in regulated environments** — by default guardrails are encrypted with an AWS-managed key. For compliance requirements (HIPAA, PCI-DSS), specify `kmsKeyId` in `CreateGuardrail` to use a customer-managed key, giving you key rotation control and audit via CloudTrail.
  _Source: https://docs.aws.amazon.com/bedrock/latest/APIReference/API_CreateGuardrail.html_

- **Protect invocation logs separately from guardrail PII masking** — PII masking in guardrails does NOT apply to CloudWatch invocation logs; the raw input is always logged. Use CloudWatch log data protection or disable model invocation logging if PII in logs is a compliance concern.
  _Source: https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-sensitive-filters.html_

- **Define denied topics with precise descriptive definitions, not instructions or negative definitions** — instructions ("block all content about X") and negative definitions ("everything except Y") reduce detection accuracy. Use concise topic descriptions of the content itself. Include 3–5 representative example phrases to improve accuracy.
  _Source: https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-denied-topics.html_

- **For ApplyGuardrail with contextual grounding, always pass all three content blocks: `grounding_source`, `query`, and the content to guard** — the grounding check requires all three components. Without the model response content block (the text to be evaluated), no grounding check is performed. Use the `qualifiers` field to mark each block's role.
  _Source: https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-contextual-grounding-check.html_

- **For cross-account enforcement, exclude automated reasoning policy from the guardrail** — Automated Reasoning checks are not supported in guardrail enforcements (AWS Organizations-level). Including an `automatedReasoningPolicyConfig` in a guardrail used for organization-level enforcement will cause runtime failures.
  _Source: https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-enforcements.html_

- **Combine Automated Reasoning checks with content filters and topic policies for full coverage** — Automated Reasoning checks operate in detect mode only and never block content. They also do not detect prompt injection or off-topic content. For full protection, always pair them with content filters (for injection detection) and topic policies (for off-topic detection).
  _Source: https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-automated-reasoning-checks.html_

- **Keep contextual grounding responses under 5,000 characters** — the grounding check enforces hard limits of 5,000 characters for the model response, 1,000 characters for the query, and 100,000 characters for the grounding source. Exceeding these limits causes the check to fail.
  _Source: https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-contextual-grounding-check.html_

---

## Code

### Create a comprehensive guardrail with all policy types (Python)

```python
import boto3

bedrock = boto3.client('bedrock', region_name='us-east-1')

response = bedrock.create_guardrail(
    name='my-production-guardrail',
    description='Guardrail for customer-facing chatbot',
    blockedInputMessaging='I cannot process that request. Please rephrase your question.',  # max 500 chars
    blockedOutputsMessaging='I cannot provide that information.',                             # max 500 chars

    # Content filters — hate, insults, sexual, violence, misconduct, prompt_attack
    # inputModalities/outputModalities enable image filtering per category (GA in select regions)
    contentPolicyConfig={
        'filtersConfig': [
            {
                'type': 'HATE',
                'inputStrength': 'HIGH',
                'outputStrength': 'HIGH',
                'inputAction': 'BLOCK',
                'outputAction': 'BLOCK',
                'inputEnabled': True,
                'outputEnabled': True,
                'inputModalities': ['TEXT', 'IMAGE'],
                'outputModalities': ['TEXT', 'IMAGE'],
            },
            {
                'type': 'INSULTS',
                'inputStrength': 'MEDIUM',
                'outputStrength': 'MEDIUM',
                'inputAction': 'BLOCK',
                'outputAction': 'BLOCK',
                'inputEnabled': True,
                'outputEnabled': True,
                'inputModalities': ['TEXT'],
                'outputModalities': ['TEXT'],
            },
            {
                'type': 'SEXUAL',
                'inputStrength': 'HIGH',
                'outputStrength': 'HIGH',
                'inputAction': 'BLOCK',
                'outputAction': 'BLOCK',
                'inputEnabled': True,
                'outputEnabled': True,
                'inputModalities': ['TEXT', 'IMAGE'],
                'outputModalities': ['TEXT', 'IMAGE'],
            },
            {
                'type': 'VIOLENCE',
                'inputStrength': 'MEDIUM',
                'outputStrength': 'MEDIUM',
                'inputAction': 'BLOCK',
                'outputAction': 'BLOCK',
                'inputEnabled': True,
                'outputEnabled': True,
                'inputModalities': ['TEXT', 'IMAGE'],
                'outputModalities': ['TEXT', 'IMAGE'],
            },
            {
                'type': 'MISCONDUCT',
                'inputStrength': 'MEDIUM',
                'outputStrength': 'MEDIUM',
                'inputAction': 'BLOCK',
                'outputAction': 'BLOCK',
                'inputEnabled': True,
                'outputEnabled': True,
                'inputModalities': ['TEXT'],
                'outputModalities': ['TEXT'],
            },
            {
                # PROMPT_ATTACK requires Standard tier; also requires input tags to function
                'type': 'PROMPT_ATTACK',
                'inputStrength': 'HIGH',
                'outputStrength': 'NONE',  # only meaningful on input
                'inputAction': 'BLOCK',
                'outputAction': 'NONE',
                'inputEnabled': True,
                'outputEnabled': False,
                'inputModalities': ['TEXT'],
                'outputModalities': ['TEXT'],
            },
        ],
        'tierConfig': {
            'tierName': 'STANDARD'  # or 'CLASSIC'
        }
    },

    # Denied topics — NLU semantic matching, up to 30 topics
    topicPolicyConfig={
        'topicsConfig': [
            {
                'name': 'InvestmentAdvice',
                # Standard tier: up to 1,000 chars. Classic tier: up to 200 chars.
                'definition': 'Inquiries, guidance, or recommendations about the management or allocation of funds or assets with the goal of generating returns or achieving financial objectives.',
                'examples': [
                    'Should I invest in gold?',
                    'Is it better to buy bonds or stocks?',
                ],
                'type': 'DENY',  # only valid value
                'inputAction': 'BLOCK',
                'inputEnabled': True,
                'outputAction': 'BLOCK',
                'outputEnabled': True,
            },
        ],
        'tierConfig': {'tierName': 'STANDARD'}
    },

    # Word filters — exact match, up to 10,000 entries, max 3 words per entry
    wordPolicyConfig={
        'managedWordListsConfig': [
            {
                'type': 'PROFANITY',
                'inputAction': 'BLOCK',
                'inputEnabled': True,
                'outputAction': 'BLOCK',
                'outputEnabled': True,
            }
        ],
        'wordsConfig': [
            {
                'text': 'competitor_name',  # max 3 words per entry
                'inputAction': 'BLOCK',
                'inputEnabled': True,
                'outputAction': 'BLOCK',
                'outputEnabled': True,
            },
        ]
    },

    # PII / sensitive information filters
    # Note: does not apply to tool_use (function call) output parameters
    sensitiveInformationPolicyConfig={
        'piiEntitiesConfig': [
            {'type': 'NAME',                       'action': 'ANONYMIZE', 'inputAction': 'ANONYMIZE', 'inputEnabled': True,  'outputAction': 'ANONYMIZE', 'outputEnabled': True},
            {'type': 'EMAIL',                      'action': 'ANONYMIZE', 'inputAction': 'ANONYMIZE', 'inputEnabled': True,  'outputAction': 'ANONYMIZE', 'outputEnabled': True},
            {'type': 'PHONE',                      'action': 'ANONYMIZE', 'inputAction': 'ANONYMIZE', 'inputEnabled': True,  'outputAction': 'ANONYMIZE', 'outputEnabled': True},
            {'type': 'US_SOCIAL_SECURITY_NUMBER',  'action': 'BLOCK',     'inputAction': 'BLOCK',     'inputEnabled': True,  'outputAction': 'BLOCK',     'outputEnabled': True},
            {'type': 'CREDIT_DEBIT_CARD_NUMBER',   'action': 'BLOCK',     'inputAction': 'BLOCK',     'inputEnabled': True,  'outputAction': 'BLOCK',     'outputEnabled': True},
            {'type': 'AWS_ACCESS_KEY',             'action': 'BLOCK',     'inputAction': 'BLOCK',     'inputEnabled': True,  'outputAction': 'BLOCK',     'outputEnabled': True},
            {'type': 'AWS_SECRET_KEY',             'action': 'BLOCK',     'inputAction': 'BLOCK',     'inputEnabled': True,  'outputAction': 'BLOCK',     'outputEnabled': True},
            {'type': 'PASSWORD',                   'action': 'BLOCK',     'inputAction': 'BLOCK',     'inputEnabled': True,  'outputAction': 'BLOCK',     'outputEnabled': True},
        ],
        'regexesConfig': [
            {
                'name': 'BookingID',
                'pattern': r'BK-[0-9]{8}',  # max 500 chars; no regex lookaround supported
                'action': 'ANONYMIZE',       # required legacy field; use inputAction/outputAction for per-direction control
                'description': 'Internal booking identifier',
                'inputAction': 'ANONYMIZE',
                'inputEnabled': True,
                'outputAction': 'ANONYMIZE',
                'outputEnabled': True,
            }
        ]
    },

    # Contextual grounding check
    # Limits: grounding_source 100,000 chars, query 1,000 chars, response 5,000 chars
    # Threshold range: 0.0 to 0.99 (1.0 is invalid)
    contextualGroundingPolicyConfig={
        'filtersConfig': [
            {'type': 'GROUNDING', 'threshold': 0.7, 'action': 'BLOCK', 'enabled': True},
            {'type': 'RELEVANCE', 'threshold': 0.5, 'action': 'BLOCK', 'enabled': True},
        ]
    },

    # Required for Standard tier; use the correct profile ID for your region
    # US: us.guardrail.v1:0  |  EU: eu.guardrail.v1:0  |  UK: uk.guardrail.v1:0
    # AU: au.guardrail.v1:0  |  CA: ca.guardrail.v1:0  |  APAC: apac.guardrail.v1:0
    # GovCloud: us-gov.guardrail.v1:0
    crossRegionConfig={
        'guardrailProfileIdentifier': 'us.guardrail.v1:0'
    },

    # Optional: customer-managed KMS encryption
    # kmsKeyId='arn:aws:kms:us-east-1:123456789012:key/your-key-id',

    # bedrock:TagResource permission required when passing tags
    tags=[{'key': 'Environment', 'value': 'production'}]
)

guardrail_id  = response['guardrailId']
guardrail_arn = response['guardrailArn']
print(f'Created guardrail: {guardrail_id} (version: {response["version"]})')  # version is always 'DRAFT'

# Publish an immutable version for production use (max 20 versions per guardrail)
version_response = bedrock.create_guardrail_version(
    guardrailIdentifier=guardrail_id,
    description='Initial production release'
)
production_version = version_response['version']  # e.g., '1'
print(f'Published version: {production_version}')
```

_Source: https://docs.aws.amazon.com/bedrock/latest/APIReference/API_CreateGuardrail.html_

---

### ApplyGuardrail API — standalone evaluation, all outcome patterns

```python
import boto3

bedrock_runtime = boto3.client('bedrock-runtime', region_name='us-east-1')

GUARDRAIL_ID      = 'abc123xyz'    # from CreateGuardrail response
GUARDRAIL_VERSION = '1'            # use numbered version in production; 'DRAFT' for testing

# --- Evaluate user input (before sending to model) ---
response = bedrock_runtime.apply_guardrail(
    guardrailIdentifier=GUARDRAIL_ID,
    guardrailVersion=GUARDRAIL_VERSION,
    source='INPUT',   # INPUT = user content; OUTPUT = model response
    content=[
        {
            'text': {
                'text': 'How should I invest my retirement savings to make $5,000/month?'
            }
        }
    ],
    # outputScope='FULL'  # default='INTERVENTIONS'; use 'FULL' for debugging to see non-detected entries
)

action = response['action']  # 'NONE' or 'GUARDRAIL_INTERVENED'

if action == 'GUARDRAIL_INTERVENED':
    # outputs contains the blocked/masked content to return to the user
    # IMPORTANT: when action=NONE, outputs array is EMPTY — always check action first
    blocked_message = response['outputs'][0]['text']
    print(f'Blocked. Message to user: {blocked_message}')

    # Inspect what triggered the intervention
    for assessment in response['assessments']:
        if 'topicPolicy' in assessment:
            for topic in assessment['topicPolicy']['topics']:
                print(f'Denied topic: {topic["name"]} — action: {topic["action"]}')
        if 'contentPolicy' in assessment:
            for f in assessment['contentPolicy']['filters']:
                print(f'Content filter: {f["type"]} confidence={f["confidence"]} action={f["action"]}')
        if 'sensitiveInformationPolicy' in assessment:
            for pii in assessment['sensitiveInformationPolicy']['piiEntities']:
                # match field returns ORIGINAL (unmasked) PII value — by design
                print(f'PII detected: type={pii["type"]} match={pii["match"]} action={pii["action"]}')
else:
    print('No guardrail intervention — proceed to model invocation')

# --- Evaluate model response (after receiving from model) ---
model_response_text = 'The best way to invest is to put everything in crypto.'
out_response = bedrock_runtime.apply_guardrail(
    guardrailIdentifier=GUARDRAIL_ID,
    guardrailVersion=GUARDRAIL_VERSION,
    source='OUTPUT',
    content=[{'text': {'text': model_response_text}}]
)
if out_response['action'] == 'GUARDRAIL_INTERVENED':
    final_text = out_response['outputs'][0]['text']
else:
    final_text = model_response_text  # outputs is empty when action=NONE
```

_Source: https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-use-independent-api.html_

---

### Inline guardrail with Converse API

```python
import boto3

bedrock_runtime = boto3.client('bedrock-runtime', region_name='us-east-1')

response = bedrock_runtime.converse(
    modelId='anthropic.claude-3-5-sonnet-20241022-v2:0',
    messages=[
        {
            'role': 'user',
            'content': [
                {'text': 'How should I invest my savings?'}
            ]
        }
    ],
    guardrailConfig={
        'guardrailIdentifier': 'abc123xyz',
        'guardrailVersion': '1',
        'trace': 'enabled'   # 'enabled' | 'enabled_full' | 'disabled'
    }
)

# The guardrail is automatically applied to both input and output.
# If intervention occurred, the output will contain the blocked message.
output_text = response['output']['message']['content'][0]['text']

# Check trace for guardrail details
# GuardrailTraceAssessment has: actionReason, inputAssessment, outputAssessments, modelOutput
# It does NOT have an 'action' field — check stopReason on the top-level response instead
if 'trace' in response:
    guardrail_trace = response['trace'].get('guardrail', {})
    action_reason = guardrail_trace.get('actionReason', '')
    print(f'Guardrail actionReason: {action_reason}')
# The authoritative intervention check is stopReason on the top-level response:
print(f'Stop reason: {response.get("stopReason", "")}')  # 'guardrail_intervened' if blocked
```

_Source: https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-use.html_

---

### Contextual grounding check with ApplyGuardrail — RAG hallucination detection

Limits: grounding source 100,000 chars, query 1,000 chars, response 5,000 chars.

```python
import boto3

bedrock_runtime = boto3.client('bedrock-runtime', region_name='us-east-1')

GUARDRAIL_ID      = 'abc123xyz'
GUARDRAIL_VERSION = '1'

# Retrieved RAG context (max 100,000 characters)
grounding_source = (
    'The monthly fee for a checking account is $10. '
    'There are no fees for opening a checking account. '
    'International wire transfers have a 1% transaction fee.'
)
# User query (max 1,000 characters)
user_query = 'What are the fees for a checking account?'
# Model response to guard (max 5,000 characters)
model_response = 'The monthly fee for a checking account is $10. There are no fees to open one.'

# Grounding check only runs when source='OUTPUT'
response = bedrock_runtime.apply_guardrail(
    guardrailIdentifier=GUARDRAIL_ID,
    guardrailVersion=GUARDRAIL_VERSION,
    source='OUTPUT',   # grounding check does NOT run on 'INPUT'
    content=[
        {
            'text': {
                'text': grounding_source,
                'qualifiers': ['grounding_source']   # marks this as the reference
            }
        },
        {
            'text': {
                'text': user_query,
                'qualifiers': ['query']              # marks this as the user question
            }
        },
        {
            'text': {
                'text': model_response               # no qualifier = content to guard (model response)
            }
        }
    ]
)

if response['action'] == 'GUARDRAIL_INTERVENED':
    print('Response blocked as hallucination or irrelevant')
    for assessment in response['assessments']:
        if 'contextualGroundingPolicy' in assessment:
            for f in assessment['contextualGroundingPolicy']['filters']:
                print(f"  type={f['type']} score={f['score']:.2f} threshold={f['threshold']} action={f['action']}")
else:
    print('Response passed grounding check')
```

_Source: https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-contextual-grounding-check.html_

---

### Associate guardrail with a Bedrock Agent via CreateAgent API

```python
import boto3

bedrock_agent = boto3.client('bedrock-agent', region_name='us-east-1')

# When creating an agent, add guardrailConfiguration
# The guardrail is applied to user-facing inputs and outputs;
# internal orchestration intermediate steps are not separately guarded
response = bedrock_agent.create_agent(
    agentName='customer-support-agent',
    foundationModel='anthropic.claude-3-5-sonnet-20241022-v2:0',
    agentResourceRoleArn='arn:aws:iam::123456789012:role/BedrockAgentRole',
    instruction='You are a helpful customer support assistant for a banking application.',
    guardrailConfiguration={
        'guardrailIdentifier': 'abc123xyz',
        'guardrailVersion': '1'   # use numbered version in production
    },
    description='Customer support agent with safety guardrails'
)

agent_id = response['agent']['agentId']
print(f'Agent created: {agent_id}')

# Update existing agent to change guardrail version
bedrock_agent.update_agent(
    agentId=agent_id,
    agentName='customer-support-agent',
    foundationModel='anthropic.claude-3-5-sonnet-20241022-v2:0',
    agentResourceRoleArn='arn:aws:iam::123456789012:role/BedrockAgentRole',
    instruction='You are a helpful customer support assistant for a banking application.',
    guardrailConfiguration={
        'guardrailIdentifier': 'abc123xyz',
        'guardrailVersion': '2'   # bump to new guardrail version
    }
)
```

_Source: https://docs.aws.amazon.com/bedrock/latest/APIReference/API_agent_CreateAgent.html_

---

### IAM policy for creating and using guardrails

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "CreateAndManageGuardrails",
      "Effect": "Allow",
      "Action": [
        "bedrock:CreateGuardrail",
        "bedrock:CreateGuardrailVersion",
        "bedrock:DeleteGuardrail",
        "bedrock:GetGuardrail",
        "bedrock:ListGuardrails",
        "bedrock:UpdateGuardrail"
      ],
      "Resource": "*"
    },
    {
      "Sid": "TagGuardrailsRequiredSeparatelyOmittingCausesAccessDeniedException",
      "Effect": "Allow",
      "Action": [
        "bedrock:TagResource"
      ],
      "Resource": "*"
    },
    {
      "Sid": "ApplyGuardrailOnlyCanBeScopedToSpecificGuardrailARN",
      "Effect": "Allow",
      "Action": [
        "bedrock:ApplyGuardrail"
      ],
      "Resource": "arn:aws:bedrock:us-east-1:123456789012:guardrail/abc123xyz"
    },
    {
      "Sid": "InvokeModelWithGuardrailRequiredForInlineGuardrailsViaInvokeModelOrConverse",
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream"
      ],
      "Resource": "arn:aws:bedrock:us-east-1::foundation-model/*"
    }
  ]
}
```

_Source: https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-permissions.html_

---

### CLI: apply guardrail and manage versions

```bash
# Apply guardrail to evaluate user input
aws bedrock-runtime apply-guardrail \
    --guardrail-identifier 'abc123xyz' \
    --guardrail-version '1' \
    --source 'INPUT' \
    --content '[{"text":{"text":"How should I invest for retirement?"}}]' \
    --region us-east-1 \
    --output json

# Get guardrail details
aws bedrock get-guardrail \
    --guardrail-identifier 'abc123xyz' \
    --guardrail-version '1' \
    --region us-east-1

# List all guardrails
aws bedrock list-guardrails --region us-east-1

# Create a new immutable version (max 20 versions per guardrail)
aws bedrock create-guardrail-version \
    --guardrail-identifier 'abc123xyz' \
    --description 'v2 — added competitor word filter' \
    --region us-east-1
```

_Source: https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-use-independent-api.html_

---

### Image content filter — create guardrail with inputModalities/outputModalities

GA in us-east-1, us-west-2, eu-central-1, ap-northeast-1. Preview in additional regions.

```python
import boto3
import json

bedrock = boto3.client('bedrock', region_name='us-east-1')

response = bedrock.create_guardrail(
    name='my-image-guardrail',
    blockedInputMessaging='Sorry, the model cannot answer this question.',
    blockedOutputsMessaging='Sorry, the model cannot answer this question.',
    contentPolicyConfig={
        'filtersConfig': [
            {
                'type': 'SEXUAL',
                'inputStrength': 'HIGH',
                'outputStrength': 'HIGH',
                'inputModalities': ['TEXT', 'IMAGE'],
                'outputModalities': ['TEXT', 'IMAGE']
            },
            {
                'type': 'VIOLENCE',
                'inputStrength': 'HIGH',
                'outputStrength': 'HIGH',
                'inputModalities': ['TEXT', 'IMAGE'],
                'outputModalities': ['TEXT', 'IMAGE']
            },
            {
                'type': 'HATE',
                'inputStrength': 'HIGH',
                'outputStrength': 'HIGH',
                'inputModalities': ['TEXT', 'IMAGE'],
                'outputModalities': ['TEXT', 'IMAGE']
            },
            {
                'type': 'MISCONDUCT',
                'inputStrength': 'HIGH',
                'outputStrength': 'HIGH',
                # MISCONDUCT image category not listed in GA regions; text only
                'inputModalities': ['TEXT'],
                'outputModalities': ['TEXT']
            },
            {
                # PROMPT_ATTACK: text only; requires input tagging to function
                'type': 'PROMPT_ATTACK',
                'inputStrength': 'HIGH',
                'outputStrength': 'NONE',
                'inputModalities': ['TEXT'],
                'outputModalities': ['TEXT']
            }
        ]
    }
)
print(json.dumps(
    {k: str(v) if not isinstance(v, str) else v for k, v in response.items()},
    indent=2
))
```

_Source: https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-mmfilter.html_

---

## Configuration reference

| Name | Description | Default / example |
|---|---|---|
| `guardrailIdentifier` (URI / request param) | ID (e.g., `'abc123xyz'`) or full ARN of the guardrail. Used in `ApplyGuardrail`, `GetGuardrail`, `CreateGuardrailVersion`, and in `guardrailConfig` for `Converse`/`InvokeModel`. Pattern: `[a-z0-9]+` (ID) or full ARN. | `arn:aws:bedrock:us-east-1:123456789012:guardrail/abc123xyz` |
| `guardrailVersion` | Either `'DRAFT'` (mutable working copy) or a numeric string `'1'`–`'99999999'` (immutable published version). Use `DRAFT` for development, numbered version in production. | `DRAFT` \| `1` \| `2` |
| `source` (ApplyGuardrail) | Required field in `ApplyGuardrail`. `'INPUT'` = content from the user (applies topic, content, word, PII policies). `'OUTPUT'` = content from the model (applies all policies including contextual grounding). Contextual grounding check runs ONLY on `OUTPUT`. | `INPUT` \| `OUTPUT` |
| `outputScope` (ApplyGuardrail) | Optional. `'INTERVENTIONS'` (default) returns only detected/intervened items. `'FULL'` returns all items including non-detected, for debugging. Does NOT apply to word filters or regex in sensitive info filters. | `INTERVENTIONS` |
| `contentPolicyConfig.filtersConfig[].inputStrength` / `outputStrength` | Filter sensitivity level per category. `NONE` = no filtering, `LOW` = block HIGH-confidence content only, `MEDIUM` = block HIGH+MEDIUM, `HIGH` = block HIGH+MEDIUM+LOW. Applies per content filter type independently. | `NONE` \| `LOW` \| `MEDIUM` \| `HIGH` |
| `contentPolicyConfig.filtersConfig[].inputModalities` / `outputModalities` | Array specifying which modalities to apply the filter to. Valid values: `['TEXT']`, `['IMAGE']`, or `['TEXT', 'IMAGE']`. Image support is GA in us-east-1, us-west-2, eu-central-1, ap-northeast-1; preview in additional regions. | `["TEXT", "IMAGE"]` |
| `topicPolicyConfig.topicsConfig[].type` | Must always be `'DENY'`. This is the only valid value. | `DENY` |
| `topicPolicyConfig.topicsConfig[].definition` | Natural language description of the topic. Classic tier: max 200 characters. Standard tier: max 1,000 characters. | `Investment advice is inquiries or recommendations about fund allocation to generate returns.` |
| `sensitiveInformationPolicyConfig.piiEntitiesConfig[].action` | Legacy single-action field. Use `inputAction`/`outputAction` for independent directional control. Valid values: `BLOCK` (reject entire content) or `ANONYMIZE` (mask with `{TYPE}` token). Does not apply to `tool_use` output parameters. | `BLOCK` \| `ANONYMIZE` |
| `contextualGroundingPolicyConfig.filtersConfig[].threshold` | Float `0.0` to `0.99` (`1.0` is invalid — throws `ValidationException`). Responses with score below this threshold are flagged/blocked. Higher = stricter. Limits: source 100,000 chars, query 1,000 chars, response 5,000 chars. | `0.7` |
| `crossRegionConfig.guardrailProfileIdentifier` | Required when using Standard tier. Profile ID or ARN. Available profile IDs: `us.guardrail.v1:0` (US), `eu.guardrail.v1:0` (EU), `uk.guardrail.v1:0` (eu-west-2 only), `au.guardrail.v1:0` (ap-southeast-2 only), `ca.guardrail.v1:0` (Canada), `apac.guardrail.v1:0` (APAC), `us-gov.guardrail.v1:0` (GovCloud). Data stays within the geographic boundary. | `us.guardrail.v1:0` |
| `crossRegionConfig.guardrailProfileIdentifier` (ARN format) | Full ARN format. Pattern: `arn:aws(-[^:]+)?:bedrock:[a-z0-9-]{1,20}:[0-9]{12}:guardrail-profile/[profile-id]`. Min 15 chars, max 2048 chars. | `arn:aws:bedrock:us-east-1:123456789012:guardrail-profile/us.guardrail.v1:0` |
| `automatedReasoningPolicyConfig.policies` | Array of 1–2 Automated Reasoning policy ARNs. Must attach versioned (immutable) policy ARNs. Operates in DETECT MODE ONLY and never blocks content. Not supported in guardrail enforcements. Policy IDs are **system-generated 12-char `[a-z0-9]` strings** (e.g., `lnq5hhz70wgk`) — you cannot choose them. | `arn:aws:bedrock:us-east-1:123456789012:automated-reasoning-policy/lnq5hhz70wgk:1` |
| `automatedReasoningPolicyConfig.confidenceThreshold` | Optional. Float `0.0`–`1.0`. Minimum confidence level for policy violations to trigger guardrail actions. | `0.8` |
| `blockedInputMessaging` | Message returned when the guardrail blocks a prompt. Min 1 char, max 500 chars. Required. | `I cannot process that request. Please rephrase your question.` |
| `blockedOutputsMessaging` | Message returned when the guardrail blocks a model response. Min 1 char, max 500 chars. Required. | `I cannot provide that information.` |
| `kmsKeyId` (CreateGuardrail) | Optional ARN or key ID of a customer-managed AWS KMS key to encrypt the guardrail. If omitted, uses AWS-managed key. | `arn:aws:kms:us-east-1:123456789012:key/mrk-xxxxxxxx` |
| `tagSuffix` (InvokeModel input tagging) | 1–20 alphanumeric characters set in `amazon-bedrock-guardrailConfig.tagSuffix`. Must match the suffix in XML tags `<amazon-bedrock-guardrails-guardContent_SUFFIX>`. Use a fresh random value per request. `PROMPT_ATTACK` filter requires input tags to be present. | `k9m2p7x1` |
| IAM: `bedrock:CreateGuardrail` | Required to create a new guardrail. Must be on `Resource: *`. | `Resource: *` |
| IAM: `bedrock:ApplyGuardrail` | Required to call `ApplyGuardrail` API or to use a guardrail with model inference. Can be scoped to a specific guardrail ARN. | `Resource: arn:aws:bedrock:REGION:ACCOUNT_ID:guardrail/GUARDRAIL_ID` |
| IAM: `bedrock:TagResource` | Required separately when passing tags in `CreateGuardrail`. Omitting this permission causes `AccessDeniedException` even if `bedrock:CreateGuardrail` is present. | `Resource: *` |
| Service quota: guardrails per account per region | Maximum 100 guardrails per AWS account per region. | `100` |
| Service quota: denied topics per guardrail | Maximum 30 topics per guardrail. | `30` |
| Service quota: custom words per word policy | Maximum 10,000 words/phrases in a single word policy list. Each entry up to 100 chars and max 3 words. | `10000` |
| Service quota: guardrail versions per guardrail | Maximum 20 published (immutable) versions per guardrail. | `20` |
| Service quota: regex entities in sensitive info filter | Maximum 30 custom regex patterns per guardrail (10 in me-central-1). Each regex up to 500 characters. No lookaround syntax supported. | `30` |
| Service quota: image content filter limits | Max 4 MB per image, max 20 images per request, max 8000x8000 pixels. Only PNG and JPEG formats supported. Default 25 images per second (not configurable). | `20 images, 4 MB each` |
| Service quota: ApplyGuardrail TPS | Default 100 TPS in us-east-1, us-west-2; 25 TPS in most other regions. Adjustable via AWS Service Quotas console. | `100 TPS (us-east-1)` |
| Control plane endpoint | Used for `CreateGuardrail`, `GetGuardrail`, `UpdateGuardrail`, etc. | `bedrock.us-east-1.amazonaws.com` |
| Runtime endpoint | Used for `ApplyGuardrail`, `InvokeModel`, `Converse` with guardrails. | `bedrock-runtime.us-east-1.amazonaws.com` |

---

## Gotchas

- **PII masking does NOT apply to CloudWatch model invocation logs.** The raw input is always logged unmasked. Separately enable CloudWatch log data protection if PII in logs is a compliance concern.

- **The trace object field `GuardrailPiiEntityFilter.match` returns the ORIGINAL PII value**, not the masked version. This is by design but can be a surprise when reading API responses.

- **When `action=NONE` in `ApplyGuardrail`, the `outputs` array is EMPTY** — not a copy of the input. Always check the `action` field first before accessing `outputs[0]`.

- **Contextual grounding check runs only on `OUTPUT`, not `INPUT`.** Setting `source='INPUT'` will not trigger grounding evaluation even if you include `grounding_source` and `query` blocks.

- **Contextual grounding `threshold=1.0` is invalid** and throws `ValidationException`. Valid range is `0.0` to `0.99`.

- **The correct Standard tier cross-region profile ID for US is `us.guardrail.v1:0`** (not `us.guardrail-standard-v1` or similar variants). Using a fictitious profile ID causes runtime failures.

- **Input tagging with XML tags (`amazon-bedrock-guardrails-guardContent_SUFFIX`) works ONLY with `InvokeModel` and `InvokeModelWithResponseStream` APIs.** For the Converse API, use the `qualifiers` field in `guardContent` blocks instead — the two mechanisms are not interchangeable.

- **`PROMPT_ATTACK` content filter requires Standard tier** — it is NOT available in Classic tier. Additionally, prompt attack detection REQUIRES input tags to be present to function; without input tagging, `PROMPT_ATTACK` has no effect.

- **A static `tagSuffix` in InvokeModel input tagging is a security vulnerability.** A malicious user can close the XML tag and inject unguarded content. Always use a random per-request `tagSuffix` (alphanumeric, 1–20 chars).

- **`CreateGuardrail` returns HTTP 202 (Accepted), not 200.** The guardrail is created asynchronously and starts in `CREATING` state before transitioning to `READY`.

- **Word filters are exact-match only** — no semantic matching, no wildcards. `'invest'` and `'investing'` are treated as different words and both must be explicitly added.

- **Custom words in word filters are limited to 3 words per entry.** Longer phrases cannot be added.

- **PII detection is probabilistic and context-dependent.** Single-word or short-phrase inputs dramatically reduce detection accuracy. Always send content with sufficient surrounding context.

- **Contextual grounding check does NOT support conversational QA/chatbot use cases.** It is designed for summarization, paraphrasing, and single-turn question answering.

- **The `bedrock:TagResource` permission is required separately when passing tags in `CreateGuardrail`.** Omitting it causes an `AccessDeniedException` even if the role has `bedrock:CreateGuardrail`.

- **Regex lookaround syntax (`(?=...)`, `(?<!...)`, etc.) is NOT supported** in custom regex patterns for sensitive information filters.

- **Contextual grounding check in streaming APIs evaluates the complete response after streaming finishes** — an irrelevant response may be streamed to the user before the check completes and marks it as blocked.

- **PII sensitive information filters do NOT detect PII in `tool_use` (function call) output parameters**, only in text inputs and model responses.

- **Automated Reasoning checks operate in DETECT MODE ONLY** — they return findings (`VALID`/`INVALID`/`TRANSLATION_AMBIGUOUS`/`TOO_COMPLEX`) but never block content. To block, you must implement blocking logic in your application based on the findings.

- **Automated Reasoning checks are NOT supported in guardrail enforcements (AWS Organizations cross-account).** Including `automatedReasoningPolicyConfig` in an enforcement guardrail causes runtime failures.

- **Automated Reasoning checks do not support streaming APIs** (`InvokeModelWithResponseStream`, `ConverseStream`). You must validate complete responses.

- **Contextual grounding limits are hard:** grounding source max 100,000 chars, query max 1,000 chars, response max 5,000 chars. Exceeding any of these causes the check to fail.

- **`blockedInputMessaging` and `blockedOutputsMessaging` have a hard maximum of 500 characters.** Longer messages cause a `ValidationException`.

- **When multiple `grounding_source` blocks are provided to `ApplyGuardrail`, they are combined and evaluated together** — they are not evaluated independently per block.

- **Image content filters are GA only in us-east-1, us-west-2, eu-central-1, ap-northeast-1.** In other listed regions they are in preview with fewer supported categories.

---

## Official sources

- [Detect and filter harmful content — Amazon Bedrock Guardrails overview](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails.html) — Entry point: lists all policy types, links to all sub-pages.
- [Create your guardrail — all filter types](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-components.html) — Overview of every configurable filter; confirms 7 policy types including automated reasoning.
- [Configure content filters](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-content-filters-overview.html) — Filter strength levels (None/Low/Medium/High) and confidence classification table.
- [Block denied topics](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-denied-topics.html) — How to define topics with name, definition, sample phrases; best-practice authoring rules.
- [Word filters](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-word-filters.html) — Profanity managed list and custom word/phrase configuration.
- [Sensitive information filters (PII)](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-sensitive-filters.html) — Full list of built-in PII types, block vs. mask modes, custom regex; important notes on log exposure.
- [Contextual grounding check](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-contextual-grounding-check.html) — Grounding and relevance scoring, threshold configuration (0 to 0.99), character limits, all three API integration patterns.
- [ApplyGuardrail API reference](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_ApplyGuardrail.html) — Full request/response schema, URI params, error codes.
- [Use the ApplyGuardrail API — usage guide with examples](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-use-independent-api.html) — Request/response examples for all three outcomes: no action, block, mask. CLI example included.
- [CreateGuardrail API reference](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_CreateGuardrail.html) — Full request syntax; `blockedInputMessaging`/`blockedOutputsMessaging` max 500 chars; response HTTP 202; version=DRAFT.
- [Use cases for Amazon Bedrock Guardrails](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-use.html) — Table mapping each integration point (inference, agents, KB, flows) to the correct API field.
- [Associate guardrail with Bedrock Agent](https://docs.aws.amazon.com/bedrock/latest/userguide/agents-guardrail.html) — `GuardrailConfiguration` field in `CreateAgent` / `UpdateAgent`.
- [IAM permissions for guardrails](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-permissions.html) — Exact IAM statements for create/manage and for invoke (`ApplyGuardrail` only needs `bedrock:ApplyGuardrail`).
- [Safeguard tiers (Classic vs Standard)](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-tiers.html) — Feature comparison table; Standard tier requires cross-region inference; lists 25+ supported regions.
- [Apply tags to user input (InvokeModel tagging)](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-tagging.html) — XML tag pattern for selective evaluation of prompt sections; security note on randomized tagSuffix.
- [Supported Regions for cross-Region guardrail inference](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-cross-region-support.html) — Complete list of guardrail profile IDs and ARNs per geographic boundary (US, EU, UK, AU, CA, APAC, US-GOV) with source/destination region mappings.
- [Distribute guardrail inference across AWS Regions](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-cross-region.html) — How cross-region guardrail inference works and how to configure it.
- [GuardrailCrossRegionConfig API reference](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_GuardrailCrossRegionConfig.html) — `guardrailProfileIdentifier` pattern: `[a-z0-9-]+[.]{1}guardrail[.]{1}v[0-9:]+` or full ARN; min 15, max 2048 chars.
- [What are Automated Reasoning checks in Amazon Bedrock Guardrails?](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-automated-reasoning-checks.html) — GA in 6 regions; English only; detect mode only (never blocks content); no streaming support.
- [Block harmful images with content filters](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-mmfilter.html) — Image content filter GA/preview regions, `inputModalities`/`outputModalities` API fields, limits (4 MB, 20 images, 8000x8000 px).
- [Apply cross-account safeguards with Amazon Bedrock Guardrails enforcements](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-enforcements.html) — Organization-level and account-level enforcement via AWS Organizations; automated reasoning policy NOT supported in enforcements.
- [Amazon Bedrock service quotas](https://docs.aws.amazon.com/general/latest/gr/bedrock.html) — All TPS limits and hard quotas for guardrails policies by region.
