# IaC Best Practices for AWS AI Agents (Terraform-first)

> Part of the **aws-bedrock-agentcore-skill** skill. See [SKILL.md](../SKILL.md) for the decision tree. Every source below is official - re-open it to verify details.

## Table of contents

- [Overview](#overview)
- [Key concepts](#key-concepts)
- [Best practices](#best-practices)
- [Code](#code)
  - [Remote state S3 with native locking GA (Terraform >= 1.11)](#remote-state-s3-with-native-locking-ga-terraform--111)
  - [Provider assume_role for CI/CD - never use static access keys in pipelines](#provider-assume_role-for-cicd--never-use-static-access-keys-in-pipelines)
  - [IAM Execution Role for AgentCore Runtime with correct trust policy (confused-deputy safe)](#iam-execution-role-for-agentcore-runtime-with-correct-trust-policy-confused-deputy-safe)
  - [ECR Repository + ARM64 build + aws_bedrockagentcore_agent_runtime](#ecr-repository--arm64-build--aws_bedrockagentcore_agent_runtime)
  - [Official aws-ia/agentcore/aws module v0.0.2](#official-aws-iaagentcoreaws-module-v002)
  - [Classic Bedrock Agent (aws_bedrockagent_agent) with prepare-agent workaround](#classic-bedrock-agent-aws_bedrockagent_agent-with-prepare-agent-workaround)
  - [IAM least-privilege policy for bedrock:InvokeModel (post simplified model access Oct 2025)](#iam-least-privilege-policy-for-bedrockinvokemodel-post-simplified-model-access-oct-2025)
  - [Dockerfile ARM64 for AgentCore Runtime (/invocations + /ping contract)](#dockerfile-arm64-for-agentcore-runtime-invocations--ping-contract)
  - [CDK STABLE (Python) - deploy container AgentCore ARM64](#cdk-stable-python--deploy-container-agentcore-arm64)
- [Configuration reference](#configuration-reference)
- [Gotchas](#gotchas)
- [Official sources](#official-sources)
- [Verify live (open questions)](#verify-live-open-questions)

---

## Overview

Operational guide for deploying AI agents on AWS with Terraform as the primary path and CDK as secondary. Covers: remote state on S3 (native locking introduced in Terraform 1.10.0, GA in 1.11.0 with `use_lockfile` argument; DynamoDB locking deprecated in 1.11), IAM least-privilege for Bedrock and AgentCore Runtime, mandatory ARM64 container build for AgentCore, model access management post-simplification (October 2025), CI/CD with OIDC, environment separation via distinct backends.

The `aws_bedrockagentcore_agent_runtime` resource exists as `aws_bedrockagentcore_agent_runtime` (hashicorp/aws >= 6.18) and as `awscc_bedrockagentcore_runtime` (hashicorp/awscc >= 1.57). The official module `aws-ia/agentcore/aws` (v0.0.2 on Terraform Registry, April 2026) uses awscc internally.

**Maturity note:** GA via hashicorp/aws >= 6.18: `aws_bedrockagentcore_agent_runtime` (introduced in 6.18, `code_configuration` added in 6.22), `aws_bedrockagentcore_agent_runtime_endpoint`, `aws_bedrockagentcore_gateway`, `aws_bedrockagentcore_browser`, `aws_bedrockagentcore_memory`, `aws_bedrockagentcore_memory_strategy`, `aws_bedrockagentcore_oauth2_credential_provider`, `aws_bedrockagentcore_workload_identity`, `aws_bedrockagentcore_gateway_target`. Classic Bedrock Agents: `aws_bedrockagent_agent`, `aws_bedrockagent_agent_alias`, `aws_bedrockagent_knowledge_base` (GA from prior versions). GA via hashicorp/awscc >= 1.57: `awscc_bedrockagentcore_runtime`, `awscc_bedrockagentcore_runtime_endpoint`. Official module `aws-ia/agentcore/aws`: v0.0.2 (April 2026), early-stage without guaranteed stable API. CDK STABLE (`aws-cdk-lib/aws-bedrockagentcore`): Runtime, RuntimeEndpoint, AgentRuntimeArtifact, NetworkConfiguration, Gateway, GatewayTarget, Browser, CodeInterpreter, Memory, MemoryStrategy, OAuth2CredentialProvider, Evaluator. CDK ALPHA (`aws-cdk.aws_bedrock_agentcore_alpha`): ONLY PolicyEngine, Policy, PolicyStatement (remained experimental). NOT yet supported natively in Terraform hashicorp/aws (June 2026): AgentCore PolicyEngine/Cedar (issue #47957, milestone v6.47.0). Removed: `bedrock:PutFoundationModelEntitlement` (removed October 2025, not needed in any IaC).

---

## Key concepts

**AgentCore Runtime - mandatory contract**
Every agent must expose `/invocations` (POST) and `/ping` (GET) on port 8080 (host 0.0.0.0). The container must be ARM64 (Graviton). The service contract is verified by AgentCore before activation.

**ARM64 mandatory for AgentCore Runtime**
Amazon Bedrock AgentCore runs exclusively on AWS Graviton (ARM64). Any container image or code package must be compiled and pushed for `linux/arm64`. Python dependencies with native code require explicit cross-compilation (`uv --python-platform aarch64-manylinux2014 --only-binary=:all:`).

**Two resource families for AgentCore Runtime**
hashicorp/aws >= 6.18 exposes `aws_bedrockagentcore_agent_runtime` (introduced in v6.18.0; `code_configuration` added in v6.22.0). The hashicorp/awscc >= 1.57 provider (used by the aws-ia module) exposes `awscc_bedrockagentcore_runtime`. The official `aws-ia/agentcore` v0.0.2 module uses awscc internally.

**Classic Bedrock Agents (aws_bedrockagent_agent) vs AgentCore Runtime**
`aws_bedrockagent_agent` manages Bedrock agents with action groups, knowledge bases, Lambda. `aws_bedrockagentcore_agent_runtime` is for agents with arbitrary container/code in isolated microVMs. They require distinct IAM roles and deploy workflows.

**Remote state S3 + native locking (Terraform >= 1.11)**
S3 native state locking was introduced in Terraform 1.10.0 (November 2024); the `use_lockfile = true` argument and GA status arrived in Terraform 1.11.0 (February 2025), which also formally deprecated DynamoDB-based locking arguments. AWS Prescriptive Guidance recommends S3 native locking. Each environment (dev/staging/prod) must have a distinct S3 backend to isolate state. _Sources: https://github.com/hashicorp/terraform/releases/tag/v1.10.0 - https://github.com/hashicorp/terraform/releases/tag/v1.11.0_

**IAM least-privilege for Terraform CI/CD**
The CI/CD runner (CodeBuild, GitHub Actions) must assume an IAM role via OIDC - never use long-term access keys. The role must have only the actions needed for managed resources. IAM Access Analyzer helps remove excess permissions over time.

**Simplified Model Access (October 2025)**
Since October 2025, Bedrock serverless models are available automatically. The `PutFoundationModelEntitlement` permission was removed. Control is via IAM: `bedrock:InvokeModel` on specific foundation model ARNs. Anthropic still requires a one-time form before first use.

**prepare-agent workaround (aws_bedrockagent_agent)**
After create/update of a classic Bedrock Agent, Terraform has no native way to prepare it. The official AWS Prescriptive Guidance workaround uses `terraform_data` with `local-exec` (`aws bedrock-agent prepare-agent`) + `time_sleep` to wait for PREPARED state.

**CDK AgentCore: stable module vs alpha**
CDK constructs for Runtime, Gateway, Browser, Memory, Evaluation, Identity are migrated to the STABLE module `aws-cdk-lib/aws-bedrockagentcore` (Python: `aws_cdk.aws_bedrockagentcore`). ONLY PolicyEngine, Policy, PolicyStatement remain in the experimental module `aws-cdk.aws_bedrock_agentcore_alpha`. Use the stable module for all new projects.

**AgentCore lifecycle_configuration defaults**
`idle_runtime_session_timeout` default: 900 seconds (15 min). `max_lifetime` default: 28800 seconds (8 hours). Valid range for both: 60–28800 seconds. Constraint: `idleRuntimeSessionTimeout` must be <= `maxLifetime`. Specifying only `max_lifetime` triggers a known bug (#45290) where Terraform reports `inconsistent result after apply`.

---

## Best practices

- **Use S3 native locking (`use_lockfile = true`) with Terraform >= 1.11 instead of DynamoDB for remote state** - S3 native state locking was introduced in Terraform 1.10.0 (November 2024) and became GA in Terraform 1.11.0 (February 2025), which also deprecated DynamoDB-based locking arguments. Native S3 locking reduces the number of resources to manage. AWS Prescriptive Guidance explicitly recommends migration. For compatibility with teams on older versions it is possible to configure both during the transition. _Source: https://github.com/hashicorp/terraform/releases/tag/v1.11.0 - https://docs.aws.amazon.com/prescriptive-guidance/latest/terraform-aws-provider-best-practices/backend.html_

- **Create a distinct S3 backend per environment (dev/staging/prod), never share workspaces** - Separate backends isolate state: an error in dev does not impact prod. Simplifies per-environment IAM management (read-only on prod for most roles). AWS Prescriptive Guidance explicitly discourages using shared workspaces as a substitute for distinct backends. _Source: https://docs.aws.amazon.com/prescriptive-guidance/latest/terraform-aws-provider-best-practices/backend.html_

- **Enable S3 versioning and CloudTrail on the state bucket for audit and rollback** - Versioning allows restoring a previous state. CloudTrail tracks who modified state (PutObject), essential for compliance audit. _Source: https://docs.aws.amazon.com/prescriptive-guidance/latest/terraform-aws-provider-best-practices/backend.html_

- **Use OIDC to authenticate GitHub Actions or GitLab to AWS, never static access keys** - OIDC generates temporary credentials for each run, eliminating manual secret rotation. Recommended by AWS Prescriptive Guidance for all CI/CD runners. _Source: https://docs.aws.amazon.com/prescriptive-guidance/latest/terraform-aws-provider-best-practices/security.html_

- **Always build AgentCore images on `linux/arm64` (Graviton); use `--platform linux/arm64` in docker buildx** - AgentCore Runtime runs exclusively on ARM64. An x86 image cannot be deployed. The `--platform linux/arm64` flag with docker buildx or a CodeBuild ARM64 environment is mandatory. Confirmed by official AWS documentation. _Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/getting-started-custom.html_

- **Do not create IAM roles with `BedrockAgentCoreFullAccess` in production; use custom policies with minimal actions** - `BedrockAgentCoreFullAccess` includes `GetWorkloadAccessTokenForUserId` which bypasses IdP verification. In prod use only `GetWorkloadAccessTokenForJWT` and explicitly deny `GetWorkloadAccessTokenForUserId`. Confirmed by official runtime-permissions documentation. _Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-permissions.html_

- **Include the trust policy with `aws:SourceAccount` (StringEquals) and `aws:SourceArn` (ArnLike) in the AgentCore Runtime execution role to prevent confused deputy** - Without the ArnLike condition on `aws:SourceArn`, any AgentCore runtime in the account could assume the role. The condition limits assumption to the specific runtime. Confirmed by the official trust policy in the DevGuide. _Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-permissions.html_

- **Pin the Terraform provider version with `~>` (minor version constraint) and add TFLint in CI/CD** - The hashicorp/aws v6.x provider is under active development with new AgentCore resources added every release and breaking changes vs v5.x. TFLint can detect unpinned versions and block the build. _Source: https://docs.aws.amazon.com/prescriptive-guidance/latest/terraform-aws-provider-best-practices/version.html_

- **For `aws_bedrockagent_agent` (classic Bedrock Agents) use `terraform_data` + `local-exec` to prepare-agent after every modification** - Terraform has no native mechanism to wait for the agent's PREPARED state. The official AWS Prescriptive Guidance workaround uses triggers on the agent hash to trigger re-prepare only when needed. _Source: https://docs.aws.amazon.com/prescriptive-guidance/latest/terraform-data-limitations/bedrock-agents.html_

- **Control Bedrock model access via `bedrock:InvokeModel` on specific foundation model ARNs, not with `Resource: *`** - Since October 2025 there is no need to manually enable models. Granular control is via IAM: specify exactly the foundation model or inference profile ARNs authorized. _Source: https://aws.amazon.com/blogs/security/simplified-amazon-bedrock-model-access/_

- **Use the official `aws-ia/agentcore/aws` module (v0.0.2) to manage CONTAINER runtimes with auto-generated IAM; evaluate stability before production use** - The module abstracts `awscc_bedrockagentcore_runtime`, ECR repository creation, ARM64 build via CodeBuild, and IAM configuration. However it is at version 0.0.2 (April 2026) without API stability guarantees. Evaluate whether the module is suitable for production before adoption. _Source: https://github.com/aws-ia/terraform-aws-agentcore_

- **ALWAYS specify both `lifecycle_configuration` values (`idle_runtime_session_timeout` and `max_lifetime`) explicitly** - Specifying only one of the two values (e.g. only `max_lifetime`) causes a known bug (#45290) where Terraform reports `inconsistent result after apply` because the provider does not mark sub-attributes as Computed. Specifying both avoids the problem. Defaults: idle=900s, max=28800s. Constraint: idle must be <= max. _Source: https://github.com/hashicorp/terraform-provider-aws/issues/45290_

- **For CDK use the stable module `aws-cdk-lib/aws-bedrockagentcore` for Runtime, Gateway, Memory, Browser; use `aws_cdk.aws_bedrock_agentcore_alpha` ONLY for PolicyEngine** - From CDK version 2.239+, all AgentCore constructs except PolicyEngine are migrated to the stable module. Using the alpha module for already-stable constructs introduces unnecessary dependencies on experimental APIs subject to breaking changes. _Source: https://docs.aws.amazon.com/cdk/api/v2/docs/aws-cdk-lib.aws_bedrockagentcore-readme.html_

- **Structure Terraform code with `main.tf`, `variables.tf`, `outputs.tf`, `locals.tf`, `providers.tf`, `versions.tf` and `iam.tf` if IAM exceeds 150 lines** - The standard structure recommended by AWS Prescriptive Guidance improves readability and collaboration. Providers must be declared only in root modules, never in reusable modules. _Source: https://docs.aws.amazon.com/prescriptive-guidance/latest/terraform-aws-provider-best-practices/structure.html_

---

## Code

### Remote state S3 with native locking GA (Terraform >= 1.11)

```hcl
# versions.tf
terraform {
  required_version = ">= 1.11"  # 1.11 = use_lockfile GA; 1.10 was experimental
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.18"  # aws_bedrockagentcore_agent_runtime introduced in 6.18
    }
    awscc = {
      source  = "hashicorp/awscc"
      version = "~> 1.57"  # awscc_bedrockagentcore_runtime available from 1.57
    }
  }

  backend "s3" {
    bucket       = "myorg-tf-state-prod"
    key          = "agents/agentcore/tfstate"
    region       = "us-east-1"
    use_lockfile = true   # S3 native locking GA from Terraform 1.11; DynamoDB deprecated
    encrypt      = true
  }
}
```

_Source: https://docs.aws.amazon.com/prescriptive-guidance/latest/terraform-aws-provider-best-practices/backend.html_

---

### Provider assume_role for CI/CD - never use static access keys in pipelines

```hcl
# providers.tf
provider "aws" {
  region = var.aws_region
  assume_role {
    role_arn     = "arn:aws:iam::111122223333:role/terraform-execution-prod"
    session_name = "terraform-session-${var.environment}"
  }
  default_tags {
    tags = {
      ManagedBy   = "terraform"
      Environment = var.environment
      Project     = var.project_name
    }
  }
}
```

_Source: https://docs.aws.amazon.com/prescriptive-guidance/latest/terraform-aws-provider-best-practices/security.html_

---

### IAM Execution Role for AgentCore Runtime with correct trust policy (confused-deputy safe)

Confirmed against official runtime-permissions documentation.

```hcl
# iam.tf
data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

resource "aws_iam_role" "agentcore_execution" {
  name = "AgentCoreRuntimeExecRole-${var.agent_name}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "AssumeRolePolicy"
      Effect = "Allow"
      Principal = {
        Service = "bedrock-agentcore.amazonaws.com"
      }
      Action = "sts:AssumeRole"
      Condition = {
        StringEquals = {
          # Limits assumption to the correct account
          "aws:SourceAccount" = data.aws_caller_identity.current.account_id
        }
        ArnLike = {
          # Limits to the specific runtime in the account (anti confused deputy)
          "aws:SourceArn" = "arn:aws:bedrock-agentcore:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:*"
        }
      }
    }]
  })
}

resource "aws_iam_role_policy" "agentcore_execution" {
  name = "AgentCoreRuntimeExecPolicy"
  role = aws_iam_role.agentcore_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ECRImageAccess"
        Effect = "Allow"
        Action = [
          "ecr:BatchGetImage",
          "ecr:GetDownloadUrlForLayer"
        ]
        Resource = ["arn:aws:ecr:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:repository/*"]
      },
      {
        # ecr:GetAuthorizationToken requires Resource: * (IAM limitation of this action)
        Sid    = "ECRTokenAccess"
        Effect = "Allow"
        Action = ["ecr:GetAuthorizationToken"]
        Resource = "*"
      },
      {
        Sid    = "CloudWatchLogsCreate"
        Effect = "Allow"
        Action = [
          "logs:DescribeLogStreams",
          "logs:CreateLogGroup"
        ]
        Resource = ["arn:aws:logs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:log-group:/aws/bedrock-agentcore/runtimes/*"]
      },
      {
        Sid    = "CloudWatchLogsDescribeAll"
        Effect = "Allow"
        Action = ["logs:DescribeLogGroups"]
        Resource = ["arn:aws:logs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:log-group:*"]
      },
      {
        Sid    = "CloudWatchLogsPut"
        Effect = "Allow"
        Action = [
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = ["arn:aws:logs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:log-group:/aws/bedrock-agentcore/runtimes/*:log-stream:*"]
      },
      {
        Sid    = "XRayTracing"
        Effect = "Allow"
        Action = [
          "xray:PutTraceSegments",
          "xray:PutTelemetryRecords",
          "xray:GetSamplingRules",
          "xray:GetSamplingTargets"
        ]
        Resource = "*"
      },
      {
        Sid    = "CloudWatchMetrics"
        Effect = "Allow"
        Action = "cloudwatch:PutMetricData"
        Resource = "*"
        Condition = {
          StringEquals = {
            "cloudwatch:namespace" = "bedrock-agentcore"
          }
        }
      },
      {
        Sid    = "BedrockModelInvocation"
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream"
        ]
        # Specify exact ARNs (no wildcard Resource: *) - post simplified model access
        Resource = [
          "arn:aws:bedrock:*::foundation-model/us.anthropic.claude-sonnet-4-*",
          "arn:aws:bedrock:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:*"
        ]
      },
      {
        # Matches official AgentCore Runtime execution role policy (runtime-permissions.html).
        # All three token actions are required by the runtime; for production, explicitly
        # deny GetWorkloadAccessTokenForUserId in a separate Deny statement and restrict
        # to GetWorkloadAccessTokenForJWT only (see best-practice note above).
        Sid    = "AgentCoreWorkloadToken"
        Effect = "Allow"
        Action = [
          "bedrock-agentcore:GetWorkloadAccessToken",
          "bedrock-agentcore:GetWorkloadAccessTokenForJWT",
          "bedrock-agentcore:GetWorkloadAccessTokenForUserId"
        ]
        Resource = [
          "arn:aws:bedrock-agentcore:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:workload-identity-directory/default",
          "arn:aws:bedrock-agentcore:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:workload-identity-directory/default/workload-identity/${var.agent_name}-*"
        ]
      }
    ]
  })
}
```

_Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-permissions.html_

---

### ECR Repository + ARM64 build + aws_bedrockagentcore_agent_runtime

hashicorp/aws >= 6.18 required; `code_configuration` available from 6.22.

```hcl
# main.tf - deploy AgentCore Runtime with ARM64 container

resource "aws_ecr_repository" "agent" {
  name                 = "${var.project_prefix}-${var.agent_name}"
  image_tag_mutability = "IMMUTABLE"  # best practice: immutable tags in prod
  image_scanning_configuration {
    scan_on_push = true
  }
  encryption_configuration {
    encryption_type = "KMS"
  }
}

# Build and push ARM64 image (requires docker buildx on the runner)
# In CI/CD use CodeBuild with native ARM64 image to avoid cross-compilation
resource "null_resource" "build_push_arm64" {
  triggers = {
    source_hash = sha256(join("", [for f in fileset("${path.module}/agent", "**") : filesha256("${path.module}/agent/${f}")]))
  }

  provisioner "local-exec" {
    command = <<-EOT
      aws ecr get-login-password --region ${data.aws_region.current.name} | \
        docker login --username AWS --password-stdin \
        ${data.aws_caller_identity.current.account_id}.dkr.ecr.${data.aws_region.current.name}.amazonaws.com

      docker buildx build \
        --platform linux/arm64 \
        -t ${aws_ecr_repository.agent.repository_url}:${var.image_tag} \
        --push \
        ${path.module}/agent
    EOT
  }

  depends_on = [aws_ecr_repository.agent]
}

# Wait for IAM role to propagate before creating the runtime
resource "time_sleep" "iam_propagation" {
  create_duration = "15s"
  depends_on      = [aws_iam_role.agentcore_execution]
}

# aws_bedrockagentcore_agent_runtime - hashicorp/aws >= 6.18
# NOTE: ALWAYS specify both lifecycle_configuration values
# to avoid bug #45290 (inconsistent result after apply)
resource "aws_bedrockagentcore_agent_runtime" "main" {
  agent_runtime_name = "${var.project_prefix}-${var.agent_name}"
  description        = "Agent runtime for ${var.agent_name} - env ${var.environment}"
  role_arn           = aws_iam_role.agentcore_execution.arn

  agent_runtime_artifact {
    container_configuration {
      container_uri = "${aws_ecr_repository.agent.repository_url}:${var.image_tag}"
    }
  }

  network_configuration {
    network_mode = "PUBLIC"  # or "VPC" with security_groups and subnets
  }

  lifecycle_configuration {
    # ALWAYS specify both values (bug #45290: partial value causes inconsistent result)
    # Defaults: idle=900, max=28800. Constraint: idle <= max. Range: 60-28800.
    idle_runtime_session_timeout = 900    # 15 minutes (default)
    max_lifetime                 = 28800  # 8 hours (default)
  }

  environment_variables = {
    _CODE_VERSION = null_resource.build_push_arm64.triggers.source_hash
  }

  depends_on = [
    null_resource.build_push_arm64,
    time_sleep.iam_propagation
  ]
}

# Separate endpoint resource (argument 'name' required)
resource "aws_bedrockagentcore_agent_runtime_endpoint" "main" {
  name             = "${var.project_prefix}-${var.agent_name}-endpoint"
  agent_runtime_id = aws_bedrockagentcore_agent_runtime.main.agent_runtime_id
}

output "agent_runtime_arn" {
  value = aws_bedrockagentcore_agent_runtime.main.agent_runtime_arn
}
```

_Source: https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/bedrockagentcore_agent_runtime_

---

### Official aws-ia/agentcore/aws module v0.0.2

Abstracts ECR + ARM64 build. Early-stage (v0.0.2, April 2026) - evaluate API stability before production adoption.

```hcl
# main.tf - using the official aws-ia module v0.0.2
# NOTE: module is early-stage (v0.0.2, April 2026);
# evaluate API stability before production use
module "agentcore" {
  source  = "aws-ia/agentcore/aws"
  version = "~> 0.0.2"  # current version on Terraform Registry

  project_prefix = "myagent-prod"

  runtimes = {
    weather_agent = {
      source_type         = "CONTAINER"
      container_image_uri = "${data.aws_caller_identity.current.account_id}.dkr.ecr.${data.aws_region.current.name}.amazonaws.com/myagent-weather:latest"
      create_endpoint     = true
      environment_variables = {
        LOG_LEVEL = "INFO"
      }
      # Provide custom execution_role_arn for production least-privilege;
      # if omitted the module creates one automatically
      execution_role_arn = aws_iam_role.agentcore_execution.arn
    }
  }

  tags = {
    Environment = "prod"
    ManagedBy   = "terraform"
  }
}
```

_Source: https://github.com/aws-ia/terraform-aws-agentcore_

---

### Classic Bedrock Agent (aws_bedrockagent_agent) with prepare-agent workaround

Official AWS Prescriptive Guidance workaround for ensuring PREPARED state.

```hcl
# Classic Bedrock Agents (action groups, knowledge base)
resource "aws_bedrockagent_agent" "this" {
  agent_name              = "${var.environment}-${var.agent_name}"
  agent_resource_role_arn = aws_iam_role.bedrock_agent.arn
  foundation_model        = "us.anthropic.claude-sonnet-4-20250514-v1:0"
  instruction             = var.agent_instruction
  idle_session_ttl_in_seconds = 600
  prepare_agent           = true  # prepares the agent automatically on create/update
}

# Official AWS Prescriptive Guidance workaround to guarantee PREPARED state
# when prepare_agent = true is not sufficient (e.g. alias creation race)
resource "terraform_data" "prepare_agent" {
  triggers_replace = {
    agent_state = sha256(jsonencode(aws_bedrockagent_agent.this))
  }

  provisioner "local-exec" {
    command = "aws bedrock-agent prepare-agent --agent-id ${aws_bedrockagent_agent.this.agent_id} --region ${data.aws_region.current.name}"
  }
}

resource "time_sleep" "prepare_agent_sleep" {
  create_duration = "10s"  # wait for agent to reach PREPARED state
  lifecycle {
    replace_triggered_by = [terraform_data.prepare_agent]
  }
}
```

_Source: https://docs.aws.amazon.com/prescriptive-guidance/latest/terraform-data-limitations/bedrock-agents.html_

---

### IAM least-privilege policy for bedrock:InvokeModel (post simplified model access Oct 2025)

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowApprovedModelsOnly",
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream",
        "bedrock:Converse",
        "bedrock:ConverseStream",
        "bedrock:GetInferenceProfile"
      ],
      "Resource": [
        "arn:aws:bedrock:*::foundation-model/us.anthropic.claude-sonnet-4-*",
        "arn:aws:bedrock:*::foundation-model/amazon.nova-*",
        "arn:aws:bedrock:*:*:inference-profile/us.anthropic.claude-sonnet-4-*"
      ]
    }
  ]
}
```

_Source: https://aws.amazon.com/blogs/security/simplified-amazon-bedrock-model-access/_

---

### Dockerfile ARM64 for AgentCore Runtime (/invocations + /ping contract)

Confirmed against official getting-started-custom documentation.

```dockerfile
# Dockerfile - ARM64 mandatory for AgentCore Runtime
# Use official ARM64 base image with uv (confirmed in AWS documentation)
FROM --platform=linux/arm64 ghcr.io/astral-sh/uv:python3.11-bookworm-slim

WORKDIR /app

# Copy dependency manifest and install reproducibly
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-cache

# Copy agent code
COPY agent.py ./

# AgentCore Runtime requires port 8080
EXPOSE 8080

# Mandatory endpoints: POST /invocations and GET /ping on 0.0.0.0:8080
CMD ["uv", "run", "uvicorn", "agent:app", "--host", "0.0.0.0", "--port", "8080"]
```

_Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/getting-started-custom.html_

---

### CDK STABLE (Python) - deploy container AgentCore ARM64

Use `aws_cdk.aws_bedrockagentcore` (NOT the alpha module for Runtime). Only PolicyEngine remains in alpha.

```python
# cdk_stack.py - STABLE module for Runtime (migrated from alpha to stable)
# Import aws_cdk.aws_bedrockagentcore, NOT aws_cdk.aws_bedrock_agentcore_alpha
import aws_cdk as cdk
import aws_cdk.aws_bedrockagentcore as agentcore
import aws_cdk.aws_ecr as ecr

# Option 1: from existing ECR repository
repository = ecr.Repository.from_repository_name(self, "AgentRepo", "my-agent-repo")
artifact = agentcore.AgentRuntimeArtifact.from_ecr_repository(repository, "v1.0.0")

# Option 2: from local asset (automatic ARM64 build)
# artifact = agentcore.AgentRuntimeArtifact.from_asset(
#     path.join(__dirname, "./agent")  # directory with Dockerfile
# )

runtime = agentcore.Runtime(
    self, "MyAgentRuntime",
    runtime_name="my-agent",
    agent_runtime_artifact=artifact,
    network_configuration=agentcore.RuntimeNetworkConfiguration.using_public_network(),
    # Specify both lifecycle values for clarity
    lifecycle_configuration=agentcore.LifecycleConfiguration(
        idle_runtime_session_timeout=cdk.Duration.seconds(900),
        max_lifetime=cdk.Duration.seconds(28800),
    ),
)

# NOTE: PolicyEngine remains in the alpha module:
# import aws_cdk.aws_bedrock_agentcore_alpha as agentcore_alpha
# policy_engine = agentcore_alpha.PolicyEngine(self, "MyPolicyEngine", ...)
```

_Source: https://docs.aws.amazon.com/cdk/api/v2/docs/aws-cdk-lib.aws_bedrockagentcore-readme.html_

---

## Configuration reference

| Name | Description | Default / example |
|------|-------------|-------------------|
| `agent_runtime_artifact.container_configuration.container_uri` | ECR URI of the ARM64 image (e.g. `123456.dkr.ecr.us-east-1.amazonaws.com/myagent:tag`). Required for CONTAINER source type. From hashicorp/aws 6.22+, `container_configuration` is optional (to allow `code_configuration`). | `"${aws_ecr_repository.agent.repository_url}:${var.image_tag}"` |
| `agent_runtime_artifact.code_configuration` (hashicorp/aws >= 6.22) | Alternative to container: uses a ZIP on S3. Added in hashicorp/aws v6.22.0. Contains `entry_point` (list of 1-2 strings, e.g. `["main.py"]`), `runtime` (enum, e.g. `PYTHON_3_13`), and a nested `code { s3 { bucket = "...", prefix = "..." } }` block. The ZIP must contain ARM64 dependencies. Valid `runtime` values: `PYTHON_3_10`, `PYTHON_3_11`, `PYTHON_3_12`, `PYTHON_3_13`. | `code_configuration { entry_point = ["main.py"] runtime = "PYTHON_3_13" code { s3 { bucket = "mybucket" prefix = "agent.zip" } } }` |
| `role_arn` | ARN of the IAM execution role that AgentCore assumes to run the container. Must have trust policy with `bedrock-agentcore.amazonaws.com` and conditions `aws:SourceAccount` (StringEquals) + `aws:SourceArn` (ArnLike). | `aws_iam_role.agentcore_execution.arn` |
| `network_configuration.network_mode` | `PUBLIC` (direct internet access) or `VPC` (requires `security_groups` and `subnets`). Choose VPC for production with sensitive data. NOTE: known bug #46569 with VPC: multiple subnets not sent correctly to the API. Monitor fix in provider. | `"PUBLIC"` \| `"VPC"` |
| `lifecycle_configuration.idle_runtime_session_timeout` | Seconds of inactivity before the session is terminated. Min 60, max 28800 (8 hours). Default 900 (15 min). MUST be <= `max_lifetime`. ALWAYS specify both values to avoid bug #45290. | `900` |
| `lifecycle_configuration.max_lifetime` | Maximum absolute duration of a session in seconds. Min 60, max 28800 (8 hours). Default 28800. MUST be >= `idle_runtime_session_timeout`. ALWAYS specify both values to avoid bug #45290. | `28800` |
| `environment_variables` | Map of environment variables injected into the container at deploy time. Use a hash of the source code as `_CODE_VERSION` to force re-deploy when code changes without touching the image URI. | `{ _CODE_VERSION = sha256(source_hash) }` |
| `aws_bedrockagent_agent.foundation_model` | Foundation model ID for classic Bedrock Agent. Use cross-region inference profile (`us.anthropic.claude-*`) for regional resilience. | `"us.anthropic.claude-sonnet-4-20250514-v1:0"` |
| `aws_bedrockagent_agent.idle_session_ttl_in_seconds` | Session TTL for classic Bedrock Agent. Min 60, max 5400 (per Bedrock Agents API). | `600` |
| `backend s3 use_lockfile` | Enables S3 native locking. Introduced in Terraform 1.10.0; GA in Terraform 1.11.0 (DynamoDB locking formally deprecated in 1.11). For new projects use `required_version >= 1.11`. _Sources: https://github.com/hashicorp/terraform/releases/tag/v1.10.0 - https://github.com/hashicorp/terraform/releases/tag/v1.11.0_ | `true` |
| `provider aws assume_role.role_arn` | Role ARN to assume in every Terraform operation. Preferred over long-term access keys. The role must have a trust policy allowing the CI/CD runner to assume it via OIDC or instance profile. | `"arn:aws:iam::ACCOUNT_ID:role/terraform-execution-prod"` |

---

## Gotchas

- **AgentCore Runtime runs ONLY on ARM64 (Graviton).** An x86_64/amd64 container will be rejected at deploy time. Always use `FROM --platform=linux/arm64` in the Dockerfile and `docker buildx build --platform linux/arm64`.

- **`use_lockfile = true` for the S3 backend was introduced in Terraform 1.10.0 and became GA in Terraform 1.11.0.** For production use `required_version >= 1.11`. Do not configure both `use_lockfile` and `dynamodb_table` in new projects. _Sources: https://github.com/hashicorp/terraform/releases/tag/v1.10.0 - https://github.com/hashicorp/terraform/releases/tag/v1.11.0_

- **`aws_bedrockagentcore_agent_runtime` was introduced in hashicorp/aws v6.18.0** (milestone issue #43424). Version v6.21.0 contains changes to `aws_bedrockagentcore_browser` (not `aws_bedrockagentcore_agent_runtime`). The recommended minimum constraint is `~> 6.22` to also have `code_configuration`.

- **The `aws-ia/agentcore/aws` module is at version 0.0.2 on Terraform Registry (April 2026), NOT v1.0.** It is in early stage without API stability guarantees. Evaluate before production adoption.

- **The CDK stable module for Runtime, Gateway, Browser, Memory is `aws-cdk-lib/aws-bedrockagentcore` (Python: `aws_cdk.aws_bedrockagentcore`).** The module `aws_cdk.aws_bedrock_agentcore_alpha` contains ONLY PolicyEngine, Policy, PolicyStatement. Using the alpha module for already-stable constructs is incorrect.

- **`lifecycle_configuration` BUG (#45290):** specifying only one of the two values (e.g. only `max_lifetime`) causes `inconsistent result after apply` because the provider does not mark sub-attributes as Computed. Solution: ALWAYS specify both `idle_runtime_session_timeout` and `max_lifetime` explicitly.

- **Known VPC bug (#45099, #46569):** in VPC mode, ENIs created by AgentCore are not destroyed, causing hang on `terraform destroy`. VPCs remain blocked. Monitor fixes in provider release notes before using VPC mode.

- **Known VPC bug (#46569):** in VPC mode, only one subnet ID is sent to the `CreateAgentRuntime` API even when multiple are specified. The runtime may fail if that subnet has no connectivity.

- **`aws_bedrockagentcore_agent_runtime` has a state bug (#45620)** that in certain scenarios produces `object already exists` error with inconsistent state. Monitor release notes.

- **DynamoDB locking for remote state is DEPRECATED from Terraform 1.11.** Do not configure `dynamodb_table` and `use_lockfile` together in new projects.

- **Policy Engine (Cedar) for AgentCore Gateway is NOT yet natively supported in Terraform hashicorp/aws** (issue #47957, milestone v6.47.0, opened May 2026). It is supported in CloudFormation (`AWS::BedrockAgentCore::PolicyEngine`) and as alpha CDK constructs. Terraform workaround: `null_resource` + `local-exec` with AWS CLI.

- **Anthropic models (Claude) require a one-time form (terms-of-use acceptance, `PutUseCaseForModelAccess`) before first use**, even after the October 2025 simplification. This cannot be automated via standard Terraform; execute it manually or via AWS CLI in bootstrap.

- **The AgentCore execution role trust policy MUST include both conditions: `StringEquals aws:SourceAccount` AND `ArnLike aws:SourceArn`.** Without ArnLike, any runtime in the account can assume the role (confused deputy).

- **The `prepare_agent = true` flag in `aws_bedrockagent_agent` does not guarantee the agent is in PREPARED state before alias creation.** Always use the `terraform_data` + `time_sleep` workaround.

- **For Python dependencies with native code (e.g. numpy, cryptography) compiled on x86 hosts**, use `uv pip install --python-platform aarch64-manylinux2014 --only-binary=:all:` or run the build directly on an ARM64 machine or CodeBuild with AWS standard ARM64 image.

- **The `ecr:GetAuthorizationToken` permission in the execution role requires `Resource: *`** because it does not accept specific ARNs. This is not a configuration error but an IAM limitation of this specific ECR action.

- **Terraform workspaces do NOT replace distinct backends for environment isolation.** With shared workspaces an error can impact multiple environments simultaneously. Always use separate S3 buckets for dev/staging/prod.

---

## Official sources

- [Best practices for using the Terraform AWS Provider (AWS Prescriptive Guidance, Aug 2025)](https://docs.aws.amazon.com/prescriptive-guidance/latest/terraform-aws-provider-best-practices/introduction.html) - Official AWS guide on security, S3 backend, codebase structure, provider versioning
- [Backend best practices – Terraform AWS Provider (AWS Prescriptive Guidance)](https://docs.aws.amazon.com/prescriptive-guidance/latest/terraform-aws-provider-best-practices/backend.html) - S3 native locking (introduced in 1.10.0, GA in 1.11.0 per HashiCorp changelog), per-environment backend separation, CloudTrail monitoring. Confirmed: DynamoDB locking deprecated. Version details sourced from https://github.com/hashicorp/terraform/releases/tag/v1.11.0
- [Security best practices – Terraform AWS Provider (AWS Prescriptive Guidance)](https://docs.aws.amazon.com/prescriptive-guidance/latest/terraform-aws-provider-best-practices/security.html) - IAM roles, OIDC, no long-term credentials, IAM Access Analyzer
- [Code base structure – Terraform AWS Provider (AWS Prescriptive Guidance)](https://docs.aws.amazon.com/prescriptive-guidance/latest/terraform-aws-provider-best-practices/structure.html) - Standard repo structure: main.tf, variables.tf, outputs.tf, locals.tf, providers.tf, versions.tf
- [Deploying Amazon Bedrock agents – terraform_data limitations (AWS Prescriptive Guidance)](https://docs.aws.amazon.com/prescriptive-guidance/latest/terraform-data-limitations/bedrock-agents.html) - Official workaround for prepare-agent with terraform_data + local-exec + time_sleep
- [IAM Permissions for AgentCore Runtime (DevGuide official)](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-permissions.html) - Exact policies for execution role, trust policy with bedrock-agentcore.amazonaws.com. Confirmed: trust policy requires StringEquals aws:SourceAccount + ArnLike aws:SourceArn
- [Get started without the AgentCore CLI – ARM64 container contract](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/getting-started-custom.html) - Runtime contract: /invocations POST + /ping GET on port 8080, mandatory ARM64 image, confirmed official Dockerfile
- [Configure Amazon Bedrock AgentCore lifecycle settings](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-lifecycle-settings.html) - Confirmed defaults: idle=900s, max=28800s. Range 60-28800s. idleRuntimeSessionTimeout must be <= maxLifetime
- [Simplified model access in Amazon Bedrock (AWS Security Blog, Oct 2025)](https://aws.amazon.com/blogs/security/simplified-amazon-bedrock-model-access/) - PutFoundationModelEntitlement removed, automatic access, control via IAM/SCP; Anthropic still requires one-time form
- [Prerequisites for running model inference (Amazon Bedrock UserGuide)](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-prereq.html) - Minimum IAM permissions for InvokeModel, Converse, InvokeModelWithResponseStream
- [Deploy AI agents on Amazon Bedrock AgentCore using GitHub Actions (AWS ML Blog, Jan 2026)](https://aws.amazon.com/blogs/machine-learning/deploy-ai-agents-on-amazon-bedrock-agentcore-using-github-actions/) - CI/CD with OIDC GitHub->AWS, ECR+Inspector scan, detailed execution role policy
- [Build AI agents with Amazon Bedrock AgentCore using AWS CloudFormation (AWS ML Blog, Jan 2026)](https://aws.amazon.com/blogs/machine-learning/build-ai-agents-with-amazon-bedrock-agentcore-using-aws-cloudformation/) - IaC best practices for AgentCore: modular templates, parametrized design, IAM least-privilege
- [Best practices for managing Terraform State files in AWS CI/CD Pipeline (AWS DevOps Blog)](https://aws.amazon.com/blogs/devops/best-practices-for-managing-terraform-state-files-in-aws-ci-cd-pipeline/) - S3+DynamoDB (legacy), IAM policy for bucket, example with CodeBuild
- [aws-ia/terraform-aws-agentcore (official AWS-IA module on GitHub)](https://github.com/aws-ia/terraform-aws-agentcore) - Official module v0.0.2 (April 2026): uses awscc_bedrockagentcore_runtime internally, manages ECR+CodeBuild ARM64, auto-generated IAM. Version 0.0.2 on Terraform Registry - NOT v1.0
- [aws_bedrockagentcore_agent_runtime – Terraform Registry (hashicorp/aws)](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/bedrockagentcore_agent_runtime) - Native hashicorp/aws resource, introduced in v6.18.0. In v6.22.0 added: code_configuration block, container_configuration made optional
- [awscc_bedrockagentcore_runtime – Terraform Registry (hashicorp/awscc)](https://registry.terraform.io/providers/hashicorp/awscc/latest/docs/resources/bedrockagentcore_runtime) - Alternative awscc resource, confirmed present from awscc 1.57.0, used internally by aws-ia module
- [awslabs/amazon-bedrock-agentcore-samples – IaC Terraform examples](https://github.com/awslabs/amazon-bedrock-agentcore-samples/tree/main/04-infrastructure-as-code/terraform) - Official examples: basic runtime, MCP server, multi-agent, weather agent; uses CodeBuild ARM64
- [Amazon Bedrock AgentCore Construct Library – aws-cdk-lib/aws-bedrockagentcore (STABLE)](https://docs.aws.amazon.com/cdk/api/v2/docs/aws-cdk-lib.aws_bedrockagentcore-readme.html) - STABLE CDK module (no longer alpha) for Runtime, Gateway, Browser, Memory, Evaluation, Identity. Import: aws_cdk.aws_bedrockagentcore. Only PolicyEngine remains in alpha
- [Amazon Bedrock AgentCore Construct Library – aws-cdk.aws_bedrock_agentcore_alpha (Policy Engine only)](https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.aws_bedrock_agentcore_alpha/README.html) - The alpha module contains ONLY PolicyEngine, Policy, PolicyStatement (remained experimental). All other constructs migrated to stable module
- [AWS::BedrockAgentCore::PolicyEngine – AWS CloudFormation](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-bedrockagentcore-policyengine.html) - PolicyEngine is now natively supported in CloudFormation. Terraform: issue #47957 open, milestone v6.47.0
- [Bedrock AgentCore Support – Issue #43424 (hashicorp/terraform-provider-aws)](https://github.com/hashicorp/terraform-provider-aws/issues/43424) - Original issue for the introduction of AgentCore resources in hashicorp/aws, milestone v6.18.0
- [aws_bedrockagentcore_agent_runtime: lifecycle_configuration inconsistent result – Issue #45290](https://github.com/hashicorp/terraform-provider-aws/issues/45290) - Known bug: partially specified lifecycle_configuration produces inconsistent result after apply

---

## Verify live (open questions)

Re-check the following in the provider CHANGELOG / Terraform Registry before relying on this guide. These items were open as of June 2026.

1. **Policy Engine (Cedar) for AgentCore Gateway in Terraform:** issue #47957 open with milestone v6.47.0 (May 2026). Current workaround: `null_resource` + `local-exec` with AWS CLI (`aws bedrock-agentcore create-policy-engine` / `put-policy`). CloudFormation already supports `AWS::BedrockAgentCore::PolicyEngine`. CDK: alpha constructs `aws_cdk.aws_bedrock_agentcore_alpha`.

2. **VPC mode bugs (#45099, #46569):** ENIs not destroyed on `terraform destroy` and single-subnet bug. Both open. Before using VPC mode in production verify the status of fixes in provider release notes.

3. **The `aws-ia/agentcore/aws` module is at version 0.0.2 (April 2026)** without a guaranteed stable public version. Verify the current version on Terraform Registry before production adoption.

4. **`lifecycle_configuration` bug (#45290 - inconsistent result after apply with partial value):** has this been fixed in more recent provider versions? Verify in the provider CHANGELOG at the version in use.

5. **Native Terraform support for AgentCore Observability** (CloudWatch Transaction Search, endpoint observability): issue #44742 tracks support for the `observability` block. Verify current status.

6. **`aws_bedrockagentcore_agent_runtime` CODE source type (S3 ZIP) via `code_configuration` block** added from version 6.22 (issue #45040). Confirmed parameter names: `entry_point` (list), `runtime` (enum e.g. `PYTHON_3_13`), `code { s3 { bucket, prefix } }`. Verify stability in the provider version in use.

7. **When will CDK PolicyEngine be GA or stable?** Currently remains in `aws_cdk.aws_bedrock_agentcore_alpha` without a public timeline.

8. **`filesystem_configuration`** (mount of S3 Files access point or EFS) on `aws_bedrockagentcore_agent_runtime` was added in a recent provider version: verify the minimum required version in the CHANGELOG before use.
