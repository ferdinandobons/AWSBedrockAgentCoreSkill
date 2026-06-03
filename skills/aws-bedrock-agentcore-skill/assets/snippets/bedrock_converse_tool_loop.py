# <!-- Asset of the aws-bedrock-agentcore-skill skill. See ../SKILL.md and ../references/ for detail and official sources. -->
#
# Raw boto3 Bedrock Converse API with a complete client-side tool_use loop.
# Pattern: call Converse → if stopReason == 'tool_use', execute the tool,
# append toolResult to messages, call again → repeat until end_turn (or other
# terminal stopReason).
#
# Key rules from the docs:
#   - Always pass status ('success' or 'error') in every toolResult.
#   - Append ALL toolResult blocks as a single user message.
#   - Loop until stopReason != 'tool_use' — the model may chain multiple tool calls.
#   - toolChoice 'auto' / 'any' / 'tool' — only 'auto' is supported with thinking.
#   - Use cross-region inference profile prefix (us.) for production throughput.
#
# Source: https://docs.aws.amazon.com/bedrock/latest/userguide/tool-use-client-side.html
# Read the matching reference file: ../references/bedrock.md

import boto3
import logging
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)
client = boto3.client("bedrock-runtime", region_name="us-east-1")


# ------------------------------------------------------------------
# Tool implementation (your business logic goes here)
# ------------------------------------------------------------------
def get_top_song(call_sign: str) -> dict:
    songs = {"WZPZ": {"song": "Elemental Hotel", "artist": "8 Storey Hike"}}
    if call_sign not in songs:
        raise ValueError(f"Station {call_sign} not found")
    return songs[call_sign]


# ------------------------------------------------------------------
# Tool specification sent to Bedrock on every Converse call
# ------------------------------------------------------------------
tool_config = {
    "tools": [
        {
            "toolSpec": {
                "name": "top_song",
                "description": "Get the most popular song currently playing on a radio station.",
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "sign": {
                                "type": "string",
                                "description": "Radio station call sign, e.g. WZPZ, WKRP.",
                            }
                        },
                        "required": ["sign"],
                    }
                },
            }
        }
    ],
    # toolChoice options: {"auto": {}} | {"any": {}} | {"tool": {"name": "top_song"}}
    # NOTE: when using extended/adaptive thinking, only "auto" or omitted is supported.
    "toolChoice": {"auto": {}},
}


# ------------------------------------------------------------------
# Main loop
# ------------------------------------------------------------------
def run_with_tools(user_input: str) -> list:
    """Run a conversation that may call tools repeatedly until end_turn."""
    model_id = "us.anthropic.claude-sonnet-4-6"  # geo cross-region profile

    messages = [{"role": "user", "content": [{"text": user_input}]}]

    while True:
        try:
            response = client.converse(
                modelId=model_id,
                messages=messages,
                toolConfig=tool_config,
                inferenceConfig={"maxTokens": 1024, "temperature": 0.7},
            )
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code == "ThrottlingException":
                logger.warning("Rate limit hit (TPM quota). Implement backoff.")
            raise

        output_message = response["output"]["message"]
        messages.append(output_message)          # keep conversation history
        stop_reason = response["stopReason"]

        if stop_reason == "tool_use":
            tool_results = []

            for block in output_message["content"]:
                if "toolUse" not in block:
                    continue

                tool = block["toolUse"]
                logger.info("Tool requested: %s (id=%s)", tool["name"], tool["toolUseId"])

                try:
                    if tool["name"] == "top_song":
                        result = get_top_song(tool["input"]["sign"])
                        tool_results.append({
                            "toolUseId": tool["toolUseId"],
                            "content": [{"json": result}],
                            "status": "success",    # required field
                        })
                    else:
                        tool_results.append({
                            "toolUseId": tool["toolUseId"],
                            "content": [{"text": f"Unknown tool: {tool['name']}"}],
                            "status": "error",
                        })
                except Exception as exc:
                    tool_results.append({
                        "toolUseId": tool["toolUseId"],
                        "content": [{"text": str(exc)}],
                        "status": "error",
                    })

            # Append ALL results as a single user turn
            messages.append({
                "role": "user",
                "content": [{"toolResult": tr} for tr in tool_results],
            })

        else:
            # end_turn, max_tokens, stop_sequence, guardrail_intervened, etc.
            final_text = ""
            for block in output_message["content"]:
                if "text" in block:
                    final_text += block["text"]
            print(final_text)

            usage = response["usage"]
            print(f"Tokens — in: {usage['inputTokens']}, out: {usage['outputTokens']}")
            break

    return messages


if __name__ == "__main__":
    run_with_tools("What is the most popular song on WZPZ?")
