# Agent Feature Flags

Feature flags let you swap the agent's capability surface (skills, and the tools derived from them) and system prompt on a per-request basis without touching the database. A client passes `"ff": "<flag-name>"` in the `POST /api/chat` request body; the server resolves this to a named `AgentConfig` and builds the agent from it.

## How it works

```mermaid
flowchart TD
    Client["Client\nPOST /api/chat\n{ ff: 'my-flag' }"]
    Router["chat.py\nrouter"]
    Service["stream_chat\n(ff='my-flag')"]
    FetchZeno["fetch_zeno\n(ff, registry)"]

    Registry["AgentConfigRegistry\n.resolve(ff)"]

    DefaultConfig["AgentConfig 'default'\nDEFAULT_SKILLS\nget_prompt(config)"]
    FlagConfig["AgentConfig 'my-flag'\nDEFAULT_SKILLS + 'my-skill'\nget_prompt(config)"]

    Agent["LangGraph agent\ntools + system prompt\nfrom resolved config"]

    Client -->|ff='my-flag'| Router --> Service --> FetchZeno --> Registry
    Registry -->|"flag known"| FlagConfig --> Agent
    Registry -->|"flag unknown\nor absent"| DefaultConfig --> Agent
```

Each `AgentConfig` bundles:
- **`skills`** — a tuple of skill names (files in `src/agent/skills/skills_md/`); the profile's tools are *derived* from each skill's `requires:` frontmatter (plus `read_skill` itself), so a skill can never be declared without its tools, and adding a tool can never silently activate a skill
- **`extra_tools`** — a tuple of `ToolSpec` objects for tools that aren't part of any skill's workflow (e.g. `inspect_view_context`)
- **`system_prompt`** — an optional override that replaces the generated prompt entirely (useful for test personas like "say only the word cat")

Declaring an unknown skill name, or a skill whose `requires:` names a tool missing from `ALL_SPECS`, raises at construction time. The system prompt is always `config.system_prompt or get_prompt(config)`. `get_prompt` renders the tools and skills sections from the config automatically, so the prompt can never describe a skill or tool that isn't bound.

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

Add the spec to `ALL_SPECS` in `agent_config.py` — its position there is its position in every profile's prompt.

### 2. Wrap it in a skill (usually) and register an `AgentConfig`

If the tool is part of a workflow, write a skill file in `src/agent/skills/skills_md/` that lists it under `requires:`, then declare the skill. Use `extra_tools` only for standalone tools:

```python
# src/agent/agent_config.py
default_registry.register(AgentConfig(
    "my-flag",
    skills=(*DEFAULT_SKILLS, "my-skill"),
    extra_tools=(my_standalone_tool_spec,),
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
from src.agent.agent_config import AgentConfig, AgentConfigRegistry, DEFAULT_PROFILE, DEFAULT_SKILLS
from src.agent.graph import fetch_zeno
from langgraph.checkpoint.memory import InMemorySaver

async def test_my_flag():
    registry = AgentConfigRegistry()
    registry.register(AgentConfig(DEFAULT_PROFILE, skills=DEFAULT_SKILLS))
    registry.register(AgentConfig("my-flag", skills=(*DEFAULT_SKILLS, "my-skill")))

    agent = await fetch_zeno(ff="my-flag", registry=registry, checkpointer=InMemorySaver())
    result = await agent.ainvoke(...)
    # assert my_tool was called, others were not
```

For a bespoke test persona with no skills or tools:

```python
registry.register(AgentConfig(
    "cat",
    system_prompt="Say only the word 'cat' in response to everything.",
))
```

See `tests/agent/test_feature_flag.py` for working examples.
