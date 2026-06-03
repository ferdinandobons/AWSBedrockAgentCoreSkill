# Amazon Bedrock AgentCore — Built-in Tools (Browser & Code Interpreter)

> Part of the **aws-bedrock-agentcore-skill** skill. See [SKILL.md](../SKILL.md) for the decision tree. Every source below is official — re-open it to verify details.

## Table of contents

- [Overview](#overview)
- [Key concepts](#key-concepts)
- [Best practices](#best-practices)
- [Code](#code)
  - [Browser Tool — Setting up the two Boto3 clients](#browser-tool--setting-up-the-two-boto3-clients-control-plane--data-plane)
  - [Browser Tool — Start session with explicit parameters](#browser-tool--start-session-with-explicit-parameters-direct-boto3)
  - [Browser Tool — Playwright integration](#browser-tool--playwright-integration-sync-via-browser_session-context-manager)
  - [Browser Tool — Nova Act integration](#browser-tool--nova-act-integration-context-manager)
  - [Browser Tool — InvokeBrowser OS-level actions](#browser-tool--invokebrowser-os-level-actions-screenshot-click-keyboard)
  - [Browser Tool — Disable automation for sensitive human input](#browser-tool--disable-automation-for-sensitive-human-input)
  - [Browser Tool — Proxy configuration (enterprise)](#browser-tool--proxy-configuration-with-authentication-enterprise)
  - [Browser Tool — Strands Agent with AgentCoreBrowser](#browser-tool--strands-agent-with-agentcorebrowser-simplest-approach)
  - [Code Interpreter — Direct usage with boto3](#code-interpreter--direct-usage-with-boto3-startstopinvoke-with-streaming)
  - [Code Interpreter — code_session context manager and SDK](#code-interpreter--usage-with-code_session-context-manager-and-sdk)
  - [Code Interpreter — JavaScript/TypeScript with Node.js runtime](#code-interpreter--javascripttypescript-with-nodejs-runtime)
  - [Code Interpreter — Strands Agent with AgentCoreCodeInterpreter](#code-interpreter--strands-agent-with-agentcorecodeinterpreter)
  - [Code Interpreter — Strands Agent with @tool decorator](#code-interpreter--strands-agent-with-code_session-and-tool-decorator-full-control)
  - [Code Interpreter — LangChain Agent with code_session](#code-interpreter--langchain-agent-with-code_session)
  - [Code Interpreter — Custom with executionRoleArn for S3 access](#code-interpreter--custom-with-executionrolearn-for-s3-access-network-sandbox)
  - [IAM Policy — Browser Tool](#iam-policy--browser-tool-user-policy--execution-role-trust-policy)
  - [IAM Policy — Code Interpreter](#iam-policy--code-interpreter-user-policy--trust-policy-for-execution-role-s3)
- [Configuration reference](#configuration-reference)
- [Gotchas](#gotchas)
- [Official sources](#official-sources)

---

## Overview

Amazon Bedrock AgentCore Browser and Code Interpreter are two **built-in GA tools** that provide, respectively, a sandboxed remote Chrome browser and an isolated code execution environment (Python/JavaScript/TypeScript) for AI agents.

Both tools follow a **session-based model** with two distinct AWS clients (control plane vs data plane), support native integration with Strands Agents, LangChain, LangGraph, and CrewAI, and are available in **16 AWS regions** (including `us-gov-west-1`).

Sessions run in isolated microVMs with dedicated CPU/memory/filesystem. State is wiped at session end. Timeouts are configurable from 15 minutes to 8 hours. Pricing is consumption-based: **$0.0895 per vCPU-hour** and **$0.00945 per GB-hour**, billed per second on peak active CPU and memory (I/O wait is not charged).

**Maturity:** GA. AgentCore Built-in Tools (Browser + Code Interpreter) are GA in 16 AWS regions from October 2025. Node.js runtime for Code Interpreter added in preview/GA in April 2026 (v24.14.0). Web Bot Auth for Browser is in Preview. AgentCore Harness, Payments, and Optimization are in Preview. Custom browser extensions are GA (announced January 2026). Browser Profiles (with S3 storage billing from April 2026) are GA. Browser Proxies are GA.

---

## Key concepts

**System ARN vs Custom ARN**
Both tools (Browser and Code Interpreter) offer a pre-created System ARN (`aws.browser.v1`, `aws.codeinterpreter.v1`) with stricter default configuration — zero setup, ready to use. Custom ARNs allow specifying `networkMode`, S3 recording, and `executionRoleArn` for accessing internal AWS resources. Use System ARN for prototypes; Custom ARN for production with specific security/network requirements.

**Control Plane vs Data Plane — Two Distinct Boto3 Clients**
The control plane (create/delete/list resources) uses `boto3.client('bedrock-agentcore-control')` with endpoint `https://bedrock-agentcore-control.{REGION}.amazonaws.com`. The data plane (start/stop/invoke sessions) uses `boto3.client('bedrock-agentcore')` with endpoint `https://bedrock-agentcore.{REGION}.amazonaws.com`. This is a fundamental pattern — mixing clients generates errors. For JavaScript/TypeScript use `@aws-sdk/client-bedrock-agentcore-control` and `@aws-sdk/client-bedrock-agentcore` respectively.

**Session-based model with isolated microVMs**
Each session (Browser or Code Interpreter) runs in a dedicated microVM with isolated CPU, memory, and filesystem. On session termination the microVM is shut down and memory sanitized — no data survives between different sessions. Hardware: Browser = 1 vCPU/4 GB per session; Code Interpreter = 2 vCPU/8 GB per session. Maximum 1,000 concurrent sessions per account per tool (default, increasable via ticket). Session data TTL: 30 days.

**Session timeout configurable**
Default: 3600 seconds (1 hour) for Browser; 900 seconds (15 minutes) for Code Interpreter. Maximum: 8 hours (28,800 seconds) for both. The parameter is `sessionTimeoutSeconds` in `start_browser_session` and `start_code_interpreter_session`. Sessions auto-terminate at timeout and resources are released automatically. Disk per session: 10 GB (not increasable).

**CDP WebSocket Automation Endpoint (Browser)**
A Browser session exposes two streams: (1) `automationStream` via WebSocket WSS for CDP — Playwright, Nova Act, browser-use connect here; (2) `liveViewStream` via HTTPS for human live view. The WebSocket URL has the form `wss://bedrock-agentcore.{REGION}.amazonaws.com/browser-streams/{browser_id}/sessions/{session_id}/automation`. The SDK method `generate_ws_headers()` returns `(ws_url, headers)` already SigV4-signed.

**InvokeBrowser — OS-level actions (complementary to CDP)**
The `InvokeBrowser` API operates at OS level — not DOM level. It handles native OS dialogs, full-desktop screenshots, keyboard shortcuts (`ctrl+s`), right-click context menus, cross-window drag-and-drop. Supported actions: `mouseClick`, `mouseMove`, `mouseDrag`, `mouseScroll`, `keyType`, `keyPress`, `keyShortcut`, `screenshot`. Unlike CDP WebSocket, uses a synchronous REST API with BrowserAction union pattern (exactly one action per request). Default viewport: 1456x819 px. Rate limit: 5 TPS.

**invoke_code_interpreter — Operation Name dispatch**
The `invoke_code_interpreter` API uses a single-operation pattern with dispatch by `name`. Supported names: `executeCode` (Python/JS/TS), `executeCommand` (synchronous shell), `startCommandExecution` (async shell with task ID), `getTask` (polling async task), `stopTask`, `writeFiles`, `readFiles`, `removeFiles`, `listFiles`. The `arguments` parameter varies per operation. Responses are event streams.

**clearContext in Code Interpreter executions**
The `clearContext` (boolean) parameter in `executeCode` controls whether to clear the kernel state between executions. With `clearContext=False` (recommended default for multi-step agents) Python variables defined in previous executions remain available in the current session, enabling iterative workflows. `clearContext=True` resets the environment.

**Streaming response — event stream**
Both `invoke_code_interpreter` and session start/stop responses return event streams. For code interpreter: iterate `response['stream']` and read `event['result']['content']` (array of `{type, text/data}`) and `event['result']['structuredContent']` (`stdout`, `stderr`, `exitCode`, `executionTime`). The `isError` field indicates errors.

**bedrock-agentcore Python SDK — context manager pattern**
The `bedrock-agentcore` PyPI package offers high-level context managers: `browser_session(region)` from `bedrock_agentcore.tools.browser_client` and `code_session(region)` from `bedrock_agentcore.tools.code_interpreter_client`. These handle start/stop automatically. The `CodeInterpreter` and `BrowserClient` classes offer explicit control with `.start()/.stop()`. For Strands: `AgentCoreBrowser(region)` and `AgentCoreCodeInterpreter(region)` wrap the tools for Strands integration.

**Network Mode — SANDBOX vs PUBLIC (Code Interpreter)**
Code Interpreter supports two network modes: `SANDBOX` (no internet access, only internal AWS resources — maximum security) and `PUBLIC` (public internet access). Browser supports only `PUBLIC` (required for web browsing). For Code Interpreter that needs to access S3 or internal AWS services without internet, use `SANDBOX` with `executionRoleArn`.

**File Support — inline vs S3**
Code Interpreter: inline files up to 100 MB (via `writeFiles` API), S3 files up to 5 GB via AWS CLI commands executed in the sandbox (`executeCommand` with `aws s3 cp`). The sandbox includes pre-installed `boto3` and AWS CLI. Browser: session recording (DOM changes, console logs, network events) to S3 with configurable prefix, replay available from the Console.

**JavaScript and TypeScript execution — Runtimes**
Code Interpreter supports Python, JavaScript, and TypeScript. For JavaScript and TypeScript, the default runtime is Deno (which supports ESM for both). A Node.js runtime (v24.14.0, April 2026) is also available by specifying `'runtime': 'nodejs'` in `executeCode` arguments. With Node.js: JavaScript uses CommonJS (CJS), TypeScript uses ESM. Pre-installed Node.js modules: `axios`, `lodash`, `uuid`, `zod`, `cheerio`.

**Browser Proxies — IP stability and corporate integration**
AgentCore Browser supports routing traffic through external proxy servers configured at session level (`StartBrowserSession` with `proxyConfiguration`). Supports Basic authentication (credentials in Secrets Manager), domain-based routing (`domainPatterns` for specific proxies), and bypass rules. Limit: maximum 5 proxies per session, 50 domain patterns per proxy, 100 total patterns. Useful for IP stability, IP allowlisting, and access to corporate intranets.

**Pricing — Active Consumption Model**
Billing for Browser and Code Interpreter: $0.0895/vCPU-hour and $0.00945/GB-hour, calculated per second with minimum 1 second. You pay only for active consumption: I/O wait (waiting for LLM responses, API calls) does not generate CPU costs if no background processes are running. Memory is billed at the per-second peak (watermark). Minimum memory billing: 128 MB. Additional storage: Browser Profiles on S3 Standard (from April 2026). Network data transfer at standard EC2 rates.

---

## Best practices

- **Use context managers for session management** — The `browser_session()` and `code_session()` context managers guarantee sessions are always stopped even on exceptions, avoiding orphan sessions that generate costs. Alternative: explicit `try/finally` with `.stop()`. _Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/code-interpreter-tool.html_

- **Explicitly stop sessions as soon as they are no longer needed** — Sessions consume resources (and generate costs) until the configured timeout or an explicit stop. Do not rely solely on automatic timeout in production. For short-lived sessions use a low `sessionTimeoutSeconds`. _Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/browser-resource-session-management.html and code-interpreter-resource-session-management.html_

- **Use the System ARN (`aws.browser.v1`, `aws.codeinterpreter.v1`) for environments without custom network requirements** — Zero setup, available in all regions, stricter default configuration. No `executionRoleArn` required. Ideal for development, testing, and standard use cases. _Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/browser-resource-session-management.html_

- **For Code Interpreter that needs S3 access, use `networkMode` SANDBOX with `executionRoleArn`** — SANDBOX blocks public internet traffic, reducing the attack surface. Access to S3 happens via the execution role IAM role through internal AWS endpoints. Use PUBLIC mode only if agent code needs to make HTTP calls to the internet. _Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/code-interpreter-s3-integration.html_

- **Include `try/except` in Python code sent to Code Interpreter** — Code executed by the agent is often model-generated. Without error handling, an uncaught exception is reported as an error in the output but can confuse the agent. The structured output includes `isError` and `stderr` for debugging. _Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/code-interpreter-tool.html_

- **Use `clearContext=False` for multi-step workflows and `clearContext=True` for independent executions** — With `clearContext=False` the Python kernel maintains state (variables, imports, DataFrames) between invocations in the same session. This is essential for iterative workflows where each step builds on previous results. `clearContext=True` is useful for isolated, reproducible executions. _Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/code-interpreter-building-agents.html_

- **Use `update_browser_stream` with `streamStatus=DISABLED` for sensitive human input** — When a human user needs to enter credentials or sensitive data in the live view, disabling the automation stream prevents the agent from reading or replicating what the user types. Re-enable with `ENABLED` when the user is done. _Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/browser-managing-sessions.html_

- **Separate control plane and data plane with two distinct boto3 clients** — Resource create/delete/list APIs use service name `'bedrock-agentcore-control'` with `*-control.*` endpoint. Session and invocation APIs use `'bedrock-agentcore'`. Using the wrong client generates endpoint not found or NoCredentialProvider errors. _Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/browser-resource-session-management.html_

- **For browser: prefer CDP WebSocket (Playwright/Nova Act) for DOM automation and InvokeBrowser for OS-level actions** — CDP via WebSocket is optimal for navigation, form filling, DOM element clicks, page scraping. InvokeBrowser is indispensable for native OS dialogs (print, file upload), blocking JavaScript alerts, keyboard shortcuts, or full-desktop screenshots that go beyond the viewport. _Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/browser-invoke.html_

- **Enable S3 session recording for production environments and debugging** — Recording captures DOM changes, user actions, console logs, and network events. Console replay enables post-mortem debugging without manually reproducing the flow. Plan an S3 lifecycle policy to control storage costs. _Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/browser-resource-session-management.html_

- **Configure CloudWatch alarms on throttles and user error metrics for Code Interpreter** — CloudWatch metrics (session counts, duration, invocations, request latency, throttles, user errors, system errors) allow detecting problems before they impact users. Throttles in particular signal approaching service quotas (30 TPS for InvokeCodeInterpreter, default increasable). _Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/code-interpreter-observability.html_

- **Use minimum IAM scope: resource ARN with wildcard on `browser/*` or `code-interpreter/*` for the specific account** — Documentation example policies use `'arn:aws:bedrock-agentcore:{region}:{accountId}:browser/*'` — not `'*'`. This limits access to resources of the correct account and region, following the principle of least privilege. _Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/browser-quickstart.html_

- **For browser in enterprise environments, configure `proxyConfiguration` with credentials in Secrets Manager** — Proxy configuration at session level enables IP stability, corporate intranet integration, and IP allowlisting. Basic authentication credentials must not be hardcoded but retrieved dynamically from Secrets Manager via `secretArn`. Use `domainPatterns` for selective routing and bypass to exclude `.amazonaws.com` from the proxy. _Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/browser-proxies.html_

- **Do not initialize `code_session()` inside a Strands `@tool` for persistent multi-turn workflows** — The `code_session()` context manager creates a new session every time it is invoked in the tool body. For multi-turn workflows where Python state must persist across consecutive calls from the same agent, initialize a single session (`code_client.start()`) outside the tool and pass the client as a closure or instance variable. _Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/code-interpreter-building-agents.html_

---

## Code

### Browser Tool — Setting up the two Boto3 clients (control plane + data plane)

```python
import boto3
import uuid

REGION = "us-west-2"
CP_ENDPOINT_URL = f"https://bedrock-agentcore-control.{REGION}.amazonaws.com"
DP_ENDPOINT_URL = f"https://bedrock-agentcore.{REGION}.amazonaws.com"

# Control plane: create/delete/list browser tools
cp_client = boto3.client(
    'bedrock-agentcore-control',
    region_name=REGION,
    endpoint_url=CP_ENDPOINT_URL
)

# Data plane: start/stop/invoke sessions
dp_client = boto3.client(
    'bedrock-agentcore',
    region_name=REGION,
    endpoint_url=DP_ENDPOINT_URL
)
```

_Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/browser-resource-session-management.html_

---

### Browser Tool — Start session with explicit parameters (direct boto3)

```python
import boto3

dp_client = boto3.client('bedrock-agentcore', region_name='us-west-2')

response = dp_client.start_browser_session(
    browserIdentifier="aws.browser.v1",  # or custom browser ID
    name="agent-session-123",
    sessionTimeoutSeconds=3600,  # 1 hour; max 28800 (8h)
    viewPort={
        'height': 819,
        'width': 1456  # default; valid coordinates: 1 < x < viewportWidth-2
    }
)
session_id = response['sessionId']
print(f"Session ID: {session_id}")
print(f"Status: {response['status']}")
# streams.automationStream.streamEndpoint = WSS URL for CDP (Playwright, Nova Act)
# streams.liveViewStream.streamEndpoint = HTTPS URL for human live view (not a WebSocket)
```

_Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/browser-managing-sessions.html_

---

### Browser Tool — Playwright integration (sync, via browser_session context manager)

```python
# pip install bedrock-agentcore strands-agents strands-agents-tools playwright nest-asyncio
from playwright.sync_api import sync_playwright, Playwright, BrowserType
import base64
from bedrock_agentcore.tools.browser_client import browser_session

def main(playwright: Playwright):
    with browser_session('us-west-2') as client:
        # Generate CDP endpoint and SigV4 headers
        ws_url, headers = client.generate_ws_headers()

        chromium: BrowserType = playwright.chromium
        browser = chromium.connect_over_cdp(ws_url, headers=headers)

        context = browser.contexts[0] if browser.contexts else browser.new_context()
        page = context.pages[0] if context.pages else context.new_page()

        page.goto("https://example.com")
        print(f"Title: {page.title()}")

        # Screenshot via CDP
        cdp_client = context.new_cdp_session(page)
        screenshot_data = cdp_client.send("Page.captureScreenshot", {
            "format": "jpeg", "quality": 80, "captureBeyondViewport": True
        })
        image_data = base64.b64decode(screenshot_data['data'])
        with open("screenshot.jpeg", "wb") as f:
            f.write(image_data)

        page.close()
        browser.close()

with sync_playwright() as p:
    main(p)
```

_Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/browser-managing-sessions.html_

---

### Browser Tool — Nova Act integration (context manager)

```python
# pip install bedrock-agentcore nova-act boto3
from bedrock_agentcore.tools.browser_client import browser_session
from nova_act import NovaAct

def browser_with_nova_act(prompt: str, starting_page: str, nova_act_key: str, region: str = "us-west-2"):
    result = None
    with browser_session(region) as client:
        ws_url, headers = client.generate_ws_headers()
        try:
            with NovaAct(
                cdp_endpoint_url=ws_url,
                cdp_headers=headers,
                nova_act_api_key=nova_act_key,
                starting_page=starting_page,
            ) as nova_act:
                result = nova_act.act(prompt)
        except Exception as e:
            print(f"NovaAct error: {e}")
    return result
```

_Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/browser-quickstart-nova-act.html_

---

### Browser Tool — InvokeBrowser OS-level actions (screenshot, click, keyboard)

```python
import boto3
import base64

dp_client = boto3.client('bedrock-agentcore', region_name='us-west-2')
SESSION_ID = "<your-session-id>"

# Screenshot full-desktop (PNG)
response = dp_client.invoke_browser(
    browserIdentifier="aws.browser.v1",
    sessionId=SESSION_ID,
    action={"screenshot": {"format": "PNG"}}
)
if response['result']['screenshot']['status'] == 'SUCCESS':
    image_data = base64.b64decode(response['result']['screenshot']['data'])
    with open("screenshot.png", "wb") as f:
        f.write(image_data)
    print("Screenshot saved as screenshot.png")

# OS-level click at coordinates (coordinates must be: 1 < x < viewportWidth-2)
dp_client.invoke_browser(
    browserIdentifier="aws.browser.v1",
    sessionId=SESSION_ID,
    action={"mouseClick": {"x": 100, "y": 200, "button": "LEFT", "clickCount": 1}}
)

# Keyboard shortcut (ctrl+s) — key names in lowercase
dp_client.invoke_browser(
    browserIdentifier="aws.browser.v1",
    sessionId=SESSION_ID,
    action={"keyShortcut": {"keys": ["ctrl", "s"]}}
)

# Typing text (ASCII only; non-ASCII characters are silently ignored)
dp_client.invoke_browser(
    browserIdentifier="aws.browser.v1",
    sessionId=SESSION_ID,
    action={"keyType": {"text": "Hello World"}}
)
```

_Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/browser-invoke.html_

---

### Browser Tool — Disable automation for sensitive human input

```python
import boto3

dp_client = boto3.client('bedrock-agentcore', region_name='us-west-2')

# Disable agent control of the session — the user can enter credentials via live view
dp_client.update_browser_stream(
    browserIdentifier="aws.browser.v1",
    sessionId="<your-session-id>",
    streamUpdate={
        "automationStreamUpdate": {
            "streamStatus": "DISABLED"
        }
    }
)

# ... the user logs in manually via live view ...

# Re-enable automation
dp_client.update_browser_stream(
    browserIdentifier="aws.browser.v1",
    sessionId="<your-session-id>",
    streamUpdate={
        "automationStreamUpdate": {
            "streamStatus": "ENABLED"
        }
    }
)
```

_Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/browser-managing-sessions.html_

---

### Browser Tool — Proxy configuration with authentication (enterprise)

```python
import boto3

dp_client = boto3.client('bedrock-agentcore', region_name='us-west-2')

# Proxy with domain-based routing and bypass for AWS endpoints
response = dp_client.start_browser_session(
    browserIdentifier="aws.browser.v1",
    name="proxy-enterprise-session",
    sessionTimeoutSeconds=3600,
    proxyConfiguration={
        "proxies": [
            {
                "externalProxy": {
                    "server": "corp-proxy.example.com",
                    "port": 8080,
                    "domainPatterns": [".company.com", ".internal.corp"],
                    "credentials": {
                        "basicAuth": {
                            # Credentials stored in Secrets Manager (JSON: {"username":"...","password":"..."})
                            "secretArn": "arn:aws:secretsmanager:us-west-2:123456789012:secret:proxy-creds"
                        }
                    }
                }
            },
            {
                "externalProxy": {
                    "server": "general-proxy.example.com",
                    "port": 8080
                    # No domainPatterns = default proxy for everything else
                }
            }
        ],
        "bypass": {
            "domainPatterns": [".amazonaws.com"]  # AWS traffic without proxy
        }
    }
)
print(f"Session ID: {response['sessionId']}")
```

_Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/browser-proxies.html_

---

### Browser Tool — Strands Agent with AgentCoreBrowser (simplest approach)

```python
# pip install bedrock-agentcore strands-agents strands-agents-tools playwright nest-asyncio
from strands import Agent
from strands_tools.browser import AgentCoreBrowser

# Initialize the Browser tool (uses aws.browser.v1 by default)
browser_tool = AgentCoreBrowser(region="us-west-2")

# Create the agent with the browser tool
agent = Agent(tools=[browser_tool.browser])

# Invoke the agent — automatically manages session and CDP
prompt = "what are the services offered by Bedrock AgentCore? Use: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/what-is-bedrock-agentcore.html"
response = agent(prompt)
print(response.message["content"][0]["text"])
```

_Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/browser-quickstart.html_

---

### Code Interpreter — Direct usage with boto3 (start/stop/invoke with streaming)

```python
import boto3
import json

client = boto3.client("bedrock-agentcore", region_name="us-west-2")

# Start session
session_response = client.start_code_interpreter_session(
    codeInterpreterIdentifier="aws.codeinterpreter.v1",
    name="data-analysis-session",
    sessionTimeoutSeconds=900  # default 900s (15 min); max 28800 (8h)
)
session_id = session_response["sessionId"]
print(f"Session ID: {session_id}")

try:
    # Execute Python code
    response = client.invoke_code_interpreter(
        codeInterpreterIdentifier="aws.codeinterpreter.v1",
        sessionId=session_id,
        name="executeCode",
        arguments={
            "language": "python",
            "code": "import numpy as np; print(np.arange(10))"
            # clearContext omitted = default behavior (keeps state)
        }
    )
    for event in response['stream']:
        if 'result' in event:
            result = event['result']
            # isError: True if execution failed
            for item in result.get('content', []):
                if item['type'] == 'text':
                    print(item['text'])
            sc = result.get('structuredContent', {})
            if sc:
                print(f"stdout: {sc.get('stdout', '')[:200]}")
                print(f"exitCode: {sc.get('exitCode', '')}")

    # Asynchronous command with task ID (for long-running processes)
    async_response = client.invoke_code_interpreter(
        codeInterpreterIdentifier="aws.codeinterpreter.v1",
        sessionId=session_id,
        name="startCommandExecution",
        arguments={"command": "sleep 5 && echo done"}
    )
    for event in async_response['stream']:
        task_id = event['result'].get('taskId')
        print(f"Async task ID: {task_id}")

finally:
    client.stop_code_interpreter_session(
        codeInterpreterIdentifier="aws.codeinterpreter.v1",
        sessionId=session_id
    )
```

_Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/code-interpreter-using-directly.html_

---

### Code Interpreter — Usage with code_session context manager and SDK

```python
# pip install bedrock-agentcore
from bedrock_agentcore.tools.code_interpreter_client import CodeInterpreter, code_session
import json

# Approach 1: context manager (automatic start() and stop())
with code_session("us-west-2") as code_client:
    # Python execution
    response = code_client.invoke("executeCode", {
        "code": "import pandas as pd; df = pd.DataFrame({'a': [1,2,3]}); print(df.describe())",
        "language": "python",
        "clearContext": False  # keep state for subsequent steps
    })
    for event in response["stream"]:
        print(json.dumps(event["result"]))

    # Synchronous shell command
    response = code_client.invoke("executeCommand", {"command": "ls -la"})
    for event in response["stream"]:
        print(json.dumps(event["result"]))

    # Write file to sandbox (inline, up to 100 MB)
    code_client.invoke("writeFiles", {
        "content": [{"path": "data.txt", "text": "file content"}]
    })

    # List files in the sandbox
    response = code_client.invoke("listFiles", {"directoryPath": ""})
    for event in response["stream"]:
        print(json.dumps(event["result"]))

# Approach 2: explicit control
code_client = CodeInterpreter('us-west-2')
code_client.start()
try:
    response = code_client.invoke("executeCode", {"language": "python", "code": 'print("Hello")'})
    for event in response["stream"]:
        print(json.dumps(event["result"], indent=2))
finally:
    code_client.stop()
```

_Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/code-interpreter-using-directly.html_

---

### Code Interpreter — JavaScript/TypeScript with Node.js runtime

```python
# pip install bedrock-agentcore
from bedrock_agentcore.tools.code_interpreter_client import code_session
import json

with code_session("us-west-2") as code_client:
    # JavaScript with Node.js runtime (default is Deno)
    # With Node.js: JS uses CommonJS (require), TS uses ESM (import)
    response = code_client.invoke("executeCode", {
        "language": "javascript",
        "runtime": "nodejs",  # Omit to use Deno (default); Node.js v24.14.0
        "code": """
const axios = require('axios');  // CJS with Node.js; with Deno use import
console.log('Node.js version:', process.version);
console.log('Axios available:', typeof axios);
""",
        "clearContext": False
    })
    for event in response["stream"]:
        result = event["result"]
        for item in result.get('content', []):
            if item['type'] == 'text':
                print(item['text'])

    # TypeScript with Deno (default) — uses ESM
    response = code_client.invoke("executeCode", {
        "language": "typescript",
        # runtime omitted = Deno by default
        "code": """
interface User { name: string; age: number; }
const user: User = { name: 'Alice', age: 30 };
console.log(`User: ${user.name}, Age: ${user.age}`);
""",
        "clearContext": False
    })
    for event in response["stream"]:
        for item in event["result"].get('content', []):
            if item['type'] == 'text':
                print(item['text'])
```

_Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/code-interpreter-tool.html_

---

### Code Interpreter — Strands Agent with AgentCoreCodeInterpreter

```python
# pip install bedrock-agentcore strands-agents strands-agents-tools
from strands import Agent
from strands_tools.code_interpreter import AgentCoreCodeInterpreter

# Initialize the Code Interpreter tool
code_interpreter_tool = AgentCoreCodeInterpreter(region="us-west-2")

SYSTEM_PROMPT = """You are an AI assistant that validates answers through code execution.
When asked about code, algorithms, or calculations, write Python code to verify your answers."""

agent = Agent(
    tools=[code_interpreter_tool.code_interpreter],
    system_prompt=SYSTEM_PROMPT
)

response = agent("Calculate the first 10 Fibonacci numbers.")
print(response.message["content"][0]["text"])
```

_Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/code-interpreter-using-strands.html_

---

### Code Interpreter — Strands Agent with code_session and @tool decorator (full control)

```python
import json
import asyncio
from strands import Agent, tool
from bedrock_agentcore.tools.code_interpreter_client import code_session

SYSTEM_PROMPT = """You are a helpful AI assistant that validates all answers through code execution.

VALIDATION PRINCIPLES:
1. When making claims about code, algorithms, or calculations - write code to verify them
2. Use execute_python to test mathematical calculations, algorithms, and logic
3. Always show your work with actual code execution

RESPONSE FORMAT: The execute_python tool returns a JSON response with:
- sessionId: The code interpreter session ID
- isError: Boolean indicating if there was an error
- content: Array of {type, text} objects
- structuredContent: {stdout, stderr, exitCode, executionTime}"""

@tool
def execute_python(code: str, description: str = "") -> str:
    """Execute Python code in a secure sandbox and return the result"""
    if description:
        code = f"# {description}\n{code}"
    print(f"\nCode: {code}")
    with code_session("us-west-2") as code_client:
        response = code_client.invoke("executeCode", {
            "code": code,
            "language": "python",
            "clearContext": False
        })
        for event in response["stream"]:
            return json.dumps(event["result"])

agent = Agent(
    tools=[execute_python],
    system_prompt=SYSTEM_PROMPT,
    callback_handler=None
)

async def main():
    async for event in agent.stream_async("Can all the planets in the solar system fit between the earth and moon?"):
        if "data" in event:
            print(event["data"], end="")

asyncio.run(main())
```

_Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/code-interpreter-building-agents.html_

---

### Code Interpreter — LangChain Agent with code_session

```python
# pip install langchain langchain_aws bedrock-agentcore
import json
from bedrock_agentcore.tools.code_interpreter_client import code_session
from langchain.agents import AgentExecutor, create_tool_calling_agent, tool
from langchain_aws import ChatBedrockConverse
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

@tool
def execute_python(code: str, description: str = "") -> str:
    """Execute Python code and return stdout/stderr output"""
    if description:
        code = f"# {description}\n{code}"
    print(f"\nGenerated Code:\n{code}")
    with code_session("us-west-2") as code_client:
        response = code_client.invoke("executeCode", {
            "code": code,
            "language": "python",
            "clearContext": False
        })
        for event in response["stream"]:
            return json.dumps(event["result"])

# Requires access to the anthropic.claude-3-5-sonnet-20240620-v1:0 model in Bedrock
llm = ChatBedrockConverse(
    model_id="anthropic.claude-3-5-sonnet-20240620-v1:0",
    region_name="us-west-2"
)

SYSTEM_PROMPT = "You are a helpful AI assistant that validates all answers through code execution."

prompt = ChatPromptTemplate.from_messages([
    ("system", SYSTEM_PROMPT),
    ("user", "{input}"),
    MessagesPlaceholder(variable_name="agent_scratchpad"),
])

agent = create_tool_calling_agent(llm, [execute_python], prompt)
agent_executor = AgentExecutor(agent=agent, tools=[execute_python], verbose=True)
result = agent_executor.invoke({"input": "Can all the planets in the solar system fit between the earth and moon?"})
print(result['output'])
```

_Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/code-interpreter-building-agents.html_

---

### Code Interpreter — Custom with executionRoleArn for S3 access (network SANDBOX)

```python
import boto3
import json
import time

REGION = "us-west-2"
cp_client = boto3.client('bedrock-agentcore-control', region_name=REGION,
                         endpoint_url=f"https://bedrock-agentcore-control.{REGION}.amazonaws.com")
dp_client = boto3.client('bedrock-agentcore', region_name=REGION,
                         endpoint_url=f"https://bedrock-agentcore.{REGION}.amazonaws.com")

S3_BUCKET_NAME = "my-bucket"  # replace with your own bucket

# Create custom Code Interpreter with execution role for S3
unique_name = f"s3-ci-{int(time.time())}"
create_response = cp_client.create_code_interpreter(
    name=unique_name,
    description="Code Interpreter with S3 access",
    executionRoleArn="arn:aws:iam::123456789012:role/CodeInterpreterS3Role",
    networkConfiguration={
        # SANDBOX = no internet, only internal AWS via execution role;
        # PUBLIC = full internet access
        "networkMode": "SANDBOX"
    }
)
code_interpreter_id = create_response['codeInterpreterId']
print(f"Created: {code_interpreter_id}")

session = dp_client.start_code_interpreter_session(
    codeInterpreterIdentifier=code_interpreter_id,
    name="s3-session",
    sessionTimeoutSeconds=1800
)
session_id = session['sessionId']

try:
    # Download file from S3 via AWS CLI in the sandbox
    response = dp_client.invoke_code_interpreter(
        codeInterpreterIdentifier=code_interpreter_id,
        sessionId=session_id,
        name="executeCommand",
        arguments={"command": f"aws s3 cp s3://{S3_BUCKET_NAME}/generate_csv.py ."}
    )
    for event in response["stream"]:
        print(json.dumps(event["result"], default=str, indent=2))

    # Execute the downloaded script
    response = dp_client.invoke_code_interpreter(
        codeInterpreterIdentifier=code_interpreter_id,
        sessionId=session_id,
        name="executeCommand",
        arguments={"command": "python generate_csv.py 5 10"}
    )
    for event in response["stream"]:
        print(json.dumps(event["result"], default=str, indent=2))

    # Upload results to S3
    response = dp_client.invoke_code_interpreter(
        codeInterpreterIdentifier=code_interpreter_id,
        sessionId=session_id,
        name="executeCommand",
        arguments={"command": f"aws s3 cp generated_data.csv s3://{S3_BUCKET_NAME}/output/"}
    )
    for event in response["stream"]:
        print(json.dumps(event["result"], default=str, indent=2))
finally:
    dp_client.stop_code_interpreter_session(
        codeInterpreterIdentifier=code_interpreter_id,
        sessionId=session_id
    )
    delete_response = cp_client.delete_code_interpreter(codeInterpreterId=code_interpreter_id)
    print(f"Deleted: {delete_response['status']}")
```

_Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/code-interpreter-s3-integration.html_

---

### IAM Policy — Browser Tool (user policy + execution role trust policy)

```json
// User/calling role policy (with Bedrock model access for Strands)
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "BedrockAgentCoreBrowserFullAccess",
      "Effect": "Allow",
      "Action": [
        "bedrock-agentcore:CreateBrowser",
        "bedrock-agentcore:ListBrowsers",
        "bedrock-agentcore:GetBrowser",
        "bedrock-agentcore:DeleteBrowser",
        "bedrock-agentcore:StartBrowserSession",
        "bedrock-agentcore:ListBrowserSessions",
        "bedrock-agentcore:GetBrowserSession",
        "bedrock-agentcore:StopBrowserSession",
        "bedrock-agentcore:UpdateBrowserStream",
        "bedrock-agentcore:ConnectBrowserAutomationStream",
        "bedrock-agentcore:ConnectBrowserLiveViewStream"
      ],
      "Resource": "arn:aws:bedrock-agentcore:us-west-2:123456789012:browser/*"
    },
    {
      "Sid": "BedrockModelAccess",
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream"
      ],
      "Resource": ["*"]
    }
  ]
}

// Trust policy for the execution role (for S3 recording)
{
  "Version": "2012-10-17",
  "Statement": [{
    "Sid": "BedrockAgentCoreBuiltInTools",
    "Effect": "Allow",
    "Principal": {"Service": "bedrock-agentcore.amazonaws.com"},
    "Action": "sts:AssumeRole",
    "Condition": {
      "StringEquals": {"aws:SourceAccount": "123456789012"},
      "ArnLike": {"aws:SourceArn": "arn:aws:bedrock-agentcore:us-west-2:123456789012:*"}
    }
  }]
}
```

_Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/browser-quickstart.html_

---

### IAM Policy — Code Interpreter (user policy + trust policy for execution role S3)

```json
// User/calling role policy
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "BedrockAgentCoreCodeInterpreterFullAccess",
      "Effect": "Allow",
      "Action": [
        "bedrock-agentcore:CreateCodeInterpreter",
        "bedrock-agentcore:StartCodeInterpreterSession",
        "bedrock-agentcore:InvokeCodeInterpreter",
        "bedrock-agentcore:StopCodeInterpreterSession",
        "bedrock-agentcore:DeleteCodeInterpreter",
        "bedrock-agentcore:ListCodeInterpreters",
        "bedrock-agentcore:GetCodeInterpreter",
        "bedrock-agentcore:GetCodeInterpreterSession",
        "bedrock-agentcore:ListCodeInterpreterSessions"
      ],
      "Resource": "arn:aws:bedrock-agentcore:us-west-2:123456789012:code-interpreter/*"
    }
  ]
}

// Trust policy for the execution role for custom Code Interpreter with S3 access
// NOTE: uses only aws:SourceAccount (NOT ArnLike on aws:SourceArn — different from Browser)
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Service": "bedrock-agentcore.amazonaws.com"},
    "Action": "sts:AssumeRole",
    "Condition": {
      "StringEquals": {"aws:SourceAccount": "123456789012"}
    }
  }]
}

// Permissions for the execution role for S3 access
{
  "Version": "2012-10-17",
  "Statement": [{
    "Sid": "VisualEditor0",
    "Effect": "Allow",
    "Action": ["s3:PutObject", "s3:GetObject"],
    "Resource": "arn:aws:s3:::my-bucket/*",
    "Condition": {
      "StringEquals": {"s3:ResourceAccount": "${aws:PrincipalAccount}"}
    }
  }]
}
```

_Source (user policy): https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/code-interpreter-resource-session-management.html — Source (execution role trust policy for S3 access): https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/code-interpreter-s3-integration.html_

---

## Configuration reference

| Name | Description | Default / example |
|------|-------------|-------------------|
| `browserIdentifier` | Identifier of the Browser tool to use in `start_browser_session`, `get_browser_session`, `stop_browser_session`, `invoke_browser`. Use `'aws.browser.v1'` for the default System ARN, or the `browserId` of a custom browser. | `aws.browser.v1` |
| `codeInterpreterIdentifier` | Identifier of the Code Interpreter to use in `start_code_interpreter_session`, `invoke_code_interpreter`, `stop_code_interpreter_session`. Use `'aws.codeinterpreter.v1'` for the default System ARN, or a custom `codeInterpreterId`. | `aws.codeinterpreter.v1` |
| `sessionTimeoutSeconds` | Session timeout in seconds. The session auto-terminates at expiry. Valid for both Browser and Code Interpreter. | Default: `3600` (1 h) for Browser; `900` (15 min) for Code Interpreter. Max: `28800` (8h) |
| `viewPort` (Browser) | Browser viewport size. Coordinates for InvokeBrowser must be in the range `1 < x < viewportWidth-2` and `1 < y < viewportHeight-2`. | `{"width": 1456, "height": 819}` |
| `networkMode` (Code Interpreter) | Network mode for the sandbox. `SANDBOX`: no internet access, only internal AWS access via execution role. `PUBLIC`: full internet access. | `SANDBOX` \| `PUBLIC` |
| `networkMode` (Browser) | The Browser Tool supports only PUBLIC network mode (required for web browsing). | `PUBLIC` |
| `executionRoleArn` | ARN of the IAM role the tool assumes to access AWS resources (S3 for recording/files, other services). The role must have a trust policy on `bedrock-agentcore.amazonaws.com`. | `arn:aws:iam::123456789012:role/BrowserExecutionRole` |
| `recording.enabled` (Browser) | Enables browser session recording. Requires `s3Location` with bucket and prefix. Records DOM changes, user actions, console logs, network events. | `false` |
| `recording.s3Location.bucket` | S3 bucket for saving browser session recordings. The execution role must have `s3:PutObject`, `s3:ListMultipartUploadParts`, `s3:AbortMultipartUpload` on the bucket. | `my-session-recordings-bucket` |
| `language` (`invoke_code_interpreter` — `executeCode`) | Language of the code to execute in the `executeCode` operation. | `python` \| `javascript` \| `typescript` |
| `runtime` (`invoke_code_interpreter` — JS/TS) | Runtime to use for JavaScript or TypeScript. If omitted, default is Deno (ESM for JS and TS). Specify `'nodejs'` for Node.js v24.14.0: JS uses CommonJS, TS uses ESM. Not directly supported by `AgentCoreCodeInterpreter` (Strands built-in) — use `code_session()` with a custom tool. | `deno` (default) \| `nodejs` |
| `clearContext` (`invoke_code_interpreter` — `executeCode`) | If `True`, resets the kernel state before execution. If `False` (recommended default), keeps variables and imports from previous executions in the same session. | `false` |
| `name` (`invoke_code_interpreter`) | Operation name for the dispatcher. Determines the action executed in the sandbox. | `executeCode` \| `executeCommand` \| `startCommandExecution` \| `getTask` \| `stopTask` \| `writeFiles` \| `readFiles` \| `removeFiles` \| `listFiles` |
| `streamStatus` (`update_browser_stream`) | Status of the CDP automation stream. `DISABLED` prevents the agent from controlling the browser (for sensitive human input). `ENABLED` re-enables control. | `ENABLED` \| `DISABLED` |
| `type` (Browser listing) | Filter for `list_browsers`: `SYSTEM` for AWS pre-created browsers, `CUSTOM` for user-created ones. | `SYSTEM` \| `CUSTOM` |
| `proxyConfiguration` (Browser) | Proxy configuration for browser traffic routing. Structure: `{proxies: [{externalProxy: {server, port, domainPatterns?, credentials?: {basicAuth: {secretArn}}}}], bypass?: {domainPatterns}}`. Max 5 proxies per session, 50 `domainPatterns` per proxy, 100 total. | `{"proxies": [{"externalProxy": {"server": "proxy.example.com", "port": 8080}}]}` |
| `CP_ENDPOINT_URL` | HTTP endpoint for the `bedrock-agentcore-control` control plane client. | `https://bedrock-agentcore-control.{REGION}.amazonaws.com` |
| `DP_ENDPOINT_URL` | HTTP endpoint for the `bedrock-agentcore` data plane client. | `https://bedrock-agentcore.{REGION}.amazonaws.com` |
| Regions (GA Built-in Tools) | AgentCore Built-in Tools (Browser + Code Interpreter) available in 16 GA regions, including `us-gov-west-1`. | `us-east-1`, `us-east-2`, `us-west-2`, `eu-central-1`, `eu-west-1`, `eu-west-2`, `eu-west-3`, `eu-north-1`, `ap-south-1`, `ap-southeast-1`, `ap-southeast-2`, `ap-northeast-1`, `ap-northeast-2`, `ca-central-1`, `sa-east-1`, `us-gov-west-1` |
| File size limits (Code Interpreter) | Maximum file size for inline upload (`writeFiles` API) and for S3 via CLI in the sandbox. | Inline `writeFiles`: 100 MB; Via S3 CLI in sandbox (`executeCommand`): 5 GB; Max payload: 100 MB |
| Max concurrent sessions | Maximum number of active sessions per account per tool. Increasable via support ticket. | Browser: 1,000 (default); Code Interpreter: 1,000 (default) |
| Hardware per session | Fixed hardware configuration per session: Browser 1 vCPU/4 GB, Code Interpreter 2 vCPU/8 GB. Not modifiable. | Browser: 1 vCPU/4 GB; Code Interpreter: 2 vCPU/8 GB |
| Disk per session | Disk space available per session, not increasable. | 10 GB per session (both Browser and Code Interpreter) |
| Session data TTL | Retention period for session data after termination. | 30 days |
| Pricing | Consumption-based model: billing per second on active CPU (peak) and memory (peak). No cost for I/O wait. Minimum 1 second per session. Minimum memory billing: 128 MB. | CPU: $0.0895/vCPU-hour; Memory: $0.00945/GB-hour |
| `InvokeBrowser` rate limit | Throttling limit for the `InvokeBrowser` API (OS-level actions). Increasable via support ticket. | 5 TPS per account |
| `InvokeCodeInterpreter` rate limit | Throttling limit for the `InvokeCodeInterpreter` API. Increasable via support ticket. | 30 TPS per account |

---

## Gotchas

- **CLASSIC ERROR: Using `boto3.client('bedrock-agentcore')` for control plane operations** — create/list/delete browser or code interpreter operations require `boto3.client('bedrock-agentcore-control')` with endpoint `*-control.{region}.amazonaws.com`. The wrong client generates `NoRegionError` or endpoint not found.

- **CLASSIC ERROR: Not stopping sessions on completion** — Sessions continue consuming resources and generating costs until timeout. Always use `try/finally` or a context manager to guarantee `stop()`. Note: memory and CPU are billed at per-second peak usage; CPU is NOT billed during I/O wait if no background processes run.

- **ERROR: Attempting to delete a Browser tool or Code Interpreter with active sessions** — The API returns an error. Stop all sessions before `delete_browser` or `delete_code_interpreter`.

- **ERROR: Passing coordinates outside the viewport in InvokeBrowser** — Coordinates `x` and `y` must be strictly inside the viewport bounds (`1 < x < viewportWidth-2` and `1 < y < viewportHeight-2`). Default viewport is 1456x819.

- **CORRECTION: Maximum concurrent Browser sessions is 1,000 (not 500)** — Per account (default, increasable). The value 500 reported previously was obsolete. Source: official service quotas.

- **WARNING: `keyType` in InvokeBrowser supports ASCII characters only** — Non-ASCII characters (Unicode, emoji, accented characters) are silently ignored — no error, but no input.

- **WARNING: `keyPress` and `keyShortcut` in InvokeBrowser do not validate key names** — An unrecognized name returns `SUCCESS` without executing the action. Key names must be lowercase: `'ctrl'`, `'alt'`, `'shift'`, `'enter'`, `'tab'`, `'space'`, `'backspace'`, `'delete'`, `'escape'`.

- **WARNING: `invoke_code_interpreter` responses are streams** — You must iterate `response['stream']` and not read the response directly as a dict. Forgetting to iterate the stream leaves the response unconsumed.

- **CONFIRMED (not a bug): Code Interpreter execution logs are not available in CloudWatch** — `stdout` and `stderr` are available directly in the response of each invocation in the `structuredContent` field. Execution logs are accessible only from the invocation response.

- **WARNING: Web Bot Auth (CAPTCHA reduction for Browser) is in Preview** — Verify availability before using in production.

- **WARNING: System ARN (`aws.browser.v1` and `aws.codeinterpreter.v1`) does not require `executionRoleArn`** and uses stricter default configuration. To customize network mode, recording, or access to internal AWS resources, create a Custom ARN.

- **WARNING: The `code_session()` context manager creates a new session every time it is used in a `@tool`** — For multi-turn workflows where state must persist across agent calls, initialize a single session outside the tool and pass the client.

- **WARNING: The `liveViewStream.streamEndpoint` URL is HTTPS, not WebSocket** — Do not attempt to connect via CDP to that URL — it is only for human live view via browser.

- **WARNING: The PyPI package is named `bedrock-agentcore` (with hyphens), but the Python import uses `bedrock_agentcore` (with underscores)** — `pip install bedrock-agentcore`, `from bedrock_agentcore.tools...`

- **CORRECTION — Code Interpreter S3 trust policy** — The trust policy for execution role of Code Interpreter with S3 access uses only the `StringEquals` condition on `aws:SourceAccount`, NOT `ArnLike` on `aws:SourceArn`. The Browser trust policy uses both conditions.

- **WARNING: JavaScript on Node.js runtime (not Deno) uses `require()` CommonJS** — With Deno (default), use ESM `import` for both JS and TypeScript. The `import` keyword in JavaScript fails on Node.js runtime. The `runtime` parameter is not supported by `AgentCoreCodeInterpreter` (Strands built-in); use `code_session()` with a custom tool.

- **WARNING: The Browser quickstart IAM policy includes `bedrock:InvokeModel` and `bedrock:InvokeModelWithResponseStream` on `Resource: '*'`** — This permission is required for Strands Agents integration but can be restricted in production to the specific ARNs of the Bedrock models used.

- **WARNING: Browser Profiles (cookie/localStorage persistence across sessions) require S3 Standard storage** — From April 2026, this storage is billable. Browser session recordings on S3 have been billable from the start (via execution role).

- **WARNING: Browser hardware (1 vCPU/4 GB) differs from Code Interpreter (2 vCPU/8 GB)** — Factor this into cost estimates: a 10-minute Browser session with 80% I/O wait at $0.0895/vCPU-hour costs ~$0.006 CPU + ~$0.0063 memory.

---

## Official sources

- [Bedrock AgentCore Browser — Overview](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/browser-tool.html) — Main page: architecture, 4-step workflow, security
- [Bedrock AgentCore Browser — Quickstart with Strands](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/browser-quickstart.html) — 5-minute guide: complete IAM policy (including `bedrock:InvokeModel`), dependency installation, AgentCoreBrowser code with Strands
- [Bedrock AgentCore Browser — Fundamentals (Resource and Session Management)](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/browser-resource-session-management.html) — Control/data plane endpoints, System vs Custom ARN, network settings, session limits (max 1000, default, TTL 30 days)
- [Bedrock AgentCore Browser — Using Browser Tool (CRUD)](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/browser-using-tool.html) — API for create/get/list/delete browser: CLI, boto3 and awscurl with exact syntax
- [Bedrock AgentCore Browser — Managing Sessions](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/browser-managing-sessions.html) — start/stop/list/get session, `update_browser_stream` to disable automation, Playwright and live-view examples
- [Bedrock AgentCore Browser — OS Action (InvokeBrowser)](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/browser-invoke.html) — `InvokeBrowser` API: mouse (click/move/drag/scroll), keyboard (type/press/shortcut), OS-level screenshot — complementary to CDP WebSocket
- [Bedrock AgentCore Browser — Using Browser Proxies](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/browser-proxies.html) — HTTP/HTTPS proxy configuration for IP stability, IP allowlisting, corporate infrastructure. Credentials via Secrets Manager, domain-based routing, bypass rules.
- [Bedrock AgentCore Browser — Quickstart with Nova Act](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/browser-quickstart-nova-act.html) — NovaAct integration: `browser_session` context manager, `generate_ws_headers()`, `cdp_endpoint_url`
- [Bedrock AgentCore Browser — Quickstart with Playwright](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/browser-quickstart-playwright.html) — Async and sync Playwright examples: `connect_over_cdp` with authentication headers, live view
- [Bedrock AgentCore Code Interpreter — Overview](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/code-interpreter-tool.html) — Overview: supported languages (Python/JS/TS), file size limits, official best practices
- [Bedrock AgentCore Code Interpreter — Getting Started](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/code-interpreter-getting-started.html) — Complete IAM policy for Code Interpreter, prerequisites (Python 3.10+, Claude Sonnet 4.0 access), service role trust policy
- [Bedrock AgentCore Code Interpreter — Usage with Strands](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/code-interpreter-using-strands.html) — `AgentCoreCodeInterpreter` Strands tool: `pip install bedrock-agentcore strands-agents strands-agents-tools`
- [Bedrock AgentCore Code Interpreter — Direct usage (SDK and Boto3)](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/code-interpreter-using-directly.html) — CodeInterpreter SDK client vs direct boto3: start/invoke/stop session, streaming response parsing
- [Bedrock AgentCore Code Interpreter — Agents (Strands + LangChain)](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/code-interpreter-building-agents.html) — Complete code for Strands and LangChain agents with `code_session` context manager
- [Bedrock AgentCore Code Interpreter — API Reference Examples](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/code-interpreter-api-reference-examples.html) — All operation names for `invoke_code_interpreter`: `executeCode`, `executeCommand`, `startCommandExecution`, `getTask`, `stopTask`, `writeFiles`, `readFiles`, `removeFiles`, `listFiles`
- [Bedrock AgentCore Code Interpreter — File Operations](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/code-interpreter-file-operations.html) — CodeInterpreter SDK class, `writeFiles/listFiles/executeCode` pattern with file upload
- [Bedrock AgentCore Code Interpreter — S3 Integration with Execution Role](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/code-interpreter-s3-integration.html) — Creating custom Code Interpreter with `executionRoleArn` for S3 access, SANDBOX vs PUBLIC network mode. Simplified trust policy (only `aws:SourceAccount`, not `ArnLike`).
- [Bedrock AgentCore Code Interpreter — Resource and Session Management](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/code-interpreter-resource-session-management.html) — Complete IAM policy, trust policy, create/start/execute/stop flow, System vs Custom ARN
- [Bedrock AgentCore Code Interpreter — Pre-installed Libraries](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/code-interpreter-preinstalled-libraries.html) — Complete list of Python libraries (`pandas`, `numpy`, `torch`, `scikit-learn`, `boto3`, `mcp`, etc.) and pre-installed Node.js modules (`axios`, `lodash`, `uuid`, `zod`, `cheerio`)
- [Bedrock AgentCore Code Interpreter — Observability](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/code-interpreter-observability.html) — CloudWatch metrics: session counts, duration, invocations, request latency, throttles, user/system errors. NOTE: execution logs are NOT available in CloudWatch — stdout/stderr are only in the invocation response.
- [Bedrock AgentCore — Quotas (Service Limits)](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/bedrock-agentcore-limits.html) — Complete limits: Browser 1,000 concurrent sessions/account (1 vCPU/4 GB hardware), Code Interpreter 1,000 concurrent sessions/account (2 vCPU/8 GB hardware), InvokeBrowser 5 TPS, InvokeCodeInterpreter 30 TPS, disk 10 GB per session
- [Bedrock AgentCore — Supported Regions](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agentcore-regions.html) — Complete table: Built-in Tools GA in 16 regions including us-east-1, us-east-2, us-west-2, eu-central-1, eu-west-1, ap-southeast-2, us-gov-west-1
- [Amazon Bedrock AgentCore Pricing](https://aws.amazon.com/bedrock/agentcore/pricing/) — Official pricing: $0.0895/vCPU-hour and $0.00945/GB-hour for Browser and Code Interpreter. Numeric examples with I/O wait adjustment. Browser Profiles on S3 Standard (from April 2026).
- [Blog AWS ML: Introducing AgentCore Code Interpreter](https://aws.amazon.com/blogs/machine-learning/introducing-the-amazon-bedrock-agentcore-code-interpreter/) — Official technical deep dive: per-second pricing, security model, differentiators vs self-managed solutions
- [Blog AWS ML: Introducing AgentCore Browser Tool](https://aws.amazon.com/blogs/machine-learning/introducing-amazon-bedrock-agentcore-browser-tool/) — Official technical deep dive on Browser tool: architecture, use cases, Playwright and Nova Act integration
- [What's New: AgentCore Browser — Web Bot Auth (Preview)](https://aws.amazon.com/about-aws/whats-new/2025/10/amazon-bedrock-agentcore-browser-web-bot-auth-preview/) — IETF Web Bot Auth protocol to reduce CAPTCHAs; supported by Akamai, Cloudflare, HUMAN Security
- [What's New: AgentCore Browser — Custom Extensions GA](https://aws.amazon.com/about-aws/whats-new/2026/01/amazon-bedrock-agentcore-browser-custom-extensions/) — Chrome extensions from S3 loaded automatically in session; announced January 2026
- [What's New: AgentCore Runtime — Node.js Support](https://aws.amazon.com/about-aws/whats-new/2026/04/amazon-bedrock-agentcore-runtime/) — AgentCore Runtime adds Node.js support for direct code deployment (April 2026)
- [AWS SDK JavaScript v3 — BedrockAgentcoreClient](https://docs.aws.amazon.com/AWSJavaScriptSDK/v3/latest/client/bedrock-agentcore/) — JavaScript/TypeScript SDK for the AgentCore data plane (Node.js, Browser, React Native)
- [AWS SDK JavaScript v3 — BedrockAgentcoreControlClient](https://docs.aws.amazon.com/AWSJavaScriptSDK/v3/latest/client/bedrock-agentcore-control/) — JavaScript/TypeScript SDK for the AgentCore control plane
- [GitHub — bedrock-agentcore-sdk-typescript](https://github.com/aws/bedrock-agentcore-sdk-typescript) — Official TypeScript SDK for AgentCore Runtime deployment and sessions
- [GitHub — bedrock-agentcore-samples-typescript](https://github.com/awslabs/bedrock-agentcore-samples-typescript) — Official TypeScript examples for AgentCore Runtime, Browser, and Code Interpreter
