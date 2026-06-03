# <!-- Asset of the aws-bedrock-agentcore-skill skill. See ../SKILL.md and ../references/ for detail and official sources. -->
#
# GraphBuilder with production limits - three patterns in one file:
#   1. Conditional routing via invocation_state (feature-flag / role-based dispatch)
#   2. Feedback loop with set_max_node_executions + reset_on_revisit
#   3. Nested Swarm as a graph node (composable multi-agent)
#
# IMPORTANT Python-vs-TypeScript semantic difference:
#   Python Graph uses OR semantics: a node fires as soon as ANY incoming edge
#   is satisfied. TypeScript Graph uses AND semantics (waits for ALL incoming
#   edges). For AND behaviour in Python, use a conditional edge that checks
#   GraphState.results for all expected predecessors manually.
#
# Production limits checklist (set ALL of these - defaults are unbounded):
#   set_max_node_executions()  - total node fires across all nodes (critical for loops)
#   set_execution_timeout()    - wall-clock seconds for the whole graph
#   reset_on_revisit(True)     - clears agent state when a loop revisits a node
#
# Source: https://strandsagents.com/docs/user-guide/concepts/multi-agent/graph/
#         https://strandsagents.com/docs/api/python/strands.multiagent.graph/
# Read the matching reference file: ../references/multi-agent.md

from strands import Agent
from strands.models import BedrockModel
from strands.multiagent import GraphBuilder, Swarm
from strands.multiagent.graph import GraphState


# ------------------------------------------------------------------
# Shared model config - one BedrockModel per agent for clarity
# (you can share a single instance if you prefer)
# ------------------------------------------------------------------
def make_model(region: str = "us-east-1") -> BedrockModel:
    return BedrockModel(
        model_id="us.anthropic.claude-sonnet-4-20250514-v1:0",  # geo cross-region
        region_name=region,
        temperature=0.3,
        max_tokens=4096,
    )


# ==================================================================
# Pattern 1 - Conditional routing based on invocation_state
# Use invocation_state to pass config (roles, feature flags, DB
# connections) without polluting the LLM context.
# ==================================================================

router = Agent(name="router", model=make_model(), system_prompt="Classify the request type.")
admin_panel = Agent(name="admin", model=make_model(), system_prompt="Handle admin requests.")
standard_path = Agent(name="standard", model=make_model(), system_prompt="Handle standard requests.")


def requires_admin(state: GraphState, *, invocation_state: dict, **kwargs) -> bool:
    return invocation_state.get("role") == "admin"


def is_standard(state: GraphState, *, invocation_state: dict, **kwargs) -> bool:
    return invocation_state.get("role") != "admin"


routing_builder = GraphBuilder()
routing_builder.add_node(router, "router")
routing_builder.add_node(admin_panel, "admin")
routing_builder.add_node(standard_path, "standard")
routing_builder.add_edge("router", "admin", condition=requires_admin)
routing_builder.add_edge("router", "standard", condition=is_standard)
routing_builder.set_entry_point("router")
routing_builder.set_execution_timeout(120)           # seconds
routing_builder.set_max_node_executions(10)          # safety cap
routing_graph = routing_builder.build()

# Invoke - invocation_state is invisible to the model but visible to
# edge conditions and @tool(context=True) handlers.
result = routing_graph(
    "Please approve the quarterly budget.",
    invocation_state={"role": "admin", "env": "production"},
)
print("Routing result:", result.status)


# ==================================================================
# Pattern 2 - Feedback loop (writer → reviewer → writer …)
# set_max_node_executions is CRITICAL here - without it a loop that
# never returns "approved" runs forever and burns tokens.
# ==================================================================

draft_writer = Agent(
    name="draft_writer",
    model=make_model(),
    system_prompt="Write a draft. Revise it when given feedback.",
)
reviewer = Agent(
    name="reviewer",
    model=make_model(),
    system_prompt="Review drafts critically. Reply exactly 'APPROVED' or 'REVISION NEEDED'.",
)
publisher = Agent(
    name="publisher",
    model=make_model(),
    system_prompt="Publish approved content as-is.",
)


def needs_revision(state: GraphState) -> bool:
    review_result = state.results.get("reviewer")
    return review_result and "REVISION NEEDED" in str(review_result.result).upper()


def is_approved(state: GraphState) -> bool:
    review_result = state.results.get("reviewer")
    return review_result and "APPROVED" in str(review_result.result).upper()


feedback_builder = GraphBuilder()
feedback_builder.add_node(draft_writer, "draft_writer")
feedback_builder.add_node(reviewer, "reviewer")
feedback_builder.add_node(publisher, "publisher")
feedback_builder.add_edge("draft_writer", "reviewer")
feedback_builder.add_edge("reviewer", "draft_writer", condition=needs_revision)  # back-edge
feedback_builder.add_edge("reviewer", "publisher", condition=is_approved)
feedback_builder.set_entry_point("draft_writer")
feedback_builder.set_max_node_executions(10)   # REQUIRED for loops
feedback_builder.set_execution_timeout(300)
feedback_builder.reset_on_revisit(True)        # clears agent state on loop revisit
feedback_graph = feedback_builder.build()

result2 = feedback_graph("Write a short article about prompt engineering.")
print("Feedback loop result:", result2.status)


# ==================================================================
# Pattern 3 - Nested Swarm as a Graph node
# Each Swarm agent has no session_manager (Python raises ValueError otherwise).
# session_manager belongs ONLY on the outer Graph/Swarm orchestrator.
# ==================================================================

# Inner swarm: three domain specialists collaborate autonomously
swarm_agents = [
    Agent(name="medical_researcher", model=make_model(),
          system_prompt="Medical research specialist. Hand off to tech_researcher when done."),
    Agent(name="tech_researcher", model=make_model(),
          system_prompt="Technology research specialist. Hand off to economic_researcher when done."),
    Agent(name="economic_researcher", model=make_model(),
          system_prompt="Economic research specialist. Do NOT hand off - produce final output."),
]
research_swarm = Swarm(
    nodes=swarm_agents,
    max_handoffs=10,
    max_iterations=10,
    execution_timeout=300.0,
    node_timeout=120.0,
    repetitive_handoff_detection_window=6,     # enable cycle detection
    repetitive_handoff_min_unique_agents=3,
)

analyst = Agent(name="analyst", model=make_model(), system_prompt="Synthesize multi-domain research.")
report_writer = Agent(name="report_writer", model=make_model(), system_prompt="Write a comprehensive report.")

nested_builder = GraphBuilder()
nested_builder.add_node(research_swarm, "research_team")   # Swarm is a valid node
nested_builder.add_node(analyst, "analysis")
nested_builder.add_node(report_writer, "report")
nested_builder.add_edge("research_team", "analysis")
nested_builder.add_edge("analysis", "report")
nested_builder.set_entry_point("research_team")
nested_builder.set_max_node_executions(30)
nested_builder.set_execution_timeout(600)
nested_graph = nested_builder.build()

result3 = nested_graph("Research AI's impact on healthcare, technology, and economics.")
print("Nested graph result:", result3.status)
