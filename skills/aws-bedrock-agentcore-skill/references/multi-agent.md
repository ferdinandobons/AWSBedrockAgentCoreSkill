# Strands Agents - Multi-Agent Patterns

> Part of the **aws-bedrock-agentcore-skill** skill. See [SKILL.md](../SKILL.md) for the decision tree. Every source below is official - re-open it to verify details.

## Table of contents

- [Overview](#overview)
- [Key concepts](#key-concepts)
  - [Agents-as-Tools](#agents-as-tools)
  - [Swarm](#swarm)
  - [Graph](#graph)
  - [Workflow](#workflow)
  - [Agent-to-Agent (A2A) Protocol](#agent-to-agent-a2a-protocol)
  - [invocation_state](#invocation_state)
  - [SharedContext (Swarm Python)](#sharedcontext-swarm-python)
  - [MultiAgentState / MultiAgentResult](#multiagentstate--multiagentresult)
  - [SessionManager](#sessionmanager)
  - [Nested Patterns (composition)](#nested-patterns-composition)
- [Best practices](#best-practices)
- [Code](#code)
  - [Agents-as-Tools Python: direct passing, .as_tool(), @tool decorator](#agents-as-tools-python-direct-passing-as_tool-tool-decorator)
  - [Agents-as-Tools TypeScript: direct passing, .asTool(), tool() with Zod](#agents-as-tools-typescript-direct-passing-astool-tool-with-zod)
  - [Swarm Python: all production parameters, SharedContext, streaming, result access](#swarm-python-all-production-parameters-sharedcontext-streaming-result-access)
  - [Swarm TypeScript: structured output handoff, maxSteps, streaming](#swarm-typescript-structured-output-handoff-maxsteps-streaming)
  - [Graph Python: GraphBuilder, conditional routing, nested Swarm, feedback loop](#graph-python-graphbuilder-conditional-routing-nested-swarm-feedback-loop)
  - [Graph TypeScript: AND semantics, EdgeHandler, streaming, all constructor parameters](#graph-typescript-and-semantics-edgehandler-streaming-all-constructor-parameters)
  - [Workflow Python: task DAG, parallelism, pause/resume (Python only)](#workflow-python-task-dag-parallelism-pauseresume-python-only)
  - [A2A Protocol Python: A2AServer, A2AAgent, A2AClientToolProvider, Graph node](#a2a-protocol-python-a2aserver-a2aagent-a2aclienttoolprovider-graph-node)
  - [BedrockModel: region priority, IAM policy, cross-region inference](#bedrockmodel-region-priority-iam-policy-cross-region-inference)
  - [SessionManager S3, OTEL tracing, AgentCore Runtime deploy](#sessionmanager-s3-otel-tracing-agentcore-runtime-deploy)
- [Configuration reference](#configuration-reference)
- [Gotchas](#gotchas)
- [Official sources](#official-sources)

---

## Overview

Strands Agents SDK (open source, **GA 1.0 released 15 July 2025** by AWS; Python SDK now at v1.42.x, TypeScript SDK at v1.4.x) provides four native primitives for multi-agent systems:

- **Agents-as-Tools** - orchestrator → specialist hierarchy
- **Swarm** - autonomous team with mutable SharedContext (Python) or serialized JSON (TypeScript)
- **Graph** - deterministic DAG with conditional routing; OR semantics in Python, AND semantics in TypeScript
- **Workflow** - task DAG with parallelism, available only via `strands_tools.workflow` in Python

The A2A protocol enables cross-platform communication via `A2AServer` and `A2AAgent`; supported in agents-as-tools and Graph, **not supported in Swarm** (architectural limitation confirmed, feature request #913 open). The default model provider is Amazon Bedrock (Claude Sonnet 4 in Python, Claude Sonnet 4.6 in TypeScript).

Amazon Bedrock AgentCore Runtime is GA since 13 October 2025 with A2A support and VPC/PrivateLink added. The `agent_graph` tool in `strands_tools` is **deprecated** - the replacement is `GraphBuilder` from the SDK.

**Maturity:** GA - Strands Agents Python SDK 1.0 (15 July 2025, current v1.42.x as of June 2026). TypeScript SDK 1.0 - GA 30 April 2026 with Graph, Swarm, A2A, and agents-as-tools. **Warning:** TypeScript pre-1.0 beta did NOT have multi-agent patterns; code written with the beta is not compatible with 1.0. Workflow (`strands_tools.workflow`) is Python-only - it is NOT a native primitive in the TypeScript SDK 1.0. Amazon Bedrock AgentCore Runtime: GA since 13 October 2025 (was public preview from July 2025); VPC/PrivateLink, A2A protocol support, CloudFormation, and resource tagging were added at GA.

---

## Key concepts

### Agents-as-Tools

Hierarchical pattern where an orchestrator agent calls specialist agents as tools. The orchestrator receives specialist agents in the `tools` array and invokes them through the model's normal tool-selection loop. Three methods:

1. **Direct passing** - pass the `Agent` directly in `tools[]`; the SDK automatically generates a schema with an `input` parameter.
2. **`.as_tool(name, description, preserve_context)` / `.asTool({name, description, preserveContext})`** - explicit control over name, description, and context continuity.
3. **`@tool` decorator (manual)** - custom pre/post logic and error handling.

An agent tool's context resets to empty by default between invocations (`preserve_context=False`).

### Swarm

Team of agents that coordinate autonomously. In **Python**: the active agent uses `handoff_to_agent(agent_name=..., message=..., context={...})` to transfer control. Each agent receives: original task, list of available agents, history of contributions, accumulated SharedContext. Python uses `SharedContext.add_context(node, key, value)` to write to shared memory; reading happens via the context the orchestrator constructs in handoff messages. In **TypeScript**: agents use structured output (`{agentId, message, context}`) instead of tool calls; context is serialized JSON. Swarm has access to `invocation_state` like all patterns. The `repetitive_handoff_detection_window` prevents ping-pong cycles. Can be used as a node inside a Graph.

### Graph

Deterministic directed-graph orchestration. Nodes are `Agent`, `Swarm`, or other `MultiAgentBase` instances. **Python** uses `GraphBuilder` with OR semantics: a node fires when ANY incoming edge completes. **TypeScript** uses the `Graph` constructor with AND semantics: a node waits for ALL incoming edges. This difference is critical for graphs with join nodes (multiple predecessors). Conditional edges receive `GraphState` (and optionally `invocation_state`) for runtime routing. Supports cycles (feedback loops) with `set_max_node_executions()` + `set_execution_timeout()` + `reset_on_revisit()`. A feature request (#1081) proposes adding AND semantics to Python as well, but it is still open.

### Workflow

Task DAG with explicit dependencies via `strands_tools.workflow`. **Python only** (Workflow as a native primitive does not exist in the TypeScript SDK 1.0). Two approaches:

1. **Imperative code** - manual chain of `agent()` calls.
2. **Built-in workflow tool** - define tasks with `task_id`, `description`, `system_prompt`, `dependencies[]`, `priority`; actions: `create`, `start`, `status`, `pause`, `resume`, `list`, `delete`. Executes tasks in parallel when dependencies are satisfied.

Does not support cycles. Suited for repeatable, deterministic processes.

### Agent-to-Agent (A2A) Protocol

**Cross-vendor open standard** (not AWS-specific - maintained by the A2A project at https://github.com/a2aproject/A2A) for cross-platform communication between agents on different networks. Strands implements:

- **`A2AServer`** (Python) / **`A2AExpressServer`** (TypeScript) - exposes an Agent via HTTP, auto-generates an agent card from tool descriptions, endpoint `/.well-known/agent-card.json`.
- **`A2AAgent`** - client that consumes a remote agent, auto-populates name/description from the agent card.
- **`A2AClientToolProvider`** - dynamically discovers multiple remote agents.

Supported in agents-as-tools and as a node in Graph. **NOT supported in Swarm** (architectural limitation, feature request #913 open).

### invocation_state

Dictionary of state/context passed to all nodes in a Graph or Swarm without appearing in the LLM prompt. Used to pass configuration (user role, feature flags, DB connections). Accessible to tools via `@tool(context=True)` and `ToolContext.invocation_state` in Python, or `context.invocationState` in TypeScript. Propagates automatically to all agents and hook events. Separate from model-visible content.

### SharedContext (Swarm Python)

Dataclass that maintains shared memory between Swarm agents in Python. API: `SharedContext.add_context(node: SwarmNode, key: str, value: Any) -> None` - adds key-value pairs associated with the calling node. Reading does not happen via direct getters exposed to agents - the orchestrator constructs handoff messages that include all accumulated values in the SharedContext. In TypeScript there is no mutable SharedContext: context is serialized as JSON in the structured handoff messages.

### MultiAgentState / MultiAgentResult

`MultiAgentState` / `SwarmState` contains: `current_node`, `task`, `shared_context`, `node_history`, `results`, `handoff_node`, `handoff_message`. `SwarmResult` extends `MultiAgentResult` with: `status`, `node_history`, `results` (dict by `node_id`), `execution_time` (ms), `accumulated_usage` (`inputTokens`, `outputTokens`, `totalTokens`, `cacheReadInputTokens`, `cacheWriteInputTokens`). `accumulated_usage` aggregates tokens from all invocations of all agents in the Swarm; it does not include separate system overhead.

`GraphResult` also extends `MultiAgentResult` and exposes: `results` (dict by node_id string, type `dict[str, NodeResult]`), `accumulated_usage`, `execution_order`, `total_nodes`, `completed_nodes`, `failed_nodes`, `execution_time`. **The key in `GraphResult.results` is the node_id string passed as the second argument to `GraphBuilder.add_node(executor, node_id)`** - it is NOT the agent's `name` attribute. A missing key returns `None` from `.get()` but raises `KeyError` if accessed directly; always use `.get(node_id)` to avoid silent errors. Per-node output is in `result.results[node_id].result` (an `AgentResult` or nested `MultiAgentResult`). `accumulated_usage` aggregates token counts across all nodes in the Graph execution, analogous to `SwarmResult.accumulated_usage`.

### SessionManager

Abstraction for agent state persistence. **Python**: `FileSessionManager` (dev) and `S3SessionManager` (prod, requires `s3:PutObject`, `s3:GetObject`, `s3:DeleteObject`, `s3:ListBucket`). **TypeScript**: `FileStorage` and `S3Storage`; also supports immutable UUID-v7 snapshots with a `snapshotTrigger` callback. In multi-agent systems: **only the orchestrator** (Graph/Swarm) should have a session manager. Python raises `ValueError` if an agent with a session manager is added to a Graph/Swarm.

### Nested Patterns (composition)

Patterns are composable: a Swarm can be a node in a Graph (`GraphBuilder.add_node(swarm, 'id')`), a Graph can orchestrate Swarms, and agents-as-tools work anywhere. Agents-as-tools, Graph, and Swarm are available in both Python and TypeScript 1.0. Workflow (`strands_tools.workflow`) is Python only. `agent_graph` (`strands_tools.agent_graph`) is **deprecated** - use `GraphBuilder`.

---

## Best practices

- **Choose pattern based on execution flow: Graph for conditional logic and approved processes, Swarm for emergent multi-perspective collaboration, Workflow for repeatable and deterministic processes, Agents-as-Tools for hierarchies with distinct specialists.** - Each pattern has different cost/benefit trade-offs. Graph offers control but requires upfront design; Swarm offers flexibility but high token cost for iterations; Workflow provides predictability but rigidity (no cycles). Choosing the wrong pattern leads to unnecessary overhead or unexpected behaviors. _Source: https://strandsagents.com/docs/user-guide/concepts/multi-agent/multi-agent-patterns/_

- **Always configure execution limits in production. For Swarm Python: `max_handoffs=20`, `max_iterations=20`, `execution_timeout=900.0`, `node_timeout=300.0`, `repetitive_handoff_detection_window=8`, `repetitive_handoff_min_unique_agents=3`. For Swarm TypeScript: `maxSteps` (single limit). For Graph Python: `set_max_node_executions()`, `set_execution_timeout()`, `reset_on_revisit(True)` for feedback loops.** - `repetitive_handoff_detection_window` and `repetitive_handoff_min_unique_agents` default to 0 (disabled). Without limits, infinite loops consume unlimited tokens in production. `repetitive_handoff_detection_window` prevents A⟺B ping-pong cycles. In TypeScript, exceeding `maxSteps` raises an exception (fail-fast); in Python it returns a FAILED result. _Source: https://strandsagents.com/docs/api/python/strands.multiagent.swarm/_

- **Use `invocation_state` for configuration context (role, feature flags, DB connections), not concatenated to the agent prompt. Access it via `@tool(context=True)` and `ToolContext.invocation_state`.** - `invocation_state` is invisible to the model but accessible to tools. Avoids polluting LLM context with system data and enables conditional routing via edge condition functions without modifying prompts. _Source: https://strandsagents.com/docs/user-guide/concepts/multi-agent/multi-agent-patterns/_

- **Add `SessionManager` ONLY to the orchestrator (Graph/Swarm), never to internal agents. In TypeScript use `S3Storage` for production with `snapshotTrigger` for immutable checkpoints.** - Python raises `ValueError` if an agent with a session manager is added to a Graph/Swarm. The orchestrator snapshots and restores each agent node's state on every execution; a session manager at the agent level would create conflicts. _Source: https://strandsagents.com/docs/user-guide/concepts/agents/session-management/_

- **Use A2A only for agents on different servers (network). For local coordination (same process) use Swarm, Graph, or agents-as-tools. Do not use `A2AClientToolProvider` for local agents.** - `A2AServer` + `A2AClientToolProvider` for local agents adds significant HTTP latency vs function calls. A2A is not supported in Swarm due to architectural limitations (issue #913 open); use Graph as an alternative for workflows with remote agents. _Source: https://strandsagents.com/docs/user-guide/concepts/multi-agent/agent-to-agent/_

- **Design specialist agents with tightly focused roles, descriptive names, and system prompts that clearly indicate expertise and when to invoke them.** - The orchestrator's tool selection is based on tool descriptions. If two agents have overlapping descriptions, the model has no basis for choosing correctly. This is one of the primary causes of wrong routing. _Source: https://aws.amazon.com/blogs/machine-learning/multi-agent-collaboration-patterns-with-strands-agents-and-amazon-nova/_

- **Enable OTEL tracing in production with `trace_attributes` for cross-agent correlation, sending to CloudWatch/X-Ray via AWS OTEL Collector.** - Multi-agent systems are hard to debug without visibility into node transitions. `trace_attributes` propagate to all spans and allow tracing the complete request path. _Source: https://strandsagents.com/docs/user-guide/observability-evaluation/traces/_

- **In Graph Python, for nodes with multiple predecessors that require AND behavior (wait for all), implement conditional edges that manually check the state of other nodes via `GraphState.results`.** - Python uses OR semantics by default: a node fires as soon as any predecessor completes. Feature request #1081 proposes adding AND semantics as a constructor option, but it is still open. TypeScript natively uses AND semantics. _Source: https://github.com/strands-agents/sdk-python/issues/1081_

- **Do not use `strands_tools.agent_graph`: it is deprecated with removal planned at the next major release. Use `GraphBuilder` from the main SDK.** - `agent_graph` is a `strands_tools` tool that creates agent networks with message-passing topologies; it already has a deprecation warning and will be removed. `GraphBuilder` is the official primitive for graph orchestration. _Source: https://github.com/strands-agents/tools_

- **Always specify `region_name` explicitly in the `BedrockModel` constructor for predictable behavior. In production on Bedrock, scope down the IAM `Resource` to specific model ARNs instead of wildcards.** - `AWS_REGION` has lower priority than the region set in the AWS profile. Not specifying it explicitly leads to invocations in an unexpected region. The principle of least privilege requires specific ARNs. _Source: https://strandsagents.com/docs/user-guide/concepts/model-providers/amazon-bedrock/_

- **Minimize dependencies between tasks in Workflow to maximize automatic parallelism. Only Workflow natively executes independent tasks in parallel.** - The workflow tool automatically resolves which tasks can run in parallel. Unnecessary dependencies serialize execution and increase latency. _Source: https://strandsagents.com/docs/user-guide/concepts/multi-agent/workflow/_

---

## Code

### Agents-as-Tools Python: direct passing, .as_tool(), @tool decorator

```python
from strands import Agent, tool
from strands_tools import retrieve, http_request

# Specialist agents
research_agent = Agent(
    name="researcher",
    system_prompt="You are a specialized research assistant. Answer research queries with citations.",
    tools=[retrieve, http_request]
)
product_agent = Agent(
    name="product_expert",
    system_prompt="You are a product expert. Answer product-related queries about selection, pricing, and availability."
)

# Method 1: Direct passing (simplest - SDK automatically generates schema with 'input' parameter)
orchestrator_direct = Agent(
    system_prompt="Route queries to the appropriate specialist.",
    tools=[research_agent, product_agent]
)

# Method 2: .as_tool() for control over name/description/context
orchestrator_astool = Agent(
    system_prompt="Route queries to specialists.",
    tools=[
        research_agent.as_tool(
            name="research_assistant",
            description="Process research queries. Use for scientific, historical, or factual questions.",
            preserve_context=False  # default: reset context between invocations
        ),
        product_agent.as_tool(
            name="product_advisor",
            description="Handle product selection, pricing, and availability queries."
        )
    ]
)

# Method 3: @tool decorator for custom logic / error handling
@tool
def research_assistant(query: str) -> str:
    """Process and respond to research-related queries. Use for scientific and factual questions.
    
    Args:
        query: A research question requiring factual information
    Returns:
        A detailed research answer
    """
    try:
        agent = Agent(
            system_prompt="You are a specialized research assistant.",
            tools=[retrieve, http_request]
        )
        response = agent(query)
        return str(response)
    except Exception as e:
        return f"Research error: {str(e)}"

orchestrator_custom = Agent(
    system_prompt="You are an orchestrator. Delegate to specialists.",
    tools=[research_assistant]
)

result = orchestrator_direct("What are the latest developments in quantum computing?")
```

_Source: https://strandsagents.com/docs/user-guide/concepts/multi-agent/agents-as-tools/_

---

### Agents-as-Tools TypeScript: direct passing, .asTool(), tool() with Zod

```typescript
import { Agent, tool } from '@strands-agents/sdk'
import { z } from 'zod'

const researchAgent = new Agent({
  name: 'researcher',
  systemPrompt: 'You are a specialized research assistant.'
})

const productAgent = new Agent({
  name: 'product_expert',
  systemPrompt: 'You are a product expert.'
})

// Method 1: direct passing
const orchestratorDirect = new Agent({
  systemPrompt: 'Route queries to specialists.',
  tools: [researchAgent, productAgent]
})

// Method 2: .asTool()
const orchestratorAsTool = new Agent({
  systemPrompt: 'Route queries to specialists.',
  tools: [
    researchAgent.asTool({
      name: 'research_assistant',
      description: 'Process research queries. Use for scientific and factual questions.',
      preserveContext: false
    }),
    productAgent.asTool({
      name: 'product_advisor',
      description: 'Handle product selection and availability queries.'
    })
  ]
})

// Method 3: tool() with Zod for custom logic
const researchTool = tool({
  name: 'research_assistant',
  description: 'Process research-related queries requiring factual information.',
  inputSchema: z.object({
    query: z.string().describe('The research question to answer')
  }),
  callback: async (input) => {
    const agent = new Agent({ systemPrompt: 'You are a research specialist.' })
    const response = await agent.invoke(input.query)
    return response.lastMessage.content
      .map((block: any) => ('text' in block ? block.text : ''))
      .join('')
  }
})

const result = await orchestratorDirect.invoke('Latest developments in quantum computing?')
```

_Source: https://strandsagents.com/docs/user-guide/concepts/multi-agent/agents-as-tools/_

---

### Swarm Python: all production parameters, SharedContext, streaming, result access

```python
from strands import Agent, tool
from strands.multiagent import Swarm
from strands.multiagent.swarm import SharedContext
from strands_tools import memory, calculator, file_write
import logging

logging.getLogger("strands.multiagent").setLevel(logging.DEBUG)

# NOTE on SharedContext: the public API exposes only one method:
#   SharedContext.add_context(node: SwarmNode, key: str, value: Any) -> None
# Reading happens implicitly: the orchestrator builds the handoff message
# including all accumulated values in SharedContext for the next agent.
# There is no public get_context() method - context is serialized
# in the messages each agent receives at the start of its turn.

researcher = Agent(
    name="researcher",
    system_prompt="""You are a research specialist. Research topics thoroughly.
    When analysis is needed, hand off to the 'analyst'.
    When a final report is needed, hand off to the 'writer'.""",
    tools=[memory]
)

analyst = Agent(
    name="analyst",
    system_prompt="""You are a data analysis specialist. Analyze data and extract insights.
    When analysis is complete, hand off to the 'writer' for the report.""",
    tools=[calculator, memory]
)

writer = Agent(
    name="writer",
    system_prompt="""You are a report writing specialist.
    Write comprehensive reports. Do not hand off - produce the final output.""",
    tools=[file_write, memory]
)

# Create Swarm with production parameters
# Exact signatures from strands.multiagent.swarm (SDK v1.42.x)
swarm = Swarm(
    nodes=[researcher, analyst, writer],  # positional parameter
    entry_point=researcher,               # Agent | None, default None (first in list)
    max_handoffs=20,                      # default 20
    max_iterations=20,                    # default 20
    execution_timeout=900.0,              # default 900.0 sec
    node_timeout=300.0,                   # default 300.0 sec
    repetitive_handoff_detection_window=8,   # default 0 (disabled!)
    repetitive_handoff_min_unique_agents=3,  # default 0 (disabled!)
    # session_manager=s3_session_manager,  # ONLY here, not on internal agents
    # hooks=[],
    # trace_attributes={"session.id": "..."},
    # plugins=[]
)

# Synchronous invocation
result = swarm(
    "Research and analyze the impact of AI on healthcare",
    invocation_state={"user_id": "user123", "debug_mode": True}
)

# Access results
print(f"Status: {result.status}")
print(f"Node history: {[node.node_id for node in result.node_history]}")
print(f"Execution time: {result.execution_time}ms")
# accumulated_usage: inputTokens, outputTokens, totalTokens, cacheReadInputTokens, cacheWriteInputTokens
print(f"Token usage: {result.accumulated_usage}")
writer_output = result.results.get("writer")
if writer_output:
    print(f"Writer result: {writer_output.result}")

# Async streaming
import asyncio

async def stream_swarm():
    async for event in swarm.stream_async("Design a REST API"):
        if event.get("type") == "multiagent_node_start":
            print(f"Agent {event['node_id']} starting")
        elif event.get("type") == "multiagent_handoff":
            print(f"Handoff: {event['from_node_ids']} -> {event['to_node_ids']}")
        elif event.get("type") == "multiagent_node_stop":
            print(f"Agent {event['node_id']} done")
        elif event.get("type") == "multiagent_result":
            print(f"Final status: {event['result'].status}")

# Access invocation_state in agent tools
from strands import ToolContext

@tool(context=True)
def query_customer_data(query: str, tool_context: ToolContext) -> str:
    """Query customer data using context from invocation_state."""
    user_id = tool_context.invocation_state.get("user_id")
    debug = tool_context.invocation_state.get("debug_mode", False)
    if debug:
        print(f"Querying for user: {user_id}, query: {query}")
    return f"Results for {user_id}: ..."
```

_Source: https://strandsagents.com/docs/api/python/strands.multiagent.swarm/_

---

### Swarm TypeScript: structured output handoff, maxSteps, streaming

```typescript
import { Agent } from '@strands-agents/sdk'
import { Swarm } from '@strands-agents/sdk/multiagent'

// In TypeScript agents use structured output ({agentId, message, context})
// instead of tool calls for handoffs - no handoff_to_agent tool is injected.
// Omitting agentId produces the final Swarm result.

const researcher = new Agent({
  id: 'researcher',
  systemPrompt: `You are a research specialist.
    When done researching, return: { agentId: "analyst", message: "<findings>" }
    to hand off to the analyst.`
})

const analyst = new Agent({
  id: 'analyst',
  systemPrompt: `You are an analyst.
    When analysis is complete, return: { agentId: "writer", message: "<analysis>" }
    to hand off to the writer.`
})

const writer = new Agent({
  id: 'writer',
  systemPrompt: `You are a writer. Write the final report and return:
    { message: "<final report>" } (no agentId - this ends the swarm).`
})

// TypeScript Swarm: maxSteps instead of separate max_handoffs + max_iterations
// NOTE: exceeding maxSteps raises an exception (unlike Python which returns FAILED)
const swarm = new Swarm({
  nodes: [researcher, analyst, writer],
  start: 'researcher',  // initial agent name/id
  maxSteps: 20,         // default: Infinity
  timeout: 900_000,     // milliseconds (default: Infinity)
  nodeTimeout: 300_000  // milliseconds per node (default: Infinity)
})

// Invocation
const result = await swarm.invoke('Research and analyze AI impact on healthcare')
console.log(result.status)

// Streaming
// NOTE: TypeScript uses PascalCase class-based event types (camelCase .type strings),
// unlike Python which uses snake_case string keys (e.g. 'multiagent_handoff').
for await (const event of swarm.stream('Analyze Q3 financials')) {
  if (event.type === 'nodeResultEvent') {
    console.log(`Agent ${event.nodeId} done`)
  } else if (event.type === 'multiAgentHandoffEvent') {
    console.log(`Handoff: ${event.source} -> ${event.targets.join(', ')}`)
  } else if (event.type === 'multiAgentResultEvent') {
    console.log(`Final: ${event.result.status}`)
  }
}
```

_Source: https://strandsagents.com/docs/user-guide/concepts/multi-agent/swarm/_

---

### Graph Python: GraphBuilder, conditional routing, nested Swarm, feedback loop

```python
from strands import Agent
from strands.multiagent import GraphBuilder, Swarm
from strands.multiagent.graph import GraphState

# === EXAMPLE 1: Conditional routing with invocation_state ===
# NOTE: Python uses OR semantics - a node fires when ANY incoming edge completes.
# For AND semantics, implement a conditional edge that checks all predecessors.

router = Agent(name="router", system_prompt="Categorize the request.")
admin_panel = Agent(name="admin", system_prompt="Handle admin requests.")
standard_path = Agent(name="standard", system_prompt="Handle standard requests.")

def requires_admin(state: GraphState, *, invocation_state: dict, **kwargs) -> bool:
    return invocation_state.get("role") == "admin"

def is_standard(state: GraphState, *, invocation_state: dict, **kwargs) -> bool:
    return invocation_state.get("role") != "admin"

builder = GraphBuilder()
builder.add_node(router, "router")
builder.add_node(admin_panel, "admin")
builder.add_node(standard_path, "standard")
builder.add_edge("router", "admin", condition=requires_admin)
builder.add_edge("router", "standard", condition=is_standard)
builder.set_entry_point("router")
builder.set_execution_timeout(300)
routing_graph = builder.build()

result = routing_graph(
    "Process this request",
    invocation_state={"role": "admin"}
)

# === EXAMPLE 2: Nested Swarm as a node in Graph ===

research_agents = [
    Agent(name="medical_researcher", system_prompt="Medical research specialist."),
    Agent(name="tech_researcher", system_prompt="Technology research specialist."),
    Agent(name="economic_researcher", system_prompt="Economic research specialist.")
]
research_swarm = Swarm(nodes=research_agents)

analyst = Agent(name="analyst", system_prompt="Synthesize multi-domain research.")
report_writer = Agent(name="report_writer", system_prompt="Write comprehensive reports.")

builder2 = GraphBuilder()
builder2.add_node(research_swarm, "research_team")  # Swarm as a node!
builder2.add_node(analyst, "analysis")
builder2.add_node(report_writer, "report")
builder2.add_edge("research_team", "analysis")
builder2.add_edge("analysis", "report")
builder2.set_entry_point("research_team")
research_graph = builder2.build()

result2 = research_graph("Research AI's impact on healthcare")

# === EXAMPLE 3: Feedback loop with set_max_node_executions ===

draft_writer = Agent(name="draft_writer", system_prompt="Write a draft. Improve based on feedback.")
reviewer = Agent(name="reviewer", system_prompt="Review drafts. Say 'approved' or 'revision needed'.")
publisher = Agent(name="publisher", system_prompt="Publish the approved content.")

def needs_revision(state: GraphState) -> bool:
    review_result = state.results.get("reviewer")
    return review_result and "revision needed" in str(review_result.result).lower()

def is_approved(state: GraphState) -> bool:
    review_result = state.results.get("reviewer")
    return review_result and "approved" in str(review_result.result).lower()

builder3 = GraphBuilder()
builder3.add_node(draft_writer, "draft_writer")
builder3.add_node(reviewer, "reviewer")
builder3.add_node(publisher, "publisher")
builder3.add_edge("draft_writer", "reviewer")
builder3.add_edge("reviewer", "draft_writer", condition=needs_revision)  # cycle!
builder3.add_edge("reviewer", "publisher", condition=is_approved)
builder3.set_max_node_executions(10)  # CRITICAL for feedback loops
builder3.set_execution_timeout(300)
builder3.reset_on_revisit(True)  # reset agent state when a node is revisited
feedback_graph = builder3.build()

result3 = feedback_graph("Write an article about AI safety")

# === EXAMPLE 4: Sequential specialist routing (A → B, B receives A's output) ===
# A router node conditionally routes to specialist A, which then routes to specialist B.
# B receives A's output automatically: downstream nodes get the original task PLUS
# the text result from every completed dependency node as combined input.
# The condition function reads GraphState.results keyed by node_id (the string passed
# to add_node as the second argument). result.results[node_id] is a NodeResult;
# .result gives the underlying AgentResult or MultiAgentResult.

intake_agent = Agent(name="intake", system_prompt="Classify the request as 'code' or 'docs'.")
code_specialist = Agent(name="coder", system_prompt="Implement the requested code feature.")
docs_specialist = Agent(name="documenter", system_prompt="Write documentation for a feature.")
finaliser = Agent(name="finaliser", system_prompt="Package the output for delivery.")

def route_to_code(state: GraphState) -> bool:
    intake_result = state.results.get("intake")  # key = node_id, not agent name
    return intake_result and "code" in str(intake_result.result).lower()

def route_to_docs(state: GraphState) -> bool:
    intake_result = state.results.get("intake")
    return intake_result and "docs" in str(intake_result.result).lower()

builder4 = GraphBuilder()
builder4.add_node(intake_agent, "intake")
builder4.add_node(code_specialist, "code")
builder4.add_node(docs_specialist, "docs")
builder4.add_node(finaliser, "finaliser")
builder4.add_edge("intake", "code", condition=route_to_code)   # conditional: code path
builder4.add_edge("intake", "docs", condition=route_to_docs)   # conditional: docs path
builder4.add_edge("code", "finaliser")    # B → C: finaliser gets code specialist's output
builder4.add_edge("docs", "finaliser")    # B → C: finaliser gets docs specialist's output
builder4.set_entry_point("intake")
builder4.set_execution_timeout(300)
sequential_graph = builder4.build()

result4 = sequential_graph("Add a retry mechanism to the HTTP client")
# Access per-node results after execution:
# GraphResult.results is a dict[str, NodeResult] keyed by the node_id string.
# result4.results["code"].result  → AgentResult from the code specialist
# result4.results["finaliser"].result  → AgentResult from the finaliser
# result4.accumulated_usage  → aggregated token counts across all nodes (see below)
code_output = result4.results.get("code")
if code_output:
    print(f"Code specialist output: {code_output.result}")
print(f"Token usage: {result4.accumulated_usage}")  # inputTokens/outputTokens/totalTokens
```

_Source: https://strandsagents.com/docs/user-guide/concepts/multi-agent/graph/_

---

### Graph TypeScript: AND semantics, EdgeHandler, streaming, all constructor parameters

```typescript
import { Agent } from '@strands-agents/sdk'
import { Graph } from '@strands-agents/sdk/multiagent'
import type { EdgeHandler } from '@strands-agents/sdk/multiagent'

// TypeScript Graph uses AND semantics: each node waits for ALL incoming edges
// (unlike Python which uses OR semantics)

const researcher = new Agent({
  id: 'researcher',
  systemPrompt: 'You are a research specialist.'
})

const writer = new Agent({
  id: 'writer',
  systemPrompt: 'You are a writing specialist.'
})

const reviewer = new Agent({
  id: 'reviewer',
  systemPrompt: 'Say APPROVED or REQUEST_REVISION.'
})

// Conditional EdgeHandler
const needsRevision: EdgeHandler = (state) => {
  const reviewNode = state.node('reviewer')
  if (!reviewNode) return false
  return reviewNode.content.some(
    (b: any) => 'text' in b && b.text.includes('REQUEST_REVISION')
  )
}

// Graph constructor with all parameters
const graph = new Graph({
  nodes: [researcher, writer, reviewer],
  edges: [
    ['researcher', 'writer'],     // unconditional
    ['writer', 'reviewer'],       // unconditional
    { source: 'reviewer', target: 'writer', handler: needsRevision }  // conditional
  ],
  sources: ['researcher'],        // entry points
  maxSteps: 10,                   // default: Infinity
  maxConcurrency: 3,              // default: no limit
  timeout: 300_000,               // total ms (default: Infinity)
  nodeTimeout: 60_000             // ms per node (default: Infinity)
})

// Invocation
const result = await graph.invoke('Write an article about AI safety')
console.log(result.status)

// Streaming
// NOTE: TypeScript uses PascalCase class-based event types (camelCase .type strings),
// unlike Python which uses snake_case string keys (e.g. 'multiagent_node_start').
for await (const event of graph.stream('Write about quantum computing')) {
  if (event.type === 'nodeResultEvent') {
    console.log(`Node ${event.nodeId} done`)
  } else if (event.type === 'multiAgentHandoffEvent') {
    console.log(`Handoff: ${event.source} -> ${event.targets.join(', ')}`)
  } else if (event.type === 'multiAgentResultEvent') {
    console.log(`Final status: ${event.result.status}`)
  }
}
```

_Source: https://strandsagents.com/docs/user-guide/concepts/multi-agent/graph/_

---

### Workflow Python: task DAG, parallelism, pause/resume (Python only)

```python
# pip install strands-agents strands-agents-tools
# NOTE: strands_tools.workflow is available ONLY in Python (not in TypeScript SDK 1.0)

from strands import Agent
from strands_tools import workflow

agent = Agent(tools=[workflow])

# Create workflow with task DAG
agent.tool.workflow(
    action="create",
    workflow_id="market_analysis",
    tasks=[
        {
            "task_id": "data_collection",
            "description": "Collect market data for Q3 from financial sources",
            "system_prompt": "You extract and structure financial data from reports.",
            "priority": 5
            # No dependencies: runs in PARALLEL with competitor_analysis
        },
        {
            "task_id": "competitor_analysis",
            "description": "Analyze top 5 competitors' market positioning",
            "system_prompt": "You analyze competitive landscapes.",
            "priority": 5
            # No dependencies: runs in PARALLEL with data_collection
        },
        {
            "task_id": "trend_analysis",
            "description": "Identify trends in collected market data",
            "system_prompt": "You identify trends in financial time series.",
            "dependencies": ["data_collection"],  # waits for data_collection
            "priority": 3
        },
        {
            "task_id": "final_report",
            "description": "Generate comprehensive market analysis report",
            "system_prompt": "You create clear financial analysis reports.",
            "dependencies": ["trend_analysis", "competitor_analysis"],  # waits for both
            "priority": 1
        }
    ]
)

# Start execution (tasks without dependencies run in parallel)
agent.tool.workflow(action="start", workflow_id="market_analysis")

# Monitor
status = agent.tool.workflow(action="status", workflow_id="market_analysis")
print(status["content"])

# Pause/resume for human review
agent.tool.workflow(action="pause", workflow_id="market_analysis")
agent.tool.workflow(action="resume", workflow_id="market_analysis")

# Alternative imperative workflow (manual sequential)
from strands.models import BedrockModel
researcher = Agent(system_prompt="You are a research specialist.", model=BedrockModel(region_name="us-west-2"))
analyst = Agent(system_prompt="You analyze research data.", model=BedrockModel(region_name="us-west-2"))
writer = Agent(system_prompt="You write polished reports.", model=BedrockModel(region_name="us-west-2"))

def process_workflow(topic: str):
    research = researcher(f"Research the latest developments in {topic}")
    analysis = analyst(f"Analyze these findings: {research}")
    report = writer(f"Write a report based on: {analysis}")
    return report
```

_Source: https://strandsagents.com/docs/user-guide/concepts/multi-agent/workflow/_

---

### A2A Protocol Python: A2AServer, A2AAgent, A2AClientToolProvider, Graph node

Note: A2A is a **cross-vendor open standard** (not AWS-specific). See https://github.com/a2aproject/A2A.

```python
# pip install 'strands-agents[a2a]'
# pip install 'strands-agents-tools[a2a_client]'

# === SERVER: expose a Strands agent via A2A ===
from strands import Agent
from strands.multiagent.a2a import A2AServer
from strands_tools.calculator import calculator

calc_agent = Agent(
    name="Calculator Agent",
    description="Performs arithmetic and mathematical operations.",
    tools=[calculator]
)

# A2AServer parameters (Python)
# host: default "127.0.0.1", port: default 9000
# version: default "0.0.1"
# http_url: public URL (e.g. behind ALB for path-based mounting)
# serve_at_root: True if load balancer removes path prefix
# skills: auto-generated from tool descriptions if omitted
# task_store, queue_manager, push_config_store, push_sender: custom components
a2a_server = A2AServer(
    agent=calc_agent,
    host="0.0.0.0",
    port=9000,
    http_url="https://my-alb.example.com/calculator"
)
a2a_server.serve()  # agent card available at /.well-known/agent-card.json

# Custom FastAPI integration
from strands.multiagent.a2a import A2AServer
fastapi_app = a2a_server.to_fastapi_app()
import uvicorn
uvicorn.run(fastapi_app, host="0.0.0.0", port=9000)


# === CLIENT: consume a remote agent ===
from strands.agent.a2a_agent import A2AAgent

# A2AAgent parameters (Python)
# endpoint: base URL (required)
# name, description: auto-populated from agent card if omitted
# timeout: default 300 sec
# a2a_client_factory: optional custom factory
a2a_agent = A2AAgent(endpoint="http://calculator-service:9000")

result = a2a_agent("What is 2^10?")
print(result.message)

async def call_async():
    result = await a2a_agent.invoke_async("Calculate sqrt of 144")
    return result

async def stream_remote():
    async for event in a2a_agent.stream_async("Explain compound interest"):
        if "data" in event:
            print(event["data"], end="", flush=True)


# === A2AClientToolProvider: discovery of multiple remote agents ===
from strands_tools.a2a_client import A2AClientToolProvider

provider = A2AClientToolProvider(
    known_agent_urls=[
        "http://calculator-service:9000",
        "http://research-service:9001",
        "https://partner-agent.example.com"
    ]
)

master_agent = Agent(
    system_prompt="You coordinate specialized remote agents.",
    tools=provider.tools  # auto-generated tools from agent cards
)


# === A2AAgent as a node in Graph ===
from strands.multiagent import GraphBuilder

local_analyst = Agent(name="analyst", system_prompt="Analyze data.")
remote_calc = A2AAgent(endpoint="http://calculator-service:9000", name="calculator")

builder = GraphBuilder()
builder.add_node(local_analyst, "analysis")
builder.add_node(remote_calc, "calculation")  # remote agent as a node!
builder.add_edge("analysis", "calculation")
builder.set_entry_point("analysis")
hybrid_graph = builder.build()

# NOTE: A2AAgent is NOT supported in Swarm (feature request #913 open)
# For workflows with remote agents, use Graph as an alternative
```

_Source: https://strandsagents.com/docs/user-guide/concepts/multi-agent/agent-to-agent/_

---

### BedrockModel: region priority, IAM policy, cross-region inference

```python
# pip install strands-agents

from strands import Agent
from strands.models import BedrockModel
import boto3

# Minimum IAM policy (scoped to specific models, not wildcard in production):
# {
#   "Version": "2012-10-17",
#   "Statement": [{
#     "Effect": "Allow",
#     "Action": [
#       "bedrock:InvokeModelWithResponseStream",
#       "bedrock:InvokeModel"
#     ],
#     "Resource": "arn:aws:bedrock:us-west-2::foundation-model/anthropic.claude-*"
#   }]
# }

# Default: Claude Sonnet 4 (Python) or Claude Sonnet 4.6 (TypeScript)
agent_default = Agent()  # BedrockModel + Claude Sonnet 4 automatically
agent_string = Agent(model="anthropic.claude-sonnet-4-20250514-v1:0")

# Advanced configuration
# Region priority: explicit parameter > session region > AWS_DEFAULT_REGION > AWS_REGION > us-west-2
bedrock_model = BedrockModel(
    model_id="anthropic.claude-sonnet-4-20250514-v1:0",
    region_name="us-west-2",  # EXPLICIT - avoids surprises from boto3 precedence
    temperature=0.3,
    max_tokens=4096,
    streaming=True  # default True - uses InvokeModelWithResponseStream
)

# Cross-region inference: add regional prefix when on-demand throughput is not supported
bedrock_cross_region = BedrockModel(
    model_id="us.anthropic.claude-sonnet-4-20250514-v1:0",  # 'us.' prefix for cross-region
    region_name="us-east-1"
)

# With custom boto3 session (cross-account, specific profiles)
custom_session = boto3.Session(
    aws_access_key_id="...",
    aws_secret_access_key="...",
    aws_session_token="...",     # temporary STS credentials
    region_name="us-west-2",
    profile_name="prod-profile"
)
bedrock_with_session = BedrockModel(
    model_id="anthropic.claude-sonnet-4-20250514-v1:0",
    boto_session=custom_session
)

# Multi-model system (different models for different agents)
researcher = Agent(
    name="researcher",
    model=BedrockModel(
        model_id="us.amazon.nova-pro-v1:0",  # Nova Pro for high throughput
        region_name="us-east-1"
    )
)
writer = Agent(
    name="writer",
    model=BedrockModel(
        model_id="anthropic.claude-sonnet-4-20250514-v1:0",
        region_name="us-west-2"
    )
)
```

_Source: https://strandsagents.com/docs/user-guide/concepts/model-providers/amazon-bedrock/_

---

### SessionManager S3, OTEL tracing, AgentCore Runtime deploy

```python
# === SESSION MANAGER ===
from strands import Agent
from strands.session.s3_session_manager import S3SessionManager
from strands.multiagent import GraphBuilder
from strands.telemetry import StrandsTelemetry

# Setup OTEL tracing before creating agents
strands_telemetry = StrandsTelemetry()
strands_telemetry.setup_otlp_exporter()  # requires OTEL_EXPORTER_OTLP_ENDPOINT
# For development:
# strands_telemetry.setup_console_exporter()

# S3SessionManager - IAM required: s3:PutObject, s3:GetObject, s3:DeleteObject, s3:ListBucket
s3_session_manager = S3SessionManager(
    session_id="customer-session-uuid-here",
    bucket="my-agent-sessions-bucket"
)

# Internal agents: NO session manager (otherwise ValueError!)
researcher = Agent(
    name="researcher",
    system_prompt="You are a researcher.",
    trace_attributes={  # propagated to all OTEL spans
        "session.id": "session-uuid-123",
        "user.id": "user@example.com",
        "env": "production"
    }
)
writer = Agent(name="writer", system_prompt="You are a writer.")

# Only the orchestrator has the session manager
builder = GraphBuilder()
builder.add_node(researcher, "researcher")
builder.add_node(writer, "writer")
builder.add_edge("researcher", "writer")
builder.set_entry_point("researcher")
builder.set_session_manager(s3_session_manager)  # only here!
graph = builder.build()

# === DEPLOY TO AGENTCORE RUNTIME ===
# Container requirements (GA since 13 October 2025):
# - Platform: linux/arm64
# - Port: 8080
# - Endpoint POST /invocations (required)
# - Endpoint GET /ping (required)
# - runtimeSessionId: min 33 characters, max 256

from bedrock_agentcore.runtime import BedrockAgentCoreApp

app = BedrockAgentCoreApp()
agent_for_runtime = Agent()

@app.entrypoint
async def invoke(payload):
    user_message = payload.get("prompt", "")
    stream = agent_for_runtime.stream_async(user_message)
    async for event in stream:
        yield event

if __name__ == "__main__":
    app.run()  # starts on port 8080

# Deploy with AgentCore CLI:
# npm install -g @aws/agentcore
# agentcore create
# agentcore dev    # local test
# agentcore deploy # push to AWS

# Client invocation:
# import boto3, json
# client = boto3.client('bedrock-agentcore')
# session_id = "my-session-id-must-be-at-least-33-chars"  # min 33 characters!
# response = client.invoke_agent_runtime(
#     agentRuntimeArn="arn:aws:...",
#     runtimeSessionId=session_id,
#     payload=json.dumps({"prompt": "Hello"}).encode()
# )

# Environment variables for OTEL -> X-Ray via AWS OTEL Collector:
# export OTEL_EXPORTER_OTLP_ENDPOINT="http://localhost:4318"
# export OTEL_SEMCONV_STABILITY_OPT_IN="gen_ai_latest_experimental,gen_ai_tool_definitions"
# export OTEL_TRACES_SAMPLER="traceidratio"
# export OTEL_TRACES_SAMPLER_ARG="1.0"  # 100% dev, 0.1 prod
```

_Source: https://strandsagents.com/docs/user-guide/deploy/deploy_to_bedrock_agentcore/python/index.md_

---

## Configuration reference

| Name | Description | Default / example |
|------|-------------|-------------------|
| `Swarm.max_handoffs` | Maximum number of control transfers between agents in the Swarm (Python). Includes handoffs to users (user interrupts). | `20` |
| `Swarm.max_iterations` | Maximum number of total node executions across all agents (Python). | `20` |
| `Swarm.execution_timeout` | Total timeout for Swarm execution in seconds (Python). | `900.0` (15 minutes) |
| `Swarm.node_timeout` | Timeout per single agent in seconds (Python). In TypeScript: `nodeTimeout` in milliseconds. | `300.0` (Python); `Infinity` ms (TypeScript) |
| `Swarm.repetitive_handoff_detection_window` | Number of recent handoffs to examine for ping-pong cycle detection. 0 = disabled (default!). Enable in production. | `0` (disabled). Recommended for production: `8` |
| `Swarm.repetitive_handoff_min_unique_agents` | Minimum number of distinct agents required in the detection window. 0 = disabled (default!). | `0` (disabled). Recommended for production: `3` |
| `Swarm.entry_point` (Python) / `start` (TypeScript) | Agent (Python: `Agent \| None`) or agent id (TypeScript: `string`) where Swarm execution starts. | `None` (Python: first in list); first element (TypeScript) |
| `Swarm.maxSteps` (TypeScript) | Single limit for total node executions in the TypeScript Swarm. Replaces Python's separate `max_handoffs` + `max_iterations`. Exceeding it raises an exception. | `Infinity` |
| `GraphBuilder.set_session_manager(session_manager)` | Attach a `SessionManager` to the Graph orchestrator for state persistence across invocations and resume-from-interrupt support. **Orchestrator-only** - do NOT set a session manager on individual agent nodes (Python raises `ValueError`). Signature: `set_session_manager(session_manager: SessionManager) -> GraphBuilder`. | `None` (no persistence). Use `S3SessionManager` in production. |
| `GraphBuilder.set_max_node_executions()` | Maximum total number of node executions in the Graph (cumulative sum of all nodes). CRITICAL for feedback loops. | No limit. Recommended for feedback loops: `10` |
| `GraphBuilder.set_execution_timeout()` | Total timeout in seconds for Graph execution. | No timeout. Recommended for production: `300`–`600` |
| `GraphBuilder.reset_on_revisit()` | If `True`, resets the agent state when a node is revisited in a feedback loop. | `False` |
| `Graph.maxSteps` (TypeScript) | Maximum number of node executions in the TypeScript Graph. | `Infinity` |
| `Graph.maxConcurrency` (TypeScript) | Maximum number of nodes executing in parallel in the TypeScript Graph. | `Infinity` (no limit) |
| `A2AServer.host` / `A2AServer.port` | Bind address and port for the A2A server (Python). TypeScript: `A2AExpressServer` has the same parameters. | `host: "127.0.0.1"`, `port: 9000` |
| `A2AAgent.timeout` (Python) / `A2AAgent.url` (TypeScript) | Python: HTTP timeout in seconds. TypeScript: required `url` parameter instead of `endpoint`. | Python: `300` sec. TypeScript: `url` required. |
| `BedrockModel.model_id` | Bedrock model ID. Default Python: Claude Sonnet 4. Default TypeScript: Claude Sonnet 4.6. | Python: `anthropic.claude-sonnet-4-20250514-v1:0`; TypeScript: `claude-sonnet-4-6` |
| `BedrockModel.region_name` | AWS region. Priority: explicit parameter > session region > `AWS_DEFAULT_REGION` > `AWS_REGION` > `us-west-2` (fallback). | `us-west-2` (fallback) |
| `runtimeSessionId` (AgentCore Runtime InvokeAgentRuntime) | Session ID for invoking AgentCore Runtime. Minimum length 33 characters, maximum 256. Pattern: `[a-zA-Z0-9][a-zA-Z0-9-_]*`. | Minimum 33 characters (e.g. `my-production-session-id-2025-001`) |
| `AWS_DEFAULT_REGION` | Preferred AWS region for boto3 (higher priority than `AWS_REGION`). | e.g. `us-west-2` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OTEL collector endpoint (required for `strands_telemetry.setup_otlp_exporter()`). | `http://localhost:4318` |
| `OTEL_SEMCONV_STABILITY_OPT_IN` | Enables gen_ai semantic conventions for LLM spans. | `gen_ai_latest_experimental,gen_ai_tool_definitions` |
| `IAM: bedrock:InvokeModel + bedrock:InvokeModelWithResponseStream` | Minimum IAM permissions to use Strands with Bedrock. Scoped to specific model ARN in production. | `arn:aws:bedrock:REGION::foundation-model/anthropic.claude-*` |
| `AgentCore execution role` | Execution role for agent in AgentCore Runtime. Includes `BedrockModelInvocation`, ECR ImageAccess, CloudWatch Logs, X-Ray, `bedrock-agentcore:GetWorkloadAccessToken*`. Trust policy: Principal `bedrock-agentcore.amazonaws.com`. | See: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-permissions.html |
| `preserve_context` / `preserveContext` (agents-as-tools) | If `True`, the agent tool's conversation context persists between invocations within the same cycle. | `False` (reset between invocations) |

---

## Gotchas

- **A2AAgent is NOT supported in Swarm** in either Python or TypeScript SDKs. Swarm coordination relies on tool-based handoffs that require capabilities not available in the A2A protocol. Use Graph as an alternative for workflows with remote agents. Feature request #913 is open with no linked PRs.

- **Python Graph uses OR semantics for edges; TypeScript Graph uses AND semantics.** In Python, a node fires when ANY incoming edge completes. In TypeScript, a node waits for ALL incoming edges. In graphs with join nodes (multiple predecessors pointing to one node), in Python the node will execute multiple times (once per completed predecessor) unless you implement conditional edges that manually check AND logic via `GraphState.results`. Feature request #1081 proposes adding AND mode to Python.

- **SharedContext in Python Swarm has only `SharedContext.add_context(node, key, value)` as a public method.** There is no directly exposed `get_context()` for agents - reading happens via handoff messages constructed by the orchestrator that include accumulated context. In TypeScript there is no mutable SharedContext: use the serialized JSON `context` field in structured handoff messages.

- **Session Manager in multi-agent: ONLY the orchestrator (Graph/Swarm) should have a session manager.** Python raises `ValueError` if an agent with a session manager is added to a Graph/Swarm. The Graph's session manager persists orchestrator state, not individual agent histories.

- **boto3 region resolution: `AWS_REGION` has LOWER priority than the region set in the AWS profile** (`~/.aws/config`, `AWS_DEFAULT_REGION`). Always use explicit `region_name` in the `BedrockModel` constructor, or set `AWS_DEFAULT_REGION`, for predictable behavior.

- **Feedback loop in Graph without `set_max_node_executions()`:** without this limit, a `reviewer -> draft_writer` cycle can run indefinitely, consuming unlimited tokens. Always set this value for graphs with cycles.

- **Swarm without `repetitive_handoff_detection_window`:** defaults to 0 (disabled!). Two agents alternately handing off to each other will consume all `max_handoffs` without completing the task. Enable with `window=8`, `min_unique=3` in production.

- **`strands_tools.agent_graph` is DEPRECATED** with removal planned at the next major release. Do not use it in new code; migrate to `GraphBuilder` from the main SDK.

- **AgentCore Runtime `runtimeSessionId` minimum length is 33 characters, maximum 256** (confirmed in the official API reference). A session ID that is too short causes a `ValidationException`.

- **AgentCore Runtime requires `linux/arm64`, port 8080, and two mandatory endpoints: `POST /invocations` and `GET /ping`.** Python 3.10+ or Node.js 20+ required. The `agentcore-starter-toolkit` tool is deprecated - use the new AgentCore CLI (`npm install -g @aws/agentcore`).

- **TypeScript SDK 1.0 (GA April 2026) supports Graph, Swarm, agents-as-tools, and A2A. It does NOT include Workflow as a native primitive** (`strands_tools.workflow` is Python only). Pre-1.0 beta code is not compatible with 1.0.

- **In TypeScript Swarm, exceeding `maxSteps` raises an exception (fail-fast).** In Python Swarm, exceeding limits returns a `SwarmResult` with `status=FAILED`. Divergent behavior that impacts error handling.

- **`Agent.name` vs `Agent.id` in Swarm:** `handoff_to_agent(agent_name=...)` uses the `name` field, not `id`. Ensure `name` is unique and matches exactly what is used in the system prompts of the other agents.

- **`GraphResult.results` is keyed by the node_id string (second argument to `add_node`), NOT by `agent.name`.** Accessing `result.results["wrong_key"]` raises `KeyError`. Always use `result.results.get("node_id")` and check for `None` before accessing `.result`. This is the most common source of silent errors in post-graph result processing. _Source: https://strandsagents.com/docs/api/python/strands.multiagent.graph/_

- **`GraphResult.accumulated_usage` aggregates token counts across all node executions in the Graph** (inherited from `MultiAgentResult`). It is directly available on the `GraphResult` object returned by `graph(task)`, identical in shape to `SwarmResult.accumulated_usage`. Per-node token usage is available via `result.results[node_id].accumulated_usage`. _Source: https://strandsagents.com/docs/user-guide/concepts/multi-agent/graph/_

- **`accumulated_usage` in `SwarmResult` aggregates `inputTokens`, `outputTokens`, `totalTokens`, `cacheReadInputTokens`, `cacheWriteInputTokens` from ALL invocations of ALL agents in the Swarm.** It is not just an application-level sum - it includes all LLM traffic in the system.

- **`invocation_state` is not visible to the LLM model:** data here is accessible only to tools (via `ToolContext.invocation_state`) and edge condition functions. If the model needs to "see" the context, include it in the `system_prompt` or user message.

---

## Official sources

- [Strands Agents - Multi-agent Patterns (user guide)](https://strandsagents.com/docs/user-guide/concepts/multi-agent/multi-agent-patterns/) - Main page comparing Graph, Swarm, Workflow with a comparison table, selection criteria, and `invocation_state`
- [Strands Agents - Agents-as-Tools](https://strandsagents.com/docs/user-guide/concepts/multi-agent/agents-as-tools/) - Direct agent passing, `.as_tool()` / `.asTool()`, `@tool` decorator, `preserve_context` / `preserveContext`, `A2AAgent` as tool
- [Strands Agents - Swarm Pattern](https://strandsagents.com/docs/user-guide/concepts/multi-agent/swarm/) - `Swarm` constructor, `handoff_to_agent`, `SharedContext`, `SwarmResult`, repetitive handoff detection, streaming
- [Strands Agents - Graph Pattern](https://strandsagents.com/docs/user-guide/concepts/multi-agent/graph/) - Full `GraphBuilder` API, OR vs AND semantics, conditional edges, nested patterns (swarm-in-graph), feedback loops, streaming
- [Strands Agents - Workflow Pattern](https://strandsagents.com/docs/user-guide/concepts/multi-agent/workflow/) - Sequential workflow with `strands_tools.workflow`, task DAG, actions `create` / `start` / `status` / `pause` / `resume`
- [Strands Agents - Agent-to-Agent (A2A) Protocol](https://strandsagents.com/docs/user-guide/concepts/multi-agent/agent-to-agent/) - `A2AAgent`, `A2AServer`, `A2AClientToolProvider`, not supported in Swarm, Graph integration, TypeScript `A2AExpressServer`
- [Strands Agents - Python API Reference: strands.multiagent.swarm](https://strandsagents.com/docs/api/python/strands.multiagent.swarm/) - Exact signatures of `SharedContext.add_context()`, `SwarmNode`, `SwarmState`, `Swarm.__init__()` with all parameters
- [Strands Agents - Python API Reference: strands.multiagent.graph](https://strandsagents.com/docs/api/python/strands.multiagent.graph/) - Full signatures of `GraphBuilder`, `Graph`, `GraphState`, `GraphNode`, `GraphEdge`, `GraphResult`
- [Strands Agents - Session Management](https://strandsagents.com/docs/user-guide/concepts/agents/session-management/) - `FileSessionManager`, `S3SessionManager`, `FileStorage` / `S3Storage` in TypeScript, multi-agent session rules, immutable snapshots
- [Strands Agents - Traces/Observability](https://strandsagents.com/docs/user-guide/observability-evaluation/traces/) - `StrandsTelemetry`, OTEL env vars, CloudWatch X-Ray integration, `trace_attributes` for multi-agent correlation
- [Blog AWS - Introducing Strands Agents 1.0](https://aws.amazon.com/blogs/opensource/introducing-strands-agents-1-0-production-ready-multi-agent-orchestration-made-simple/) - GA announcement 15 July 2025: `SessionManager`, async streaming, handoffs, A2A, code for all 1.0 patterns
- [Blog AWS - Multi-Agent Collaboration with Strands and Amazon Nova](https://aws.amazon.com/blogs/machine-learning/multi-agent-collaboration-patterns-with-strands-agents-and-amazon-nova/) - Practical comparison of the 4 patterns with pros/cons and code; uses Nova Pro as alternative model
- [Amazon Bedrock AgentCore - GA announcement](https://aws.amazon.com/about-aws/whats-new/2025/10/amazon-bedrock-agentcore-available/) - GA on 13 October 2025: VPC/PrivateLink, A2A protocol support, CloudFormation, resource tagging added
- [Strands Agents - Deploy to AgentCore Runtime (Python)](https://strandsagents.com/docs/user-guide/deploy/deploy_to_bedrock_agentcore/python/index.md) - Requirements: `linux/arm64`, port 8080, `/invocations` POST and `/ping` GET mandatory; AgentCore CLI and `boto3` manual deployment
- [IAM Permissions for AgentCore Runtime](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-permissions.html) - Full IAM permissions for execution: `BedrockModelInvocation`, ECR, CloudWatch Logs, X-Ray, `bedrock-agentcore:*`
- [InvokeAgentRuntime API Reference](https://docs.aws.amazon.com/bedrock-agentcore/latest/APIReference/API_InvokeAgentRuntime.html) - `runtimeSessionId`: minimum length 33, maximum 256 characters (officially confirmed)
- [Strands Agents - Amazon Bedrock Model Provider](https://strandsagents.com/docs/user-guide/concepts/model-providers/amazon-bedrock/) - `BedrockModel` config, region resolution priority, minimum IAM policy, caching, guardrails, cross-region inference
- [GitHub Issue #1081 - Add Graph AND semantics option (Python)](https://github.com/strands-agents/sdk-python/issues/1081) - Feature request to add AND semantics to the Python Graph; status: open, no linked PR
- [GitHub Issue #913 - Improve Swarm Handoff Extensibility (A2A in Swarm)](https://github.com/strands-agents/sdk-python/issues/913) - Feature request for A2A node integration in Swarm; status: open, no linked PR
- [Strands Agents TypeScript 1.0 announcement](https://strandsagents.com/blog/strands-agents-typescript-v1/) - TypeScript 1.0 GA on 30 April 2026: Graph, Swarm, agents-as-tools, A2A available; Workflow (`strands_tools`) Python only
- [A2A Protocol - GitHub Organization](https://github.com/a2aproject/A2A) - **Cross-vendor open standard** (not AWS) - open standard specification for the Agent-to-Agent protocol, Python and TypeScript SDKs
