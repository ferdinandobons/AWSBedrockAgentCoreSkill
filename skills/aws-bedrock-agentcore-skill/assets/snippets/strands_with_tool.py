# <!-- Asset of the aws-bedrock-agentcore-skill skill. See ../SKILL.md and ../references/ for detail and official sources. -->
#
# Strands Agent with a custom @tool decorator.
# Shows the three tool-registration methods:
#   1. @tool decorator (recommended for full control / custom error handling)
#   2. Direct function passing in tools=[]
#   3. ToolContext injection for accessing agent state inside a tool
#
# Source: https://strandsagents.com/docs/user-guide/concepts/agents/state/index.md
#         https://strandsagents.com/docs/user-guide/concepts/multi-agent/agents-as-tools/
# Read the matching reference file: ../references/strands.md

from strands import Agent, tool, ToolContext
from strands.models import BedrockModel

# ------------------------------------------------------------------
# 1. Simple @tool - docstring is the description the model sees.
#    Keep it clear and unambiguous so the model picks the right tool.
# ------------------------------------------------------------------
@tool
def get_product_price(product_name: str) -> str:
    """Return the current price (USD) for the requested product.

    Args:
        product_name: Exact product name to look up.

    Returns:
        A string with the price, e.g. 'Widget X: $29.99'.
    """
    # Replace with your real data source.
    catalogue = {"Widget X": 29.99, "Gadget Pro": 149.00}
    price = catalogue.get(product_name)
    if price is None:
        return f"Product '{product_name}' not found."
    return f"{product_name}: ${price:.2f}"


# ------------------------------------------------------------------
# 2. @tool with context=True - injects ToolContext so the tool can
#    read/write agent state without polluting the LLM context.
# ------------------------------------------------------------------
@tool(context=True)
def increment_request_counter(tool_context: ToolContext) -> str:
    """Increment the internal request counter and return the new value.

    Returns:
        The updated request count as a string.
    """
    count = tool_context.agent.state.get("request_count") or 0
    tool_context.agent.state.set("request_count", count + 1)
    return f"Request count is now {count + 1}."


# ------------------------------------------------------------------
# Build the agent with both tools.
# state dict must be JSON-serializable (non-serializable values raise ValueError).
# ------------------------------------------------------------------
model = BedrockModel(
    model_id="anthropic.claude-sonnet-4-20250514-v1:0",
    region_name="us-east-1",
)

agent = Agent(
    model=model,
    system_prompt="You are a product assistant. Use tools to answer questions.",
    tools=[get_product_price, increment_request_counter],
    state={"request_count": 0},
    callback_handler=None,     # silence stdout; handle output yourself
)

result = agent("How much does Widget X cost? Also track this request.")
print(result)
print("Request count in state:", agent.state.get("request_count"))
