# Deployment & IaC — AWS CDK (secondary)

> Part of the **aws-ai-agent-architect** skill. See [SKILL.md](../SKILL.md) for the decision tree. Every source below is official — re-open it to verify details.

## Table of contents

- [Overview](#overview)
- [Key concepts](#key-concepts)
- [Best practices](#best-practices)
- [Code](#code)
  - [Bedrock Agent base with Guardrail and content filter](#bedrock-agent-base-with-guardrail-and-content-filter)
  - [Action Group with type-safe FunctionSchema](#action-group-with-type-safe-functionschema)
  - [Agent Collaboration with SUPERVISOR\_ROUTER](#agent-collaboration-with-supervisor_router)
  - [Cross-Region Inference Profile with Agent](#cross-region-inference-profile-with-agent)
  - [VectorKnowledgeBase with @cdklabs (deprecated workaround)](#vectorknowledgebase-with-cdklabs-deprecated-workaround)
  - [CfnKnowledgeBase L1 with OpenSearch Serverless (stable path)](#cfnknowledgebase-l1-with-opensearch-serverless-stable-path)
  - [AgentCore Runtime with ECR and model invoke permission](#agentcore-runtime-with-ecr-and-model-invoke-permission)
  - [AgentCore Memory with built-in strategies](#agentcore-memory-with-built-in-strategies)
  - [AgentCore Gateway with Lambda target](#agentcore-gateway-with-lambda-target)
  - [PolicyEngine with Cedar and Gateway via L1 escape hatch](#policyengine-with-cedar-and-gateway-via-l1-escape-hatch)
- [Configuration reference](#configuration-reference)
- [Gotchas](#gotchas)
- [Official sources](#official-sources)
- [Verify live (open questions)](#verify-live-open-questions)

---

## Overview

CDK support for Amazon Bedrock and AgentCore is split across **four packages** at different maturity levels (verified June 2026):

| Package | Contents | Maturity |
|---|---|---|
| `aws-cdk-lib/aws_bedrock` | L1 (`CfnAgent`, `CfnKnowledgeBase`, `CfnDataSource`, `CfnGuardrail`) + factory L2 (`FoundationModel.fromFoundationModelId`, `ProvisionedModel.fromProvisionedModelArn`) | **GA** |
| `@aws-cdk/aws-bedrock-alpha` | `Agent`, `AgentAlias`, `AgentActionGroup`, `Guardrail`, `Prompt`, `ApplicationInferenceProfile`, `CrossRegionInferenceProfile`, `BedrockFoundationModel` | **Experimental** (no semver) |
| `aws-cdk-lib/aws_bedrockagentcore` | `Runtime`, `RuntimeEndpoint`, `Gateway`, `GatewayTarget`, `Browser`, `CodeInterpreter`, `Memory`, `OnlineEvaluation`, `WorkloadIdentity`, `OAuth2CredentialProvider`, `ApiKeyCredentialProvider` | **GA** |
| `@aws-cdk/aws-bedrock-agentcore-alpha` | `PolicyEngine`, `Policy`, `PolicyStatement`, `PolicyValidationMode`, `PolicyEngineMode` only | **Experimental** (no semver) |

**This is the secondary IaC path.** Terraform is primary — see `deployment-iac.md` for the primary path. Use CDK when the team already runs CDK stacks or when AgentCore constructs (which have no Terraform equivalents yet) are needed.

**Knowledge Base gap (as of June 2026):** `VectorKnowledgeBase` and `S3DataSource` L2 constructs do **not** exist in `@aws-cdk/aws-bedrock-alpha` (issue [aws/aws-cdk#36592](https://github.com/aws/aws-cdk/issues/36592), open since January 2026). The `Agent` construct in `@aws-cdk/aws-bedrock-alpha` has **no `knowledgeBases` prop**. Use `CfnKnowledgeBase` + `CfnDataSource` L1 (stable) or `@cdklabs/generative-ai-cdk-constructs` as a **deprecated** temporary workaround.

---

## Key concepts

### L1 vs L2 CDK for Bedrock

`aws-cdk-lib/aws_bedrock` contains exclusively L1 constructs (`CfnAgent`, `CfnKnowledgeBase`, `CfnDataSource`, `CfnGuardrail`, etc.) that map 1:1 to CloudFormation, plus factory utility L2s (`FoundationModel.fromFoundationModelId`, `ProvisionedModel.fromProvisionedModelArn`). The real high-level L2 constructs (`Agent`, `Guardrail`, `Prompt`, `InferenceProfile`) live in the **separate** package `@aws-cdk/aws-bedrock-alpha`, which is experimental and does not follow semver.

### @aws-cdk/aws-bedrock-alpha — verified current scope

Contains: `Agent`, `AgentAlias`, `AgentActionGroup`, `ApiSchema`, `FunctionSchema`, `Guardrail`, `Prompt`, `ApplicationInferenceProfile`, `CrossRegionInferenceProfile`, `BedrockFoundationModel` (class, not enum), `PromptOverrideConfiguration`, `Memory.sessionSummary` (agent session), `AgentCollaboration`.

Does **not** contain: Knowledge Base L2 (`VectorKnowledgeBase`, `S3DataSource`) — there is no `knowledgeBases` prop on `Agent`.

### AgentCollaboratorType — verified enum values

Confirmed values from the API reference: `SUPERVISOR` (supervisor agent using LLM routing), `SUPERVISOR_ROUTER` (supervisor with automatic low-latency routing), `DISABLED` (collaboration disabled). The value `PEER` does **not exist** in the CDK. The Agent Collaboration section of the README mentions "SUPERVISOR or PEER" in prose, but the actual enum has no `PEER` member — any code using `AgentCollaboratorType.PEER` will fail at compile time.

### Knowledge Base: L1 only in aws-cdk-lib

As of June 2026, `VectorKnowledgeBase` and `S3DataSource` L2 constructs do not exist in `@aws-cdk/aws-bedrock-alpha`. Feature request is open ([aws/aws-cdk#36592](https://github.com/aws/aws-cdk/issues/36592), January 2026). Workarounds: (a) `CfnKnowledgeBase` + `CfnDataSource` L1 — stable and correct; (b) `@cdklabs/generative-ai-cdk-constructs` — **deprecated**, functions but receives no further Bedrock updates.

### aws-cdk-lib/aws_bedrockagentcore — GA stable (updated Gateway API)

Stable module inside `aws-cdk-lib`. Constructs: `Runtime`, `RuntimeEndpoint`, `Gateway`, `GatewayTarget`, `Browser` (`BrowserCustom`), `CodeInterpreter` (`CodeInterpreterCustom`), `Memory`, `OnlineEvaluation`, `WorkloadIdentity`, `OAuth2CredentialProvider`, `ApiKeyCredentialProvider`.

`Gateway` uses dedicated methods for adding targets: `addLambdaTarget()`, `addOpenApiTarget()`, `addSmithyTarget()`, `addMcpServerTarget()`, `addApiGatewayTarget()`. Default inbound auth when `authorizerConfiguration` is not specified: Cognito M2M (automatic).

### @aws-cdk/aws-bedrock-agentcore-alpha — Policy only

After all other AgentCore constructs were promoted to stable, this alpha package retains only `PolicyEngine`, `Policy`, `PolicyStatement`, `PolicyValidationMode`, `PolicyEngineMode`. Connecting `PolicyEngine` (alpha) to `Gateway` (stable) requires the L1 escape hatch pattern documented officially on the aws-bedrock-agentcore-alpha page.

### BedrockFoundationModel — class with static members

This is a JavaScript/TypeScript class, **not** a TypeScript enum. Each model is a static member of type `BedrockFoundationModel`. Verified static members include: `ANTHROPIC_CLAUDE_HAIKU_V1_0`, `ANTHROPIC_CLAUDE_3_5_SONNET_V1_0`, `ANTHROPIC_CLAUDE_3_5_SONNET_V2_0`, `ANTHROPIC_CLAUDE_3_7_SONNET_V1_0`, `ANTHROPIC_CLAUDE_SONNET_4_5_V1_0`, `AMAZON_NOVA_LITE_V1`, `AMAZON_NOVA_PRO_V1`, `TITAN_EMBED_TEXT_V1`, `TITAN_EMBED_TEXT_V2_1024`, and others. Accepts `new BedrockFoundationModel('my-model-id')` for models not listed as static members.

### AgentCore Runtime — verified artifact types

Stable construct (`aws-cdk-lib/aws_bedrockagentcore.Runtime`). Factory methods for artifacts: `fromEcrRepository(repo, tag)`, `fromAsset(dockerfileDirPath)`, `fromS3({bucketName, objectKey}, runtime, entrypoint)`, `fromCodeAsset({path, runtime, entrypoint})`, `fromImageUri(uri)`. The `fromS3` and `fromCodeAsset` paths require a ZIP with Linux arm64 dependencies.

### AgentCore Memory — STM and LTM verified

Stable `Memory` construct in `aws-cdk-lib/aws_bedrockagentcore`. Props: `memoryName`, `expirationDuration` (7–365 days, default 90), `description`, `kmsKey`, `memoryStrategies`, `executionRole`, `tags`. Built-in factory methods for LTM: `MemoryStrategy.usingBuiltInSummarization()`, `usingBuiltInSemantic()`, `usingBuiltInUserPreference()`, `usingBuiltInEpisodic()`. LTM memories are extracted asynchronously.

---

## Best practices

- **Use `@aws-cdk/aws-bedrock-alpha` for `Agent`, `Guardrail`, `Prompt` — not the L1 `CfnAgent`/`CfnGuardrail` equivalents.** L2 constructs automatically handle IAM role creation, trust policies, draft preparation, and inter-resource dependencies. With L1 constructs all of this must be wired manually. _Source: https://docs.aws.amazon.com/cdk/api/v2/docs/aws-bedrock-alpha-readme.html_

- **Set `shouldPrepareAgent: true` when creating an `AgentAlias`.** Alias creation does not automatically prepare the agent. Without `shouldPrepareAgent: true` the DRAFT is not updated and the deploy can fail with an opaque version-not-updated error. _Source: https://docs.aws.amazon.com/cdk/api/v2/docs/aws-bedrock-alpha-readme.html_

- **Include `agent.lastUpdated` in the `AgentAlias` description to force a new version on every deploy.** Without this, redeploying after changes to the agent causes Bedrock to return errors because the version has not changed. The `lastUpdated?: string` property is present on the `Agent` object and changes with every modification. _Source: https://docs.aws.amazon.com/cdk/api/v2/docs/@aws-cdk_aws-bedrock-alpha.Agent.html_

- **For Knowledge Base use `CfnKnowledgeBase` L1 — do not attempt L2 constructs that do not yet exist in `aws-bedrock-alpha`.** As of June 2026, `aws-bedrock-alpha` has no `VectorKnowledgeBase` L2 and `Agent` has no `knowledgeBases` prop. L1 is the correct and stable choice. `@cdklabs/generative-ai-cdk-constructs` is a temporary workaround but is DEPRECATED. _Source: https://github.com/aws/aws-cdk/issues/36592_

- **For AgentCore use `aws-cdk-lib/aws_bedrockagentcore` (stable), NOT `@aws-cdk/aws-bedrock-agentcore-alpha` except for `PolicyEngine`.** All AgentCore constructs except Policy have been promoted to stable. Using the alpha package for already-stable constructs introduces unnecessary semver instability. _Source: https://docs.aws.amazon.com/cdk/api/v2/docs/aws-cdk-lib.aws_bedrockagentcore-readme.html_

- **To add targets to `Gateway` use the dedicated methods: `addLambdaTarget()`, `addOpenApiTarget()`, `addSmithyTarget()`, `addMcpServerTarget()`, `addApiGatewayTarget()`.** These methods eliminate the need to pass explicit gateway references and provide a fluent API. Using `GatewayTarget.fromLambdaFunction()` as a direct static call on gateway is not the recommended pattern. _Source: https://docs.aws.amazon.com/cdk/api/v2/docs/aws-cdk-lib.aws_bedrockagentcore-readme.html_

- **Add `iam:CreateServiceLinkedRole` to the CDK deployment role before deploying AgentCore stacks.** AgentCore creates a Service Linked Role on first deploy. Without this permission the first deploy fails with a non-obvious `AccessDenied` error. _Source: https://docs.aws.amazon.com/cdk/api/v2/docs/aws-cdk-lib.aws_bedrockagentcore-readme.html_

- **Use `PolicyEngineMode.LOG_ONLY` during development; switch to `ENFORCE` only after validation.** `LOG_ONLY` evaluates Cedar policies and adds trace output without blocking operations. This lets you test policies without interrupting traffic. _Source: https://docs.aws.amazon.com/cdk/api/v2/docs/aws-bedrock-agentcore-alpha-readme.html_

- **Use a KMS customer managed key with `enableKeyRotation: true` for `PolicyEngine` and `Memory` when handling sensitive data.** Once a KMS key is set on `PolicyEngine` it cannot be changed (requires replacement). If the key becomes inaccessible, all authorization decisions are automatically DENIED. _Source: https://docs.aws.amazon.com/cdk/api/v2/docs/aws-bedrock-agentcore-alpha-readme.html_

---

## Code

### Bedrock Agent base with Guardrail and content filter

```typescript
import * as bedrock from '@aws-cdk/aws-bedrock-alpha';
import { Duration } from 'aws-cdk-lib';

// Guardrail with content filter
const guardrail = new bedrock.Guardrail(this, 'bedrockGuardrails', {
  guardrailName: 'my-BedrockGuardrails',
  description: 'Legal ethical guardrails.',
});

guardrail.addContentFilter({
  type: bedrock.ContentFilterType.SEXUAL,
  inputStrength: bedrock.ContentFilterStrength.HIGH,
  outputStrength: bedrock.ContentFilterStrength.MEDIUM,
});

// Agent with guardrail and session memory
const agent = new bedrock.Agent(this, 'Agent', {
  foundationModel: bedrock.BedrockFoundationModel.ANTHROPIC_CLAUDE_HAIKU_V1_0,
  instruction: 'You are a helpful and friendly agent that answers questions about literature.',
  guardrail: guardrail,
  shouldPrepareAgent: true,
  memory: bedrock.Memory.sessionSummary({
    maxRecentSessions: 10,
    memoryDuration: Duration.days(20),
  }),
});

// AgentAlias: include lastUpdated to force a new version on every deploy
const agentAlias = new bedrock.AgentAlias(this, 'myAlias', {
  agentAliasName: 'production',
  agent: agent,
  description: `Production version of my agent. Created at ${agent.lastUpdated}`,
});
```

_Source: https://docs.aws.amazon.com/cdk/api/v2/docs/aws-bedrock-alpha-readme.html_

---

### Action Group with type-safe FunctionSchema

```typescript
import * as bedrock from '@aws-cdk/aws-bedrock-alpha';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as path from 'path';

const actionGroupFunction = new lambda.Function(this, 'ActionGroupFunction', {
  runtime: lambda.Runtime.PYTHON_3_12,
  handler: 'index.handler',
  code: lambda.Code.fromAsset(path.join(__dirname, '../lambda/action-group')),
});

const functionSchema = new bedrock.FunctionSchema({
  functions: [
    {
      name: 'searchBooks',
      description: 'Search for books in the library catalog',
      parameters: {
        'query': {
          type: bedrock.ParameterType.STRING,
          required: true,
          description: 'The search query string',
        },
        'maxResults': {
          type: bedrock.ParameterType.INTEGER,
          required: false,
          description: 'Maximum number of results to return',
        },
      },
      requireConfirmation: bedrock.RequireConfirmation.DISABLED,
    },
  ],
});

const actionGroup = new bedrock.AgentActionGroup({
  name: 'library-functions',
  description: 'Functions for interacting with the library catalog',
  executor: bedrock.ActionGroupExecutor.fromLambda(actionGroupFunction),
  functionSchema: functionSchema,
  enabled: true,
});

const agent = new bedrock.Agent(this, 'Agent', {
  foundationModel: bedrock.BedrockFoundationModel.ANTHROPIC_CLAUDE_HAIKU_V1_0,
  instruction: 'You are a helpful and friendly agent that answers questions about literature.',
  actionGroups: [actionGroup],
});
```

_Source: https://docs.aws.amazon.com/cdk/api/v2/docs/aws-bedrock-alpha-readme.html_

---

### Agent Collaboration with SUPERVISOR\_ROUTER

```typescript
import * as bedrock from '@aws-cdk/aws-bedrock-alpha';

// Specialized sub-agent
const customerSupportAgent = new bedrock.Agent(this, 'CustomerSupportAgent', {
  instruction: 'You specialize in answering customer support questions.',
  foundationModel: bedrock.BedrockFoundationModel.AMAZON_NOVA_LITE_V1,
  shouldPrepareAgent: true,
});

const customerSupportAlias = new bedrock.AgentAlias(this, 'CustomerSupportAlias', {
  agent: customerSupportAgent,
  agentAliasName: 'production',
});

// Supervisor agent that delegates
// Verified AgentCollaboratorType enum values: SUPERVISOR, DISABLED, SUPERVISOR_ROUTER
// PEER does NOT exist as an enum value.
const mainAgent = new bedrock.Agent(this, 'MainAgent', {
  instruction: 'You route specialized questions to other agents.',
  foundationModel: bedrock.BedrockFoundationModel.AMAZON_NOVA_LITE_V1,
  agentCollaboration: {
    type: bedrock.AgentCollaboratorType.SUPERVISOR,
    collaborators: [
      new bedrock.AgentCollaborator({
        agentAlias: customerSupportAlias,
        collaborationInstruction: 'Route customer support questions to this agent.',
        collaboratorName: 'CustomerSupport',
        relayConversationHistory: true,
      }),
    ],
  },
});

// For automatic low-latency routing use SUPERVISOR_ROUTER:
// type: bedrock.AgentCollaboratorType.SUPERVISOR_ROUTER
```

_Source: https://docs.aws.amazon.com/cdk/api/v2/docs/@aws-cdk_aws-bedrock-alpha.AgentCollaboratorType.html_

---

### Cross-Region Inference Profile with Agent

```typescript
import * as bedrock from '@aws-cdk/aws-bedrock-alpha';

// Cross-region profile (reduces throttling, improves availability)
const crossRegionProfile = bedrock.CrossRegionInferenceProfile.fromConfig({
  geoRegion: bedrock.CrossRegionInferenceProfileRegion.US,
  model: bedrock.BedrockFoundationModel.ANTHROPIC_CLAUDE_3_5_SONNET_V1_0,
});

const agent = new bedrock.Agent(this, 'Agent', {
  foundationModel: crossRegionProfile,
  instruction: 'You are a helpful and friendly agent that answers questions about agriculture.',
});
```

_Source: https://docs.aws.amazon.com/cdk/api/v2/docs/aws-bedrock-alpha-readme.html_

---

### VectorKnowledgeBase with @cdklabs (deprecated workaround)

> **WARNING:** `@cdklabs/generative-ai-cdk-constructs` is **DEPRECATED** for Bedrock constructs. Use only as a temporary workaround until `aws-bedrock-alpha` ships `VectorKnowledgeBase` L2 (tracking: [aws/aws-cdk#36592](https://github.com/aws/aws-cdk/issues/36592)). Note that `Agent` in `@aws-cdk/aws-bedrock-alpha` has **no `knowledgeBases` prop** — the prop shown below is specific to the `@cdklabs` package API.

```typescript
// NOTICE: @cdklabs/generative-ai-cdk-constructs is DEPRECATED for Bedrock constructs.
// Use as a workaround until aws-bedrock-alpha ships VectorKnowledgeBase L2.
// See: https://github.com/aws/aws-cdk/issues/36592
// NOTE: Agent in @aws-cdk/aws-bedrock-alpha does NOT have a 'knowledgeBases' prop.
// The KB-Agent link below is specific to @cdklabs/generative-ai-cdk-constructs.
import { bedrock } from '@cdklabs/generative-ai-cdk-constructs';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as cdk from 'aws-cdk-lib';

const docBucket = new s3.Bucket(this, 'DocBucket', {
  enforceSSL: true,
  versioned: true,
  publicReadAccess: false,
  blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
  encryption: s3.BucketEncryption.S3_MANAGED,
  removalPolicy: cdk.RemovalPolicy.DESTROY,
  autoDeleteObjects: true,
});

// Vector knowledge base (automatically manages AOSS)
const kb = new bedrock.VectorKnowledgeBase(this, 'KB', {
  embeddingsModel: bedrock.BedrockFoundationModel.TITAN_EMBED_TEXT_V1,
  instruction: 'Use this knowledge base to answer questions about books.',
});

// S3 data source with fixed-size chunking
const dataSource = new bedrock.S3DataSource(this, 'DataSource', {
  bucket: docBucket,
  knowledgeBase: kb,
  dataSourceName: 'books',
  chunkingStrategy: bedrock.ChunkingStrategy.fixedSize({
    maxTokens: 500,
    overlapPercentage: 20,
  }),
});

// Agent using the knowledge base (@cdklabs-specific API)
const agent = new bedrock.Agent(this, 'Agent', {
  foundationModel: bedrock.BedrockFoundationModel.ANTHROPIC_CLAUDE_3_5_SONNET_V1_0,
  instruction: 'You are a helpful and friendly agent that answers questions about literature.',
  knowledgeBases: [kb],
  userInputEnabled: true,
  shouldPrepareAgent: true,
});
```

_Source: https://awslabs.github.io/generative-ai-cdk-constructs/_

---

### CfnKnowledgeBase L1 with OpenSearch Serverless (stable path)

> This is the recommended stable path for Knowledge Base until L2 constructs arrive in `aws-bedrock-alpha`. You must provision `CfnCollection`, encryption/network/data-access policies, and the vector index separately — CDK does not do this automatically with L1. `@cdklabs/generative-ai-cdk-constructs` handles all of it automatically but is deprecated.

```typescript
import { aws_bedrock as bedrock } from 'aws-cdk-lib';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as s3 from 'aws-cdk-lib/aws-s3';

// IAM role for the knowledge base
const kbRole = new iam.Role(this, 'KBRole', {
  assumedBy: new iam.ServicePrincipal('bedrock.amazonaws.com'),
});
// See: https://docs.aws.amazon.com/bedrock/latest/userguide/kb-permissions.html

// Prerequisite: create CfnCollection (aws_opensearchserverless.CfnCollection)
// + encryption/network/data-access policies + vector index separately.
// @cdklabs/generative-ai-cdk-constructs handles all of this automatically.
const cfnKb = new bedrock.CfnKnowledgeBase(this, 'MyCfnKnowledgeBase', {
  name: 'my-knowledge-base',
  roleArn: kbRole.roleArn,
  knowledgeBaseConfiguration: {
    type: 'VECTOR',
    vectorKnowledgeBaseConfiguration: {
      embeddingModelArn: 'arn:aws:bedrock:us-east-1::foundation-model/amazon.titan-embed-text-v1',
    },
  },
  storageConfiguration: {
    type: 'OPENSEARCH_SERVERLESS',
    opensearchServerlessConfiguration: {
      collectionArn: 'arn:aws:aoss:us-east-1:123456789012:collection/my-collection',
      vectorIndexName: 'my-vector-index',
      fieldMapping: {
        vectorField: 'embedding',
        textField: 'text',
        metadataField: 'metadata',
      },
    },
  },
});

declare const docBucket: s3.IBucket;

const cfnDataSource = new bedrock.CfnDataSource(this, 'MyCfnDataSource', {
  knowledgeBaseId: cfnKb.attrKnowledgeBaseId,
  name: 'my-s3-datasource',
  dataSourceConfiguration: {
    type: 'S3',
    s3Configuration: {
      bucketArn: docBucket.bucketArn,
    },
  },
});
```

_Source: https://docs.aws.amazon.com/cdk/api/v2/docs/aws-cdk-lib.aws_bedrock.CfnKnowledgeBase.html_

---

### AgentCore Runtime with ECR and model invoke permission

```typescript
import * as agentcore from 'aws-cdk-lib/aws-bedrockagentcore';
import * as ecr from 'aws-cdk-lib/aws-ecr';
import * as bedrock from 'aws-cdk-lib/aws-bedrock';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as path from 'path';

// Option 1: existing ECR image
const repository = new ecr.Repository(this, 'TestRepository', {
  repositoryName: 'test-agent-runtime',
});

const runtime = new agentcore.Runtime(this, 'MyAgentRuntime', {
  runtimeName: 'myAgent',
  agentRuntimeArtifact: agentcore.AgentRuntimeArtifact.fromEcrRepository(repository, 'v1.0.0'),
});

// Grant the runtime permission to invoke a Bedrock model
const model = bedrock.FoundationModel.fromFoundationModelId(
  this,
  'Model',
  bedrock.FoundationModelIdentifier.ANTHROPIC_CLAUDE_3_7_SONNET_20250219_V1_0,
);
runtime.role.addToPrincipalPolicy(new iam.PolicyStatement({
  actions: ['bedrock:InvokeModel'],
  resources: [model.modelArn],
}));

// Option 2: local asset (Dockerfile in directory)
const artifactFromAsset = agentcore.AgentRuntimeArtifact.fromAsset(
  path.join(__dirname, 'path/to/agent/dockerfile/directory')
);

// Option 3: direct code (Linux arm64 ZIP pre-uploaded to S3)
const artifactFromS3 = agentcore.AgentRuntimeArtifact.fromS3(
  { bucketName: 'my-code-bucket', objectKey: 'deployment_package.zip' },
  agentcore.AgentCoreRuntime.PYTHON_3_12,
  ['opentelemetry-instrument', 'main.py']
);

// Option 4: local asset auto-zip (CDK handles S3 upload)
const artifactFromCode = agentcore.AgentRuntimeArtifact.fromCodeAsset({
  path: path.join(__dirname, 'path/to/agent/code'),
  runtime: agentcore.AgentCoreRuntime.PYTHON_3_12,
  entrypoint: ['opentelemetry-instrument', 'main.py'],
});
```

_Source: https://docs.aws.amazon.com/cdk/api/v2/docs/aws-cdk-lib.aws_bedrockagentcore-readme.html_

---

### AgentCore Memory with built-in strategies

```typescript
import * as agentcore from 'aws-cdk-lib/aws-bedrockagentcore';
import * as kms from 'aws-cdk-lib/aws-kms';
import * as cdk from 'aws-cdk-lib';

const encryptionKey = new kms.Key(this, 'MemoryEncryptionKey', {
  enableKeyRotation: true,
  description: 'KMS key for memory encryption',
});

const memory = new agentcore.Memory(this, 'MyMemory', {
  memoryName: 'my_memory',
  description: 'Memory with all built-in LTM strategies',
  expirationDuration: cdk.Duration.days(90),
  kmsKey: encryptionKey,
  memoryStrategies: [
    agentcore.MemoryStrategy.usingBuiltInSummarization(),
    agentcore.MemoryStrategy.usingBuiltInSemantic(),
    agentcore.MemoryStrategy.usingBuiltInUserPreference(),
    agentcore.MemoryStrategy.usingBuiltInEpisodic(),
  ],
});
```

_Source: https://docs.aws.amazon.com/cdk/api/v2/docs/aws-cdk-lib.aws_bedrockagentcore-readme.html_

---

### AgentCore Gateway with Lambda target

```typescript
import * as agentcore from 'aws-cdk-lib/aws-bedrockagentcore';
import * as lambda from 'aws-cdk-lib/aws-lambda';

// Gateway with automatic Cognito M2M auth (default)
const gateway = new agentcore.Gateway(this, 'MyGateway', {
  gatewayName: 'my-gateway',
});

const lambdaFunction = new lambda.Function(this, 'MyFunction', {
  runtime: lambda.Runtime.NODEJS_22_X,
  handler: 'index.handler',
  code: lambda.Code.fromInline(`
    exports.handler = async (event) => {
      return { statusCode: 200, body: JSON.stringify({ message: 'Hello!' }) };
    };
  `),
});

// Recommended method for adding a Lambda target
const lambdaTarget = gateway.addLambdaTarget('MyLambdaTarget', {
  gatewayTargetName: 'my-lambda-target',
  description: 'Lambda function target',
  lambdaFunction: lambdaFunction,
  toolSchema: agentcore.ToolSchema.fromInline([
    {
      name: 'hello_world',
      description: 'A simple hello world tool',
      inputSchema: {
        type: agentcore.SchemaDefinitionType.OBJECT,
        properties: {
          name: {
            type: agentcore.SchemaDefinitionType.STRING,
            description: 'The name to greet',
          },
        },
        required: ['name'],
      },
    },
  ]),
});
// Other gateway methods: addOpenApiTarget(), addSmithyTarget(), addMcpServerTarget(), addApiGatewayTarget()
```

_Source: https://docs.aws.amazon.com/cdk/api/v2/docs/aws-cdk-lib.aws_bedrockagentcore-readme.html_

---

### PolicyEngine with Cedar and Gateway via L1 escape hatch

> This pattern is **officially documented** in the `aws-bedrock-agentcore-alpha` README. It is required because `PolicyEngine` remains in alpha while `Gateway` is stable — there is no native L2 integration yet.

```typescript
import * as agentcore from 'aws-cdk-lib/aws-bedrockagentcore';
import * as agentcoreAlpha from '@aws-cdk/aws-bedrock-agentcore-alpha';
import * as iam from 'aws-cdk-lib/aws-iam';

// PolicyEngine remains in alpha
const policyEngine = new agentcoreAlpha.PolicyEngine(this, 'Engine', {
  policyEngineName: 'my_engine',
});

// Gateway is stable
const gateway = new agentcore.Gateway(this, 'Gateway', {
  gatewayName: 'my-gateway',
});

// Wire via L1 escape hatch (native L2 integration not yet available)
const cfnGateway = gateway.node.defaultChild as agentcore.CfnGateway;
cfnGateway.policyEngineConfiguration = {
  arn: policyEngine.policyEngineArn,
  mode: agentcoreAlpha.PolicyEngineMode.ENFORCE.value,
};

// Grant the gateway permission to evaluate policies
gateway.role.addToPrincipalPolicy(new iam.PolicyStatement({
  actions: ['bedrock-agentcore:GetPolicyEngine'],
  resources: [policyEngine.policyEngineArn],
}));
gateway.role.addToPrincipalPolicy(new iam.PolicyStatement({
  actions: ['bedrock-agentcore:AuthorizeAction', 'bedrock-agentcore:PartiallyAuthorizeActions'],
  resources: [policyEngine.policyEngineArn, gateway.gatewayArn],
}));

// Type-safe Cedar policy (addPolicy on PolicyEngine)
policyEngine.addPolicy('AllowWeatherTool', {
  statement: agentcoreAlpha.PolicyStatement.permit()
    .forPrincipal('AgentCore::OAuthUser')
    .onActions(['AgentCore::Action::WeatherTool__get_forecast'])
    .onResource('AgentCore::Gateway', gateway.gatewayArn),
  description: 'Allow weather tool access',
  validationMode: agentcoreAlpha.PolicyValidationMode.FAIL_ON_ANY_FINDINGS,
});
```

_Source: https://docs.aws.amazon.com/cdk/api/v2/docs/aws-bedrock-agentcore-alpha-readme.html_

---

## Configuration reference

| Name | Description | Default / example |
|---|---|---|
| `@aws-cdk/aws-bedrock-alpha` — `Agent.foundationModel` | Type `IBedrockInvokable`. Accepts `BedrockFoundationModel.*` (class with static members), `CrossRegionInferenceProfile.fromConfig()`, `ApplicationInferenceProfile`. Required. | `bedrock.BedrockFoundationModel.ANTHROPIC_CLAUDE_HAIKU_V1_0` |
| `@aws-cdk/aws-bedrock-alpha` — `Agent.instruction` | String with behavior instructions. Minimum 40 characters. Required. | `'You are a helpful and friendly agent that answers questions about literature.'` |
| `@aws-cdk/aws-bedrock-alpha` — `Agent.shouldPrepareAgent` | Boolean. If `true`, automatically updates the DRAFT after every change. Must be `true` if creating an `AgentAlias`. | `false` (default) |
| `@aws-cdk/aws-bedrock-alpha` — `Agent.idleSessionTTL` | `Duration`. How long sessions stay open. Default is **1 hour** per the official Agent Properties table. | `Duration.hours(1)` (default) |
| `@aws-cdk/aws-bedrock-alpha` — `AgentAlias` props (verified) | Constructor props: `agent` (required `IAgent`), `agentAliasName` (optional, default `'latest'`), `agentVersion` (optional, creates new version by default), `description` (optional), `routingConfiguration` (optional, `AgentAliasRoutingConfiguration`). | `new bedrock.AgentAlias(this, 'myAlias', { agent, agentAliasName: 'production', description: \`...${agent.lastUpdated}\` })` |
| `@aws-cdk/aws-bedrock-alpha` — `AgentCollaboratorType` enum values | Verified values: `SUPERVISOR` (supervisor using LLM), `SUPERVISOR_ROUTER` (supervisor with automatic low-latency routing), `DISABLED` (collaboration disabled). `PEER` does not exist. | `bedrock.AgentCollaboratorType.SUPERVISOR` |
| `aws-cdk-lib.aws_bedrock.CfnKnowledgeBase` — `knowledgeBaseConfiguration.type` | Knowledge base type. CloudFormation/L1 values: `VECTOR`, `KENDRA`, `SQL`. | `'VECTOR'` |
| `aws-cdk-lib.aws_bedrock.CfnKnowledgeBase` — `storageConfiguration.type` | Vector store type. Values: `OPENSEARCH_SERVERLESS`, `OPENSEARCH_MANAGED_CLUSTER`, `RDS`, `PINECONE`, `MONGO_DB_ATLAS`, `S3_VECTORS`, `NEPTUNE_ANALYTICS`. Redis Enterprise is **not** supported in CloudFormation. | `'OPENSEARCH_SERVERLESS'` |
| `aws-cdk-lib/aws_bedrockagentcore` — `Runtime.agentRuntimeArtifact` | Required. Factory: `AgentRuntimeArtifact.fromEcrRepository(repo, tag)`, `fromAsset(dockerfileDirPath)`, `fromS3({bucketName, objectKey}, runtime, entrypoint)`, `fromCodeAsset({path, runtime, entrypoint})`, `fromImageUri(uri)`. `fromS3` and `fromCodeAsset` require Linux arm64. | `agentcore.AgentRuntimeArtifact.fromEcrRepository(repository, 'v1.0.0')` |
| `aws-cdk-lib/aws_bedrockagentcore` — `Memory.expirationDuration` | Short-term memory retention period. Range: 7–365 days. Default: 90 days. | `cdk.Duration.days(90)` |
| `aws-cdk-lib/aws_bedrockagentcore` — `Gateway` default auth | If `authorizerConfiguration` is not specified, the construct automatically creates a Cognito User Pool configured for OAuth 2.0 client credentials (M2M). Accessible via `gateway.userPool` and `gateway.userPoolClient`. | Cognito M2M automatic (default) |

---

## Gotchas

- `VectorKnowledgeBase` and `S3DataSource` L2 constructs do **not** exist in `@aws-cdk/aws-bedrock-alpha` (June 2026, issue [aws/aws-cdk#36592](https://github.com/aws/aws-cdk/issues/36592)). The `Agent` construct in `@aws-cdk/aws-bedrock-alpha` has **no `knowledgeBases` prop**. These constructs exist only in `@cdklabs/generative-ai-cdk-constructs` (DEPRECATED).

- `AgentCollaboratorType` has no `PEER` value. The confirmed values from the API reference are `SUPERVISOR`, `DISABLED`, `SUPERVISOR_ROUTER`. Any code using `AgentCollaboratorType.PEER` will fail at compile time.

- `Agent.idleSessionTTL` default is **1 hour**, per the official Agent Properties table (`idleSessionTTL | Duration | No | … Defaults to 1 hour`). Earlier drafts of this file incorrectly stated 10 minutes.

- `AgentAlias` **does** have a `routingConfiguration` prop (`AgentAliasRoutingConfiguration`, optional). Verified in the official Agent Alias Properties table. The optional props are: `agent` (required), `agentAliasName`, `agentVersion`, `description`, `routingConfiguration`.

- `@cdklabs/generative-ai-cdk-constructs` is **DEPRECATED** for Bedrock constructs. The awslabs project has announced that Bedrock L2 constructs are migrating to `aws-bedrock-alpha` and the library will receive no further updates for these constructs.

- `@aws-cdk/aws-bedrock-alpha` is **EXPERIMENTAL** — it does not follow semver. Breaking changes can be introduced in any minor version. Pin the version in `package.json`.

- `Gateway.addTarget()` is **not** the recommended pattern. Use the specific methods: `addLambdaTarget()`, `addOpenApiTarget()`, `addSmithyTarget()`, `addMcpServerTarget()`, `addApiGatewayTarget()`. `GatewayTarget` as a static factory is available for advanced cases and imported gateways.

- `storageConfiguration` in `CfnKnowledgeBase` requires **REPLACEMENT** (not update-in-place) if changed after deploy. You cannot change the vector store type of an existing Knowledge Base.

- For OpenSearch Serverless with `CfnKnowledgeBase` L1: the vector index is **not** created automatically. You must separately create `CfnCollection`, encryption/network/data-access policies, and the vector index. `@cdklabs/generative-ai-cdk-constructs` handles all of this automatically (but is deprecated).

- KMS key on `PolicyEngine`: once set it cannot be modified (requires replacement). If the key becomes inaccessible, all authorization decisions are automatically DENIED.

- AgentCore requires `iam:CreateServiceLinkedRole` in the CDK deployment role. Without it the first deploy fails with a non-obvious `AccessDenied` error.

- `PolicyEngine` remains in `@aws-cdk/aws-bedrock-agentcore-alpha` while `Gateway` is now in `aws-cdk-lib/aws_bedrockagentcore` (stable). Connecting them requires the L1 escape hatch pattern officially documented in `aws-bedrock-agentcore-alpha`.

- S3 data ingestion into a Knowledge Base is **not** automatic after deploy. It requires a `StartIngestionJob` API call (typically via EventBridge or a Lambda trigger).

- Redis Enterprise Cloud as a vector store is **not** supported in CloudFormation/CDK. Only via the AWS Console or direct API.

- `BedrockFoundationModel` is a JavaScript class, not a TypeScript enum. You can instantiate it directly with `new BedrockFoundationModel('model-id')` for models not listed as static members.

---

## Official sources

- [aws-bedrock-alpha README — official CDK documentation](https://docs.aws.amazon.com/cdk/api/v2/docs/aws-bedrock-alpha-readme.html) — Primary source for `Agent`, `Guardrail`, `Prompt`, `InferenceProfile` L2. Confirms: no `knowledgeBases` prop on `Agent`, no `VectorKnowledgeBase` L2.
- [class Agent (construct) — aws-bedrock-alpha API reference](https://docs.aws.amazon.com/cdk/api/v2/docs/@aws-cdk_aws-bedrock-alpha.Agent.html) — Verified complete list of props: `foundationModel`, `instruction`, `actionGroups`, `agentCollaboration`, `agentName`, `codeInterpreterEnabled`, `customOrchestrationExecutor`, `description`, `existingRole`, `forceDelete`, `guardrail`, `idleSessionTTL`, `kmsKey`, `memory`, `promptOverrideConfiguration`, `shouldPrepareAgent`, `userInputEnabled`. Does NOT include `knowledgeBases`. `lastUpdated?: string` confirmed as output.
- [class AgentAlias (construct) — aws-bedrock-alpha API reference](https://docs.aws.amazon.com/cdk/api/v2/docs/@aws-cdk_aws-bedrock-alpha.AgentAlias.html) — Verified props per official Agent Alias Properties table: `agent` (required), `agentAliasName` (optional), `agentVersion` (optional), `description` (optional), `routingConfiguration` (optional, `AgentAliasRoutingConfiguration`).
- [enum AgentCollaboratorType — aws-bedrock-alpha API reference](https://docs.aws.amazon.com/cdk/api/v2/docs/@aws-cdk_aws-bedrock-alpha.AgentCollaboratorType.html) — Confirmed values: `SUPERVISOR`, `DISABLED`, `SUPERVISOR_ROUTER`. No `PEER` value.
- [class BedrockFoundationModel — aws-bedrock-alpha API reference](https://docs.aws.amazon.com/cdk/api/v2/docs/@aws-cdk_aws-bedrock-alpha.BedrockFoundationModel.html) — It is a class (not enum). Verified static members include: `ANTHROPIC_CLAUDE_HAIKU_V1_0`, `ANTHROPIC_CLAUDE_3_5_SONNET_V1_0`, `ANTHROPIC_CLAUDE_3_5_SONNET_V2_0`, `ANTHROPIC_CLAUDE_3_7_SONNET_V1_0`, `AMAZON_NOVA_LITE_V1`, `TITAN_EMBED_TEXT_V1`, `TITAN_EMBED_TEXT_V2_1024`, `ANTHROPIC_CLAUDE_SONNET_4_5_V1_0`, and others.
- [aws-cdk-lib.aws_bedrockagentcore README — stable construct](https://docs.aws.amazon.com/cdk/api/v2/docs/aws-cdk-lib.aws_bedrockagentcore-readme.html) — `Runtime`, `Gateway`, `GatewayTarget`, `Browser`, `CodeInterpreter`, `Memory`, `OnlineEvaluation`: all GA in `aws-cdk-lib`. Gateway methods: `addLambdaTarget()`, `addOpenApiTarget()`, `addSmithyTarget()`, `addMcpServerTarget()`, `addApiGatewayTarget()`. Default Gateway auth: automatic Cognito M2M.
- [aws-bedrock-agentcore-alpha README — remaining alpha portion](https://docs.aws.amazon.com/cdk/api/v2/docs/aws-bedrock-agentcore-alpha-readme.html) — Only `PolicyEngine`, `Policy`, `PolicyStatement`, `PolicyValidationMode`, `PolicyEngineMode` remain in alpha. L1 escape hatch pattern for connecting `PolicyEngine` (alpha) to `Gateway` (stable) is documented and confirmed on this page.
- [aws-cdk-lib.aws_bedrock.CfnKnowledgeBase — L1 API reference](https://docs.aws.amazon.com/cdk/api/v2/docs/aws-cdk-lib.aws_bedrock.CfnKnowledgeBase.html) — Official L1 for KnowledgeBase. Supports `VECTOR`, `KENDRA`, `SQL` as `knowledgeBaseConfiguration.type`. Storage types: `OPENSEARCH_SERVERLESS`, `OPENSEARCH_MANAGED_CLUSTER`, `RDS`, `PINECONE`, `MONGO_DB_ATLAS`, `S3_VECTORS`, `NEPTUNE_ANALYTICS`. Redis Enterprise NOT supported in CloudFormation.
- [aws-cdk-lib.aws_bedrock README — stable L1 module](https://docs.aws.amazon.com/cdk/api/v2/docs/aws-cdk-lib.aws_bedrock-readme.html) — Confirms that `aws-cdk-lib/aws_bedrock` contains only utility factory L2 (`FoundationModel`, `ProvisionedModel`) and L1 (`Cfn*`). Full L2 constructs are in `@aws-cdk/aws-bedrock-alpha`.
- [aws-bedrock-alpha feature request: Knowledge Base L2 constructs](https://github.com/aws/aws-cdk/issues/36592) — Issue opened January 6, 2026, no linked PR. Confirms that `VectorKnowledgeBase` L2 is not yet available in `aws-bedrock-alpha`.
- [awslabs/generative-ai-cdk-constructs — official page](https://awslabs.github.io/generative-ai-cdk-constructs/) — Confirms deprecation: Bedrock L2 constructs are migrating to `@aws-cdk/aws-bedrock-alpha`; the awslabs library will no longer receive updates for Bedrock constructs.

---

## Verify live (open questions)

Re-check these in the CDK CHANGELOG, GitHub issue tracker, and AWS release notes before relying on the current state:

1. **When will `VectorKnowledgeBase` and `S3DataSource` L2 land in `@aws-cdk/aws-bedrock-alpha`?** Issue [aws/aws-cdk#36592](https://github.com/aws/aws-cdk/issues/36592) opened January 2026, no PR or scheduled date as of June 2026.

2. **Will `@cdklabs/generative-ai-cdk-constructs` continue to receive security fixes despite being deprecated for Bedrock constructs?** Unclear from the official deprecation announcement — verify before keeping it in production pipelines.

3. **When will native L2 integration between `PolicyEngine` (alpha) and `Gateway` (stable) be available without the L1 escape hatch?** No timeline published as of June 2026.

4. **Do AgentCore Runtime constructs support ARM64 via `fromAsset` (Dockerfile)?** The documentation explicitly states that `fromS3`/`fromCodeAsset` require Linux arm64 dependencies, but does not explicitly confirm or deny this for `fromAsset`.

5. **How to bootstrap an OpenSearch Serverless vector index idempotently from CDK?** The vector index is not a native CloudFormation resource. Options are a Custom Resource with SDK call vs `AwsCustomResource` — no canonical CDK-native pattern is documented.

6. **Will `@aws-cdk/aws-bedrock-alpha` ever include constructs for `AWS::Bedrock::Flow` (Bedrock Flows / Prompt Flows)?** Not in current documentation nor in any tracked issue as of June 2026.
