# <!-- Asset of the aws-ai-agent-architect skill. See ../SKILL.md and ../references/ for detail and official sources. -->
#
# Minimal Strands Agent with an explicit BedrockModel + region_name.
# Demonstrates the cleanest entry-point pattern for AWS-hosted agents:
# - BedrockModel uses the Bedrock Converse API internally (not InvokeModel legacy).
# - region_name is set explicitly because AWS_REGION is NOT in the boto3
#   resolution chain; always prefer BedrockModel(region_name=...) or
#   AWS_DEFAULT_REGION.
# - model shorthand string is equivalent to building BedrockModel manually.
#
# Source: https://strandsagents.com/docs/user-guide/quickstart/python/index.md
#         https://strandsagents.com/docs/user-guide/concepts/model-providers/amazon-bedrock/index.md
# Read the matching reference file: ../references/strands.md
#
# IAM minimum:
#   bedrock:InvokeModelWithResponseStream on the model resource
#   (streaming=True is the default)

from strands import Agent
from strands.models import BedrockModel

model = BedrockModel(
    model_id="anthropic.claude-sonnet-4-20250514-v1:0",
    region_name="us-east-1",   # explicit — do NOT rely on AWS_REGION
    temperature=0.3,
    max_tokens=4096,
    streaming=True,            # default True — uses Converse streaming API
)

agent = Agent(
    model=model,
    system_prompt="You are a helpful technical assistant.",
)

result = agent("What is Amazon Bedrock?")
print(result)               # full response text
print(result.stop_reason)   # 'end_turn'
print(result.metrics.get_summary())  # latency, token usage

# Equivalent shorthand — Agent(model="...") auto-creates a BedrockModel:
#   agent2 = Agent(model="anthropic.claude-sonnet-4-20250514-v1:0")
