# Deployment & IaC - Terraform (primary): Bedrock & AgentCore Resources

> Part of the **aws-bedrock-agentcore-skill** skill. See [SKILL.md](../SKILL.md) for the decision tree. Every source below is official - re-open it to verify details.

**Companion files (do not duplicate):**
- `deployment-best-practices.md` - cross-cutting IaC patterns, state management, CI/CD
- `deployment-cdk.md` - CDK constructs and AgentCore CLI (`agentcore deploy`)
- `deployment-frameworks.md` - Strands Agents, LangGraph, CrewAI framework-level deployment

---

## Table of contents

- [Part 1 - Terraform for Amazon Bedrock](#part-1--terraform-for-amazon-bedrock)
  - [Overview](#overview-part-1)
  - [Key concepts](#key-concepts-part-1)
  - [Best practices](#best-practices-part-1)
  - [Code](#code-part-1)
  - [Configuration reference](#configuration-reference-part-1)
  - [Gotchas](#gotchas-part-1)
  - [Official sources](#official-sources-part-1)
- [Part 2 - Terraform for Bedrock AgentCore](#part-2--terraform-for-bedrock-agentcore)
  - [Overview](#overview-part-2)
  - [Key concepts](#key-concepts-part-2)
  - [Best practices](#best-practices-part-2)
  - [Code](#code-part-2)
  - [Configuration reference](#configuration-reference-part-2)
  - [Gotchas](#gotchas-part-2)
  - [Official sources](#official-sources-part-2)
- [Verify live (open questions)](#verify-live-open-questions)

---

## Part 1 - Terraform for Amazon Bedrock

<a id="overview-part-1"></a>
### Overview

The `hashicorp/aws` provider (v6.x, latest ~v6.47 as of mid-2026) exposes Bedrock resources across three namespaces: `aws_bedrock_*` (account-level config), `aws_bedrockagent_*` (agent orchestration), and `aws_bedrockagentcore_*` (container-based AgentCore runtime, GA April 2026). The `hashicorp/awscc` provider mirrors CloudFormation and retains exclusive coverage for resources not yet promoted to the classic provider - most notably `awscc_bedrock_flow_alias` and `awscc_bedrock_flow_version`. The official `aws-ia/bedrock/aws` Terraform module wraps both providers and is the recommended starting point.

**Maturity:** GA in `hashicorp/aws` for core Bedrock resources (agents, knowledge bases, guardrails, flows); `aws_bedrockagentcore_*` resources are GA (April 2026, introduced v6.17.0+). Several advanced features (flow alias/version, automated reasoning, enforced guardrail config) remain `awscc`-only. Requires `hashicorp/aws >= ~6.27` for the full 8-backend knowledge base and `>= v5.69` for native `guardrail_configuration` on agents.

---

<a id="key-concepts-part-1"></a>
### Key concepts

**hashicorp/aws provider namespaces for Bedrock**
Three distinct namespaces in v6.x:
1. `aws_bedrock_*` - account-level configuration:
   - `aws_bedrock_custom_model` (added v5.35.0)
   - `aws_bedrock_guardrail` (v5.50+; `input_action`/`output_action` on PII since v6.8.0)
   - `aws_bedrock_guardrail_version` (v5.50+)
   - `aws_bedrock_inference_profile` (v5.65+)
   - `aws_bedrock_model_invocation_logging_configuration` (v5.49+)
   - `aws_bedrock_provisioned_model_throughput` (v5.45+)
2. `aws_bedrockagent_*` - agent orchestration:
   - `aws_bedrockagent_agent` (v5.49+; `guardrail_configuration` since v5.69)
   - `aws_bedrockagent_agent_alias` (v5.49+)
   - `aws_bedrockagent_agent_action_group` (v5.49+)
   - `aws_bedrockagent_agent_collaborator` (v5.68+, multi-agent)
   - `aws_bedrockagent_knowledge_base` (v5.49+; 8 storage backends since v6.27)
   - `aws_bedrockagent_data_source` (v5.49+)
   - `aws_bedrockagent_flow` (v6.x+)
   - `aws_bedrockagent_prompt` (v5.98+)
   - **NOT present:** `aws_bedrockagent_flow_alias`, `aws_bedrockagent_flow_version` - use `awscc_bedrock_flow_alias` / `awscc_bedrock_flow_version`
3. `aws_bedrockagentcore_*` - see Part 2.

**hashicorp/awscc provider for Bedrock**
Auto-generated from CloudFormation schemas; arrives faster for new features. Confirmed resources from `all_schemas.hcl`:
- `awscc_bedrock_agent`, `awscc_bedrock_agent_alias`, `awscc_bedrock_application_inference_profile`
- `awscc_bedrock_automated_reasoning_policy`, `awscc_bedrock_automated_reasoning_policy_version`
- `awscc_bedrock_blueprint`, `awscc_bedrock_data_automation_library`, `awscc_bedrock_data_automation_project`
- `awscc_bedrock_data_source`, `awscc_bedrock_enforced_guardrail_configuration`
- `awscc_bedrock_flow`, `awscc_bedrock_flow_alias` (**no classic equiv.**), `awscc_bedrock_flow_version` (**no classic equiv.**)
- `awscc_bedrock_guardrail`, `awscc_bedrock_guardrail_version`
- `awscc_bedrock_intelligent_prompt_router`, `awscc_bedrock_knowledge_base`
- `awscc_bedrock_prompt`, `awscc_bedrock_prompt_version`, `awscc_bedrock_resource_policy`

The `awscc_bedrockagentcore_*` set uses different resource names from the classic provider (e.g., `awscc_bedrockagentcore_runtime` vs `aws_bedrockagentcore_agent_runtime`).

**aws_bedrockagent_agent guardrail_configuration (CORRECTED)**
`aws_bedrockagent_agent` in the classic `hashicorp/aws` provider **does** have a `guardrail_configuration` block added in v5.69.0 (PR #39440, Issue #39404). The block takes `guardrail_identifier` and `guardrail_version`. It is no longer necessary to use `awscc_bedrock_agent` solely to attach a guardrail.

**aws_bedrock_guardrail input_action/output_action (CORRECTED)**
As of v6.8.0 (PR #43702), `aws_bedrock_guardrail` supports granular `input_action`, `output_action`, `input_enabled`, and `output_enabled` attributes on both `pii_entities_config` and `regexes_config` within `sensitive_information_policy_config`. The claim that only `awscc_bedrock_guardrail` supports per-direction action is **outdated** for provider v6.8.0+.

**aws_bedrockagent_knowledge_base expanded storage backends (CORRECTED)**
As of v6.27.0 (PR #45465, December 2025), the classic `aws_bedrockagent_knowledge_base` gained support for `OPENSEARCH_MANAGED_CLUSTER`, `NEPTUNE_ANALYTICS`, `S3_VECTORS`, and `MONGO_DB_ATLAS`. The classic provider now supports all 8 major backends: `OPENSEARCH_SERVERLESS`, `PINECONE`, `REDIS_ENTERPRISE_CLOUD`, `RDS`, `MONGO_DB_ATLAS`, `NEPTUNE_ANALYTICS`, `OPENSEARCH_MANAGED_CLUSTER`, `S3_VECTORS`. Using `awscc_bedrock_knowledge_base` is no longer required for these backends.

**Agent lifecycle: DRAFT → version → alias**
A Bedrock agent always starts in DRAFT state. In Terraform: `aws_bedrockagent_agent` has `prepare_agent = true` (default) to trigger preparation after agent-level changes. However, `aws_bedrockagent_agent_action_group` does **not** trigger re-preparation - requires a `null_resource` `local-exec` workaround. For SUPERVISOR agents with multi-agent collaboration, `prepare_agent` should not fire until collaborators are attached (active bug Issue #43059). `aws_bedrockagent_agent_alias` points to a specific version and is the stable endpoint for application integration.

**Flow lifecycle in Terraform: classic vs awscc**
`aws_bedrockagent_flow` exists in the classic provider for flow CRUD. However, `aws_bedrockagent_flow_alias` and `aws_bedrockagent_flow_version` do **not** exist in the classic provider - these are **only** available as `awscc_bedrock_flow_alias` and `awscc_bedrock_flow_version`. This is a confirmed gap that requires the hybrid provider pattern for any flow deployment beyond creation.

**IAM service roles: naming conventions and trust scope**
- Knowledge base role name must start with `AmazonBedrockExecutionRoleForKnowledgeBase_`
- Agent role name must start with `AmazonBedrockExecutionRoleForAgents_`
- Trust principal is `bedrock.amazonaws.com` with mandatory conditions: `StringEquals aws:SourceAccount` and `ArnLike AWS:SourceArn` pointing to the specific resource ARN. AWS docs explicitly recommend replacing the `*` wildcard after resource creation.
- For guardrail-attached agents the service role also needs `bedrock:ApplyGuardrail`.

---

<a id="best-practices-part-1"></a>
### Best practices

- **Use the hybrid provider pattern: hashicorp/aws for stable resources, hashicorp/awscc for features not yet in the classic provider** - The classic provider has higher quality (custom logic like `prepare_agent`, better docs, fewer drift bugs) but awscc receives new Bedrock features immediately via CloudFormation schemas. The pattern is explicitly endorsed by HashiCorp and is what the official `aws-ia/bedrock/aws` module does. _Source: https://www.hashicorp.com/en/blog/aws-and-awscc-terraform-providers-better-together_

- **Start with the aws-ia/bedrock/aws module rather than assembling resources from scratch** - The module correctly handles the `prepare_agent` workaround, IAM role naming conventions, OpenSearch Serverless policy ordering, `awscc` vs `aws` resource selection for flow alias/version, and agent lifecycle nuances. It encodes lessons that are not obvious from provider docs alone. _Source: https://registry.terraform.io/modules/aws-ia/bedrock/aws/latest_

- **Use `aws_bedrockagent_agent` guardrail_configuration (classic provider) rather than switching to awscc_bedrock_agent just for guardrails** - As of v5.69.0, the classic provider's `aws_bedrockagent_agent` has a native `guardrail_configuration` block. Switching the entire agent resource to `awscc_bedrock_agent` introduces Cloud Control API drift risks and lower documentation quality. Only use `awscc_bedrock_agent` if you have other awscc-only requirements. _Source: https://github.com/hashicorp/terraform-provider-aws/issues/39404_

- **Use granular `input_action` / `output_action` in `aws_bedrock_guardrail` for per-direction PII control (available since v6.8.0)** - Since v6.8.0 (PR #43702) the classic provider supports `input_action`, `output_action`, `input_enabled`, and `output_enabled` on `pii_entities_config` and `regexes_config`. Use these fields rather than migrating to `awscc_bedrock_guardrail` solely for direction-specific PII control. _Source: https://github.com/hashicorp/terraform-provider-aws/issues/42253_

- **Always create an explicit `aws_bedrock_guardrail_version` with `skip_destroy = true` for production guardrails** - The DRAFT version updates in-place on every `terraform apply`, which can silently change production behavior. A pinned version is immutable. `skip_destroy = true` prevents Terraform destroy from removing versions that live production aliases may still reference. _Source: https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/bedrock_guardrail_version_

- **For Bedrock Flows: use `aws_bedrockagent_flow` (classic) for the flow definition, but `awscc_bedrock_flow_alias` and `awscc_bedrock_flow_version` (awscc) for versioning and aliases** - `aws_bedrockagent_flow_alias` and `aws_bedrockagent_flow_version` do not exist in the classic `hashicorp/aws` provider. The official `aws-ia` module confirms the hybrid approach. _Source: https://github.com/aws-ia/terraform-aws-bedrock_

- **Add a `time_sleep` after IAM role policy attachments before creating Bedrock resources** - IAM changes take several seconds to propagate globally. Creating a Bedrock knowledge base or agent immediately after attaching the service role policy causes `AccessDeniedException`. A `time_sleep` of 15–60 seconds with `depends_on` on the IAM resources prevents this race condition. _Source: https://blog.avangards.io/how-to-manage-an-amazon-bedrock-knowledge-base-using-terraform_

- **Use `prepare_agent = true` on `aws_bedrockagent_agent` and add a `null_resource` local-exec for action group changes** - `aws_bedrockagent_agent` triggers `PrepareAgent` automatically when the agent itself changes. But `aws_bedrockagent_agent_action_group` does NOT re-prepare the agent. A `null_resource` with a local-exec calling `aws bedrock-agent prepare-agent --agent-id ...` triggered by the action group SHA addresses this gap. _Source: https://github.com/hashicorp/terraform-provider-aws/issues/39400_

- **Pre-create the OpenSearch Serverless collection with all three policy types before creating the knowledge base, and wait for collection ACTIVE status** - `aws_bedrockagent_knowledge_base` fails if the collection does not exist or if the Bedrock service role lacks AOSS data-access permissions. All three policy types (`aws_opensearchserverless_security_policy` encryption, network; `aws_opensearchserverless_access_policy` data) must be in place before KB creation. _Source: https://blog.avangards.io/how-to-manage-an-amazon-bedrock-knowledge-base-using-terraform_

- **For BedrockAgentCore gateway resources, use `lifecycle { ignore_changes = [description, protocol_configuration] }`** - Known provider bug: the gateway resource does not read back `description` and `protocol_configuration` from the API, causing perpetual drift on every plan. The `ignore_changes` lifecycle block prevents spurious updates until the upstream issue is resolved. _Source: https://dev.to/aws-builders/terraform-your-aws-agentcore-11kl_

- **For multiple `aws_bedrockagent_agent_action_group` resources on the same agent, create them sequentially (not in parallel) with explicit `depends_on` chains** - Creating multiple action groups in parallel triggers concurrent `PrepareAgent` calls, causing "Prepare operation cannot be performed on Agent when it is in Preparing state" errors. _Source: https://github.com/hashicorp/terraform-provider-aws/issues/42845_

- **Treat `aws_bedrock_model_invocation_logging_configuration` as a singleton - manage it in a dedicated Terraform state** - This resource configures a single account-region setting. If multiple Terraform configurations apply it, the last apply wins and silently disables logging configured by others. Isolate it in a shared-services state with state locking enabled. _Source: https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/bedrock_model_invocation_logging_configuration_

---

<a id="code-part-1"></a>
### Code

#### Provider block: hybrid aws + awscc configuration (required_providers)

```hcl
terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.27"
    }
    awscc = {
      source  = "hashicorp/awscc"
      version = "~> 1.86"
    }
  }
}

provider "aws" {
  region = "us-east-1"
}

provider "awscc" {
  region = "us-east-1"
}
```

_Source: https://www.hashicorp.com/en/blog/aws-and-awscc-terraform-providers-better-together_

---

#### aws_bedrockagent_agent – full IAM service role with trust policy, guardrail_configuration (native, v5.69+), and agent resource

```hcl
resource "aws_iam_role" "bedrock_agent" {
  name = "AmazonBedrockExecutionRoleForAgents_my_agent"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "bedrock.amazonaws.com" }
      Action    = "sts:AssumeRole"
      Condition = {
        StringEquals = { "aws:SourceAccount" = data.aws_caller_identity.current.account_id }
        ArnLike      = { "AWS:SourceArn" = "arn:aws:bedrock:us-east-1:${data.aws_caller_identity.current.account_id}:agent/*" }
      }
    }]
  })
}

resource "aws_iam_role_policy" "bedrock_agent_model" {
  name = "bedrock-agent-model-invoke"
  role = aws_iam_role.bedrock_agent.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["bedrock:InvokeModel"]
        Resource = ["arn:aws:bedrock:us-east-1::foundation-model/*"]
      },
      {
        Effect   = "Allow"
        Action   = ["bedrock:ApplyGuardrail"]
        Resource = [aws_bedrock_guardrail.this.guardrail_arn]
      }
    ]
  })
}

resource "time_sleep" "iam_propagation" {
  depends_on      = [aws_iam_role_policy.bedrock_agent_model]
  create_duration = "20s"
}

# guardrail_configuration is native in classic provider since v5.69.0
resource "aws_bedrockagent_agent" "this" {
  agent_name                  = "my-bedrock-agent"
  agent_resource_role_arn     = aws_iam_role.bedrock_agent.arn
  foundation_model            = "anthropic.claude-3-5-sonnet-20241022-v2:0"
  instruction                 = "You are a helpful assistant."
  idle_session_ttl_in_seconds = 1800
  prepare_agent               = true

  guardrail_configuration {
    guardrail_identifier = aws_bedrock_guardrail.this.guardrail_id
    guardrail_version    = aws_bedrock_guardrail_version.v1.version
  }

  depends_on = [time_sleep.iam_propagation]
  tags       = { ManagedBy = "terraform" }
}
```

_Source: https://github.com/hashicorp/terraform-provider-aws/issues/39404_

---

#### aws_bedrockagent_agent_action_group with null_resource re-prepare workaround

```hcl
resource "aws_bedrockagent_agent_action_group" "search" {
  action_group_name = "search-action-group"
  agent_id          = aws_bedrockagent_agent.this.agent_id
  agent_version     = "DRAFT"

  action_group_executor {
    lambda = aws_lambda_function.action_handler.arn
  }

  api_schema {
    s3 {
      s3_bucket_name = aws_s3_bucket.schemas.id
      s3_object_key  = "openapi/search-schema.yaml"
    }
  }
}

# action_group creation does NOT re-prepare the agent - workaround required
resource "null_resource" "prepare_agent" {
  triggers = {
    action_group_state = sha256(jsonencode(aws_bedrockagent_agent_action_group.search))
    agent_id           = aws_bedrockagent_agent.this.agent_id
  }
  provisioner "local-exec" {
    command = "aws bedrock-agent prepare-agent --agent-id ${aws_bedrockagent_agent.this.agent_id} --region us-east-1"
  }
  depends_on = [aws_bedrockagent_agent_action_group.search]
}
```

_Source: https://blog.avangards.io/how-to-manage-an-amazon-bedrock-agent-using-terraform_

---

#### aws_bedrockagent_agent_alias – stable production endpoint pinned to a version

```hcl
resource "aws_bedrockagent_agent_alias" "prod" {
  agent_id         = aws_bedrockagent_agent.this.agent_id
  agent_alias_name = "prod"
  description      = "Production alias"

  routing_configuration {
    agent_version = "1"   # pin to explicit version, never DRAFT
  }

  depends_on = [null_resource.prepare_agent]
  tags       = { Environment = "prod" }
}
```

_Source: https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/bedrockagent_agent_alias_

---

#### aws_bedrockagent_knowledge_base with OpenSearch Serverless backend + aws_bedrockagent_data_source

```hcl
resource "aws_iam_role" "bedrock_kb" {
  name = "AmazonBedrockExecutionRoleForKnowledgeBase_my_kb"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "bedrock.amazonaws.com" }
      Action    = "sts:AssumeRole"
      Condition = {
        StringEquals = { "aws:SourceAccount" = data.aws_caller_identity.current.account_id }
        ArnLike      = { "AWS:SourceArn" = "arn:aws:bedrock:us-east-1:${data.aws_caller_identity.current.account_id}:knowledge-base/*" }
      }
    }]
  })
}

resource "aws_opensearchserverless_security_policy" "kb_enc" {
  name   = "my-kb-enc"
  type   = "encryption"
  policy = jsonencode({
    Rules       = [{ Resource = ["collection/my-kb"], ResourceType = "collection" }]
    AWSOwnedKey = true
  })
}

resource "aws_opensearchserverless_security_policy" "kb_net" {
  name   = "my-kb-net"
  type   = "network"
  policy = jsonencode([{
    Rules = [
      { ResourceType = "collection", Resource = ["collection/my-kb"] },
      { ResourceType = "dashboard",  Resource = ["collection/my-kb"] }
    ]
    AllowFromPublic = true
  }])
}

resource "aws_opensearchserverless_access_policy" "kb_data" {
  name   = "my-kb-data"
  type   = "data"
  policy = jsonencode([{
    Rules = [
      {
        ResourceType = "index"
        Resource     = ["index/my-kb/*"]
        Permission   = ["aoss:CreateIndex","aoss:DescribeIndex","aoss:ReadDocument","aoss:UpdateIndex","aoss:WriteDocument"]
      },
      {
        ResourceType = "collection"
        Resource     = ["collection/my-kb"]
        Permission   = ["aoss:CreateCollectionItems","aoss:DescribeCollectionItems","aoss:UpdateCollectionItems"]
      }
    ]
    Principal = [aws_iam_role.bedrock_kb.arn, data.aws_caller_identity.current.arn]
  }])
}

resource "aws_opensearchserverless_collection" "kb" {
  name = "my-kb"
  type = "VECTORSEARCH"
  depends_on = [
    aws_opensearchserverless_security_policy.kb_enc,
    aws_opensearchserverless_security_policy.kb_net,
    aws_opensearchserverless_access_policy.kb_data,
  ]
}

resource "time_sleep" "iam_and_oss" {
  depends_on      = [aws_iam_role_policy.bedrock_kb_model, aws_opensearchserverless_collection.kb]
  create_duration = "60s"
}

resource "aws_bedrockagent_knowledge_base" "this" {
  name     = "my-knowledge-base"
  role_arn = aws_iam_role.bedrock_kb.arn

  knowledge_base_configuration {
    type = "VECTOR"
    vector_knowledge_base_configuration {
      embedding_model_arn = "arn:aws:bedrock:us-east-1::foundation-model/amazon.titan-embed-text-v2:0"
    }
  }

  storage_configuration {
    type = "OPENSEARCH_SERVERLESS"
    opensearch_serverless_configuration {
      collection_arn    = aws_opensearchserverless_collection.kb.arn
      vector_index_name = "bedrock-knowledge-base-default-index"
      field_mapping {
        vector_field   = "bedrock-knowledge-base-default-vector"
        text_field     = "AMAZON_BEDROCK_TEXT_CHUNK"
        metadata_field = "AMAZON_BEDROCK_METADATA"
      }
    }
  }
  depends_on = [time_sleep.iam_and_oss]
}

resource "aws_bedrockagent_data_source" "s3" {
  knowledge_base_id = aws_bedrockagent_knowledge_base.this.id
  name              = "my-kb-s3-source"
  data_source_configuration {
    type = "S3"
    s3_configuration {
      bucket_arn = aws_s3_bucket.kb_data.arn
    }
  }
}
```

_Source: https://blog.avangards.io/how-to-manage-an-amazon-bedrock-knowledge-base-using-terraform_

---

#### aws_bedrock_guardrail – with per-direction PII control (input_action/output_action, available since v6.8.0)

```hcl
resource "aws_bedrock_guardrail" "this" {
  name                      = "prod-ai-safety-guardrail"
  description               = "Content safety, PII protection, topic restrictions"
  blocked_input_messaging   = "This input violates our usage policies."
  blocked_outputs_messaging = "The response was blocked for safety reasons."

  content_policy_config {
    filters_config { type = "HATE";          input_strength = "HIGH";   output_strength = "HIGH"   }
    filters_config { type = "INSULTS";       input_strength = "HIGH";   output_strength = "HIGH"   }
    filters_config { type = "SEXUAL";        input_strength = "HIGH";   output_strength = "HIGH"   }
    filters_config { type = "VIOLENCE";      input_strength = "HIGH";   output_strength = "HIGH"   }
    filters_config { type = "MISCONDUCT";    input_strength = "MEDIUM"; output_strength = "MEDIUM" }
    filters_config { type = "PROMPT_ATTACK"; input_strength = "HIGH";   output_strength = "NONE"   }
  }

  topic_policy_config {
    topics_config {
      name       = "financial-advice"
      definition = "Specific investment recommendations or portfolio advice"
      examples   = ["Should I buy TSLA stock?", "Where should I invest my savings?"]
      type       = "DENY"
    }
  }

  word_policy_config {
    managed_word_lists_config { type = "PROFANITY" }
    words_config { text = "competitor-brand-a" }
  }

  sensitive_information_policy_config {
    # input_action / output_action available since hashicorp/aws v6.8.0
    pii_entities_config {
      type          = "EMAIL"
      action        = "ANONYMIZE"   # legacy single-direction field (still valid)
      input_action  = "ANONYMIZE"   # granular: v6.8.0+
      output_action = "BLOCK"       # granular: v6.8.0+
      input_enabled  = true
      output_enabled = true
    }
    pii_entities_config { type = "CREDIT_DEBIT_CARD_NUMBER"; action = "BLOCK" }
    regexes_config {
      name          = "employee-id"
      pattern       = "EMP-[0-9]{6}"
      action        = "ANONYMIZE"
      input_action  = "ANONYMIZE"
      output_action = "ANONYMIZE"
    }
  }

  contextual_grounding_policy_config {
    filters_config { type = "GROUNDING"; threshold = 0.75 }
    filters_config { type = "RELEVANCE"; threshold = 0.75 }
  }

  tags = { Environment = "prod", ManagedBy = "terraform" }
}

resource "aws_bedrock_guardrail_version" "v1" {
  guardrail_arn = aws_bedrock_guardrail.this.guardrail_arn
  description   = "Initial production version"
  skip_destroy  = true
}
```

_Source: https://github.com/hashicorp/terraform-provider-aws/issues/42253_

---

#### aws_bedrockagent_knowledge_base with MongoDB Atlas backend (classic provider since v6.27.0)

```hcl
# MONGO_DB_ATLAS is now available in the classic aws provider since v6.27.0
# (awscc_bedrock_knowledge_base remains an alternative)
resource "aws_bedrockagent_knowledge_base" "mongo" {
  name     = "my-mongo-kb"
  role_arn = aws_iam_role.bedrock_kb.arn

  knowledge_base_configuration {
    type = "VECTOR"
    vector_knowledge_base_configuration {
      embedding_model_arn = "arn:aws:bedrock:us-east-1::foundation-model/amazon.titan-embed-text-v2:0"
    }
  }

  storage_configuration {
    type = "MONGO_DB_ATLAS"
    mongo_db_atlas_configuration {
      collection_name        = "bedrock-kb"
      credentials_secret_arn = aws_secretsmanager_secret.mongo_creds.arn
      database_name          = "my_db"
      endpoint               = "cluster0.example.mongodb.net"
      vector_index_name      = "bedrock-index"
      field_mapping {
        metadata_field = "metadata"
        text_field     = "text"
        vector_field   = "embedding"
      }
    }
  }
}
```

_Source: https://github.com/hashicorp/terraform-provider-aws/pull/45465_

---

#### Flow lifecycle: aws_bedrockagent_flow (classic) + awscc_bedrock_flow_alias/version (awscc - no classic equivalent)

```hcl
# Flow definition: use classic provider
resource "aws_bedrockagent_flow" "this" {
  name              = "my-bedrock-flow"
  execution_role_arn = aws_iam_role.bedrock_flow.arn
  # ... definition block here
}

# Flow VERSION and ALIAS: aws_bedrockagent_flow_alias/version do NOT exist in
# the classic hashicorp/aws provider - use awscc_bedrock_flow_alias/version
resource "awscc_bedrock_flow_version" "v1" {
  flow_arn    = aws_bedrockagent_flow.this.arn
  description = "Initial version"
}

resource "awscc_bedrock_flow_alias" "prod" {
  flow_arn = aws_bedrockagent_flow.this.arn
  name     = "prod"
  routing_configuration = [{
    flow_version = awscc_bedrock_flow_version.v1.version
  }]
  tags = { Environment = "prod" }
}
```

_Source: https://github.com/aws-ia/terraform-aws-bedrock_

---

#### aws_bedrock_model_invocation_logging_configuration – singleton, S3 + CloudWatch destinations

```hcl
resource "aws_bedrock_model_invocation_logging_configuration" "this" {
  logging_config {
    text_data_delivery_enabled      = true
    image_data_delivery_enabled     = true
    embedding_data_delivery_enabled = true

    s3_config {
      bucket_name = aws_s3_bucket.bedrock_logs.id
      key_prefix  = "bedrock/invocation-logs"
    }

    cloudwatch_config {
      log_group_name = aws_cloudwatch_log_group.bedrock_logs.name
      role_arn       = aws_iam_role.bedrock_logging.arn
      large_data_delivery_s3_config {
        bucket_name = aws_s3_bucket.bedrock_logs.id
        key_prefix  = "bedrock/large-data"
      }
    }
  }

  depends_on = [
    aws_s3_bucket_policy.bedrock_logs,
    aws_iam_role_policy.bedrock_logging,
  ]
}
```

_Source: https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/bedrock_model_invocation_logging_configuration_

---

#### aws_bedrock_custom_model – fine-tuning job + aws_bedrock_provisioned_model_throughput

```hcl
resource "aws_bedrock_custom_model" "finetune" {
  custom_model_name     = "my-finetuned-cohere"
  job_name              = "finetune-cohere-command-v1"
  base_model_identifier = "cohere.command-light-text-v14:7:4k"
  customization_type    = "FINE_TUNING"  # or CONTINUED_PRE_TRAINING
  role_arn              = aws_iam_role.bedrock_custom_model.arn

  training_data_config {
    s3_uri = "s3://${aws_s3_bucket.training.id}/data/train.jsonl"
  }

  output_data_config {
    s3_uri = "s3://${aws_s3_bucket.training.id}/output/"
  }

  hyperparameters = {
    epochCount             = "1"
    batchSize              = "8"
    learningRate           = "0.00001"
    earlyStoppingPatience  = "6"
    earlyStoppingThreshold = "0.01"
    evalPercentage         = "20.0"
  }

  tags = { ManagedBy = "terraform" }
}

resource "aws_bedrock_provisioned_model_throughput" "this" {
  provisioned_model_name = "${aws_bedrock_custom_model.finetune.custom_model_name}-prod"
  model_arn              = aws_bedrock_custom_model.finetune.custom_model_arn
  model_units            = 1
  # commitment_duration  = "OneMonth"  # valid: OneMonth, SixMonths
}
```

_Source: https://aws.amazon.com/blogs/machine-learning/streamline-custom-model-creation-and-deployment-for-amazon-bedrock-with-provisioned-throughput-using-terraform/_

---

#### aws_bedrock_inference_profile – application inference profile for cost tracking

```hcl
data "aws_region" "current" {}

resource "aws_bedrock_inference_profile" "claude_tagged" {
  name        = "claude-production-profile"
  description = "Claude Sonnet profile with cost tags for team-A"

  model_source {
    copy_from = "arn:aws:bedrock:${data.aws_region.current.name}::foundation-model/anthropic.claude-3-5-sonnet-20241022-v2:0"
  }

  tags = { Team = "team-a", CostCenter = "1234" }
}

output "inference_profile_arn" {
  value = aws_bedrock_inference_profile.claude_tagged.arn
}
```

_Source: https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/bedrock_inference_profile_

---

#### awscc_bedrock_data_automation_project + awscc_bedrock_blueprint – Bedrock Data Automation (BDA)

```hcl
resource "awscc_bedrock_data_automation_project" "docs" {
  project_name        = "document-extraction-project"
  project_description = "Extracts structured data from PDFs and images"

  standard_output_configuration = {
    document = {
      types_of_documents_with_text_response = ["NATIVE_RICH_TEXT"]
    }
  }

  tags = [{ key = "ManagedBy", value = "terraform" }]
}

resource "awscc_bedrock_blueprint" "invoice" {
  blueprint_name = "invoice-extractor"
  type           = "DOCUMENT"
  schema = jsonencode({
    type = "object"
    properties = {
      vendor_name  = { type = "string" }
      total_amount = { type = "number" }
      invoice_date = { type = "string", format = "date" }
    }
  })
}
```

_Source: https://github.com/aws-ia/terraform-aws-bedrock/blob/main/bda.tf_

---

<a id="configuration-reference-part-1"></a>
### Configuration reference

| Name | Description | Default / example |
|------|-------------|-------------------|
| `aws_bedrockagent_agent – foundation_model` | Required. Model identifier for orchestration. Use full model ID or inference profile ARN. Cross-region system profiles (`us.anthropic.claude-3-5-sonnet-20241022-v2:0`) are supported. | `anthropic.claude-3-5-sonnet-20241022-v2:0` |
| `aws_bedrockagent_agent – prepare_agent` | Optional bool. When true (default), Terraform calls `PrepareAgent` after create or update of the agent resource itself. Does NOT fire after action group changes. For SUPERVISOR agents with multi-agent collaboration, set to `false` and call prepare manually (Issue #43059). | `true` |
| `aws_bedrockagent_agent – guardrail_configuration` | Optional block. Added in v5.69.0 (PR #39440). Takes `guardrail_identifier` (guardrail ID or ARN) and `guardrail_version` (numeric string or DRAFT). Requires `bedrock:ApplyGuardrail` on agent service role. | `guardrail_configuration { guardrail_identifier = "abc123" guardrail_version = "1" }` |
| `aws_bedrockagent_agent – idle_session_ttl_in_seconds` | Optional. How long (seconds) to keep an agent session open. Range: 60–3600. | `1800` |
| `aws_bedrockagent_knowledge_base – storage_configuration.type` | Required. Valid values in classic aws provider as of v6.27.0: `OPENSEARCH_SERVERLESS`, `PINECONE`, `REDIS_ENTERPRISE_CLOUD`, `RDS`, `MONGO_DB_ATLAS`, `NEPTUNE_ANALYTICS`, `OPENSEARCH_MANAGED_CLUSTER`, `S3_VECTORS`. `awscc_bedrock_knowledge_base` adds `KENDRA` and SQL/Redshift (`STRUCTURED` type). | `OPENSEARCH_SERVERLESS` |
| `aws_bedrockagent_agent_action_group – agent_version` | Required. The agent version the action group belongs to. Only `DRAFT` is valid at creation time. | `DRAFT` |
| `aws_bedrock_guardrail – sensitive_information_policy_config.pii_entities_config` | Supports: `type` (required), `action` (legacy, both directions), `input_action` (v6.8.0+), `output_action` (v6.8.0+), `input_enabled` (v6.8.0+, bool), `output_enabled` (v6.8.0+, bool). Valid action values: `BLOCK`, `ANONYMIZE`. | `pii_entities_config { type = "EMAIL"; input_action = "ANONYMIZE"; output_action = "BLOCK" }` |
| `aws_bedrock_guardrail – content_policy_config.filters_config.type` | Required for each filter block. Valid values: `HATE`, `INSULTS`, `SEXUAL`, `VIOLENCE`, `MISCONDUCT`, `PROMPT_ATTACK`. `PROMPT_ATTACK` only applies to input; set `output_strength = NONE`. | `HATE \| INSULTS \| SEXUAL \| VIOLENCE \| MISCONDUCT \| PROMPT_ATTACK` |
| `aws_bedrock_guardrail_version – skip_destroy` | Optional bool (default `false`). When `true`, the version is NOT deleted on `terraform destroy`. Set to `true` for production versions still referenced by running applications. | `true` |
| `aws_bedrock_custom_model – customization_type` | Required. `FINE_TUNING`: adapts model on labeled input/output pairs. `CONTINUED_PRE_TRAINING`: continues pre-training on unlabeled text. Not all base models support both types. | `FINE_TUNING \| CONTINUED_PRE_TRAINING` |
| `aws_bedrock_provisioned_model_throughput – commitment_duration` | Optional. Omit for on-demand (no commitment, higher per-unit price). Valid values: `OneMonth`, `SixMonths`. Committing to custom models is required for a persistent endpoint. | `OneMonth \| SixMonths` |
| `aws_bedrock_model_invocation_logging_configuration – logging_config` | Required block. Contains `text_data_delivery_enabled`, `image_data_delivery_enabled`, `embedding_data_delivery_enabled` (all bool), plus `s3_config` and/or `cloudwatch_config`. At least one delivery target must be specified. | `text_data_delivery_enabled = true, s3_config { bucket_name = "...", key_prefix = "bedrock/" }` |
| `aws_bedrock_inference_profile – model_source.copy_from` | Required for application inference profiles. Full ARN of the foundation model to wrap. The profile inherits model capabilities and adds cost tagging. | `arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-3-5-sonnet-20241022-v2:0` |
| `IAM role naming convention` | KB roles must be prefixed with `AmazonBedrockExecutionRoleForKnowledgeBase_`; agent roles with `AmazonBedrockExecutionRoleForAgents_`. These prefixes are enforced by the Bedrock service trust evaluation. | `AmazonBedrockExecutionRoleForAgents_my_agent` |
| `IAM trust policy – ArnLike condition` | Required condition on the `bedrock.amazonaws.com` trust relationship. `AWS:SourceArn` restricts which Bedrock resource can assume the role. AWS docs recommend replacing `*` with specific IDs after resource creation. | `arn:aws:bedrock:us-east-1:123456789012:agent/*` |

---

<a id="gotchas-part-1"></a>
### Gotchas

- **CORRECTED:** `aws_bedrockagent_agent` DOES have a native `guardrail_configuration` block since v5.69.0 - it is NOT awscc-only. The earlier claim that only `awscc_bedrock_agent` supports guardrail association is outdated.
- **CORRECTED:** `aws_bedrock_guardrail` DOES support per-direction `input_action`/`output_action` on `pii_entities_config` and `regexes_config` since v6.8.0. The earlier claim that this requires `awscc_bedrock_guardrail` is outdated for provider v6.8.0+.
- **CORRECTED:** `aws_bedrockagent_knowledge_base` supports `MONGO_DB_ATLAS`, `NEPTUNE_ANALYTICS`, `OPENSEARCH_MANAGED_CLUSTER`, and `S3_VECTORS` in the classic provider since v6.27.0. Using `awscc_bedrock_knowledge_base` is no longer required for these backends.
- `aws_bedrockagent_flow_alias` and `aws_bedrockagent_flow_version` **DO NOT EXIST** in the classic `hashicorp/aws` provider. For flow alias and version management, use `awscc_bedrock_flow_alias` and `awscc_bedrock_flow_version`. The official `aws-ia/terraform-aws-bedrock` module confirms this pattern.
- `aws_bedrockagent_action_group` does NOT trigger `PrepareAgent` after creation or update - the agent stays in `NOT_PREPARED` state. A `null_resource` with `local-exec` calling `aws bedrock-agent prepare-agent --agent-id ...` is required.
- Creating multiple `aws_bedrockagent_agent_action_group` resources in parallel causes "Prepare operation cannot be performed on Agent when it is in Preparing state". Use explicit `depends_on` chains between action groups to serialize creation.
- SUPERVISOR agents with multi-agent collaboration and `prepare_agent = true` may fail during creation when no collaborators are defined yet (Issue #43059). Set `prepare_agent = false` for SUPERVISOR agents and call prepare manually via `null_resource` after all collaborators are attached.
- `aws_bedrock_model_invocation_logging_configuration` is a singleton per account per region. Defining it in more than one Terraform state causes silent overwrites. Manage it in a dedicated shared-services stack.
- `aws_bedrock_guardrail` always updates the DRAFT version in-place. If production model invocations reference DRAFT (not a pinned version), every `terraform apply` silently changes production guardrail behavior. Always use `aws_bedrock_guardrail_version` with `skip_destroy = true`.
- IAM role propagation lag: attaching a policy to an IAM role and immediately creating a Bedrock knowledge base or agent causes `AccessDeniedException`. A `time_sleep` of 15–60 seconds with `depends_on` is required.
- OpenSearch Serverless: the collection requires all three policy types (encryption, network, data access) before the collection is created, and the collection must be ACTIVE before the knowledge base can be created.
- `awscc_bedrockagentcore_gateway` and `aws_bedrockagentcore_gateway` have a known drift issue: `description` and `protocol_configuration` are not read back from the API, causing perpetual plan diffs. Workaround: `lifecycle { ignore_changes = [description, protocol_configuration] }`.
- `aws_bedrock_custom_model` is an asynchronous long-running job. Terraform polls until completion, which can take hours. There is no way to cancel a running training job via `terraform destroy` - destroy only removes the Terraform resource record.
- The `awscc` provider and classic provider have **different resource names** for the same AgentCore concept: `awscc_bedrockagentcore_runtime` maps to `aws_bedrockagentcore_agent_runtime`; `awscc_bedrockagentcore_o_auth_2_credential_provider` maps to `aws_bedrockagentcore_oauth2_credential_provider`. Do not mix both providers managing the same logical resource.
- System-defined cross-region inference profiles (e.g., `us.anthropic.claude-3-5-sonnet-20241022-v2:0`) are NOT managed with `aws_bedrock_inference_profile` - use `data.aws_bedrock_inference_profile`. The resource is only for creating application inference profiles.
- Model access must be explicitly enabled in the AWS console or via the Bedrock API before any resource that invokes a foundation model can succeed. Terraform has no native resource for enabling model access - use a `null_resource` or handle it as a pre-flight step.
- `aws_bedrockagent_data_source` has no "sync" or "ingest" capability - after creation the data source must be synced via console, CLI (`aws bedrock-agent start-ingestion-job`), or a `null_resource` `local-exec`.

---

<a id="official-sources-part-1"></a>
### Official sources

- [AWS CloudFormation – AWS::Bedrock resource type reference (all 20 CFN resource types)](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/AWS_Bedrock.html) - Canonical list of every Bedrock resource that CloudFormation (and therefore awscc) supports. Confirmed 20 types as of June 2026: Agent, AgentAlias, ApplicationInferenceProfile, AutomatedReasoningPolicy, AutomatedReasoningPolicyVersion, Blueprint, DataAutomationLibrary, DataAutomationProject, DataSource, EnforcedGuardrailConfiguration, Flow, FlowAlias, FlowVersion, Guardrail, GuardrailVersion, IntelligentPromptRouter, KnowledgeBase, Prompt, PromptVersion, ResourcePolicy.
- [Amazon Bedrock – create resources with CloudFormation (Bedrock User Guide)](https://docs.aws.amazon.com/bedrock/latest/userguide/cfn-bedrock-resources.html) - Official list of supported CloudFormation resource types for Bedrock control-plane.
- [Terraform Registry – hashicorp/aws provider (Bedrock resources)](https://registry.terraform.io/providers/hashicorp/aws/latest/docs) - Primary reference for all `aws_bedrock_*`, `aws_bedrockagent_*`, `aws_bedrockagentcore_*` resources and data sources.
- [Terraform Registry – hashicorp/awscc provider (awscc_bedrock_*)](https://registry.terraform.io/providers/hashicorp/awscc/latest/docs) - Cloud Control API-backed provider. Authoritative for `awscc_bedrock_flow_alias/version`, `awscc_bedrock_automated_reasoning_policy`, `awscc_bedrock_enforced_guardrail_configuration`, `awscc_bedrock_intelligent_prompt_router`, `awscc_bedrock_data_automation_library`, and all `awscc_bedrockagentcore_*` resources.
- [aws-ia/terraform-aws-bedrock – official AWS module (Terraform Registry)](https://registry.terraform.io/modules/aws-ia/bedrock/aws/latest) - Official AWS-IA module. Internally uses `awscc_bedrock_flow_alias/version` (not `aws_`), `awscc_bedrock_prompt/prompt_version`, and `awscc_bedrock_knowledge_base` only for backends not yet in classic provider.
- [aws-ia/terraform-aws-bedrock – GitHub source](https://github.com/aws-ia/terraform-aws-bedrock) - Source confirms the module uses `awscc_bedrock_flow_alias` and `awscc_bedrock_flow_version` for flow management; `awscc_bedrock_data_automation_project` and `awscc_bedrock_blueprint` in `bda.tf`.
- [AWS Blog – Deploy Amazon Bedrock Knowledge Bases using Terraform for RAG](https://aws.amazon.com/blogs/machine-learning/deploy-amazon-bedrock-knowledge-bases-using-terraform-for-rag-based-generative-ai-applications/) - AWS official blog with working Terraform example for `aws_bedrockagent_knowledge_base` + OpenSearch Serverless.
- [AWS Blog – Streamline custom model creation with Provisioned Throughput using Terraform](https://aws.amazon.com/blogs/machine-learning/streamline-custom-model-creation-and-deployment-for-amazon-bedrock-with-provisioned-throughput-using-terraform/) - Shows `aws_bedrock_provisioned_model_throughput` + aws-ia module for fine-tuning and provisioned capacity.
- [Amazon Bedrock Agents – IAM service role permissions](https://docs.aws.amazon.com/bedrock/latest/userguide/agents-permissions.html) - Required trust policy, identity-based policies for model invocation, knowledge base retrieval, guardrail (`bedrock:ApplyGuardrail`), collaborator access, and provisioned throughput.
- [Amazon Bedrock Knowledge Bases – IAM service role permissions](https://docs.aws.amazon.com/bedrock/latest/userguide/kb-permissions.html) - Trust policy, model invocation, S3 data source, OpenSearch Serverless, Neptune, RDS, Pinecone/Redis Secrets Manager permissions.
- [awslabs/amazon-bedrock-agentcore-samples – Terraform IaC examples](https://github.com/awslabs/amazon-bedrock-agentcore-samples/blob/main/04-infrastructure-as-code/terraform/README.md) - Official AgentCore samples showing basic-runtime, mcp-server, multi-agent, and end-to-end patterns.
- [HashiCorp Blog – AWS and AWSCC Terraform providers: Better together](https://www.hashicorp.com/en/blog/aws-and-awscc-terraform-providers-better-together) - Explains the hybrid-provider pattern: use `aws` for stable resources, `awscc` for cutting-edge/new features.
- [hashicorp/terraform-provider-awscc – all_schemas.hcl (awscc resource list)](https://github.com/hashicorp/terraform-provider-awscc/blob/main/internal/provider/all_schemas.hcl) - Authoritative source for the complete list of `awscc_bedrock_*` and `awscc_bedrockagentcore_*` resources.
- [AWS Prescriptive Guidance – Configure model invocation logging in Bedrock using CloudFormation](https://docs.aws.amazon.com/prescriptive-guidance/latest/patterns/configure-bedrock-invocation-logging-cloudformation.html) - Architecture and IAM requirements for `aws_bedrock_model_invocation_logging_configuration`.

---

## Part 2 - Terraform for Bedrock AgentCore

<a id="overview-part-2"></a>
### Overview

Amazon Bedrock AgentCore is supported in Terraform via `hashicorp/aws` (first release: **v6.17.0, October 2025**) and `hashicorp/awscc` (first release: **v1.57.0, September 2025**). The `hashicorp/aws` provider contains **16 native `aws_bedrockagentcore_*` resources** (0 data sources). The `hashicorp/awscc` provider exposes the same resources via Cloud Control API with broader coverage for advanced features (custom browser/code interpreter, payment credential provider, policy engine, dataset, browser profile).

The official module `aws-ia/terraform-aws-agentcore` is at **v1.0.0 (February 2026)** and internally uses `awscc_bedrockagentcore_runtime` (not `aws_bedrockagentcore_agent_runtime`) for runtimes, combining `awscc` and `aws` for gateway targets and memory resources.

The AgentCore CLI supports CDK natively (announced April 2026). Terraform CLI support is "coming soon" - not yet released as of June 2026.

**Maturity:** GA (April 2026). Provider `hashicorp/aws`: 16 resources, 0 data sources. Provider `hashicorp/awscc`: parallel resources plus `awscc`-only resources (custom browser, custom code interpreter, dataset, evaluator, payment credential provider, policy, policy engine, browser profile). Module `aws-ia/terraform-aws-agentcore` v1.0.0: stable API. CloudFormation: 20 resource types.

---

<a id="key-concepts-part-2"></a>
### Key concepts

**aws_bedrockagentcore_agent_runtime**
Terraform native resource (provider `hashicorp/aws`, first version: v6.17.0, October 2025). Required arguments: `agent_runtime_name` (pattern `[a-zA-Z][a-zA-Z0-9_]{0,47}`), `role_arn`, `network_configuration`, `agent_runtime_artifact`. The `agent_runtime_artifact` field accepts `container_configuration` (ECR URI) or `code_configuration` (S3 zip, added in v6.22.0). `filesystem_configuration` was added in v6.46.0 (May 2026) for mounting EFS, S3 Files, or session storage. `authorizer_configuration.custom_jwt_authorizer` supports `custom_claim` (v6.38.0) and `allowed_scopes` (v6.36.0). Changing `agent_runtime_name` requires replacement.

**aws_bedrockagentcore_memory**
Manages AgentCore memory. Required arguments: `name` (pattern `[a-zA-Z][a-zA-Z0-9_]{0,47}`, ForceNew), `event_expiry_duration` (3–365 days, no interruption). Optional: `memory_execution_role_arn` (no interruption), `encryption_key_arn` (requires replacement). Memory strategies are NOT inline - use the separate `aws_bedrockagentcore_memory_strategy` resource.

**aws_bedrockagentcore_memory_strategy**
Separate resource for memory strategies. Required argument: `memory_id`. Built-in types: `semantic_memory_strategy`, `summary_memory_strategy`, `user_preference_memory_strategy`, `episodic_memory_strategy` (`EPISODIC` added in v6.43.0, April 2026). Limit: max 1 built-in strategy per type, max 6 strategies total per memory.

**aws_bedrockagentcore_gateway and aws_bedrockagentcore_gateway_target**
Gateway creates the MCP proxy toward tools and APIs. Required arguments: `name` (pattern `^([0-9a-zA-Z][-]?){1,100}$`), `role_arn`, `authorizer_type` (classic `aws` provider: `CUSTOM_JWT | AWS_IAM`; awscc/CFN also adds `NONE | AUTHENTICATE_ONLY`; ForceNew in the `aws` provider). GatewayTarget: required `name` and `target_configuration`; `gateway_identifier` is optional but requires replacement if changed. `credential_provider_configuration` made optional in v6.21.0. `mcp.mcp_server` support added v6.21.0; `target_configuration.mcp.api_gateway` added v6.38.0.

**aws_bedrockagentcore_workload_identity**
Creates an OAuth2-based identity for agentic workloads. Required argument: `name` (3–255 char, pattern `[A-Za-z0-9_.-]+`, ForceNew). Optional: `allowed_resource_oauth2_return_urls` (array of strings). Tags are a **map of strings** in Terraform HCL - NOT an array of `{key, value}` objects (that is the CloudFormation/API JSON structure, not HCL).

**aws_bedrockagentcore_browser and aws_bedrockagentcore_code_interpreter**
Resources in the `aws` provider (introduced v6.17.0) for the managed browser and code interpreter. Arguments: `name`, `description`, `network_configuration.network_mode` (`PUBLIC`/`VPC`). **Critical distinction:** `aws_bedrockagentcore_browser` and `aws_bedrockagentcore_code_interpreter` (managed, no `execution_role_arn`) vs `awscc_bedrockagentcore_browser_custom` and `awscc_bedrockagentcore_code_interpreter_custom` (custom, with `execution_role_arn` and `recording_config`). The `aws-ia` module uses the `awscc` custom variants.

**awscc_bedrockagentcore_runtime**
Cloud Control resource (provider `awscc` v1.57.0+) mapping directly to `AWS::BedrockAgentCore::Runtime`. This is the resource used by the `aws-ia/terraform-aws-agentcore` module. Supports `code_configuration` (S3 source), `container_configuration` (ECR), `network_configuration.network_mode_config` with `security_groups` and `subnets`, `protocol_configuration` (string: `MCP | HTTP | A2A | AGUI` - all four valid in awscc/CFN; the classic `aws` provider supports `MCP | HTTP | A2A` only, not `AGUI`), `filesystem_configurations` (array with `EfsAccessPoint`, `S3FilesAccessPoint`, `SessionStorage`).

**Module aws-ia/terraform-aws-agentcore v1.0.0**
Official AWS module (org `aws-ia`) v1.0.0 (February 2026). Requires Terraform >= 1.14, `aws >= 6.18.0`, `awscc >= 1.30.0`. Internally uses: `awscc_bedrockagentcore_runtime` (for CODE and CONTAINER runtimes), `awscc_bedrockagentcore_runtime_endpoint`, `awscc_bedrockagentcore_memory`, `awscc_bedrockagentcore_gateway`, `awscc_bedrockagentcore_browser_custom`, `awscc_bedrockagentcore_code_interpreter_custom`, and `aws_bedrockagentcore_gateway_target`. Manages ARM64 build automatically via `terraform_data` + CodeBuild. No `null_resource` in recent versions.

**aws_bedrockagentcore_harness**
Resource added in v6.46.0 (May 2026, `aws` provider) and v1.86.0 (`awscc`). Manages the AgentCore managed agent loop: define and invoke agents with a single API call specifying model, system prompt, and tools. Each session runs in an isolated microVM.

**Pattern: CodeBuild for container builds in awslabs samples**
The `awslabs/agentcore-samples` use `aws_codebuild_project` + `null_resource.trigger_build` (with local-exec invoking a shell script) to build and push ARM64 images to ECR. The runtime depends on `null_resource` via `depends_on`. The `aws-ia` v1.0.0 module uses `terraform_data` for build triggers, eliminating `null_resource`. Both patterns require AWS CLI in the CI/CD environment.

**AgentCore Runtime - microVM architecture and protocols**
Each session runs in an isolated microVM (dedicated CPU, memory, filesystem). Supports real-time and long-running sessions up to 8 hours. Supported frameworks: LangGraph, CrewAI, LlamaIndex, Strands Agents, Google ADK, OpenAI Agents SDK. CloudFormation/awscc-confirmed protocols: `MCP`, `HTTP`, `A2A`, `AGUI`; the classic `aws` provider supports `MCP`, `HTTP`, `A2A` (`AGUI` is awscc/CFN only). ARM64 (AWS Graviton) only. Direct code deployment (S3 zip) supported from `aws` provider v6.22.0.

---

<a id="best-practices-part-2"></a>
### Best practices

- **Use the `aws-ia/terraform-aws-agentcore` v1.0.0 module for new projects instead of calling raw resources** - The module automatically manages the ARM64 CodeBuild pipeline, minimal IAM roles, ECR lifecycle, resource dependencies, and uses `terraform_data` instead of `null_resource`. The v1.0.0 (February 2026) has a stable API. _Source: https://github.com/aws-ia/terraform-aws-agentcore_

- **Apply the trust policy with `aws:SourceAccount` and `aws:SourceArn` conditions on the Runtime execution role** - AWS prescribes these conditions to prevent confused-deputy attacks. The primary service to authorize is `bedrock-agentcore.amazonaws.com`. Confirmed in official `awslabs/agentcore-samples` examples. _Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-permissions.html_

- **Do not use `BedrockAgentCoreFullAccess` without additional restrictions in production** - The managed policy includes `GetWorkloadAccessTokenForUserId` which issues tokens without IdP verification. For production, grant only `GetWorkloadAccessTokenForJWT` and `GetWorkloadAccessToken` with specific resource ARNs. However, the awslabs samples use `BedrockAgentCoreFullAccess` + supplemental inline policy: follow that pattern by adding an explicit deny on `GetWorkloadAccessTokenForUserId`. _Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-permissions.html_

- **Choose `aws` vs `awscc` provider based on the specific use case** - The awslabs samples use only `aws` provider (`~> 6.21`) without `awscc`. The `aws-ia` module uses `awscc` for Runtime/RuntimeEndpoint/Memory/Gateway (for advanced `code_configuration`, `network_mode_config`, `protocol_configuration`) and `aws` for GatewayTarget. Use `awscc` when you need: `protocol_configuration` `AGUI` (the `aws` provider supports `MCP | HTTP | A2A` but not `AGUI`), `filesystem_configurations` with `EfsAccessPoint`/`S3FilesAccessPoint` structure, `recording_config` on browser, `code_configuration` S3 with alternative structure. _Source: https://github.com/aws-ia/terraform-aws-agentcore_

- **Declare `aws` provider with version `>= 6.22` for `code_configuration`, `>= 6.46` for `filesystem_configuration`** - `aws_bedrockagentcore_agent_runtime` received relevant updates: `code_configuration` in v6.22.0 (November 2025), `filesystem_configuration` in v6.46.0 (May 2026). For production, constrain to a known-good minimum version rather than `~> 6.17`. _Source: https://github.com/hashicorp/terraform-provider-aws/releases_

- **Use explicit `depends_on` between `null_resource`/`terraform_data` build steps, `aws_iam_role_policy`, and `aws_bedrockagentcore_agent_runtime`** - Terraform does not know the implicit dependency between the ECR push and runtime creation. Without `depends_on` the runtime may be created before the image is available in ECR. _Source: https://github.com/awslabs/amazon-bedrock-agentcore-samples/blob/main/04-infrastructure-as-code/terraform/basic-runtime/main.tf_

- **Plan `name`, `encryption_key_arn`, and `gateway_identifier` before initial deploy - they require replacement if changed** - The following fields require destroy + recreate: `agent_runtime_name` in `aws_bedrockagentcore_agent_runtime`; `name` and `encryption_key_arn` in `aws_bedrockagentcore_memory` (data loss); `name` in `aws_bedrockagentcore_workload_identity`; `gateway_identifier` in `aws_bedrockagentcore_gateway_target`; `authorizer_type` in `aws_bedrockagentcore_gateway` (ForceNew in the classic `aws` provider; CloudFormation marks it as no interruption). _Source: https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-bedrockagentcore-memory.html_

- **For the Gateway, prefer `AWS_IAM` for internal agent-to-agent environments; `CUSTOM_JWT` for external IdPs** - `AWS_IAM` is simpler to manage with standard IAM policies. `CUSTOM_JWT` requires an OIDC discovery URL (pattern `.+/.well-known/openid-configuration`) and management of `allowed_clients` or `allowed_audience`. `NONE` and `AUTHENTICATE_ONLY` are available in awscc/CFN only (not in the classic `aws` provider) and are for development/testing only. _Source: https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-bedrockagentcore-gateway.html_

- **Configure remote state on S3 + DynamoDB for team/production environments** - The `backend.tf.example` in awslabs samples shows the recommended structure. Local state is suitable only for individual testing. _Source: https://github.com/awslabs/amazon-bedrock-agentcore-samples/tree/main/04-infrastructure-as-code/terraform_

---

<a id="code-part-2"></a>
### Code

#### Provider block: minimal Terraform configuration for AgentCore with aws-only (awslabs/samples pattern)

```hcl
terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.22"  # minimum for code_configuration; ~> 6.46 for filesystem_configuration
    }
    null = {
      source  = "hashicorp/null"
      version = "~> 3.0"
    }
    time = {
      source  = "hashicorp/time"
      version = "~> 0.9"
    }
  }
}
```

_Source: https://github.com/awslabs/amazon-bedrock-agentcore-samples/blob/main/04-infrastructure-as-code/terraform/end-to-end-weather-agent/versions.tf_

---

#### Provider block: configuration for aws-ia module (uses both aws and awscc)

```hcl
terraform {
  required_version = ">= 1.14"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.18.0"
    }
    awscc = {
      source  = "hashicorp/awscc"
      version = ">= 1.30.0"
    }
    null = {
      source  = "hashicorp/null"
      version = ">= 3.0.0"
    }
  }
}
```

_Source: https://github.com/aws-ia/terraform-aws-agentcore/blob/main/versions.tf_

---

#### IAM Execution Role for AgentCore Runtime with correct trust policy (from official awslabs samples)

```hcl
data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

resource "aws_iam_role" "agent_execution" {
  name = "${var.stack_name}-agent-execution-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "AssumeRolePolicy"
      Effect = "Allow"
      Principal = { Service = "bedrock-agentcore.amazonaws.com" }
      Action = "sts:AssumeRole"
      Condition = {
        StringEquals = { "aws:SourceAccount" = data.aws_caller_identity.current.id }
        ArnLike      = { "aws:SourceArn" = "arn:aws:bedrock-agentcore:${data.aws_region.current.id}:${data.aws_caller_identity.current.id}:*" }
      }
    }]
  })
}

# Pattern awslabs: managed policy + supplemental inline policy
resource "aws_iam_role_policy_attachment" "agent_execution_managed" {
  role       = aws_iam_role.agent_execution.name
  policy_arn = "arn:aws:iam::aws:policy/BedrockAgentCoreFullAccess"
}

resource "aws_iam_role_policy" "agent_execution" {
  name = "AgentCoreExecutionPolicy"
  role = aws_iam_role.agent_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ECRImageAccess"
        Effect = "Allow"
        Action = ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer", "ecr:BatchCheckLayerAvailability"]
        Resource = aws_ecr_repository.agent_ecr.arn
      },
      { Effect = "Allow", Action = ["ecr:GetAuthorizationToken"], Resource = "*" },
      {
        Effect = "Allow"
        Action = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents", "logs:DescribeLogGroups", "logs:DescribeLogStreams"]
        Resource = "arn:aws:logs:${data.aws_region.current.id}:${data.aws_caller_identity.current.id}:log-group:/aws/bedrock-agentcore/runtimes/*"
      },
      { Effect = "Allow", Action = ["xray:PutTraceSegments", "xray:PutTelemetryRecords", "xray:GetSamplingRules", "xray:GetSamplingTargets"], Resource = "*" },
      { Effect = "Allow", Action = ["cloudwatch:PutMetricData"], Resource = "*", Condition = { StringEquals = { "cloudwatch:namespace" = "bedrock-agentcore" } } },
      { Effect = "Allow", Action = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"], Resource = "*" },
      {
        Sid    = "GetAgentAccessToken"
        Effect = "Allow"
        Action = ["bedrock-agentcore:GetWorkloadAccessToken", "bedrock-agentcore:GetWorkloadAccessTokenForJWT", "bedrock-agentcore:GetWorkloadAccessTokenForUserId"]
        Resource = [
          "arn:aws:bedrock-agentcore:${data.aws_region.current.id}:${data.aws_caller_identity.current.id}:workload-identity-directory/default",
          "arn:aws:bedrock-agentcore:${data.aws_region.current.id}:${data.aws_caller_identity.current.id}:workload-identity-directory/default/workload-identity/*"
        ]
      }
    ]
  })
}
```

_Source: https://github.com/awslabs/amazon-bedrock-agentcore-samples/blob/main/04-infrastructure-as-code/terraform/basic-runtime/iam.tf_

---

#### aws_bedrockagentcore_agent_runtime with container ECR, JWT Cognito and dependencies (awslabs samples pattern for MCP server)

```hcl
resource "aws_bedrockagentcore_agent_runtime" "mcp_server" {
  agent_runtime_name = replace("${var.stack_name}_${var.agent_name}", "-", "_")
  description        = var.description
  role_arn           = aws_iam_role.agent_execution.arn

  agent_runtime_artifact {
    container_configuration {
      container_uri = "${aws_ecr_repository.server_ecr.repository_url}:${var.image_tag}"
    }
  }

  network_configuration {
    network_mode = var.network_mode  # "PUBLIC" or "VPC"
  }

  protocol_configuration {
    server_protocol = "MCP"  # aws provider valid values: MCP, HTTP, A2A (AGUI: awscc/CFN only)
  }

  authorizer_configuration {
    custom_jwt_authorizer {
      allowed_clients = [aws_cognito_user_pool_client.mcp_client.id]
      discovery_url   = "https://cognito-idp.${data.aws_region.current.id}.amazonaws.com/${aws_cognito_user_pool.mcp_user_pool.id}/.well-known/openid-configuration"
    }
  }

  environment_variables = {
    AWS_REGION         = var.aws_region
    AWS_DEFAULT_REGION = var.aws_region
  }

  depends_on = [
    null_resource.trigger_build,
    aws_iam_role_policy.agent_execution,
    aws_iam_role_policy_attachment.agent_execution_managed,
  ]
}
```

_Source: https://github.com/awslabs/amazon-bedrock-agentcore-samples/blob/main/04-infrastructure-as-code/terraform/mcp-server-agentcore-runtime/main.tf_

---

#### aws_bedrockagentcore_memory with event_expiry_duration (no inline strategies - use separate aws_bedrockagentcore_memory_strategy)

```hcl
resource "aws_bedrockagentcore_memory" "agent_memory" {
  name                  = replace("${var.stack_name}_memory", "-", "_")  # ForceNew
  description           = "Persistent conversation context for ${var.stack_name}"
  event_expiry_duration = 30  # days; min 3, max 365; NOT ForceNew
  # memory_execution_role_arn = aws_iam_role.memory_execution.arn  # optional, NOT ForceNew
  # encryption_key_arn = aws_kms_key.memory.arn  # ForceNew: plan before deploy

  tags = {
    Name      = "${var.stack_name}-memory"
    ManagedBy = "terraform"
  }
}

# Separate resource for strategies - autonomous resource
resource "aws_bedrockagentcore_memory_strategy" "semantic" {
  memory_id = aws_bedrockagentcore_memory.agent_memory.id

  semantic_memory_strategy {
    name        = "semantic_facts"
    description = "Extract factual knowledge from conversations"
    namespaces  = ["/strategies/{memoryStrategyId}/actors/{actorId}"]
  }
}
```

_Source: https://github.com/awslabs/amazon-bedrock-agentcore-samples/blob/main/04-infrastructure-as-code/terraform/end-to-end-weather-agent/memory.tf_

---

#### aws_bedrockagentcore_gateway + aws_bedrockagentcore_gateway_target with AWS_IAM auth

```hcl
resource "aws_bedrockagentcore_gateway" "mcp_gateway" {
  name            = "mcp-gateway"  # pattern ^([0-9a-zA-Z][-]?){1,100}$
  role_arn        = aws_iam_role.gateway.arn
  authorizer_type = "AWS_IAM"   # ForceNew; classic aws provider: CUSTOM_JWT | AWS_IAM; awscc/CFN also: NONE | AUTHENTICATE_ONLY

  protocol_configuration {
    mcp {
      instructions       = "Gateway for external service integration"
      search_type        = "SEMANTIC"   # Only valid value per CloudFormation/awscc docs: SEMANTIC
      supported_versions = ["2025-11-25"]
    }
  }

  tags = { ManagedBy = "terraform" }
}

resource "aws_bedrockagentcore_gateway_target" "lambda_target" {
  gateway_identifier = aws_bedrockagentcore_gateway.mcp_gateway.gateway_identifier  # ForceNew
  name               = "lambda-weather-tool"
  description        = "Lambda function integration"

  target_configuration {
    mcp {
      lambda {
        lambda_arn = aws_lambda_function.weather_tool.arn

        tool_schema {
          inline_payload {
            name        = "get_weather"
            description = "Retrieve current weather for a location"
            input_schema {
              type = "object"
              property {
                name        = "location"
                type        = "string"
                description = "City and country"
                required    = true
              }
            }
          }
        }
      }
    }
  }

  # credential_provider_configuration is optional from v6.21.0
}
```

_Source: https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/bedrockagentcore_gateway_target_

---

#### aws_bedrockagentcore_workload_identity - tags as MAP (not array) in Terraform

```hcl
resource "aws_bedrockagentcore_workload_identity" "agent_identity" {
  name = "my-agent-workload-identity"  # pattern [A-Za-z0-9_.-]+, 3-255 char; ForceNew

  allowed_resource_oauth2_return_urls = [
    "https://my-agent.example.com/callback"
  ]

  # NOTE: in Terraform tags are a map, NOT an array of {key, value} objects
  # The array-Tag structure is CloudFormation/API JSON, not HCL
  tags = {
    ManagedBy = "terraform"
    Project   = "my-agent"
  }
}

output "workload_identity_arn" {
  value = aws_bedrockagentcore_workload_identity.agent_identity.workload_identity_arn
}
```

_Source: https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-bedrockagentcore-workloadidentity.html_

---

#### Official aws-ia/terraform-aws-agentcore v1.0.0 module - complete example with Runtime CODE, Memory, Gateway

```hcl
module "agentcore" {
  source  = "aws-ia/agentcore/aws"
  version = "~> 1.0"  # v1.0.0 released February 2026

  runtimes = {
    python_agent = {
      source_type      = "CODE"           # or "CONTAINER"
      code_source_path = "./src"          # local source directory
      code_entry_point = ["agent.py"]
      code_runtime     = "PYTHON_3_11"
      description      = "Main agent runtime"
      create_endpoint  = true
      environment_variables = { MODEL_ID = "anthropic.claude-3-sonnet-20240229-v1:0" }
    }
  }

  memories = {
    agent_memory = {
      description           = "Long-term memory"
      event_expiry_duration = 90
      strategies = [{
        semantic_memory_strategy = {
          name        = "semantic_facts"
          description = "Extract factual knowledge"
          namespaces  = ["/strategies/{memoryStrategyId}/actors/{actorId}"]
        }
      }]
    }
  }

  gateways = {
    mcp-gateway = {
      protocol_type   = "MCP"
      authorizer_type = "AWS_IAM"
      protocol_configuration = {
        mcp = {
          instructions       = "Gateway for tool integration"
          search_type        = "SEMANTIC"   # Only valid value per CloudFormation docs: SEMANTIC
          supported_versions = ["2025-11-25"]
        }
      }
    }
  }

  tags = { Environment = "production", ManagedBy = "terraform" }
  # NOTE: the module internally uses awscc_bedrockagentcore_runtime (not aws_bedrockagentcore_agent_runtime)
  # ARM64 build is managed automatically via terraform_data + CodeBuild
}
```

_Source: https://github.com/aws-ia/terraform-aws-agentcore_

---

#### awscc_bedrockagentcore_runtime as alternative - CORRECT structure for code_configuration and network_mode_config

```hcl
# awscc structure verified from aws-ia/terraform-aws-agentcore v1.0.0 module
resource "awscc_bedrockagentcore_runtime" "code_runtime" {
  agent_runtime_name = "my-code-runtime"
  role_arn           = aws_iam_role.agent_execution.arn

  agent_runtime_artifact = {
    code_configuration = {
      code = {
        s3 = {
          bucket = aws_s3_bucket.agent_source.id
          prefix = "source.zip"
        }
      }
      entry_point = ["agent.py"]
      runtime     = "PYTHON_3_11"  # AgentCore runtime value (e.g. PYTHON_3_11)
    }
  }

  network_configuration = {
    network_mode = "PUBLIC"   # PUBLIC or VPC
    network_mode_config = null  # for VPC: { security_groups = [...], subnets = [...] }
  }

  # protocol_configuration: string, NOT a nested object
  # awscc/CFN valid values: MCP | HTTP | A2A | AGUI
  # Classic aws provider supports: MCP | HTTP | A2A (AGUI is awscc/CFN only)

  environment_variables = { AWS_REGION = "us-east-1" }
  tags = { ManagedBy = "terraform" }
}
```

_Source: https://github.com/aws-ia/terraform-aws-agentcore/blob/main/main.tf_

---

<a id="configuration-reference-part-2"></a>
### Configuration reference

| Name | Description | Default / example |
|------|-------------|-------------------|
| `agent_runtime_name` (`aws_bedrockagentcore_agent_runtime`) | Runtime name. Pattern: `[a-zA-Z][a-zA-Z0-9_]{0,47}`. Change requires replacement (ForceNew). Do not use hyphens - replace with underscores. | `replace("${var.stack_name}_${var.agent_name}", "-", "_")` |
| `role_arn` (`aws_bedrockagentcore_agent_runtime`) | ARN of IAM execution role. Pattern `arn:aws(-[^:]+)?:iam::([0-9]{12})?:role/.+`. Service `bedrock-agentcore.amazonaws.com` must have `sts:AssumeRole` with `aws:SourceAccount` and `aws:SourceArn` conditions. | `aws_iam_role.agent_execution.arn` |
| `agent_runtime_artifact` (`aws_bedrockagentcore_agent_runtime`) | Mutually exclusive: `container_configuration` (ECR URI) or `code_configuration` (S3 source, added v6.22.0 November 2025). | `container_configuration { container_uri = "${aws_ecr_repository.ecr.repository_url}:${var.image_tag}" }` |
| `network_configuration.network_mode` (`aws_bedrockagentcore_agent_runtime`) | Network mode. Values: `PUBLIC` (default) or `VPC`. For VPC, configure `vpc_config` with `subnet_ids` and `security_group_ids`. | `"PUBLIC"` |
| `protocol_configuration.server_protocol` (`aws_bedrockagentcore_agent_runtime`) | Runtime protocol in `aws` provider. Supported values: `MCP \| HTTP \| A2A`. `AGUI` is awscc/CFN only - use `awscc_bedrockagentcore_runtime` with `protocol_configuration` as a string for `AGUI`. _Source: https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/bedrockagentcore_agent_runtime_ | `"MCP"` |
| `authorizer_configuration.custom_jwt_authorizer` (`aws_bedrockagentcore_agent_runtime` / gateway) | JWT auth for inbound authentication. Requires `discovery_url` (pattern `.+/.well-known/openid-configuration`). Optional: `allowed_clients`, `allowed_audience`, `allowed_scopes` (added v6.36.0), `custom_claim` (added v6.38.0). | `discovery_url = "https://cognito-idp.{region}.amazonaws.com/{pool_id}/.well-known/openid-configuration"` |
| `event_expiry_duration` (`aws_bedrockagentcore_memory`) | Days before memory events expire. Min 3, max 365. Does NOT require replacement (no interruption). Modifiable after creation. | `30` |
| `name` (`aws_bedrockagentcore_memory`) | Memory name. Pattern `[a-zA-Z][a-zA-Z0-9_]{0,47}`. ForceNew: change destroys the resource and all data. | `replace("${var.stack_name}_memory", "-", "_")` |
| `authorizer_type` (`aws_bedrockagentcore_gateway`) | Gateway authorizer type. Required. ForceNew in the classic `aws` provider. Classic `aws` provider values: `CUSTOM_JWT \| AWS_IAM`. awscc/CFN additionally supports `NONE \| AUTHENTICATE_ONLY`. _Source: https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-bedrockagentcore-gateway.html_ | `"AWS_IAM"` |
| `gateway_identifier` (`aws_bedrockagentcore_gateway_target`) | Parent gateway ID. Pattern `^([0-9a-z][-]?){1,100}-[0-9a-z]{10}$`. Optional. ForceNew if changed. | `aws_bedrockagentcore_gateway.mcp.gateway_identifier` |
| `filesystem_configuration` (`aws_bedrockagentcore_agent_runtime`) | Added in v6.46.0 (May 2026). Allows mounting session storage, S3 Files access points, or EFS access points in the runtime. Corresponds to `FilesystemConfigurations` in CloudFormation. | `filesystem_configuration { session_storage { ... } }` |
| `BedrockAgentCoreFullAccess` (IAM managed policy) | AWS managed policy for full AgentCore access. Used as base in awslabs samples combined with supplemental inline policy. In production, evaluate explicit deny on `GetWorkloadAccessTokenForUserId`. | `arn:aws:iam::aws:policy/BedrockAgentCoreFullAccess` |

---

<a id="gotchas-part-2"></a>
### Gotchas

- AgentCore Runtime runs **exclusively on AWS Graviton (ARM64)**. Any custom container image must be built for `arm64/v8`. The `aws-ia` module handles this automatically via CodeBuild. The awslabs samples use a `buildspec.yml` with `image: aws/codebuild/amazonlinux-aarch64-standard:3.0`.
- The `hashicorp/aws` provider has **NO data sources for `bedrockagentcore`**: 16 resources, 0 data sources confirmed. To import existing resources use `terraform import`. The `awscc` provider has both resources and data sources for all resources.
- The first version of the `aws` provider with `bedrockagentcore` resources is **v6.17.0 (October 2025)**, not v6.21.0 as often reported. The awslabs samples use `~> 6.21` because it is the tested version, but the resources exist from v6.17.0.
- **Critical distinction between managed and custom browser/code_interpreter:** `aws_bedrockagentcore_browser` and `aws_bedrockagentcore_code_interpreter` (aws provider) are the managed variants without `execution_role_arn` and without `recording_config`. `awscc_bedrockagentcore_browser_custom` and `awscc_bedrockagentcore_code_interpreter_custom` (awscc provider) are the custom variants with `execution_role_arn`, `recording_config` (for browser), and enterprise policies. The `aws-ia` module uses the `awscc` custom variants.
- **CORRECTION - awscc filesystem snippet:** The previous structure using `filesystem_type='EFS'` and `efs.access_point_id`/`mount_point` does **not exist**. The correct CloudFormation/awscc structure for filesystem is: `EfsAccessPoint` (block with `EfsAccessPointConfiguration`), `S3FilesAccessPoint`, or `SessionStorage`. There is no `filesystem_type` or `mount_point` field directly.
- Tags on `aws_bedrockagentcore_workload_identity` in Terraform HCL are a **map of strings** (like all standard AWS Terraform tags), NOT an array of `[{key='...', value='...'}]` objects. The array-Tag structure is CloudFormation/API JSON only.
- The `aws-ia/terraform-aws-agentcore` v1.0.0 module uses `terraform_data` for build triggers, **not** `null_resource`. Older awslabs samples use `null_resource`. Both patterns require AWS CLI configured in the CI/CD environment for `local-exec` provisioners that invoke CodeBuild.
- `awscc_bedrockagentcore_payment_connector` is **not yet available** in the awscc provider as of June 2026. Only `awscc_bedrockagentcore_payment_credential_provider` is available (v1.85.0, May 2026). To create a `PaymentConnector`, use AWS CLI or CloudFormation directly.
- A known bug (issue #45099) affects `aws_bedrockagentcore_agent_runtime` with VPC mode: `destroy` can hang because the runtime creates ENIs that cannot be deleted or detached even from the console. Workaround: use `PUBLIC` mode if possible, or plan the manual cleanup sequence.
- The `authorizer_type` field on `aws_bedrockagentcore_gateway` is **ForceNew** in the classic `aws` provider: changing the authorizer type requires destroy + recreate of the gateway and all its targets. (CloudFormation/awscc marks it as "no interruption" - ForceNew is a Terraform provider behavior.)
- The `aws-ia/terraform-aws-agentcore` module uses `awscc_bedrockagentcore_runtime` (not `aws_bedrockagentcore_agent_runtime`) for runtimes: this is intentional because `awscc` exposes `code_configuration` S3 and `network_mode_config` VPC with a more complete structure than the native `aws` provider.

---

<a id="official-sources-part-2"></a>
### Official sources

- [AWS CloudFormation Template Reference - Bedrock AgentCore (complete index, 20 resource types)](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/AWS_BedrockAgentCore.html) - Authoritative list of 20 CloudFormation resource types: ApiKeyCredentialProvider, Browser, BrowserCustom, BrowserProfile, CodeInterpreterCustom, Dataset, Evaluator, Gateway, GatewayTarget, Harness, Memory, OAuth2CredentialProvider, OnlineEvaluationConfig, PaymentConnector, PaymentCredentialProvider, Policy, PolicyEngine, Runtime, RuntimeEndpoint, WorkloadIdentity.
- [AWS CloudFormation - AWS::BedrockAgentCore::Runtime](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-bedrockagentcore-runtime.html) - Authoritative schema: AgentRuntimeArtifact, NetworkConfiguration, ProtocolConfiguration (MCP|HTTP|A2A|AGUI), FilesystemConfigurations, LifecycleConfiguration, RequestHeaderConfiguration, AuthorizerConfiguration, EnvironmentVariables, Tags.
- [AWS CloudFormation - AWS::BedrockAgentCore::Memory](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-bedrockagentcore-memory.html) - Fields: Name (required, pattern `[a-zA-Z][a-zA-Z0-9_]{0,47}`, replacement), EventExpiryDuration (required, 3–365 days, no interruption), EncryptionKeyArn (replacement), MemoryStrategies, IndexedKeys, StreamDeliveryResources.
- [AWS CloudFormation - AWS::BedrockAgentCore::Gateway](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-bedrockagentcore-gateway.html) - Fields: Name (pattern `^([0-9a-zA-Z][-]?){1,100}$`), AuthorizerType (CUSTOM_JWT|AWS_IAM|NONE|AUTHENTICATE_ONLY), RoleArn, ProtocolConfiguration, InterceptorConfigurations, KmsKeyArn, PolicyEngineConfiguration, ExceptionLevel, ProtocolType.
- [AWS CloudFormation - AWS::BedrockAgentCore::GatewayTarget](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-bedrockagentcore-gatewaytarget.html) - Fields: Name (required), TargetConfiguration (required), GatewayIdentifier (optional, replacement), CredentialProviderConfigurations (max 1), MetadataConfiguration, Description.
- [AWS CloudFormation - AWS::BedrockAgentCore::WorkloadIdentity](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-bedrockagentcore-workloadidentity.html) - Fields: Name (required, `[A-Za-z0-9_.-]+`, 3–255 char, replacement), AllowedResourceOauth2ReturnUrls (array of strings, no interruption), Tags (Array of Tag with key/value).
- [AWS CloudFormation - AWS::BedrockAgentCore::FilesystemConfiguration](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-properties-bedrockagentcore-runtime-filesystemconfiguration.html) - Three types: EfsAccessPoint (EfsAccessPointConfiguration), S3FilesAccessPoint (S3FilesAccessPointConfiguration), SessionStorage (SessionStorageConfiguration). NOT the `filesystem_type` field hypothesized in earlier research.
- [IAM Permissions for AgentCore Runtime (AWS official)](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-permissions.html) - Canonical execution role and trust policy. Service: `bedrock-agentcore.amazonaws.com`. Conditions `aws:SourceAccount` + `aws:SourceArn` mandatory.
- [What is Amazon Bedrock AgentCore - official overview](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/what-is-bedrock-agentcore.html) - Full overview of all components: Runtime, Harness, Memory, Gateway, Identity, Code Interpreter, Browser, Observability, Payments, Evaluations, Policy, Registry.
- [Terraform Registry - hashicorp/aws changelog (official)](https://github.com/hashicorp/terraform-provider-aws/releases) - Canonical source for `bedrockagentcore` resource release versions. First resource: v6.17.0 (October 2025). Last verified: v6.47.0 (May 2026).
- [Terraform Registry - hashicorp/awscc releases (official)](https://github.com/hashicorp/terraform-provider-awscc/releases) - Canonical awscc source. First `bedrockagentcore` resource: v1.57.0 (September 2025). Last verified: v1.86.0 (May 2026) with `awscc_bedrockagentcore_harness`.
- [Terraform Registry - aws_bedrockagentcore_agent_runtime](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/bedrockagentcore_agent_runtime)
- [Terraform Registry - aws_bedrockagentcore_memory](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/bedrockagentcore_memory)
- [Terraform Registry - aws_bedrockagentcore_gateway](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/bedrockagentcore_gateway)
- [Terraform Registry - aws_bedrockagentcore_gateway_target](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/bedrockagentcore_gateway_target)
- [Terraform Registry - awscc_bedrockagentcore_runtime](https://registry.terraform.io/providers/hashicorp/awscc/latest/docs/resources/bedrockagentcore_runtime) - awscc provider - uses Cloud Control API. First version: awscc 1.57.0 (September 2025).
- [Official module aws-ia/terraform-aws-agentcore (v1.0.0)](https://github.com/aws-ia/terraform-aws-agentcore) - v1.0.0 released February 2026. Requires Terraform >= 1.14, aws >= 6.18.0, awscc >= 1.30.0. Uses awscc for Runtime/RuntimeEndpoint/Browser/CodeInterpreter/Memory/Gateway; uses aws for GatewayTarget.
- [awslabs/agentcore-samples - Terraform IaC folder](https://github.com/awslabs/amazon-bedrock-agentcore-samples/tree/main/04-infrastructure-as-code/terraform) - Official AWS Labs examples: basic-runtime, mcp-server, multi-agent, end-to-end-weather-agent. Use `aws` provider `~> 6.21` (without awscc).
- [AWS Blog - Build AI agents with Amazon Bedrock AgentCore using AWS CloudFormation](https://aws.amazon.com/blogs/machine-learning/build-ai-agents-with-amazon-bedrock-agentcore-using-aws-cloudformation/)
- [AgentCore new features: managed harness, CLI, skills (April 2026)](https://aws.amazon.com/about-aws/whats-new/2026/04/agentcore-new-features-to-build-agents-faster/) - CLI supports CDK natively. Terraform CLI support listed as "coming soon" - confirmed not yet released as of June 2026.

---

## Verify live (open questions)

> Re-check in the provider CHANGELOG / Terraform Registry before relying on the items below - these were open as of June 2026.

**Part 1 - Terraform for Amazon Bedrock:**

1. **Flow alias/version in classic provider:** When will `aws_bedrockagent_flow_alias` and `aws_bedrockagent_flow_version` be added to the classic `hashicorp/aws` provider? Currently both are `awscc`-only (`awscc_bedrock_flow_alias`, `awscc_bedrock_flow_version`). No tracked issue found as of June 2026.
2. **SUPERVISOR multi-agent stability (Issue #43059):** `prepare_agent = true` on a SUPERVISOR agent without collaborators fails. When will this be fixed in the classic provider?
3. **awscc_bedrockagentcore_gateway drift:** When will the `description` and `protocol_configuration` drift bug be resolved in the classic or awscc provider?
4. **aws_bedrock_guardrail import path:** What is the correct import path when the ARN includes a version suffix? (Issue #41441 in `hashicorp/terraform-provider-aws`)
5. **awscc_bedrock_enforced_guardrail_configuration (cross-account, GA April 2026):** Will this eventually get a classic provider equivalent in `aws_bedrock_*`?
6. **awscc_bedrockagentcore_policy_engine:** Is this fully GA or still in preview as of June 2026?
7. **action group re-prepare (Issue #39400):** `aws_bedrockagent_agent_action_group` still does not trigger `PrepareAgent` automatically - the `null_resource` workaround is still required. Track this issue for a native fix.

**Part 2 - Terraform for Bedrock AgentCore:**

1. **Terraform CLI support in AgentCore CLI:** The Terraform support announced "coming soon" in April 2026 - has it been released? The CLI simplifies end-to-end deployment (build + push + create runtime) for Terraform similarly to CDK.
2. **awscc_bedrockagentcore_payment_connector:** Will this be added to the awscc provider? The CloudFormation type `AWS::BedrockAgentCore::PaymentConnector` exists but does not appear in awscc release notes as of May 2026. Same question for Dataset and BrowserProfile, which are absent from the `aws` provider.
3. **Data sources for bedrockagentcore in aws provider:** Will the `hashicorp/aws` provider add data sources for querying existing runtimes/memory? Currently 0 data sources for `bedrockagentcore`; workaround is `terraform import` or using the `awscc` provider which has data sources.
4. **AgentCore Runtime concurrency limits:** What are the official concurrent session limits for a single `aws_bedrockagentcore_agent_runtime`? Is auto-scaling configurable via Terraform or entirely managed by AWS transparently?
5. **AgentCore Registry Terraform resources:** The Registry is a new component (announced in what-is doc) not yet present in `aws` or `awscc` providers. Will `AWS::BedrockAgentCore::Registry` get Terraform resources?
6. **aws-ia module coverage:** Will `aws-ia/terraform-aws-agentcore` add support for harness, workload_identity, policy_engine, and payment_credential_provider, which are absent from the module v1.0.0?
