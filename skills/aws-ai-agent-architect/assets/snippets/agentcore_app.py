# <!-- Asset of the aws-ai-agent-architect skill. See ../SKILL.md and ../references/ for detail and official sources. -->
#
# BedrockAgentCoreApp entrypoint — respects the /invocations + /ping contract.
#
# AgentCore Runtime requires ANY hosted agent to expose exactly:
#   POST /invocations  — receives payload dict, returns JSON or SSE stream
#   GET  /ping         — returns {"status": "Healthy"|"HealthyBusy",
#                                 "time_of_last_update": <unix_seconds>}
# Both on port 8080, ARM64. BedrockAgentCoreApp handles this automatically.
#
# This file shows three patterns from the official docs in one place:
#   1. Synchronous entrypoint (minimal)
#   2. Async generator entrypoint for SSE streaming
#   3. Async background task with /ping management via add_async_task /
#      complete_async_task (SDK sets HealthyBusy automatically)
#
# Container requirements:
#   - Platform: linux/arm64  (docker buildx build --platform linux/arm64)
#   - Port 8080 exposed
#   - pip install bedrock-agentcore strands-agents
#   - Session IDs must be >= 33 characters
#
# Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/using-any-agent-framework.html
#         https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/response-streaming.html
#         https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-long-run.html
# Read the matching reference file: ../references/agentcore-runtime.md

import threading
import time

from strands import Agent, tool
from bedrock_agentcore.runtime import BedrockAgentCoreApp

# ------------------------------------------------------------------
# Create one shared App instance (serves /invocations, /ping, /ws)
# ------------------------------------------------------------------
app = BedrockAgentCoreApp()

# Create your agent — swap in any model or tools here.
agent = Agent(
    system_prompt="You are a helpful assistant deployed on Bedrock AgentCore Runtime.",
)

# ------------------------------------------------------------------
# Pattern 1 — Synchronous entrypoint (simplest path)
# ------------------------------------------------------------------
# Uncomment this block and comment out the async generator below to use it.
#
# @app.entrypoint
# def agent_invocation_sync(payload, context):
#     """Synchronous handler.
#
#     payload: dict deserialized from POST /invocations body
#              e.g. {"prompt": "Hello"}
#     context.session_id: the runtimeSessionId from the caller (>= 33 chars)
#     """
#     user_message = payload.get(
#         "prompt",
#         "No prompt found. Send JSON with a 'prompt' key.",
#     )
#     result = agent(user_message)
#     return {"result": str(result.message)}

# ------------------------------------------------------------------
# Pattern 2 — Async generator entrypoint (SSE streaming)
# SDK automatically sets Content-Type: text/event-stream.
# Each yielded value becomes one SSE data chunk.
# ------------------------------------------------------------------
@app.entrypoint
async def agent_invocation(payload, context):
    """Streaming SSE entrypoint — recommended for interactive agents."""
    user_message = payload.get(
        "prompt",
        "No prompt found. Send JSON with a 'prompt' key.",
    )
    async for event in agent.stream_async(user_message):
        yield event


# ------------------------------------------------------------------
# Pattern 3 — Async background task with /ping HealthyBusy management
#
# app.add_async_task(name)    → SDK sets /ping to HealthyBusy
# app.complete_async_task(id) → SDK reverts /ping to Healthy
# Without this, a long background job looks idle and the session is
# terminated after the configured idleRuntimeSessionTimeout (default 15 min).
# IMPORTANT: omitting time_of_last_update from /ping causes premature
# termination even when HealthyBusy is set — the SDK fills it in automatically.
# ------------------------------------------------------------------
@tool
def start_background_task(duration: int = 5) -> str:
    """Start a background task that keeps the session alive via HealthyBusy.

    Args:
        duration: How many seconds the background work takes.
    Returns:
        Confirmation message with task ID.
    """
    task_id = app.add_async_task("background_processing", {"duration": duration})

    def do_work():
        time.sleep(duration)
        app.complete_async_task(task_id)   # reverts /ping to Healthy

    threading.Thread(target=do_work, daemon=True).start()
    return f"Background task {task_id} started for {duration}s."


# ------------------------------------------------------------------
# Entry point — starts HTTP server on 0.0.0.0:8080
# ------------------------------------------------------------------
if __name__ == "__main__":
    app.run()
