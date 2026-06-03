<!-- Asset of the aws-ai-agent-architect skill. See ../SKILL.md and ../references/ for detail and official sources. -->

# Snippets Index

Copy-paste starter snippets for the `aws-ai-agent-architect` skill.
Each file is taken faithfully from code examples in the research bundles under
`.aws-research/bundles/`. Do not invent APIs or parameter names — check the
live AWS / Strands docs for values that change over time (model IDs, quotas,
pricing).

---

## Files

### `strands_bedrock_minimal.py`

**Pattern:** Minimal Strands Agent + explicit BedrockModel with `region_name`.

The cleanest entry point for AWS-hosted agents. Demonstrates:
- `BedrockModel` uses the Bedrock Converse API internally (not the legacy InvokeModel).
- Why `region_name` must be set explicitly (`AWS_REGION` is not in the boto3 resolution chain).
- The model-string shorthand (`Agent(model="...")`) and its full equivalent.

**Install:** `pip install strands-agents`

---

### `strands_with_tool.py`

**Pattern:** Strands Agent with a custom `@tool`.

Three tool-registration styles in one file:
1. `@tool` decorator — recommended for full control and custom error handling.
2. Direct passing in `tools=[]`.
3. `@tool(context=True)` + `ToolContext` — access/write agent `state` inside a
   tool without leaking data into the LLM context.

**Install:** `pip install strands-agents`

---

### `bedrock_converse_tool_loop.py`

**Pattern:** Raw boto3 `client.converse()` with a complete `tool_use` loop.

Use this when you need direct control over the Bedrock API without a framework.
Key rules:
- Loop until `stopReason != 'tool_use'` — the model can chain multiple calls.
- Always pass `status` (`'success'` or `'error'`) in every `toolResult`.
- Append all `toolResult` blocks as a single user message.
- Use the cross-region inference profile prefix (`us.`) for production throughput.

**Install:** `pip install boto3`

---

### `agentcore_app.py`

**Pattern:** `BedrockAgentCoreApp` entrypoint respecting the `/invocations` + `/ping` contract.

Shows three entrypoint patterns in one file:
1. Synchronous handler (commented out — uncomment to use).
2. Async generator for SSE streaming (active default).
3. Background task with `add_async_task` / `complete_async_task` — SDK sets
   `/ping` to `HealthyBusy` automatically, preventing premature session teardown.

Container requirements: `linux/arm64`, port `8080`.

**Install:** `pip install bedrock-agentcore strands-agents`

---

### `multi_agent_graph.py`

**Pattern:** `GraphBuilder` with production limits — three graph compositions.

1. **Conditional routing via `invocation_state`** — role-based dispatch without
   polluting the LLM context.
2. **Feedback loop** (writer → reviewer → writer …) — requires
   `set_max_node_executions()` and `set_execution_timeout()` or the loop runs
   forever.
3. **Nested Swarm as a graph node** — composable multi-agent with inner Swarm
   cycle detection (`repetitive_handoff_detection_window`).

Critical Python semantic note: Python Graph uses **OR semantics** (a node fires
when ANY incoming edge is satisfied). TypeScript Graph uses AND semantics. For
AND behaviour in Python, implement a conditional edge that checks
`GraphState.results` for all expected predecessors manually.

`session_manager` belongs **only on the outer orchestrator** — assigning one to
an inner agent raises `ValueError`.

**Install:** `pip install strands-agents`

---

## Cross-reference

| File | Research bundle |
|---|---|
| `strands_bedrock_minimal.py` | `.aws-research/bundles/strands.json` |
| `strands_with_tool.py` | `.aws-research/bundles/strands.json` |
| `bedrock_converse_tool_loop.py` | `.aws-research/bundles/bedrock.json` |
| `agentcore_app.py` | `.aws-research/bundles/agentcore-runtime.json` |
| `multi_agent_graph.py` | `.aws-research/bundles/multi-agent.json` |
