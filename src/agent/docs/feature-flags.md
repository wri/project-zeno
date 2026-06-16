# Agent Feature Flags

Feature flags let you swap the agent's tool set and system prompt on a per-request basis without touching the database. A client passes `"ff": "<flag-name>"` in the `POST /api/chat` request body; the server resolves this to a named `AgentConfig` and builds the agent from it.

## How it works

```mermaid
flowchart TD
    Client["Client\nPOST /api/chat\n{ ff: 'my-flag' }"]
    Router["chat.py\nrouter"]
    Service["stream_chat\n(ff='my-flag')"]
    FetchZeno["fetch_zeno\n(ff, registry)"]

    Registry["AgentConfigRegistry\n.resolve(ff)"]

    DefaultConfig["AgentConfig 'default'\nCORE_SPECS\nget_prompt(config)"]
    FlagConfig["AgentConfig 'my-flag'\nCORE_SPECS + new_tool_spec\nget_prompt(config)"]

    Agent["LangGraph agent\ntools + system prompt\nfrom resolved config"]

    Client -->|ff='my-flag'| Router --> Service --> FetchZeno --> Registry
    Registry -->|"flag known"| FlagConfig --> Agent
    Registry -->|"flag unknown\nor absent"| DefaultConfig --> Agent
```

Each `AgentConfig` bundles:
- **`specs`** — a tuple of `ToolSpec` objects; each spec carries the tool object, its category, and the prompt fragment that describes it
- **`system_prompt`** — an optional override that replaces the generated prompt entirely (useful for test personas like "say only the word cat")

The system prompt is always `config.system_prompt or get_prompt(config)`. `get_prompt` renders the tools and skills sections from the config's specs automatically, so the prompt can never describe a tool that isn't bound.

## Adding a new feature flag

### 1. Implement the tool and define its `SPEC`

In your tool file, add a `SPEC` constant at the bottom after the tool function:

```python
# src/agent/subagents/my_tool/tool.py
from src.agent.tool_spec import ToolCategory, ToolSpec

@tool("my_tool")
async def my_tool(query: str, ...) -> Command:
    """..."""
    ...

SPEC = ToolSpec(
    tool=my_tool,
    category=ToolCategory.SUBAGENT,
    prompt_fragment="- my_tool(query): one-line description for the system prompt.",
)
```

### 2. Register an `AgentConfig` in `agent_config.py`

Import the spec and register a new config on `default_registry`:

```python
# src/agent/agent_config.py
from src.agent.subagents.my_tool.tool import SPEC as my_tool_spec

default_registry.register(AgentConfig(
    "my-flag",
    specs=(*CORE_SPECS, my_tool_spec),
))
```

The config's `name` is the exact string the client passes as `ff`.

### 3. Use the flag from a client

```json
POST /api/chat
{
  "query": "...",
  "thread_id": "...",
  "ff": "my-flag"
}
```

Unknown or absent `ff` values silently fall back to the default config — no error, no change in behaviour.

## Testing a flag

Because `AgentConfigRegistry` is injected as a dependency, tests create isolated instances without touching global state:

```python
from src.agent.agent_config import AgentConfig, AgentConfigRegistry, DEFAULT_PROFILE
from src.agent.graph import fetch_zeno
from langgraph.checkpoint.memory import InMemorySaver

async def test_my_flag():
    registry = AgentConfigRegistry()
    registry.register(AgentConfig(DEFAULT_PROFILE, specs=CORE_SPECS))
    registry.register(AgentConfig("my-flag", specs=(*CORE_SPECS, my_tool_spec)))

    agent = await fetch_zeno(ff="my-flag", registry=registry, checkpointer=InMemorySaver())
    result = await agent.ainvoke(...)
    # assert my_tool was called, others were not
```

For a bespoke test persona with no tools:

```python
registry.register(AgentConfig(
    "cat",
    specs=(),
    system_prompt="Say only the word 'cat' in response to everything.",
))
```

See `tests/agent/test_feature_flag.py` for working examples.
