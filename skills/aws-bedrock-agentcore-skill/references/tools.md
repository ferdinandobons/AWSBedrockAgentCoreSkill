# Strands Tools — @tool & MCP Integration

> Part of the **aws-bedrock-agentcore-skill** skill. See [SKILL.md](../SKILL.md) for the decision tree. Every source below is official — re-open it to verify details.

## Table of contents

- [Overview](#overview)
- [Key concepts](#key-concepts)
- [Best practices](#best-practices)
- [Code](#code)
  - [Custom tool with @tool decorator — basic Python pattern](#custom-tool-with-tool-decorator--basic-python-pattern-with-type-hints-and-docstring)
  - [@tool decorator with parameter overrides](#tool-decorator-with-parameter-overrides-custom-name-description-and-json-schema)
  - [@tool with ToolContext](#tool-with-toolcontext-for-accessing-agent-state-and-per-invocation-data)
  - [Async tool with streaming via AsyncGenerator](#async-tool-with-streaming-via-asyncgenerator-python)
  - [Class-based tools sharing a database connection](#class-based-tools-sharing-a-database-connection-python)
  - [Module-based tool (TOOL_SPEC pattern)](#module-based-tool-tool_spec-pattern-python-only-no-sdk-import-required-in-tool-file)
  - [TypeScript tool with Zod schema and AsyncGenerator](#typescript-tool-with-zod-schema-json-schema-alternative-and-asyncgenerator-streaming)
  - [MCP — Managed approach (recommended)](#mcp-integration--managed-approach-recommended-pass-mcpclient-directly-to-agent-python)
  - [MCP — Manual context manager](#mcp-integration--manual-context-manager-explicit-lifecycle-control)
  - [MCP — All three transport types](#mcp--all-three-transport-types-stdio-with-windows-variant-streamable-http-with-auth-sse-and-aws-iam)
  - [MCP — Multiple servers with tool_filters and prefix](#mcp--multiple-servers-with-tool_filters-and-prefix-to-avoid-name-conflicts-python-only)
  - [MCP Elicitation — human-in-the-loop consent](#mcp-elicitation--human-in-the-loop-consent-for-destructive-server-side-operations-python)
  - [strands-agents-tools pre-built tools](#using-strands-agents-tools-package-pre-built-tools-python-only)
  - [TypeScript vended tools](#typescript-vended-tools--pre-built-tools-included-in-strands-agentssdk)
  - [MCP TypeScript — stdio, HTTP, and SSE with McpClient](#mcp-typescript--stdio-http-and-sse-clients-with-mcpclient--elicitation-callback)
  - [Tool executor configuration](#tool-executor-configuration-concurrent-default-vs-sequential-python-and-typescript)
  - [Creating a custom MCP server with FastMCP](#creating-a-custom-mcp-server-with-fastmcp--python-and-typescript)
- [Configuration reference](#configuration-reference)
- [Gotchas](#gotchas)
- [Official sources](#official-sources)

---

## Overview

Strands Agents (open-source SDK by AWS) uses tools as the primary mechanism to extend agent capabilities beyond text generation. Tools are defined via the `@tool` decorator (Python) or `tool()` function (TypeScript), using docstrings/type hints or Zod schemas to auto-generate OpenAPI-compatible tool specs. The SDK integrates natively with the Model Context Protocol (MCP) via `MCPClient`, supporting stdio, Streamable HTTP, and SSE transports. The `strands-agents-tools` package (Python-only, community-supported) provides 40 pre-built tools (_Source: https://strandsagents.com/docs/user-guide/concepts/tools/community-tools-package/_). Human-in-the-loop is implemented either through the `elicitation_callback` on `MCPClient` or through the `handoff_to_user` tool, with `BYPASS_TOOL_CONSENT` controlling confirmation prompts for sensitive operations.

**Maturity:** Both SDKs are GA as of 2025–2026. The Python SDK (`strands-agents`) has been production-ready since May 2025 with 25M+ downloads. The TypeScript SDK (`@strands-agents/sdk`) reached 1.0 GA on **April 30, 2026** — prior to that it was in public preview. `tool_filters` and `prefix` on `MCPClient` are **Python-only** and confirmed unsupported in TypeScript `McpClient` (as of TypeScript 1.0). Custom `ToolExecutors` are planned but not yet supported in Python (tracked at [GitHub Issue #762](https://github.com/strands-agents/sdk-python/issues/762), open as of June 2026). The `mcp-proxy-for-aws` package is an official AWS package, reached GA in October 2025, currently at version 1.6.0. MCP elicitation is an MCP protocol feature integrated in both SDKs; its exact API surface may evolve as the MCP spec finalizes.

---

## Key concepts

### @tool decorator (Python)

Decorator from `strands` that transforms any Python function into an SDK-compatible tool. Extracts tool name from function name, description from docstring (first paragraph), and parameter schema from type hints and `Args:` section. Works as a simple `@tool` or parametrically as `@tool(name='x', description='y', inputSchema={...}, context=True)`. A custom parameter name for context injection is set via `@tool(context='ctx')`. The decorated function still works as a normal callable. Returns a `DecoratedFunctionTool` instance which implements the `AgentTool` interface.

### tool() function (TypeScript)

Function from `@strands-agents/sdk` used to define tools in TypeScript. Accepts an object with `name`, `description`, `inputSchema` (either a Zod schema for runtime validation or a plain JSON Schema object), and a `callback`. The callback receives typed input (with Zod) or `unknown` input (with JSON Schema), and optionally a `ToolContext` as second parameter. `AsyncGenerator` callbacks enable streaming progress updates. Return values are automatically converted to `ToolResultBlock` — any JSON-serializable value is accepted.

### TOOL_SPEC (module-based tools, Python only)

Alternative to `@tool` decorator. A Python module defines a `TOOL_SPEC` dict variable (with keys: `name`, `description`, `inputSchema`) and a function with the same name as the tool. The function signature is `def tool_name(tool: ToolUse, **kwargs: Any) -> ToolResult`. The function may also be defined async. Useful for dependency-free tool implementations. Load by importing the module or passing a file path string to `Agent(tools=[...])`.

### ToolResult structure

The return format expected from tool functions. Python dict: `{'toolUseId': str, 'status': 'success'|'error', 'content': [{'text': str} | {'json': any}]}`. The `@tool` decorator automatically wraps simple return values (strings, dicts without ToolResult structure) into this format. A dict returned without the `'status'` key is wrapped as JSON content, not an error. TypeScript: return any JSON-serializable value and the SDK wraps it into `ToolResultBlock` automatically.

### ToolUse structure

The input dict received by module-based tool functions and available via `ToolContext`. Contains: `toolUseId` (string), `name` (string), `input` (dict of parameter values). Imported from `strands.types.tools`.

### ToolContext

Context object injected into tools decorated with `@tool(context=True)` or `@tool(context='param_name')`. Provides: `context.agent` (the invoking `Agent` instance), `context.tool_use` (the `ToolUse` dict), `context.invocation_state` (per-invocation kwargs passed to `agent()`). In TypeScript, passed as optional second parameter to callback with properties `agent`, `toolUse`, `invocationState`. The `invocation_state` is particularly useful for Graph and Swarm multi-agent patterns where state is shared across agents.

### MCPClient (Python)

Class from `strands.tools.mcp` that connects to MCP servers and exposes their tools. Full constructor: `MCPClient(transport_callable, *, startup_timeout=30, tool_filters=None, prefix=None, elicitation_callback=None, tasks_config=None)`. Implements `ToolProvider` interface so can be passed directly to `Agent(tools=[mcp_client])` for automatic lifecycle management. Also supports explicit context manager usage. Key methods:

- `list_tools_sync(pagination_token=None, prefix=None, tool_filters=None) -> PaginatedList[MCPAgentTool]` — the per-call `prefix`/`tool_filters` override constructor defaults if explicitly provided (including empty string/dict).
- `call_tool_sync(tool_use_id, name, arguments, read_timeout_seconds, meta)` and `call_tool_async()` for direct invocations.

### MCPAgentTool

Internal adapter class `MCPAgentTool(AgentTool)` in `strands.tools.mcp.mcp_agent_tool`. Wraps an MCP tool and exposes it as a standard `AgentTool`. Constructor params: `mcp_tool`, `mcp_client`, `name_override` (optional, for disambiguation), `timeout` (`timedelta | None`, optional — sets per-tool execution timeout). Created automatically by `MCPClient.list_tools_sync()`. To configure per-tool timeouts, post-process the returned list and reconstruct `MCPAgentTool` instances with the `timeout` parameter. For per-call timeout control (without reconstructing instances), use `call_tool_sync(read_timeout_seconds=timedelta(...))` directly on the `MCPClient`.

### MCP Transport Types

Three supported transports in both Python and TypeScript:

1. **stdio** — for local process MCP servers launched as subprocesses via `StdioServerParameters(command, args)`. Windows requires `'--from server@version server.exe'` args pattern.
2. **Streamable HTTP** — for HTTP-based servers via `streamablehttp_client(url, headers={})`. Supports AWS IAM SigV4 via `mcp-proxy-for-aws` (official AWS package, GA since Oct 2025).
3. **SSE (Server-Sent Events)** — via `sse_client(url)`, legacy HTTP transport.

All three are wrapped in a lambda passed to `MCPClient`. TypeScript uses `@modelcontextprotocol/sdk` transport classes (`StdioClientTransport`, `StreamableHTTPClientTransport`, `SSEClientTransport`).

### Elicitation (Human-in-the-Loop via MCP)

MCP protocol feature allowing a server-side tool to pause execution and request structured user input. The MCP server calls `server.get_context().elicit(message, schema=PydanticModel)`. The Strands `MCPClient` fires the `elicitation_callback(context, params)` async function which returns an `ElicitResult(action='accept'|'decline'|'cancel', content={...})`. Both Python and TypeScript support this pattern. The `elicitation_callback` is a constructor parameter on `MCPClient` (Python) / `McpClient` (TypeScript).

### strands-agents-tools package

Python-only community package (`pip install strands-agents-tools`) providing 40 pre-built tools (as of June 2026; _Source: https://strandsagents.com/docs/user-guide/concepts/tools/community-tools-package/_). Key categories and tools:

- **RAG/Memory:** `retrieve`, `memory`, `agent_core_memory`, `mem0_memory`
- **File Ops:** `editor`, `file_read`, `file_write`
- **Shell/System:** `shell`, `environment`, `cron`, `use_computer`
- **Code:** `python_repl`, `code_interpreter` (`python_repl` not supported on Windows)
- **Web:** `http_request`, `slack`, `browser`, `rss`
- **Multi-modal:** `generate_image`, `nova_reels`, `speak`, `diagram`, `image_reader`, `generate_image_stability`
- **AWS:** `use_aws`
- **Utilities:** `calculator`, `current_time`, `load_tool`, `sleep`
- **Agents/Workflows:** `graph`, `agent_graph`, `swarm`, `handoff_to_user`, `use_agent`, `use_llm`, `think`, `workflow`, `batch`, `a2a_client`, `journal`, `stop`

TypeScript users should use vended-tools from `@strands-agents/sdk` instead.

### Vended Tools (TypeScript)

TypeScript-only pre-built tools shipped directly in `@strands-agents/sdk` under `@strands-agents/sdk/vended-tools/*`. Four tools available:

- **bash** — Node.js Unix/Linux/macOS only; shell state persists across invocations within session
- **fileEditor** — Node.js only; full-path file read/write/edit
- **httpRequest** — Node.js 20+ and browsers; 30s default timeout
- **notebook** — Node.js and browsers; persistent scratchpad integrated with session management

Imported individually: `import { bash } from '@strands-agents/sdk/vended-tools/bash'`.

### handoff_to_user tool

Tool in `strands_tools` enabling human-in-the-loop workflows. Two modes:

- **Interactive Mode** (`breakout_of_loop=False`) — pauses agent, collects user input, continues execution.
- **Complete Handoff Mode** (`breakout_of_loop=True`) — stops the agent event loop entirely and transfers control to the human operator.

Designed for terminal environments as a reference implementation; for production web applications implement custom handoff mechanisms tailored to the specific UI/UX.

### BYPASS_TOOL_CONSENT

Environment variable (`BYPASS_TOOL_CONSENT=true`) that disables user confirmation prompts for sensitive operations in the `strands-agents-tools` package (`shell`, `file_write`, `python_repl`, `editor`, etc.). Off by default. Setting it is appropriate for fully automated CI/CD pipelines but removes an important safety check in interactive or production environments. Note: removing it is a **global** setting — it applies to all sensitive tools in the process, not selectively.

### Tool Executors

Control whether multiple tool calls from a single LLM turn execute concurrently or sequentially. Python classes: `ConcurrentToolExecutor()` (default) and `SequentialToolExecutor()`. TypeScript `Agent` options: `toolExecutor: 'concurrent'` (default) | `'sequential'`. Concurrent mode minimizes latency; sequential mode is required when later tool calls depend on side effects of earlier ones. Event ordering is preserved per-tool in both modes; in concurrent mode events from different tools may interleave. Custom executors are planned (tracked at [GitHub Issue #762](https://github.com/strands-agents/sdk-python/issues/762), open as of June 2026).

### Auto-loading from ./tools/ directory

Python-only feature enabled by `Agent(load_tools_from_directory=True)`. Any `.py` file in the `./tools/` directory relative to the current working directory is automatically loaded and hot-reloaded on modification. Disabled by default. Security warning: any file placed in that directory will be executed automatically — never point this at a directory writable by untrusted processes or users.

### Direct Tool Invocation

**Python:** every tool becomes a method on `agent.tool` (singular proxy accessor). Always use keyword arguments: `agent.tool.my_tool(param='value')`. Names with hyphens resolve via underscore substitution: `agent.tool.read_all` resolves to `'read-all'`. Throws `ToolNotFoundError` if name doesn't resolve.

**TypeScript:** `agent.tool.toolName!.invoke(input)` for result, `agent.tool.toolName!.stream(input)` for events. Pass `{ recordDirectToolCall: false }` to skip recording in conversation history (required when calling tools during an active agent invocation to avoid `ConcurrentInvocationError`).

### ToolFilters TypedDict (Python)

TypedDict class `ToolFilters` in `strands.tools.mcp.mcp_client`. Keys: `'allowed'` and `'rejected'`, each accepting a list of strings (exact name match) or compiled `re.Pattern` objects. Filter order:

1. If `'allowed'` is specified, only matching tools are included.
2. Tools matching `'rejected'` patterns are then excluded from the allowed set.

Can be set at `MCPClient` construction time or overridden per `list_tools_sync()` call.

---

## Best practices

- **Write rich, multi-paragraph tool docstrings as the primary tool description** — The LLM relies entirely on the tool description to decide when and how to call it. Include: what the tool does, when to use it, example response structure, parameter ranges, limitations, and related tools. Vague one-liners cause the model to misuse or skip tools. _Source: https://strandsagents.com/docs/user-guide/concepts/tools/_

- **Use the @tool decorator for simple tools and module-based TOOL_SPEC for dependency-free tools** — `@tool` is the most concise pattern and handles type coercion automatically via Pydantic. Use `TOOL_SPEC` modules when you want zero Strands SDK dependency in the tool file (e.g., for sharing tools across frameworks), since the module just needs a dict and a plain function. _Source: https://strandsagents.com/docs/user-guide/concepts/tools/custom-tools/_

- **Always use keyword arguments when calling tools directly via `agent.tool.my_tool()`** — Positional arguments to the `agent.tool` proxy are not supported and will fail. Always use `agent.tool.my_tool(param1='val', param2=123)`. In TypeScript, use `agent.tool.toolName!.invoke({param1: 'val'})`. _Source: https://strandsagents.com/docs/user-guide/concepts/tools/_

- **Pass `MCPClient` directly to `Agent(tools=[mcp_client])` rather than using `list_tools_sync()` manually** — Passing the `MCPClient` directly (Python) or `McpClient` directly (TypeScript) enables automatic lifecycle management: the connection is opened before the first call and closed after the agent finishes, preventing resource leaks. Manual context managers require keeping the `with` block open for the entire agent lifetime. _Source: https://strandsagents.com/docs/user-guide/concepts/tools/mcp-tools/_

- **Use `prefix=` on `MCPClient` to namespace tools from different servers** — When combining multiple MCP servers, tool name collisions are common (both may have a `'search'` tool). The `prefix` parameter namespaces tools as `aws_docs_search_documentation` vs `other_search`, avoiding conflicts and making the agent's choices more predictable. Python-only feature; TypeScript users must manage naming manually. _Source: https://strandsagents.com/docs/user-guide/concepts/tools/mcp-tools/_

- **Use `tool_filters={'allowed': [...]}` to limit which MCP tools are loaded** — MCP servers often expose dozens of tools, but the agent only needs a subset. Fewer tools in context reduces token cost, reduces the chance of the model picking the wrong tool, and improves performance. Combine with regex patterns for flexible matching. Python-only; in TypeScript filter manually after `mcpClient.listTools()`. _Source: https://strandsagents.com/docs/user-guide/concepts/tools/mcp-tools/_

- **Implement `elicitation_callback` for human-in-the-loop confirmation of destructive MCP operations** — The MCP elicitation protocol allows server-side tools to pause and request explicit user approval before performing irreversible actions (file deletion, API calls). This is the correct pattern for human-in-the-loop in MCP-based tools, as opposed to simply logging the action. _Source: https://strandsagents.com/docs/user-guide/concepts/tools/mcp-tools/_

- **Follow least-privilege when designing tools: validate paths, scope permissions, audit-log sensitive ops** — Tools execute with the permissions of the host process. A compromised or hallucinating agent could pass malicious paths or arguments. Path traversal checks (`realpath`/`abspath` validation against allowed dirs), strict input validation, and logging protect against both bugs and prompt injection attacks. _Source: https://strandsagents.com/docs/user-guide/safety-security/responsible-ai/_

- **Use `SequentialToolExecutor` only when tool calls have explicit ordering dependencies** — The default `ConcurrentToolExecutor` runs all tools from a single LLM turn in parallel, minimizing wall-clock time. Switching to sequential adds latency. Only use it when tool B genuinely needs the output or side effect of tool A (e.g., 'screenshot then email the screenshot'). Note: even the concurrent executor is sequential if the model only emits one tool call per turn. _Source: https://strandsagents.com/docs/user-guide/concepts/tools/executors/_

- **Use class-based tools to share expensive resources (DB connections, API clients) across tool calls** — Class-based tools initialized once and passed as bound methods (`db_tools.query_database`) share the same connection object across all invocations. This avoids reconnecting on every tool call and keeps credentials out of tool parameters (where the LLM could log or expose them). _Source: https://strandsagents.com/docs/user-guide/concepts/tools/custom-tools/_

- **Never set `BYPASS_TOOL_CONSENT=true` in interactive or production environments** — `BYPASS_TOOL_CONSENT` removes the user confirmation prompts for shell execution, file writes, and code execution — it applies globally to all sensitive tools in the process, not selectively. Disabling it in production removes the last line of defense against an agent taking irreversible destructive actions. Reserve it for fully automated, audited CI pipelines. _Source: https://strandsagents.com/docs/user-guide/concepts/tools/community-tools-package/_

- **Return informative error messages (`status: 'error'`) from tools rather than raising unhandled exceptions** — When a tool raises an unhandled exception, the agent receives an opaque error and may retry indefinitely or give up. Returning a structured error with a clear message (e.g., `'File not found at /path/x'`) gives the LLM enough context to adapt its strategy. A dict without a `'status'` key is silently treated as a JSON success response, not an error — explicitly set `'status': 'error'` for failures. _Source: https://strandsagents.com/docs/user-guide/concepts/tools/custom-tools/_

- **For TypeScript tools, use vended-tools (`@strands-agents/sdk/vended-tools/*`) instead of `strands-agents-tools`** — `strands-agents-tools` is Python-only. TypeScript users should import from the vended-tools subpaths (`bash`, `fileEditor`, `httpRequest`, `notebook`) included in `@strands-agents/sdk`. These are maintained at SDK parity. For custom tools, use the `tool()` function with Zod or JSON Schema. _Source: https://strandsagents.com/docs/user-guide/concepts/tools/vended-tools/_

- **Pass `{ recordDirectToolCall: false }` when invoking tools directly during an active agent invocation in TypeScript** — Calling `agent.tool.toolName!.invoke()` while an agent invocation is already in progress will throw `ConcurrentInvocationError` unless `recordDirectToolCall` is set to `false`. This is the correct pattern for side-effect tools or utility calls whose output should not enter the conversation context. _Source: https://strandsagents.com/docs/user-guide/concepts/tools/_

---

## Code

### Custom tool with @tool decorator — basic Python pattern with type hints and docstring

```python
from strands import Agent, tool

@tool
def weather_forecast(city: str, days: int = 3) -> str:
    """Get weather forecast for a city.

    Use this tool when the user asks about weather conditions in any location.
    Returns a plain-text forecast summary.

    Args:
        city: The name of the city (e.g., 'Seattle', 'London')
        days: Number of days for the forecast (default: 3, range: 1-7)
    """
    return f"Weather forecast for {city} for the next {days} days: Sunny, 22C"

agent = Agent(tools=[weather_forecast])
agent("What's the weather in Rome for the next 5 days?")

# Direct tool invocation (always use keyword args)
result = agent.tool.weather_forecast(city="Rome", days=5)
```

_Source: https://strandsagents.com/docs/user-guide/concepts/tools/custom-tools/_

---

### @tool decorator with parameter overrides: custom name, description, and JSON schema

```python
from strands import tool

@tool(
    name="calculate_area",
    description="Calculate the area of a shape (circle or rectangle).",
    inputSchema={
        "json": {
            "type": "object",
            "properties": {
                "shape": {
                    "type": "string",
                    "enum": ["circle", "rectangle"],
                    "description": "The shape type"
                },
                "radius": {"type": "number", "description": "Radius for circle"},
                "width":  {"type": "number", "description": "Width for rectangle"},
                "height": {"type": "number", "description": "Height for rectangle"}
            },
            "required": ["shape"]
        }
    }
)
def calculate_area(shape: str, radius: float = None, width: float = None, height: float = None) -> float:
    """Calculate area of a shape."""
    import math
    if shape == "circle" and radius:
        return math.pi * radius ** 2
    elif shape == "rectangle" and width and height:
        return width * height
    return 0.0
```

_Source: https://strandsagents.com/docs/user-guide/concepts/tools/custom-tools/_

---

### @tool with ToolContext for accessing agent state and per-invocation data (supports custom context param name)

```python
from strands import tool, Agent, ToolContext
import requests

# context=True uses 'tool_context' as the param name
@tool(context=True)
def api_call(query: str, tool_context: ToolContext) -> dict:
    """Make an API call with authenticated user context.

    Args:
        query: The search query to send to the API
    """
    user_id = tool_context.invocation_state.get("user_id")
    agent_name = tool_context.agent.name
    tool_use_id = tool_context.tool_use["toolUseId"]

    response = requests.get(
        "https://api.example.com/search",
        headers={"X-User-ID": user_id},
        params={"q": query}
    )
    return response.json()

# context="ctx" uses 'ctx' as the param name
@tool(context="ctx")
def get_agent_name(ctx: ToolContext) -> str:
    """Return the agent's name."""
    return f"Agent name: {ctx.agent.name}"

agent = Agent(tools=[api_call, get_agent_name], name="search-agent")
# Pass invocation state as keyword args to agent()
result = agent("Find products about running shoes", user_id="user-123")
```

_Source: https://strandsagents.com/docs/user-guide/concepts/tools/custom-tools/_

---

### Async tool with streaming via AsyncGenerator (Python)

```python
import asyncio
from typing import AsyncGenerator
from strands import tool, Agent

@tool
async def process_dataset(records: int) -> AsyncGenerator[str, None]:
    """Process a dataset with real-time progress updates.

    Args:
        records: Number of records to process
    """
    for i in range(0, records, 10):
        await asyncio.sleep(0.1)
        yield f"Processed {i}/{records} records"
    yield f"Completed {records} records"

async def main():
    agent = Agent(tools=[process_dataset])
    async for event in agent.stream_async("Process 50 records"):
        if tool_stream := event.get("tool_stream_event"):
            if update := tool_stream.get("data"):
                print(f"Progress: {update}")

asyncio.run(main())
```

_Source: https://strandsagents.com/docs/user-guide/concepts/tools/custom-tools/_

---

### Class-based tools sharing a database connection (Python)

```python
from strands import Agent, tool

class DatabaseTools:
    def __init__(self, connection_string: str):
        # Expensive initialization done once
        self.connection = self._connect(connection_string)

    def _connect(self, conn_str: str):
        # e.g., psycopg2.connect(conn_str)
        return {"connected": True, "db": "mydb"}

    @tool
    def query_database(self, sql: str) -> dict:
        """Execute a read-only SQL query against the database.

        Args:
            sql: The SQL SELECT query to execute
        """
        return {"results": f"Results for: {sql}", "conn": self.connection}

    @tool
    def insert_record(self, table: str, data: dict) -> str:
        """Insert a record into the specified database table.

        Args:
            table: The table name
            data: Record data as a dictionary
        """
        return f"Inserted into {table}: {data}"

# Instantiate once, pass bound methods to agent
db = DatabaseTools("postgresql://localhost/mydb")
agent = Agent(tools=[db.query_database, db.insert_record])
agent("Find all users created this week")
```

_Source: https://strandsagents.com/docs/user-guide/concepts/tools/custom-tools/_

---

### Module-based tool (TOOL_SPEC pattern, Python-only, no SDK import required in tool file)

```python
# File: weather.py
from typing import Any
from strands.types.tools import ToolResult, ToolUse

# 1. Tool Specification
TOOL_SPEC = {
    "name": "weather",
    "description": "Get weather information for a location.",
    "inputSchema": {
        "json": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "City or location name"
                }
            },
            "required": ["location"]
        }
    }
}

# 2. Function name MUST exactly match TOOL_SPEC["name"]
# May also be defined as async
def weather(tool: ToolUse, **kwargs: Any) -> ToolResult:
    tool_use_id = tool["toolUseId"]
    location = tool["input"]["location"]
    weather_info = f"Weather for {location}: Sunny, 72F"
    return {
        "toolUseId": tool_use_id,
        "status": "success",
        "content": [{"text": weather_info}]
    }

# --- agent.py ---
from strands import Agent
import weather          # import module directly

agent = Agent(tools=[weather])
# --- OR load by file path ---
agent2 = Agent(tools=["./weather.py"])
```

_Source: https://strandsagents.com/docs/user-guide/concepts/tools/custom-tools/_

---

### TypeScript tool with Zod schema, JSON Schema alternative, and AsyncGenerator streaming

```typescript
import { Agent, tool } from '@strands-agents/sdk'
import { z } from 'zod'

// Tool with Zod schema — input is typed and validated at runtime
const weatherTool = tool({
  name: 'weather_forecast',
  description: 'Get weather forecast for a city. Use when user asks about weather.',
  inputSchema: z.object({
    city: z.string().describe('The name of the city'),
    days: z.number().default(3).describe('Number of forecast days (1-7)'),
  }),
  callback: (input) => {
    return `Forecast for ${input.city} (${input.days} days): Sunny, 22C`
  },
})

// Same tool with plain JSON Schema — input is `unknown`, cast manually
const weatherToolJson = tool({
  name: 'weather_forecast',
  description: 'Get weather forecast for a city.',
  inputSchema: {
    type: 'object',
    properties: {
      city: { type: 'string', description: 'The name of the city' },
      days: { type: 'number', description: 'Number of forecast days' },
    },
    required: ['city'],
  },
  callback: (input) => {
    const { city, days = 3 } = input as { city: string; days?: number }
    return `Forecast for ${city} (${days} days): Sunny, 22C`
  },
})

// AsyncGenerator callback for streaming progress
const insertDataTool = tool({
  name: 'insert_data',
  description: 'Insert data with progress updates',
  inputSchema: z.object({
    table: z.string().describe('The table name'),
    data: z.record(z.string(), z.any()).describe('The data to insert'),
  }),
  callback: async function* (input: {
    table: string
    data: Record<string, any>
  }): AsyncGenerator<string, string, unknown> {
    yield 'Starting data insertion...'
    await new Promise((r) => setTimeout(r, 1000))
    yield 'Validating data...'
    await new Promise((r) => setTimeout(r, 1000))
    return `Inserted data into ${input.table}: ${JSON.stringify(input.data)}`
  },
})

const agent = new Agent({ tools: [weatherTool, insertDataTool] })
await agent.invoke('What is the weather in Tokyo?')
```

_Source: https://strandsagents.com/docs/user-guide/concepts/tools/custom-tools/_

---

### MCP integration — Managed approach (recommended): pass MCPClient directly to Agent (Python)

```python
from mcp import stdio_client, StdioServerParameters
from strands import Agent
from strands.tools.mcp import MCPClient

# Recommended: pass MCPClient directly — lifecycle managed automatically
mcp_client = MCPClient(lambda: stdio_client(
    StdioServerParameters(
        command="uvx",
        args=["awslabs.aws-documentation-mcp-server@latest"]
    )
))

agent = Agent(tools=[mcp_client])
agent("What is AWS Lambda?")  # Connection opened/closed automatically
```

_Source: https://strandsagents.com/docs/user-guide/concepts/tools/mcp-tools/_

---

### MCP integration — Manual context manager (explicit lifecycle control) — agent MUST be inside with block

```python
from mcp import stdio_client, StdioServerParameters
from strands import Agent
from strands.tools.mcp import MCPClient

mcp_client = MCPClient(lambda: stdio_client(
    StdioServerParameters(command="uvx", args=["my-mcp-server@latest"])
))

# CRITICAL: agent() call must be INSIDE the with block
with mcp_client:
    tools = mcp_client.list_tools_sync()  # Returns PaginatedList[MCPAgentTool]
    agent = Agent(tools=tools)
    response = agent("Use the tools")  # Works

# response = agent("This fails")  # MCPClientInitializationError — outside context

# Multiple servers: use multiple context managers together
with server1, server2:
    all_tools = server1.list_tools_sync() + server2.list_tools_sync()
    agent = Agent(tools=all_tools)
    agent("Use all tools")
```

_Source: https://strandsagents.com/docs/user-guide/concepts/tools/mcp-tools/_

---

### MCP — All three transport types: stdio (with Windows variant), Streamable HTTP with auth, SSE, and AWS IAM

```python
import os
from mcp import stdio_client, StdioServerParameters
from mcp.client.streamable_http import streamablehttp_client
from mcp.client.sse import sse_client
from strands import Agent
from strands.tools.mcp import MCPClient

# 1. stdio — local process (macOS/Linux)
stdio_client_obj = MCPClient(lambda: stdio_client(
    StdioServerParameters(command="uvx", args=["my-mcp-server@latest"])
))

# stdio — Windows variant (must specify .exe explicitly)
stdio_win = MCPClient(lambda: stdio_client(
    StdioServerParameters(
        command="uvx",
        args=["--from", "awslabs.aws-documentation-mcp-server@latest",
              "awslabs.aws-documentation-mcp-server.exe"]
    )
))

# 2. Streamable HTTP with Bearer token auth
http_client = MCPClient(
    lambda: streamablehttp_client(
        url="https://api.githubcopilot.com/mcp/",
        headers={"Authorization": f"Bearer {os.getenv('MCP_PAT')}"}
    )
)

# 3. AWS IAM SigV4 auth (mcp-proxy-for-aws is official AWS package, GA Oct 2025)
#    pip install mcp-proxy-for-aws
from mcp_proxy_for_aws.client import aws_iam_streamablehttp_client
iam_client = MCPClient(lambda: aws_iam_streamablehttp_client(
    endpoint="https://your-service.us-east-1.amazonaws.com/mcp",
    aws_region="us-east-1",
    aws_service="bedrock-agentcore"
))

# 4. SSE transport
sse_client_obj = MCPClient(lambda: sse_client("http://localhost:8000/sse"))

# Use any of these directly with Agent
agent = Agent(tools=[http_client])
agent("Search the docs")
```

_Source: https://strandsagents.com/docs/user-guide/concepts/tools/mcp-tools/_

---

### MCP — Multiple servers with tool_filters and prefix to avoid name conflicts (Python-only)

```python
import re
from mcp import stdio_client, StdioServerParameters
from strands import Agent
from strands.tools.mcp import MCPClient

# Server 1: AWS docs — load only 2 specific tools, prefix with 'aws_docs'
aws_docs_client = MCPClient(
    lambda: stdio_client(StdioServerParameters(
        command="uvx",
        args=["awslabs.aws-documentation-mcp-server@latest"]
    )),
    tool_filters={"allowed": ["search_documentation", "read_documentation"]},
    prefix="aws_docs"
)

# Server 2: Custom server — regex filter, combined allowed+rejected
my_server_client = MCPClient(
    lambda: stdio_client(StdioServerParameters(
        command="python",
        args=["/path/to/my_mcp_server.py"]
    )),
    tool_filters={
        # Filter order: allowed first, then rejected from allowed set
        "allowed": [re.compile(r".*documentation$")],
        "rejected": ["read_documentation"]
    },
    prefix="myapp"
)

# Tools will be named: aws_docs_search_documentation, aws_docs_read_documentation, etc.
agent = Agent(tools=[aws_docs_client, my_server_client])
agent("Search AWS docs and our catalog")
```

_Source: https://strandsagents.com/docs/user-guide/concepts/tools/mcp-tools/_

---

### MCP Elicitation — human-in-the-loop consent for destructive server-side operations (Python)

```python
# server.py — MCP server that pauses for user approval
from mcp.server import FastMCP
from pydantic import BaseModel, Field

class ApprovalSchema(BaseModel):
    username: str = Field(description="Who is approving?")
    confirmed: bool = Field(description="Explicit confirmation")

server = FastMCP("file-ops")

@server.tool()
async def delete_files(paths: list[str]) -> str:
    result = await server.get_context().elicit(
        message=f"Confirm deletion of {paths}?",
        schema=ApprovalSchema,
    )
    if result.action != "accept" or not result.data.confirmed:
        return f"Deletion rejected by {result.data.username}"
    # Perform deletion...
    return f"Deleted {paths} — approved by {result.data.username}"

server.run()

# client.py — Strands agent with elicitation callback
from mcp import stdio_client, StdioServerParameters
from mcp.types import ElicitResult
from strands import Agent
from strands.tools.mcp import MCPClient

async def elicitation_callback(context, params):
    print(f"\n[APPROVAL REQUIRED] {params.message}")
    username = input("Your name: ")
    confirmed_str = input("Confirm? (yes/no): ")
    action = "accept" if confirmed_str.lower() == "yes" else "decline"
    return ElicitResult(
        action=action,
        content={"username": username, "confirmed": action == "accept"}
    )

client = MCPClient(
    lambda: stdio_client(
        StdioServerParameters(command="python", args=["/path/to/server.py"])
    ),
    elicitation_callback=elicitation_callback,
)

# Use managed approach — lifecycle handled automatically
agent = Agent(tools=[client])
agent("Delete '/tmp/old_logs.txt'")
```

_Source: https://strandsagents.com/docs/user-guide/concepts/tools/mcp-tools/_

---

### Using strands-agents-tools package pre-built tools (Python-only)

```python
# Install: pip install strands-agents-tools
# With extras: pip install 'strands-agents-tools[mem0_memory,use_computer]'

from strands import Agent
from strands_tools import (
    calculator,
    file_read,
    file_write,
    shell,
    http_request,
    python_repl,   # Not supported on Windows
    retrieve,       # RAG / Knowledge Base
    use_aws,        # AWS SDK calls via boto3 (credential chain: env vars, ~/.aws, instance role)
    handoff_to_user, # Human-in-the-loop
    think,          # Internal reasoning
    swarm,          # Multi-agent coordination
)
import os

# BYPASS_TOOL_CONSENT: disable confirmation prompts globally (CI/CD only, not production)
# os.environ["BYPASS_TOOL_CONSENT"] = "true"

agent = Agent(
    tools=[calculator, file_read, file_write, shell, http_request, use_aws, handoff_to_user]
)
agent("What is 2^32? Then read the file /etc/hostname")
```

_Source: https://strandsagents.com/docs/user-guide/concepts/tools/community-tools-package/_

---

### TypeScript vended tools — pre-built tools included in @strands-agents/sdk

```typescript
import { Agent } from '@strands-agents/sdk'
import { bash } from '@strands-agents/sdk/vended-tools/bash'
import { fileEditor } from '@strands-agents/sdk/vended-tools/file-editor'
import { httpRequest } from '@strands-agents/sdk/vended-tools/http-request'
import { notebook } from '@strands-agents/sdk/vended-tools/notebook'

// All four vended tools in one agent
const agent = new Agent({
  tools: [bash, fileEditor, httpRequest, notebook],
  systemPrompt:
    'Before starting any multi-step task, create a notebook with a checklist of steps.',
})

// bash: shell state persists across invocations
await agent.invoke('Run: export MY_VAR="hello"')
await agent.invoke('Run: echo $MY_VAR')  // prints "hello"

// notebook: state persists with session management
await agent.invoke('Create a notebook called "plan" with "# Task Plan"')
await agent.invoke('Add "Step 1: gather data" to the plan notebook')
```

_Source: https://strandsagents.com/docs/user-guide/concepts/tools/vended-tools/_

---

### MCP TypeScript — stdio, HTTP, and SSE clients with McpClient + elicitation callback

```typescript
import { Agent, McpClient } from '@strands-agents/sdk'
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js'
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js'
import { SSEClientTransport } from '@modelcontextprotocol/sdk/client/sse.js'
import type { Transport } from '@modelcontextprotocol/sdk/shared/transport.js'
import type { ElicitResult } from '@modelcontextprotocol/sdk/types.js'

// stdio transport
const stdioClient = new McpClient({
  transport: new StdioClientTransport({
    command: 'uvx',
    args: ['awslabs.aws-documentation-mcp-server@latest'],
  }),
})

// Streamable HTTP with auth
const httpClient = new McpClient({
  applicationName: 'My Agent App',
  applicationVersion: '1.0.0',
  transport: new StreamableHTTPClientTransport(
    new URL('https://api.githubcopilot.com/mcp/'),
    {
      requestInit: {
        headers: { Authorization: `Bearer ${process.env.GITHUB_PAT}` },
      },
    }
  ) as Transport,
})

// SSE transport
const sseClient = new McpClient({
  transport: new SSEClientTransport(new URL('http://localhost:8000/sse')),
})

// With elicitation callback (human-in-the-loop)
const clientWithElicitation = new McpClient({
  transport: new StdioClientTransport({
    command: 'python',
    args: ['/path/to/server.py'],
  }),
  elicitationCallback: async (_context, params): Promise<ElicitResult> => {
    console.log(`[APPROVAL] ${params.message}`)
    // In production: prompt user via UI, webhook, etc.
    return { action: 'accept', content: { username: 'operator', confirmed: true } }
  },
})

// NOTE: tool_filters and prefix are NOT supported in TypeScript McpClient (Python-only)
// For TypeScript, filter tools manually after listing:
const allTools = await stdioClient.listTools()
const filteredTools = allTools.filter(t => ['search_docs', 'read_docs'].includes(t.name))

// Pass multiple clients directly to Agent
const agent = new Agent({
  tools: [stdioClient, httpClient],
})
await agent.invoke('Search AWS docs for Lambda pricing')
```

_Source: https://strandsagents.com/docs/user-guide/concepts/tools/mcp-tools/_

---

### Tool executor configuration: concurrent (default) vs sequential (Python and TypeScript)

```python
from strands import Agent
from strands.tools.executors import SequentialToolExecutor, ConcurrentToolExecutor
from strands_tools import shell, file_write, calculator

# Default: concurrent execution (all tools in a turn run in parallel)
# Equivalent to explicit: Agent(tool_executor=ConcurrentToolExecutor(), ...)
concurrent_agent = Agent(tools=[calculator, shell])
concurrent_agent("What is 2^10 and what files are in /tmp?")

# Sequential execution: use when tool B depends on side effect of tool A
# e.g., 'take a screenshot then email it'
sequential_agent = Agent(
    tool_executor=SequentialToolExecutor(),
    tools=[shell, file_write]
)
sequential_agent("Run the test suite and save the output to results.txt")

# TypeScript equivalent:
# const agent = new Agent({ tools: [screenshotTool, emailTool], toolExecutor: 'sequential' })
```

_Source: https://strandsagents.com/docs/user-guide/concepts/tools/executors/_

---

### Creating a custom MCP server with FastMCP — Python and TypeScript

```python
# my_mcp_server.py (Python using FastMCP)
from mcp.server import FastMCP

mcp = FastMCP("Calculator Server")

@mcp.tool(description="Calculator tool which performs calculations")
def calculator(x: int, y: int) -> int:
    """Add two numbers and return the result."""
    return x + y

@mcp.tool(description="Search product database")
def search_products(query: str, limit: int = 10) -> list[dict]:
    """Search the product catalog.

    Args:
        query: Search keywords
        limit: Max results to return
    """
    return [{"id": "P001", "name": f"Product matching: {query}"}]

# Run with SSE transport (http://localhost:8000/sse)
if __name__ == "__main__":
    mcp.run(transport="sse")
    # Or: mcp.run(transport="streamable-http")  # Recommended modern transport
```

_Source: https://strandsagents.com/docs/user-guide/concepts/tools/mcp-tools/_

---

## Configuration reference

| Name | Description | Default / example |
|------|-------------|-------------------|
| `BYPASS_TOOL_CONSENT` | Environment variable for `strands-agents-tools`. When set to `'true'`, disables user confirmation prompts for ALL sensitive tools in the process (`shell`, `file_write`, `python_repl`, `editor`, etc.) globally. WARNING: disabling removes the human safety check across every sensitive tool — use only in CI/automated pipelines. | `os.environ['BYPASS_TOOL_CONSENT'] = 'true'` or `export BYPASS_TOOL_CONSENT=true` |
| `Agent(tools=[...])` | List of tools passed to the Agent constructor. Accepts: `@tool`-decorated functions (Python), module objects with `TOOL_SPEC` (Python), file path strings (Python), `MCPClient` instances implementing `ToolProvider`, `Agent` instances (auto-converted to tools for multi-agent), or pre-built tools from `strands_tools` / `@strands-agents/sdk/vended-tools/*`. | `Agent(tools=[my_tool, mcp_client, './path/tool.py', research_agent])` |
| `Agent(load_tools_from_directory=True)` | Python-only. Auto-loads all `.py` files from `./tools/` in the current working directory and hot-reloads them on modification. Disabled by default. Security risk: executes any file placed in that directory automatically. | `Agent(load_tools_from_directory=True)` |
| `Agent(tool_executor=SequentialToolExecutor())` | Override the default `ConcurrentToolExecutor`. Use `SequentialToolExecutor` when tool calls within a single LLM turn must execute in order due to side-effect dependencies. TypeScript equivalent: `new Agent({ toolExecutor: 'sequential' })`. | `from strands.tools.executors import SequentialToolExecutor`<br>`Agent(tool_executor=SequentialToolExecutor())` |
| `MCPClient(transport_callable, *, startup_timeout, tool_filters, prefix, elicitation_callback, tasks_config)` | Full `MCPClient` constructor. `transport_callable`: lambda returning a transport context manager. `startup_timeout`: int seconds before init is cancelled (default 30). `tool_filters`: `ToolFilters` TypedDict with `'allowed'` and/or `'rejected'` lists of strings or compiled regexes (allowed first, then rejected). `prefix`: string prepended to all tool names. `elicitation_callback`: async callable returning `ElicitResult`. `tasks_config`: experimental for long-running tool execution. | `MCPClient(`<br>&nbsp;&nbsp;`lambda: stdio_client(StdioServerParameters(command='uvx', args=['server@latest'])),`<br>&nbsp;&nbsp;`startup_timeout=30,`<br>&nbsp;&nbsp;`tool_filters={'allowed': ['search_docs'], 'rejected': []},`<br>&nbsp;&nbsp;`prefix='aws',`<br>&nbsp;&nbsp;`elicitation_callback=my_callback`<br>`)` |
| `MCPClient.list_tools_sync(pagination_token, prefix, tool_filters)` | Returns `PaginatedList[MCPAgentTool]`. The `prefix` and `tool_filters` parameters OVERRIDE constructor defaults if explicitly provided (including empty string `''` or empty dict `{}`). If passed as `None`, constructor defaults are used. Supports pagination via `pagination_token`. | `tools = mcp_client.list_tools_sync(prefix='my_prefix', tool_filters={'allowed': ['tool_a']})` |
| `MCPClient.call_tool_sync / call_tool_async read_timeout_seconds` | Per-call timeout for MCP tool execution. Pass as a `timedelta`. Prevents agent hanging on slow or unresponsive MCP tools. Primary mechanism for per-call timeout control. | `from datetime import timedelta`<br>`mcp_client.call_tool_sync('id', 'my_tool', arguments={}, read_timeout_seconds=timedelta(seconds=30))` |
| `MCPAgentTool(mcp_tool, mcp_client, name_override, timeout)` | Adapter wrapping an MCP tool as an `AgentTool`. `timeout`: `timedelta \| None` — default execution timeout. `name_override`: `str \| None` — overrides the MCP tool name. Created automatically by `list_tools_sync()`; construct manually to set per-tool timeouts. | `from datetime import timedelta`<br>`from strands.tools.mcp.mcp_agent_tool import MCPAgentTool`<br>`tool_with_timeout = MCPAgentTool(mcp_tool=raw_tool, mcp_client=client, timeout=timedelta(seconds=30))` |
| `@tool` decorator parameters | All optional: `name` (str), `description` (str), `inputSchema` (dict with `'json'` key containing JSON Schema), `context` (bool \| str — `True` uses `'tool_context'` param name; a string value sets a custom param name). | `@tool(name='custom_name', description='Override description', context=True)`<br>or: `@tool(context='ctx')` |
| `strands-agents-tools` extras | Optional dependency groups for specialized tools. Install with bracket syntax. | `pip install 'strands-agents-tools[mem0_memory]'`<br>`pip install 'strands-agents-tools[local_chromium_browser]'`<br>`pip install 'strands-agents-tools[agent_core_browser]'`<br>`pip install 'strands-agents-tools[agent_core_code_interpreter]'`<br>`pip install 'strands-agents-tools[a2a_client]'`<br>`pip install 'strands-agents-tools[diagram]'`<br>`pip install 'strands-agents-tools[rss]'`<br>`pip install 'strands-agents-tools[use_computer]'` |
| Tool name constraints | Tool names must match `^[a-zA-Z0-9_-]+` and be 1–64 characters long. Names not matching this format are replaced with `INVALID_TOOL_NAME` in assistant messages (request still succeeds but the model cannot reference the original name). | Valid: `my_tool`, `search-docs`, `FileReader123`<br>Invalid: `my tool` (space), `tool@name` (special char) |
| `use_aws` tool IAM permissions | The `strands_tools.use_aws` tool calls arbitrary boto3 operations. It has no hardcoded IAM policy — permissions depend entirely on what the agent needs. The tool enforces confirmation prompts for mutative and credential-returning operations (create/delete/update, STS, Secrets Manager, ECR). Credentials resolved via standard AWS chain (env vars, `~/.aws/credentials`, EC2/ECS instance role, etc.). Apply least-privilege IAM policies. No single minimum policy exists. | Grant only needed policies, e.g., `AmazonBedrockReadOnly` for model invocation. Do not use `AdministratorAccess` or wildcard resource ARNs. Use explicit Deny statements. |
| TypeScript `McpClient` optional metadata | Accepts optional application metadata: `applicationName` (string) and `applicationVersion` (string). Passed to MCP servers as client metadata. `tool_filters` and `prefix` are NOT supported in TypeScript `McpClient`. | `new McpClient({ applicationName: 'My Agent', applicationVersion: '1.0.0', transport: ... })` |

---

## Gotchas

- **`MCPClientInitializationError`**: When using `list_tools_sync()` with a context manager, the agent MUST be invoked INSIDE the `with` block. Any `agent()` call after the `with` block exits will raise `MCPClientInitializationError` because the connection is closed. Prefer passing `MCPClient` directly to `Agent(tools=[mcp_client])` to avoid this entirely.

- **Positional arguments to `agent.tool` proxy are NOT supported in Python.** `agent.tool.my_tool('value', 3)` fails. Always use `agent.tool.my_tool(param1='value', param2=3)` with explicit keyword arguments.

- **Tool names with hyphens**: in Python, the `agent.tool` proxy resolves names by exact match first, then with underscores substituted for hyphens, then case-insensitively. A tool registered as `'read-all'` is called as `agent.tool.read_all()`. Calling a name that doesn't resolve raises `ToolNotFoundError`.

- **Module-based tools**: the function name MUST exactly match `TOOL_SPEC['name']`. A mismatch causes the tool to fail to load with a confusing error.

- **`@tool` on class methods requires instantiation before passing to Agent.** Pass `db_tools.query_database` (bound method), not `DatabaseTools.query_database` (unbound). The decorator uses `__get__` for descriptor binding.

- **`strands-agents-tools` is Python-only.** TypeScript SDK users must use vended tools from `@strands-agents/sdk/vended-tools/*` (`bash`, `fileEditor`, `httpRequest`, `notebook`) or create custom tools with `tool()`. There is no NPM equivalent of `strands-agents-tools`.

- **The `strands-agents-tools` package is community-supported, not AWS-production-supported.** For production workloads, audit each tool's behavior (file access, network calls, shell execution) and consider creating custom tools with tighter scope.

- **`BYPASS_TOOL_CONSENT=true` disables confirmation prompts globally for ALL sensitive tools in the process.** Setting it in a shared environment means every tool call bypasses consent, not just specific ones.

- **MCP elicitation API surface may evolve.** MCP elicitation is an MCP protocol feature integrated in Strands Agents. Its API surface may change as the MCP specification continues to be finalized.

- **`tool_filters` and `prefix` parameters on `MCPClient` are Python-only.** TypeScript `McpClient` does not support them as of TypeScript SDK 1.0 (April 2026). TypeScript users must filter tools manually after calling `mcpClient.listTools()` and manage naming by choosing distinct server-specific tool names.

- **Auto-loading from `./tools/` directory (`load_tools_from_directory=True`) hot-reloads ANY `.py` file placed there**, including potentially malicious ones. Never point this at a directory writable by untrusted processes or users.

- **Silent success for missing `'status'` key**: the `@tool` decorator wraps simple return values automatically (strings → `{text: ...}`) but if you return a dict that does NOT have the `ToolResult` structure (no `'status'` key), it is wrapped as JSON content (a success response). If you want a proper error response, return `{'status': 'error', 'content': [{'text': 'msg'}]}` explicitly rather than raising an exception.

- **TypeScript `ConcurrentInvocationError`**: calling `agent.tool.toolName!.invoke()` while an agent invocation is already in progress throws `ConcurrentInvocationError`. Use `{ recordDirectToolCall: false }` to call tools outside the conversation history, or use this pattern only between agent invocations.

- **`list_tools_sync()` parameter override semantics**: the `prefix` and `tool_filters` parameters OVERRIDE constructor defaults only if explicitly provided. Passing `None` uses the constructor default. Passing an empty string `''` for `prefix` or empty dict `{}` for `tool_filters` also overrides (applies no prefix / no filter).

- **`python_repl` from `strands-agents-tools` is NOT supported on Windows** because it depends on the `fcntl` module which is Unix-only. Use `code_interpreter` as an alternative on Windows.

- **`MCPClient` `startup_timeout` defaults to 30 seconds.** For slow MCP servers (e.g., large `uvx` packages downloading on first run), increase this: `MCPClient(transport, startup_timeout=120)`.

---

## Official sources

- [Strands Agents — Tools Overview](https://strandsagents.com/docs/user-guide/concepts/tools/) — Index page covering all tool types, loading mechanisms, executors, direct invocation, and best practices. Most comprehensive entry point.
- [Strands Agents — Creating Custom Tools](https://strandsagents.com/docs/user-guide/concepts/tools/custom-tools/) — Covers `@tool` decorator, module-based tools (TOOL_SPEC), class-based tools, ToolContext, ToolResult format, async/streaming tools.
- [Strands Agents — MCP Tools](https://strandsagents.com/docs/user-guide/concepts/tools/mcp-tools/) — Full MCP integration guide: MCPClient, transport types, lifecycle management, tool_filters, prefix, elicitation callback, troubleshooting.
- [Strands Agents — @tool Decorator API Reference](https://strandsagents.com/docs/api/python/strands.tools.decorator/) — Full API for the `@tool` decorator: `DecoratedFunctionTool` class, `FunctionToolMetadata`, all decorator parameters (name, description, inputSchema, context).
- [Strands Agents — MCPAgentTool API Reference](https://strandsagents.com/docs/api/python/strands.tools.mcp.mcp_agent_tool/) — Internal adapter class `MCPAgentTool(AgentTool)` that wraps MCP tools. Constructor: `MCPAgentTool(mcp_tool, mcp_client, name_override=None, timeout: timedelta | None = None)`.
- [Strands Agents — MCPClient API Reference](https://strandsagents.com/docs/api/python/strands.tools.mcp.mcp_client/) — Full `MCPClient` constructor signature (including `startup_timeout` and `tasks_config`), `list_tools_sync()` with per-call prefix and tool_filters override, `call_tool_sync`/`async` with `read_timeout_seconds`.
- [Strands Agents — Community Tools Package](https://strandsagents.com/docs/user-guide/concepts/tools/community-tools-package/) — Complete list of 40 pre-built tools in `strands-agents-tools`, installation extras, `BYPASS_TOOL_CONSENT` documentation, `handoff_to_user` modes.
- [Strands Agents — Tool Executors](https://strandsagents.com/docs/user-guide/concepts/tools/executors/) — `ConcurrentToolExecutor` vs `SequentialToolExecutor`, cancellation behavior, event ordering, Custom Executors tracking issue #762.
- [Strands Agents — Vended Tools (TypeScript)](https://strandsagents.com/docs/user-guide/concepts/tools/vended-tools/) — TypeScript-only pre-built tools shipped in `@strands-agents/sdk`: `bash`, `fileEditor`, `httpRequest`, `notebook`. Node.js and browser support varies by tool.
- [GitHub — strands-agents/tools](https://github.com/strands-agents/tools) — Source repo for `strands-agents-tools` package. Check README for latest tool list, extras install flags, and security warnings.
- [GitHub — aws/mcp-proxy-for-aws](https://github.com/aws/mcp-proxy-for-aws) — Official AWS package for SigV4 authentication on AWS-hosted MCP servers. GA since October 2025, v1.6.0 as of May 2026.
- [Strands Agents — Responsible AI / Tool Design](https://strandsagents.com/docs/user-guide/safety-security/responsible-ai/) — Official security principles for tool design: least privilege, input validation, audit logging, error handling.
- [AWS Blog — Introducing Strands Agents 1.0](https://aws.amazon.com/blogs/opensource/introducing-strands-agents-1-0-production-ready-multi-agent-orchestration-made-simple/) — Announces 1.0 production-ready features: multi-agent patterns, session management, async, A2A protocol.
- [Strands Agents Blog — TypeScript SDK 1.0](https://strandsagents.com/blog/strands-agents-typescript-v1/) — Announces TypeScript SDK GA on April 30, 2026. Covers tools, vended tools, MCP, plugins, multi-agent, streaming, session management, browser support.
- [GitHub Issue #762 — Custom ToolExecutor support](https://github.com/strands-agents/sdk-python/issues/762) — Tracking issue for custom `ToolExecutor` interface (planned, not yet available). Open as of June 2026.
