# Amazon Bedrock AgentCore - Gateway & Identity

> Part of the **aws-bedrock-agentcore-skill** skill. See [SKILL.md](../SKILL.md) for the decision tree. Every source below is official - re-open it to verify details.

## Table of contents

- [Overview](#overview)
- [Key concepts](#key-concepts)
  - [AgentCore Gateway](#agentcore-gateway)
  - [Gateway Target](#gateway-target)
  - [Inbound Authorization (Gateway)](#inbound-authorization-gateway)
  - [Outbound Authorization (Gateway Targets)](#outbound-authorization-gateway-targets)
  - [Semantic Tool Search](#semantic-tool-search)
  - [AgentCore Identity](#agentcore-identity)
  - [OAuth2 Credential Provider](#oauth2-credential-provider)
  - [Workload Access Token](#workload-access-token)
  - [Auth Flows (USER_FEDERATION vs M2M)](#auth-flows-user_federation-vs-m2m)
  - [Token Vault](#token-vault)
  - [Gateway Service Role](#gateway-service-role)
  - [Gateway Interceptors](#gateway-interceptors)
  - [Gateway Rules](#gateway-rules)
  - [MCP Stateful Sessions](#mcp-stateful-sessions)
- [Best practices](#best-practices)
- [Code](#code)
  - [Create Gateway with CUSTOM_JWT inbound auth and semantic search (Boto3)](#create-gateway-with-custom_jwt-inbound-auth-and-semantic-search-boto3)
  - [Create Gateway with CUSTOM_JWT via AWS CLI](#create-gateway-with-custom_jwt-via-aws-cli)
  - [Add Lambda target with inline tool schema (Boto3)](#add-lambda-target-with-inline-tool-schema-boto3)
  - [Add OpenAPI target (S3 spec) with API Key outbound auth (Boto3)](#add-openapi-target-s3-spec-with-api-key-outbound-auth-boto3)
  - [Add API Gateway target with filters and overrides (Boto3)](#add-api-gateway-target-with-filters-and-overrides-boto3)
  - [Gateway Service Role trust policy with gateway ARN condition](#gateway-service-role-trust-policy-with-gateway-arn-condition)
  - [Create OAuth2 Credential Provider with BYOS Secrets Manager (GitHub)](#create-oauth2-credential-provider-with-byos-secrets-manager-github)
  - [Create custom OAuth2 Credential Provider (CustomOauth2) via CLI](#create-custom-oauth2-credential-provider-customoauth2-via-cli)
  - [Get workload access token - Pattern 1 JWT-based (recommended)](#get-workload-access-token--pattern-1-jwt-based-recommended)
  - [IAM policy: Deny GetWorkloadAccessTokenForUserId](#iam-policy-deny-getworkloadaccesstokenforuserid)
  - [Scope credential provider access to a specific workload identity (IAM)](#scope-credential-provider-access-to-a-specific-workload-identity-iam)
  - [On-Behalf-Of Token Exchange - TOKEN_EXCHANGE with M2M actor token (CLI)](#on-behalf-of-token-exchange--token_exchange-with-m2m-actor-token-cli)
  - [Create Gateway with VPC-hosted private IdP (managed Lattice)](#create-gateway-with-vpc-hosted-private-idp-managed-lattice)
  - [Gateway rule with 50/50 A/B split between two configuration bundle versions](#gateway-rule-with-5050-ab-split-between-two-configuration-bundle-versions)
  - [Semantic tool search via MCP JSON-RPC call](#semantic-tool-search-via-mcp-json-rpc-call)
- [Configuration reference](#configuration-reference)
- [Gotchas](#gotchas)
- [Official sources](#official-sources)

---

## Overview

Amazon Bedrock AgentCore Gateway and Identity are two fully managed services within the AgentCore platform. **Gateway** converts existing APIs, Lambda functions, OpenAPI/Smithy specifications, and MCP servers into MCP-compatible tools, exposing them through a single secure HTTPS endpoint with managed inbound and outbound authentication. **Identity** handles both inbound auth (who calls the agent, via IAM or JWT/OAuth from any IdP) and outbound auth (how the agent obtains credentials for external services), including a secure token vault that stores refresh tokens and access tokens.

CDK L2 constructs for both services became stable in May 2026 (aws-cdk-lib v2.255.0+); only the Policy module remains in alpha. Gateway pricing is consumption-based: $0.005/1,000 MCP invocations, $0.025/1,000 semantic search queries, $0.02/100 tools indexed/month. Identity is free when used via Runtime or Gateway; in other scenarios $0.010/1,000 token or API key requests.

**Maturity:** Gateway and Identity are **GA** since October 2025, available in 15+ AWS regions (including GovCloud US-West from May 2026, São Paulo and Canada Central from April 2026). Key GA milestones: VPC Egress for Gateway/Identity/Runtime and OBO Token Exchange (April 2026); Policy engine with Cedar and AgentCore CLI v0.4.0 (March 2026); MCP Stateful Sessions, Response Streaming, Elicitation Pass-Through, Sampling Messages, Progress/Logging Notifications (May 2026). **Preview (as of June 2026):** AgentCore Payments (Coinbase CDP / Stripe Privy), AWS Agent Registry, AgentCore Harness, Optimization Loop.

---

## Key concepts

### AgentCore Gateway

A fully managed service that transforms APIs, Lambda functions, OpenAPI specs, Smithy models, API Gateway stages, and MCP servers into MCP-compatible tools, exposing them on a single HTTPS endpoint. Operates in two modes:

- **MCP aggregation mode** (`protocolType=MCP`): aggregates all MCP targets into a single virtual MCP server; only MCP targets are accepted.
- **Mixed mode** (omit `protocolType`): supports both MCP and HTTP targets.

The client connects via Streamable HTTP MCP transport. The gateway runtime URL format is:

```
https://{gateway-Id}.gateway.bedrock-agentcore.{Region}.amazonaws.com
```

### Gateway Target

A target is the configuration that specifies where the gateway routes requests.

**MCP target types:**
- `lambda` - Lambda function ARN + tool schema JSON
- `apiGateway` - REST API stage + optional `toolFilters` and `toolOverrides`
- `openApiSchema` - OpenAPI 3.0/3.1 spec from S3 or inline
- `smithyModel` - Smithy model from S3
- `mcpServer` - external MCP server endpoint

**HTTP target type:**
- `agentcoreRuntime` - Runtime agent ARN for direct traffic without protocol translation

**Quotas:** max 100 targets per gateway (adjustable), max 1,000 tools per target (adjustable). Each target has `credentialProviderConfigurations` for outbound auth.

### Inbound Authorization (Gateway)

Controls who can invoke the gateway. Four modes:

| Mode | Behavior |
|---|---|
| `CUSTOM_JWT` | Validates JWT from any OIDC-compatible IdP via `discoveryUrl`. Checks `allowedAudience`, `allowedClients`, `allowedScopes`, `customClaims`. Supports claim validation operators: `EQUALS`, `CONTAINS`, `CONTAINS_ANY`. |
| `AWS_IAM` | SigV4 signing. Caller must have `bedrock-agentcore:InvokeGateway` permission. |
| `AUTHENTICATE_ONLY` | Validates JWT but delegates authorization to the downstream target. |
| `NONE` | No authentication - use only alongside a custom REQUEST interceptor Lambda. |

Supports private IdPs in VPC via VPC Lattice (managed or self-managed). When a client sends a request without a valid token, the gateway returns 401/403 with a `WWW-Authenticate` header following RFC 6750 Bearer token challenge, including required scopes and a `resource_metadata` URL.

### Outbound Authorization (Gateway Targets)

Manages how the gateway authenticates to backend targets. `credentialProviderType` values:

| Type | Behavior |
|---|---|
| `GATEWAY_IAM_ROLE` | SigV4 with the gateway's IAM role - default for Lambda, API GW, and Runtime targets. |
| `OAUTH` | Client credentials flow via an `OAuth2CredentialProvider` ARN. |
| `API_KEY` | API key injected into header/query/path via an `ApiKeyCredentialProvider` ARN, with `credentialLocation` set to `HEADER`, `QUERY_PARAMETER`, or `PATH`. |

### Semantic Tool Search

Optional feature enabled at gateway creation time - **cannot be changed after creation**. Adds the built-in tool `x_amz_bedrock_agentcore_search` to the MCP server. Accepts a natural-language query and returns the most relevant tools among all registered gateway tools. Configured via `protocolConfiguration.mcp.searchType=SEMANTIC`. Requires `bedrock-agentcore:SynchronizeGatewayTargets` IAM permission. Rate limit: 25 transactions per minute for search-based tool calls. Pricing: $0.025 per 1,000 search invocations.

### AgentCore Identity

Manages authentication and authorization for agents and tools. Responsibilities split:

- **Inbound auth:** controls who calls the agent (configured on Runtime/Gateway).
- **Outbound auth:** how the agent obtains credentials for external services.

Maintains a secure **token vault** storing access tokens, refresh tokens, and API keys.

**Quotas (per account per region):**
- Max 1,000 workload identities (non-adjustable)
- Max 50 OAuth2 credential providers (non-adjustable)
- Max 50 API key credential providers (non-adjustable)

**Pricing:** Free when used via AgentCore Runtime or Gateway. Standalone use: $0.010 per 1,000 token or API key requests.

### OAuth2 Credential Provider

A configuration that associates an OAuth2 client registered with an external IdP to a referenceable name in agent code. Features:

- 26 pre-configured vendors (`OAuth2CredentialProviderVendor`) plus `CustomOauth2`.
- Includes discovery URL, client ID, client secret (inline or via `clientSecretSource=EXTERNAL` referencing Secrets Manager with `clientSecretConfig.secretId`).
- Has a `callbackUrl` generated by AgentCore that **must be registered** with the IdP as an authorized Redirect URI.
- Supports OBO Token Exchange via `onBehalfOfTokenExchangeConfig`.

### Workload Access Token

An opaque token signed by AWS representing the (agent, user) pair. Authorizes the agent to access credential providers in the token vault. Runtime/Gateway generate and inject it automatically as a header when the agent is invoked with inbound auth.

For **external agents**, obtain it with:

- **Pattern 1 (production):** `get_workload_access_token(workload_name=..., user_token=jwt)` - AgentCore verifies the JWT signature, issuer, and expiration.
- **Pattern 2 (development):** `get_workload_access_token(workload_name=..., user_id=string)` - platform treats `user_id` as an opaque unverified string; security is entirely the application's responsibility.

**Important:** workload identities managed by Runtime or Gateway cannot directly retrieve workload access tokens - they receive it automatically via the injected header (error: `WorkloadIdentity is linked to a service`).

### Auth Flows (USER_FEDERATION vs M2M)

| Flow | Description |
|---|---|
| `USER_FEDERATION` (3LO / Authorization Code) | The `@requires_access_token` decorator requires human user consent; generates an authorization URL that must be opened in the browser. `on_auth_url` callback streams it to the caller. |
| `M2M` (2LO / Client Credentials) | Machine-to-machine authentication without human intervention; uses client ID and client secret directly. |
| `ON_BEHALF_OF_TOKEN_EXCHANGE` | Exchanges the inbound user token for a token scoped to a downstream resource server. Supports RFC 8693 `TOKEN_EXCHANGE` (with `actorTokenContent`: `M2M`, `AWS_IAM_ID_TOKEN_JWT`, or `NONE`) and RFC 7523 `JWT_AUTHORIZATION_GRANT`. Microsoft OBO uses `JWT_AUTHORIZATION_GRANT` natively. |

### Token Vault

Secure storage managed by Identity for access tokens, refresh tokens, and API keys. When an agent obtains user consent (3LO), the token vault stores the refresh token. On subsequent invocations, if the refresh token is still valid, Identity returns a new access token without re-prompting the user. The vault is scoped per (agent-workload, user) pair. Use `force_authentication=True` to clear the cache and force a new auth flow.

### Gateway Service Role

IAM role assumed by the gateway to invoke backend targets. Required configuration:

- **Trust policy:** `Principal=bedrock-agentcore.amazonaws.com` with condition `aws:SourceArn` scoped to the specific gateway ARN.
- **Permissions:** `lambda:InvokeFunction` for Lambda targets; `s3:GetObject` for OpenAPI/Smithy specs in S3; `execute-api:Invoke` for API Gateway targets.
- **Gateway ARN format:** `arn:${Partition}:bedrock-agentcore:${Region}:${Account}:gateway/${gateway-Id}`

Created automatically by the console/CLI or manually for customization.

### Gateway Interceptors

Lambda functions that execute custom code during every gateway invocation.

| Type | Executes | Use case |
|---|---|---|
| `REQUEST` | Before the gateway calls the target | Validation, transformation, custom auth |
| `RESPONSE` | After the target's response, before returning to caller | Response transformation, filtering |

**Limits:** max 1 REQUEST and 1 RESPONSE interceptor per gateway. `passRequestHeaders` defaults to `false`; setting it to `true` exposes sensitive headers (including Authorization tokens) to the interceptor Lambda - use with caution. Primary use: pair with `authorizerType=NONE` to implement fully custom auth logic.

### Gateway Rules

Traffic routing and configuration override system that operates without redeployment. Each rule has:

- **Priority:** 1–1,000,000 (lower numbers = higher priority).
- **Conditions (optional):** `matchPrincipals` (IAM ARN matching) and/or `matchPaths` (HTTP path matching). Max 2 condition types per rule, with AND logic between types and OR logic within each type.
- **Actions:** `configurationBundle` override (`staticOverride` or `weightedOverride`) or `routeToTarget` (`staticRoute` or `weightedRoute`).

**Limits:** max 20 rules per gateway. `weightedOverride` A/B testing: the two weights must each be between 1 and 99 (0 and 100 are invalid) and must sum to 100. `matchPaths` conditions work only for gateways with HTTP targets (not MCP-only). Reserved paths (`/mcp`, `/a2a`, `/responses`, `/converse`, `/.well-known`) cannot be used in `matchPaths`.

### MCP Stateful Sessions

**GA since May 2026.** The gateway maintains stateful sessions with MCP clients (`Mcp-Session-Id` in the header). Session timeout is configurable from 1 to 8 hours (default: 1 hour). Prerequisite for:

- **Elicitation pass-through** - mid-execution user input.
- **Sampling messages** - server-initiated LLM calls.
- **Progress/Logging notifications** - human-in-the-loop features introduced in May 2026.

---

## Best practices

- **Use `CUSTOM_JWT` as inbound auth in production; never `NONE` without a Lambda interceptor.** `NONE` exposes the gateway to anyone without any verification. `CUSTOM_JWT` validates issuer, signature, audience, and scopes of the JWT before invoking any target. For quick-start, Cognito can be auto-created by the AgentCore CLI. Use `NONE` only when implementing a custom REQUEST Lambda interceptor for authentication. _Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-inbound-auth.html_

- **Scope the Service Role trust policy to the specific gateway ARN after creation.** Before creation the gateway ARN is unknown, so the `Condition` is omitted. After creation, update with `aws:SourceArn` and `aws:SourceAccount` to prevent confused deputy attacks. Gateway ARN format: `arn:${Partition}:bedrock-agentcore:${Region}:${Account}:gateway/${gateway-Id}`. _Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-prerequisites-permissions.html_

- **Enable semantic search (`searchType=SEMANTIC`) at gateway creation time.** Semantic search cannot be enabled after creation. With many tools, it reduces context sent to the model: instead of listing all tools, the agent searches only the relevant ones, improving latency and reducing costs. Rate limit: 25 TPM for search vs. 1,000 concurrent connections for tool-call/tool-list. _Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-create-api.html_

- **Prefer `GetWorkloadAccessTokenForJWT` (Pattern 1) over `GetWorkloadAccessTokenForUserId` (Pattern 2) in production.** Pattern 1 validates the JWT signature, issuer, and expiration before issuing the workload token, providing cryptographic proof of identity. Pattern 2 accepts an unverified opaque string - the risk of impersonation is entirely on the application. For workloads that always have a JWT available, also add an explicit Deny on `bedrock-agentcore:GetWorkloadAccessTokenForUserId`. _Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/get-workload-access-token.html_

- **Use `clientSecretSource=EXTERNAL` to reference secrets already in Secrets Manager instead of passing the secret inline.** Available for OAuth2, API key, and payment credential providers. Allows applying custom CMKs, automatic rotation, resource policies, and your own tagging strategy. Secrets remain customer-owned; AgentCore reads them at runtime without copying. Also supported for API keys (`apiKeySecretSource=EXTERNAL`) and payment providers (`apiKeySecretSource`, `walletSecretSource`, `appSecretSource`, `authorizationPrivateKeySource`). _Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/resource-providers.html_

- **Prefix `userId` with the provider name when using multiple IdPs with `GetWorkloadAccessTokenForUserId`.** Two users with the same `sub` from different IdPs (e.g., `cognito+user123` vs `auth0+user123`) would otherwise occupy the same slot in the token vault, causing cross-contamination of credentials. This is an explicit security requirement in the documentation. _Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/get-workload-access-token.html_

- **Include the provider-specific refresh token scope in the first token request.** The token vault stores the refresh token automatically only if the provider returns one. Google requires `access_type=offline`; Microsoft, Atlassian, and Slack require `offline_access` in the scope; Salesforce requires `refresh_token` in the scope. Without this, every agent invocation re-prompts the user for consent. _Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/identity-authentication.html_

- **Add semantically rich descriptions to Lambda tool schemas (`toolSchema`) and OpenAPI operations.** The gateway's semantic search uses tool descriptions for natural-language query matching. Vague descriptions degrade retrieval quality. The quality of semantic search depends directly on the richness of the `description` field for each tool. _Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-using-mcp-semantic-search.html_

- **Use VPC Egress (`privateEndpoint`) for private IdPs instead of exposing OIDC endpoints on the internet.** GA since April 2026. Gateway supports `privateEndpoint` on `customJWTAuthorizer` for IdPs in a VPC (managed Lattice or self-managed). Avoids exposing OIDC/token/JWKS endpoints on the public network. If token/JWKS endpoints use different domains from `discoveryUrl`, use `privateEndpointOverrides` (self-managed Lattice only). Requires `iam:CreateServiceLinkedRole` for `identity-network.bedrock-agentcore.amazonaws.com`. _Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-inbound-auth.html_

- **Use gateway rules for A/B testing of configuration bundles without redeployment.** GA (released Q1 2026): gateway rules with `weightedOverride` allow splitting traffic between two configuration bundle versions (each weight must be 1–99; 0 and 100 are invalid; weights must sum to 100). Max 20 rules per gateway - leave gaps between priorities (e.g., 100, 200, 300) to insert future rules without renumbering. _Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-rules.html_

- **Use interceptors for fine-grained access control instead of custom logic in the targets.** REQUEST interceptors execute before the gateway calls the target, allowing JWT claim validation, role-based/attribute-based access control, and returning authorization errors before consuming backend resources. Implement fail-safe defaults (deny by default), log decisions for auditing, and do not log sensitive headers when `passRequestHeaders=true`. _Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-fine-grained-access-control.html_

- **Use IAM policies to scope credential provider access to specific workload identities.** Explicitly specify both `workload-identity-directory/default` and the specific `workload-identity/{name}` in IAM policies for `GetResourceOauth2Token` and `GetResourceApiKey`, along with `token-vault/default`. This ensures only authorized workloads access credentials of a specific provider, preventing lateral movement between agents. _Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/scope-credential-provider-access.html_

---

## Code

### Create Gateway with CUSTOM_JWT inbound auth and semantic search (Boto3)

```python
import boto3

# Initialize the AgentCore client
client = boto3.client('bedrock-agentcore-control')

# Create a gateway
gateway = client.create_gateway(
    name="my-gateway",
    roleArn="arn:aws:iam::123456789012:role/my-gateway-service-role",
    protocolType="MCP",
    authorizerType="CUSTOM_JWT",
    authorizerConfiguration={
        "customJWTAuthorizer": {
            "discoveryUrl": "https://cognito-idp.us-west-2.amazonaws.com/some-user-pool/.well-known/openid-configuration",
            "allowedClients": ["clientId"],
            "allowedAudience": ["api.example.com"],
            "allowedScopes": ["openid", "profile"]
        }
    },
    protocolConfiguration={
        "mcp": {
            "searchType": "SEMANTIC"
        }
    }
)

print(f"MCP Endpoint: {gateway['gatewayUrl']}")
```

_Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-create-api.html_

---

### Create Gateway with CUSTOM_JWT via AWS CLI

```bash
aws bedrock-agentcore-control create-gateway \
  --name my-gateway \
  --role-arn arn:aws:iam::123456789012:role/my-gateway-service-role \
  --protocol-type MCP \
  --authorizer-type CUSTOM_JWT \
  --authorizer-configuration '{
    "customJWTAuthorizer": {
      "discoveryUrl": "https://cognito-idp.us-west-2.amazonaws.com/some-user-pool/.well-known/openid-configuration",
      "allowedClients": ["clientId"]
    }
  }'

# The gatewayUrl in the response is the endpoint to use for invoking the gateway
```

_Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-create-api.html_

---

### Add Lambda target with inline tool schema (Boto3)

```python
import boto3

# Create the agentcore client
agentcore_client = boto3.client('bedrock-agentcore-control')

# Create a Lambda target
target = agentcore_client.create_gateway_target(
    gatewayIdentifier="your-gateway-id",
    name="LambdaTarget",
    targetConfiguration={
        "mcp": {
            "lambda": {
                "lambdaArn": "arn:aws:lambda:us-west-2:123456789012:function:YourLambdaFunction",
                "toolSchema": {
                    "inlinePayload": [
                        {
                            "name": "get_weather",
                            "description": "Get current weather conditions and forecast for a specific city or geographic location",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "location": {
                                        "type": "string",
                                        "description": "City name or coordinates, e.g. 'Seattle, WA' or '47.6,-122.3'"
                                    },
                                    "units": {
                                        "type": "string",
                                        "enum": ["celsius", "fahrenheit"],
                                        "description": "Temperature unit"
                                    }
                                },
                                "required": ["location"]
                            }
                        },
                        {
                            "name": "get_time",
                            "description": "Get time for a timezone",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "timezone": {"type": "string"}
                                },
                                "required": ["timezone"]
                            }
                        }
                    ]
                }
            }
        }
    },
    credentialProviderConfigurations=[
        {
            "credentialProviderType": "GATEWAY_IAM_ROLE"
        }
    ]
)
```

_Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-add-target-api-target-config.html_

---

### Add OpenAPI target (S3 spec) with API Key outbound auth (Boto3)

```python
import boto3

agentcore_client = boto3.client('bedrock-agentcore-control')

# Create an OpenAPI target with API Key authentication
target = agentcore_client.create_gateway_target(
    gatewayIdentifier="your-gateway-id",
    name="SearchAPITarget",
    targetConfiguration={
        "mcp": {
            "openApiSchema": {
                "s3": {
                    "uri": "s3://your-bucket/path/to/open-api-spec.json",
                    "bucketOwnerAccountId": "123456789012"
                }
            }
        }
    },
    credentialProviderConfigurations=[
        {
            "credentialProviderType": "API_KEY",
            "credentialProvider": {
                "apiKeyCredentialProvider": {
                    # Note: ARN format from official documentation uses agent-credential-provider
                    "providerArn": "arn:aws:agent-credential-provider:us-east-1:123456789012:token-vault/default/apikeycredentialprovider/abcdefghijk",
                    "credentialLocation": "HEADER",
                    "credentialParameterName": "X-API-Key"
                }
            }
        }
    ]
)
```

_Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-add-target-api-target-config.html_

---

### Add API Gateway target with filters and overrides (Boto3)

```python
import boto3

agentcore_client = boto3.client('bedrock-agentcore-control')

# Create an API gateway REST API target with gateway service role authentication
target = agentcore_client.create_gateway_target(
    gatewayIdentifier="your-gateway-id",
    name="SearchAPITarget",
    targetConfiguration={
        "mcp": {
            "apiGateway": {
                "restApiId": "your-rest-api-id",
                "stage": "prod",
                "apiGatewayToolConfiguration": {
                    "toolFilters": [
                        {
                            "filterPath": "/products",
                            "methods": ["GET", "POST"]
                        }
                    ],
                    "toolOverrides": [
                        {
                            "path": "/products",
                            "method": "GET",
                            "name": "get_items",
                            "description": "Gets information for items in the list of products."
                        }
                    ]
                }
            }
        }
    },
    credentialProviderConfigurations=[
        {
            "credentialProviderType": "GATEWAY_IAM_ROLE"
        }
    ]
)
```

_Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-add-target-api-target-config.html_

---

### Gateway Service Role trust policy with gateway ARN condition

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "GatewayAssumeRolePolicy",
      "Effect": "Allow",
      "Principal": {
        "Service": "bedrock-agentcore.amazonaws.com"
      },
      "Action": "sts:AssumeRole",
      "Condition": {
        "StringEquals": {
          "aws:SourceAccount": "111122223333"
        },
        "ArnLike": {
          "aws:SourceArn": "arn:aws:bedrock-agentcore:us-east-1:111122223333:gateway/my-gateway-*"
        }
      }
    }
  ]
}
```

_Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-prerequisites-permissions.html_

---

### Create OAuth2 Credential Provider with BYOS Secrets Manager (GitHub)

```bash
# Bring Your Own Secret: reference a secret already in Secrets Manager
aws bedrock-agentcore-control create-oauth2-credential-provider \
  --name "github-provider" \
  --credential-provider-vendor "GithubOauth2" \
  --oauth2-provider-config-input '{
    "githubOauth2ProviderConfig": {
      "clientId": "your-github-client-id",
      "clientSecretSource": "EXTERNAL",
      "clientSecretConfig": {
        "secretId": "arn:aws:secretsmanager:us-east-1:123456789012:secret:my-secret",
        "jsonKey": "clientSecret"
      }
    }
  }' \
  --region us-east-1
```

_Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/resource-providers.html_

---

### Create custom OAuth2 Credential Provider (CustomOauth2) via CLI

```bash
# ISSUER_URL must point to .well-known/openid-configuration
export ISSUER_URL="https://cognito-idp.us-east-1.amazonaws.com/us-east-1_POOL_ID/.well-known/openid-configuration"
export CLIENT_ID="your-client-id"
export CLIENT_SECRET="your-client-secret"

OAUTH2_CREDENTIAL_PROVIDER_RESPONSE=$(aws bedrock-agentcore-control create-oauth2-credential-provider \
  --name "MyIdentityProvider" \
  --credential-provider-vendor "CustomOauth2" \
  --oauth2-provider-config-input '{
    "customOauth2ProviderConfig": {
      "oauthDiscovery": {
        "discoveryUrl": "'$ISSUER_URL'"
      },
      "clientId": "'$CLIENT_ID'",
      "clientSecret": "'$CLIENT_SECRET'"
    }
  }' \
  --output json)

# Callback URL to register with the IdP as an authorized Redirect URI
OAUTH2_CALLBACK_URL=$(echo $OAUTH2_CREDENTIAL_PROVIDER_RESPONSE | jq -r '.callbackUrl')
echo "Register this callback URL with your IdP: $OAUTH2_CALLBACK_URL"
```

_Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/identity-getting-started-cognito.html_

---

### Get workload access token - Pattern 1 JWT-based (recommended)

```python
from bedrock_agentcore.services.identity import IdentityClient

identity_client = IdentityClient("us-east-1")

# Pattern 1 (production): JWT from IdP - AgentCore verifies signature, issuer, and expiration
workload_access_token = identity_client.get_workload_access_token(
    workload_name="my-demo-agent",
    user_token="insert-jwt-here"  # JWT issued by the IdP for the user
)

# Pattern 2 (development/enterprise with own user ID): UserId string
# Note: the platform does NOT verify this string. Security is the application's responsibility.
workload_access_token_dev = identity_client.get_workload_access_token(
    workload_name="my-demo-agent",
    user_id="cognito+user-123"  # provider prefix to avoid multi-IdP collisions
)

print(workload_access_token)
```

_Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/get-workload-access-token.html_

---

### IAM policy: Deny GetWorkloadAccessTokenForUserId

```json
{
  "Statement": [
    {
      "Sid": "DenyForUserIdAccess",
      "Effect": "Deny",
      "Action": "bedrock-agentcore:GetWorkloadAccessTokenForUserId",
      "Resource": "arn:aws:bedrock-agentcore:REGION:ACCOUNT_ID:workload-identity-directory/default"
    }
  ]
}
```

_Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/get-workload-access-token.html_

---

### Scope credential provider access to a specific workload identity (IAM)

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "GetResourceOauth2Token",
      "Effect": "Allow",
      "Action": [
        "bedrock-agentcore:GetResourceOauth2Token"
      ],
      "Resource": [
        "arn:aws:bedrock-agentcore:us-east-1:<account_id>:workload-identity-directory/default",
        "arn:aws:bedrock-agentcore:us-east-1:<account_id>:workload-identity-directory/default/workload-identity/<workload-identity-name>",
        "arn:aws:bedrock-agentcore:us-east-1:<account_id>:token-vault/default"
      ]
    }
  ]
}
```

_Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/scope-credential-provider-access.html_

---

### On-Behalf-Of Token Exchange - TOKEN_EXCHANGE with M2M actor token (CLI)

```bash
# Step 1: configure credential provider with OBO mode TOKEN_EXCHANGE
aws bedrock-agentcore-control create-oauth2-credential-provider \
  --cli-input-json '{
    "name": "sample-obo-custom",
    "credentialProviderVendor": "CustomOauth2",
    "oauth2ProviderConfigInput": {
      "customOauth2ProviderConfig": {
        "oauthDiscovery": {
          "discoveryUrl": "https://my.idp.com/.well-known/openid-configuration"
        },
        "clientId": "your-client-id",
        "clientSecret": "your-client-secret",
        "clientAuthenticationMethod": "CLIENT_SECRET_BASIC",
        "onBehalfOfTokenExchangeConfig": {
          "grantType": "TOKEN_EXCHANGE",
          "tokenExchangeGrantTypeConfig": {
            "actorTokenContent": "M2M",
            "actorTokenScopes": ["scope1", "scope2"]
          }
        }
      }
    }
  }'

# Step 2: obtain workload access token from the inbound user JWT
WORKLOAD_TOKEN=$(aws bedrock-agentcore get-workload-access-token-for-jwt \
  --workload-name "sample-workload" \
  --user-token "$INBOUND_USER_JWT" \
  --query workloadAccessToken --output text)

# Step 3: perform the OBO token exchange
aws bedrock-agentcore get-resource-oauth2-token \
  --resource-credential-provider-name "sample-obo-custom" \
  --oauth2-flow ON_BEHALF_OF_TOKEN_EXCHANGE \
  --scopes "sample-scope" \
  --workload-identity-token "$WORKLOAD_TOKEN"
```

_Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/on-behalf-of-token-exchange.html_

---

### Create Gateway with VPC-hosted private IdP (managed Lattice)

```json
{
  "name": "my-private-idp-gateway",
  "protocolType": "MCP",
  "roleArn": "arn:aws:iam::123456789012:role/my-gateway-role",
  "authorizerType": "CUSTOM_JWT",
  "authorizerConfiguration": {
    "customJWTAuthorizer": {
      "allowedAudience": [
        "my-audience"
      ],
      "discoveryUrl": "https://my-idp.internal.example.com/.well-known/openid-configuration",
      "privateEndpoint": {
        "managedVpcResource": {
          "vpcIdentifier": "vpc-0abc123def456",
          "subnetIds": ["subnet-0abc123", "subnet-0def456"],
          "endpointIpAddressType": "IPV4",
          "securityGroupIds": ["sg-0abc123def"]
        }
      }
    }
  }
}
```

_Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-inbound-auth.html_

---

### Gateway rule with 50/50 A/B split between two configuration bundle versions

```bash
aws bedrock-agentcore-control create-gateway-rule \
  --gateway-identifier "your-gateway-id" \
  --priority 100 \
  --description "A/B test: 50/50 traffic split between two bundle versions" \
  --actions '[
    {
      "configurationBundle": {
        "weightedOverride": {
          "trafficSplit": [
            {
              "name": "variant-a",
              "weight": 50,
              "configurationBundle": {
                "bundleArn": "arn:aws:bedrock-agentcore:us-east-1:123456789012:configuration-bundle/myBundle-abc1234567",
                "bundleVersion": "1234abcd-12ab-34cd-56ef-1234567890ab"
              },
              "description": "Control variant"
            },
            {
              "name": "variant-b",
              "weight": 50,
              "configurationBundle": {
                "bundleArn": "arn:aws:bedrock-agentcore:us-east-1:123456789012:configuration-bundle/myBundle-abc1234567",
                "bundleVersion": "12345678-1234-5678-9abc-123456789012"
              },
              "description": "Treatment variant"
            }
          ]
        }
      }
    }
  ]'
```

_Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-rules.html, https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-rules-examples.html_

---

### Semantic tool search via MCP JSON-RPC call

```python
import requests
import json

def search_gateway_tools(gateway_url: str, access_token: str, query: str):
    """Search tools in the gateway with a natural-language query.
    Requires the gateway to have been created with searchType=SEMANTIC.
    The gateway URL format is:
    https://{gateway-Id}.gateway.bedrock-agentcore.{Region}.amazonaws.com
    """
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access_token}"
    }
    payload = {
        "jsonrpc": "2.0",
        "id": "search-request-1",
        "method": "tools/call",
        "params": {
            "name": "x_amz_bedrock_agentcore_search",
            "arguments": {
                "query": query
            }
        }
    }
    response = requests.post(f"{gateway_url}/mcp", headers=headers, json=payload)
    response.raise_for_status()
    return response.json()

# Example:
gateway_url = "https://your-gateway-id.gateway.bedrock-agentcore.us-east-1.amazonaws.com"
result = search_gateway_tools(
    gateway_url=gateway_url,
    access_token="your-jwt-access-token",
    query="find customer order history and shipping status"
)
print(json.dumps(result, indent=2))
```

_Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-using-mcp-semantic-search.html_

---

## Configuration reference

| Name | Description | Default / example |
|---|---|---|
| `protocolType` | Protocol type of the gateway. `MCP` = aggregation mode (only MCP targets, endpoint `/mcp`). Omitted = supports both MCP and HTTP targets in mixed mode. | `"MCP"` |
| `authorizerType` | Type of inbound auth. Values: `CUSTOM_JWT`, `AWS_IAM`, `AUTHENTICATE_ONLY`, `NONE`. | `"CUSTOM_JWT"` |
| `authorizerConfiguration.customJWTAuthorizer.discoveryUrl` | OIDC configuration endpoint URL of the provider. Must be the full URL including `/.well-known/openid-configuration`. Required for `CUSTOM_JWT`. | `"https://cognito-idp.us-east-1.amazonaws.com/us-east-1_POOL_ID/.well-known/openid-configuration"` |
| `authorizerConfiguration.customJWTAuthorizer.allowedAudience` | List of valid audiences to verify against the `aud` claim of the JWT. | `["api.example.com"]` |
| `authorizerConfiguration.customJWTAuthorizer.allowedClients` | List of allowed `client_id` values, verified against the `client_id` claim. | `["your-cognito-client-id"]` |
| `authorizerConfiguration.customJWTAuthorizer.allowedScopes` | List of required scopes in the JWT. At least one must match. | `["openid", "profile"]` |
| `authorizerConfiguration.customJWTAuthorizer.customClaims` | Array of `CustomClaimValidationsType` for custom claims. Each object specifies `inboundTokenClaimName`, `inboundTokenClaimValueType` (`STRING` or `STRING_ARRAY`), and `authorizingClaimMatchValue` with `claimMatchOperator` (`EQUALS`, `CONTAINS`, `CONTAINS_ANY`) and `claimMatchValue`. | `{"inboundTokenClaimName": "role", "inboundTokenClaimValueType": "STRING", "authorizingClaimMatchValue": {"claimMatchValue": {"matchValueString": "admin"}, "claimMatchOperator": "EQUALS"}}` |
| `authorizerConfiguration.customJWTAuthorizer.privateEndpoint` | Enables access to private IdPs in VPC. Supports `managedVpcResource` (with `vpcIdentifier`, `subnetIds`, `securityGroupIds`) or `selfManagedLatticeResource` (with `resourceConfigurationIdentifier`). For different domains in token/JWKS endpoint, use `privateEndpointOverrides` (self-managed Lattice only). | `{"managedVpcResource": {"vpcIdentifier": "vpc-0abc", "subnetIds": ["subnet-0abc"], "endpointIpAddressType": "IPV4", "securityGroupIds": ["sg-0abc"]}}` |
| `protocolConfiguration.mcp.searchType` | Enables semantic search. `SEMANTIC` = adds tool `x_amz_bedrock_agentcore_search`. Not modifiable after creation. Rate limit: 25 TPM for search requests. | `"SEMANTIC"` |
| `exceptionLevel` | Level of detail for errors returned during invocation. `DEBUG` = detailed error messages (development only - never use in production). | `"DEBUG"` |
| `interceptorConfigurations` | Array that configures Lambda interceptors. Max 1 `REQUEST` (executes before the target) and 1 `RESPONSE` (executes after the target) per gateway. Each entry has: `interceptor.lambda.arn` (Lambda ARN), `interceptionPoints` (array: `"REQUEST"` and/or `"RESPONSE"`), and `inputConfiguration.passRequestHeaders` (boolean; if true, request headers including sensitive tokens are passed to the Lambda - use with caution). | `[{"interceptor": {"lambda": {"arn": "arn:aws:lambda:us-west-2:123456789012:function:my-interceptor"}}, "interceptionPoints": ["REQUEST"], "inputConfiguration": {"passRequestHeaders": false}}]` |
| `credentialProviderType` (target) | Type of outbound auth for the target. Values: `GATEWAY_IAM_ROLE`, `OAUTH`, `API_KEY`. | `"GATEWAY_IAM_ROLE"` |
| `apiKeyCredentialProvider.credentialLocation` | Where to inject the API key in the outbound request. Values: `HEADER`, `QUERY_PARAMETER`, `PATH`. | `"HEADER"` |
| `credentialProviderVendor` (OAuth2) | 26 pre-configured vendors: `GithubOauth2`, `GoogleOauth2`, `MicrosoftOauth2`, `SalesforceOauth2`, `SlackOauth2`, `JiraOauth2`, `AsanaOauth2`, `ZendeskOauth2`, `OktaOauth2`, `Auth0Oauth2`, `AmazonCognitoOauth2`, `LinkedinOauth2`, `TwitterOauth2`, `DropboxOauth2`, `BoxOauth2`, `HubspotOauth2`, `ZoomOauth2`, `NotionOauth2`, `GitlabOauth2`, `BitbucketOauth2`, `TwilioOauth2`, `StripeOauth2`, `FigmaOauth2`, `SpotifyOauth2`, `AtlassianOauth2`, `CustomOauth2`. Payment providers (Preview): `CoinbaseCDP`, `StripePrivy`. | `"GithubOauth2"` or `"CustomOauth2"` |
| `oauth2ProviderConfigInput.*.clientSecretSource` | `MANAGED` (default, AgentCore manages the secret) or `EXTERNAL` (reference to Secrets Manager via `clientSecretConfig.secretId` and `clientSecretConfig.jsonKey`). Also available for API keys (`apiKeySecretSource`) and payment providers. | `"EXTERNAL"` |
| `onBehalfOfTokenExchangeConfig.grantType` | Grant type for OBO token exchange. `TOKEN_EXCHANGE` = RFC 8693 (`actorTokenContent`: `M2M`, `AWS_IAM_ID_TOKEN_JWT`, or `NONE`). `JWT_AUTHORIZATION_GRANT` = RFC 7523 (assertion = inbound JWT, used natively by Microsoft OBO). | `"TOKEN_EXCHANGE"` |
| Gateway Service Quotas | Max 1,000 gateways/account (adjustable), max 100 targets/gateway (adjustable), max 1,000 tools/target (adjustable). Invocation rate: 1,000 concurrent connections per gateway and per account (adjustable). Search rate: 25 TPM (adjustable). Max invocation timeout: 15 minutes (adjustable). Max inline schema: 1 MB, max S3 schema: 10 MB. | See https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/bedrock-agentcore-limits.html |
| Identity Service Quotas | Max 1,000 workload identities/account/region (non-adjustable), max 50 OAuth2 credential providers/account/region (non-adjustable), max 50 API key credential providers/account/region (non-adjustable). | See https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/bedrock-agentcore-limits.html |
| `IAM Action: bedrock-agentcore:InvokeGateway` | Permission required on the caller's identity to invoke a gateway with `AWS_IAM` inbound auth. Scope to the specific gateway resource after creation. | `Resource: arn:aws:bedrock-agentcore:us-east-1:123456789012:gateway/my-gateway-12345` |
| `IAM Action: bedrock-agentcore:SynchronizeGatewayTargets` | Permission required to create a gateway with semantic search enabled. | `Resource: arn:aws:bedrock-agentcore:*:*:gateway/*` |
| `IAM Managed Policy: BedrockAgentCoreFullAccess` | AWS managed policy granting full access to all AgentCore services (Gateway, Identity, Runtime, Memory, etc.). Includes `passRole` scoped to `bedrock-agentcore.amazonaws.com` and Secrets Manager access for secrets with prefix `bedrock-agentcore-`. | `arn:aws:iam::aws:policy/BedrockAgentCoreFullAccess` |
| Gateway Pricing | API Invocations (ListTools, InvokeTool, Ping): $0.005 per 1,000 invocations. Search API: $0.025 per 1,000 invocations. Tool Indexing: $0.02 per 100 tools indexed per month. VPC Egress: $0.006 per GB to customer VPC. | See https://aws.amazon.com/bedrock/agentcore/pricing/ |
| Identity Pricing | $0.010 per 1,000 token or API key requests from the agent (only for non-Runtime, non-Gateway scenarios). Identity is free when used via AgentCore Runtime or AgentCore Gateway. | See https://aws.amazon.com/bedrock/agentcore/pricing/ |
| MCP Sessions timeout | Configurable timeout for MCP stateful sessions (GA May 2026). Default 1 hour, maximum 8 hours. Sessions scoped per authenticated user. | Default: 1h, max: 8h |
| SDK: `bedrock-agentcore` Python package | Python SDK for AgentCore. Contains `BedrockAgentCoreApp`, `requires_access_token`, `IdentityClient`, `GatewayClient`. The starter toolkit is in `bedrock_agentcore_starter_toolkit`. | `pip install bedrock-agentcore` |
| CLI: `@aws/agentcore` npm package | Node.js CLI to create, configure, and deploy AgentCore agents (GA March 2026, v0.4.0). Main commands: `agentcore create`, `agentcore add gateway`, `agentcore add gateway-target`, `agentcore add credential`, `agentcore deploy`, `agentcore status`, `agentcore logs`, `agentcore traces`, `agentcore dev` (with Agent Inspector browser UI). | `npm install -g @aws/agentcore` |
| Gateway Runtime Endpoint URL format | The gateway runtime URL uses the format: `https://{gateway-Id}.gateway.bedrock-agentcore.{Region}.amazonaws.com` (not `.api.aws` as in some older examples). | `https://your-gateway-id.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp` |

---

## Gotchas

- **Semantic search cannot be enabled after gateway creation.** It is a one-way decision at `CreateGateway` time. Use `protocolConfiguration.mcp.searchType=SEMANTIC` in the `CreateGateway` call, or enable it via the AgentCore CLI (enabled by default with the CLI).

- **The `callbackUrl` returned by `create-oauth2-credential-provider` MUST be registered in the OAuth IdP as an authorized Redirect URI BEFORE invoking the agent.** If missing, the 3LO flow fails with an invalid `redirect_uri` error.

- **The `ISSUER_URL` for AgentCore Identity must be the full URL including `/.well-known/openid-configuration`, not just the base URL of the pool.** Correct example: `https://cognito-idp.REGION.amazonaws.com/POOL_ID/.well-known/openid-configuration`

- **Runtime-managed and Gateway-managed workload identities CANNOT retrieve workload access tokens directly.** Only unmanaged identities can. Agents on Runtime receive the token automatically in the header. Error message: `WorkloadIdentity is linked to a service and cannot retrieve an access token by the caller`.

- **The Service Role trust policy must be updated AFTER gateway creation** to add the `Condition` with `aws:SourceArn` scoped to the specific gateway ARN. Before creation, the gateway ARN is unknown.

- **With `protocolType=MCP`, the gateway operates ONLY in aggregation mode and accepts only MCP targets.** To mix MCP and HTTP targets, omit `protocolType`.

- **JWT claims are logged in CloudTrail for gateways with `CUSTOM_JWT` auth.** The entry includes the Subject (`sub` claim) of the JWT. Avoid PII in the `sub` field. Prefer GUIDs or pairwise identifiers as recommended by the OIDC spec.

- **Tokens in the vault are not guaranteed to be valid** - they can be revoked on the provider side without AgentCore knowing. On a 401 error, use `force_authentication=True` in the decorator to force a new authentication flow.

- **`GetWorkloadAccessTokenForUserId`: the platform treats `userId` as an opaque unverified string.** For workloads that always have a JWT available, add an explicit `Deny` on `bedrock-agentcore:GetWorkloadAccessTokenForUserId` in the IAM policy.

- **To access a Lambda in a different account from the gateway service role, a resource-based policy on the Lambda is also required**, in addition to the identity-based policy on the service role.

- **Creating a gateway with a private VPC IdP (`privateEndpoint`) requires `iam:CreateServiceLinkedRole`** for `identity-network.bedrock-agentcore.amazonaws.com`, if the service-linked role `AWSServiceRoleForBedrockAgentCoreIdentity` does not already exist.

- **CDK constructs `aws_bedrockagentcore` (stable, from `aws-cdk-lib` v2.255.0+) and `aws_bedrock_agentcore.alpha` coexist.** The Policy module remains in alpha. Do not mix the two import namespaces.

- **The refresh token must be explicitly requested with provider-specific parameters:** `access_type=offline` for Google; `offline_access` in the scope for Microsoft, Atlassian, and Slack; `refresh_token` in the scope for Salesforce. Without this, every agent invocation re-prompts the user for consent.

- **User ID collision between different providers:** when using multiple IdPs with `GetWorkloadAccessTokenForUserId`, use the pattern `provider_id+user_id` (e.g., `cognito+user123` and `auth0+user123`) to prevent the same user ID from different providers from accessing the same tokens in the vault.

- **Gateway Rules rate limit:** max 20 rules per gateway, priorities 1–1,000,000. `matchPaths` conditions work ONLY for gateways with HTTP targets (not MCP-only). Reserved paths (`/mcp`, `/a2a`, `/responses`, `/converse`, `/.well-known`) cannot be used in `matchPaths`.

- **Interceptors: `passRequestHeaders=false` by default.** Enabling it exposes sensitive tokens (Authorization header) to the interceptor Lambda. Ensure the interceptor Lambda does NOT log these sensitive headers.

- **Identity is free when used via Runtime or Gateway** - this is a critical pricing detail. Only standalone scenarios (external agents) incur the cost of $0.010/1K tokens.

---

## Official sources

- [AgentCore Gateway - Overview](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway.html) - Master page with all key concepts, capabilities, and links to sub-guides.
- [AgentCore Gateway - Supported Target Types](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-supported-targets.html) - Categorization of MCP targets vs HTTP targets.
- [AgentCore Gateway - Configuring targets (Lambda, API GW, OpenAPI, Smithy, MCP Server, HTTP)](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-add-target-api-target-config.html) - Boto3 and CLI code for all target types with exact parameters.
- [AgentCore Gateway - Create a gateway via API](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-create-api.html) - CreateGateway with all authorizer types (CUSTOM_JWT, AWS_IAM, NONE, AUTHENTICATE_ONLY), semantic search, interceptors, policy engine, and debug messages.
- [AgentCore Gateway - Inbound auth setup](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-inbound-auth.html) - IAM, JWT, NONE, and private VPC-hosted IdP with managed/self-managed Lattice for ingress auth; scope advertisement RFC 6750.
- [AgentCore Gateway - Permissions and Service Role](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-prerequisites-permissions.html) - Trust policy, service role permissions, resource-based policies for Lambda/S3.
- [AgentCore Gateway - Semantic Tool Search](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-using-mcp-semantic-search.html) - How to use `x_amz_bedrock_agentcore_search` with natural-language queries.
- [AgentCore Gateway - Inbound JWT Authorizer config](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/inbound-jwt-authorizer.html) - Parameters `discoveryUrl`, `allowedAudience`, `allowedClients`, `allowedScopes`, `customClaims`.
- [AgentCore Gateway - Fine-Grained Access Control](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-fine-grained-access-control.html) - Implementation via interceptors (REQUEST/RESPONSE Lambda), JWT claims validation, IAM principal matching, external authorization services.
- [AgentCore Gateway - Interceptors](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-interceptors.html) - Lambda interceptor configuration (REQUEST before target, RESPONSE after): max 1 REQUEST and 1 RESPONSE per gateway. `passRequestHeaders` details and security.
- [AgentCore Gateway - Rules](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-rules.html) - Traffic routing and config bundle override without redeployment: priority 1–1M, max 20 rules/gateway, `matchPrincipals` and `matchPaths` conditions, A/B testing with `weightedOverride`/`weightedRoute`.
- [AgentCore Identity - Credential Providers (OAuth2, API Key, Payment)](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/resource-providers.html) - Create OAuth2 providers (26 pre-configured vendors + custom), API key, and payment providers (CoinbaseCDP, StripePrivy) with BYOS Secrets Manager.
- [AgentCore Identity - Getting OAuth2 Access Token](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/identity-authentication.html) - `requires_access_token` decorator, USER_FEDERATION vs M2M flows, automatic refresh token storage.
- [AgentCore Identity - Workload Access Token](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/get-workload-access-token.html) - JWT-based pattern (GetWorkloadAccessTokenForJWT) and UserId-based pattern, detailed security controls including explicit Deny for UserId.
- [AgentCore Identity - On-Behalf-Of Token Exchange](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/on-behalf-of-token-exchange.html) - RFC 8693 TOKEN_EXCHANGE (`actorTokenContent`: M2M/AWS_IAM_ID_TOKEN_JWT/NONE) and RFC 7523 JWT_AUTHORIZATION_GRANT, native Microsoft OBO.
- [AgentCore Identity - Scope Credential Provider Access](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/scope-credential-provider-access.html) - IAM policies to restrict credential provider access to specific workload identities; examples with GetResourceOauth2Token and GetResourceApiKey.
- [AgentCore Identity - Tutorial: first authenticated agent with Cognito](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/identity-getting-started-cognito.html) - End-to-end tutorial with real code: Cognito user pool, credential provider, deploy on Runtime.
- [AgentCore Release Notes](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/release-notes.html) - Complete changelog with GA/preview dates for every feature from July 2025 to June 2026.
- [Quotas for Amazon Bedrock AgentCore](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/bedrock-agentcore-limits.html) - Complete quotas for Gateway (targets, tools, invocation rate), Identity (workload identities, credential providers), and all other services.
- [Amazon Bedrock AgentCore Pricing](https://aws.amazon.com/bedrock/agentcore/pricing/) - Official pricing: Gateway $0.005/1K invocations, $0.025/1K searches, $0.02/100 tools/month; Identity $0.010/1K tokens (free via Runtime/Gateway); Policy $0.000025/authorization request.
- [BedrockAgentCoreFullAccess - Managed Policy](https://docs.aws.amazon.com/aws-managed-policy/latest/reference/BedrockAgentCoreFullAccess.html) - AWS managed policy for full access to Gateway and Identity.
- [AWS What's New - AgentCore GA](https://aws.amazon.com/about-aws/whats-new/2025/10/amazon-bedrock-agentcore-available/) - GA announcement October 2025 with main features.
- [AWS What's New - AgentCore Identity BYOS (Secrets Manager)](https://aws.amazon.com/about-aws/whats-new/2026/06/agentcore-identity-secrets-manager/) - June 2026: bring-your-own-secret with Secrets Manager for credential providers.
