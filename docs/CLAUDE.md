# CLAUDE.md — Development Guidelines for project-zeno Backend

> **For Claude Code and AI-assisted development.**
> This document codifies the team's engineering practices as synthesised from PR review feedback (Feb–Apr 2026) and codebase analysis. Read it at the start of every development session.

---

## Overview

project-zeno is an LLM-powered geospatial agent built on:
- **FastAPI** — HTTP layer, streaming responses, quota enforcement
- **LangGraph** — ReAct agent orchestration (sequential tool calls, state machine)
- **LangChain / Anthropic / Gemini** — LLM backends with retry and fallback middleware
- **PostgreSQL + PostGIS** — Spatial queries, GADM/KBA/WDPA geometries, Alembic migrations
- **LanceDB** — Dataset vector search
- **Langfuse** — Observability and tracing
- **structlog** — Structured logging (console + rotating file)
- **Pydantic v2** — All schemas and settings; strict typing throughout
- **uv + ruff** — Package management and formatting

The backend lives in `src/` (agent, api, shared, ingest). Tests live in `tests/` (unit, tools, evals).

---

## Core Principles

Before writing any code, ask: does this reduce complexity or increase it? Is there an existing pattern in the codebase I should follow rather than inventing something new? These habits prevent the most common failure modes in AI-assisted development on this project.

1. **Lean system prompts.** Keep agent instructions concise and focused. The system prompt is not a catch-all specification document. Avoid bloating it with edge-case handling that belongs in code.
2. **System prompt examples must match implementation exactly.** If the code checks for `"global"` in a list of trigger words, the prompt example must use `"global"` — not `"Global World"`. Mismatched examples cause silent failures that are extremely hard to debug. (See PR #610.)
3. **Fix LLM behaviour with prompt instructions first, not schema changes.** When the LLM behaves incorrectly, add a targeted instruction to the relevant prompt step before considering a new Pydantic output field or ToolMessage restructure. Schema complexity without a root-cause fix compounds over time. (See PR #621.)
4. **Centralise dependencies.** DB calls, SQL queries, and external service interactions belong in clearly defined modules, not scattered across tool functions. (See PR #610 — Justin: "we should clean up these direct DB/SQL calls and try to keep our DB dependencies in one place".)
5. **Fail loudly.** Unknown model names, invalid config, and edge-case inputs should raise exceptions, not silently skip or return partial results. (See PR #602 — sunu: "This silently skips unknown model names with no warning at all. Compare this to `get_model()` above which raises `ValueError` loudly".)
6. **AI-readable code.** Write comments that explain *why*, not *what*. This is especially important for complex spatial logic, middleware interactions, and non-obvious design decisions — both humans and future AI sessions need this context.
7. **Test-first, dependency-free.** The priority is unit tests without any external dependencies. Only add DB-hitting or LLM-hitting tests when genuinely needed.
8. **Tool instructions must not assume a fixed call order.** When a tool's prompt uses data from a previous tool call, make that input optional. The agent can call tools in different orders depending on the query, and silent failures caused by missing upstream state are hard to debug. (See PR #614.)
9. **Cross-team architectural decisions need a design discussion before implementation.** Changes that affect the API contract, module structure, or the WRI/DevSeed boundary should be flagged and discussed before coding starts, even when the code change looks straightforward. (See PR #609.)

---

## Before You Code

This codebase is complex. A wrong-direction implementation takes significant effort to undo, particularly when it touches agent state, the streaming handler, or the frontend contract. Slowing down to align before coding is almost always faster than correcting afterwards.

### Clarify scope before writing anything

For anything beyond a trivial fix, ask one or two targeted questions before touching files. Prefer pointed questions that surface hidden constraints rather than open-ended ones — for example: "Should this raise or return `None` when the input is empty?" or "Does this need to be backwards-compatible with existing checkpoints?" If the requirements feel underspecified, say so and propose an interpretation to confirm rather than guessing.

### Propose and confirm before executing significant changes

For non-trivial work — new tools, state schema changes, middleware additions, architectural refactors — write a short plan (what you will change, why, what you will test, what the risks are) and wait for confirmation before modifying files. This is especially important when the change crosses module boundaries, affects the streaming handler, or has implications for the frontend API contract.

The team uses `/plan` to request this upfront planning step explicitly, and `/go` to confirm and proceed once the plan looks right. If you are unsure whether to proceed, surface the plan first.

### Explore before proposing

For architectural questions where multiple valid approaches exist, scan the relevant files and understand the existing patterns before proposing anything. Then offer the option most consistent with the codebase and note the trade-offs. Do not invent a new pattern when an existing one will do — look at neighbouring tools, services, or test files before drafting an approach.

### Prefer the simpler implementation

Once you have a working approach, ask whether a simpler version achieves the same goal. A targeted prompt instruction is simpler than a new Pydantic field. Prefix matching is simpler than a spatial join. A monkeypatched unit test is simpler than a DB integration test. If you are unsure whether a simpler path exists, use `/simplify` to prompt a second pass over the design before committing to it.

### Use sub-agents for complex exploration

When a task requires understanding several interconnected parts of the codebase before a proposal can be made — for example, tracing how a state field flows from a tool through the streaming handler to the frontend — use a sub-agent to do the exploration, then synthesise the findings before writing code. Do not conflate exploration and implementation in a single pass.

---

## Pull Request Discipline

### One problem per branch

Each branch should solve exactly one problem. If you notice a second issue while working, note it and open a separate branch — do not fix it here. Bundling multiple concerns onto one branch makes review harder, makes the git history harder to understand, and increases the risk of a reviewer asking for a split late in the process.

This applies even when the second fix looks small or obviously correct. "While I was in here I also..." is a signal to stop and ask whether it belongs on this branch.

### Keep PRs human-reviewable

A reviewer should be able to hold the entire change in their head. As a rough guide: if the diff is too large to review in a single sitting without losing the thread, it is too large. Prefer multiple focused PRs over one large one.

Concrete signs a PR needs splitting:
- It touches unrelated modules or layers (e.g., agent tools *and* API auth *and* a migration).
- The description requires more than two or three sentences to explain what changed.
- A reviewer would need to context-switch between different mental models to follow the diff.

### Resist the urge to clean up while you're there

When implementing a feature or fixing a bug, you will frequently notice adjacent code that could be improved — a function that could be renamed, a constant that should be extracted, a test that could be simplified. Resist the urge to include these in the same PR. Each cleanup is a separate, reviewable concern. If the cleanup is genuinely blocking your work, extract it into a preparatory commit on a separate branch and land it first.

### Keep the diff surface minimal

Change only what is required to solve the stated problem. Do not reformat unrelated lines, reorganise imports in files you are not otherwise touching, or restructure code that works correctly. Noise in the diff obscures the signal and slows review.

---

## Architecture

### Module Structure

```
src/
├── agent/
│   ├── graph.py          # ReAct agent creation, middleware stack, checkpointing
│   ├── state.py          # AgentState TypedDict — the single source of truth for state schema
│   ├── prompts.py        # WORDING_INSTRUCTIONS (neutral language, caution on adjectives)
│   ├── config.py         # AgentSettings (model selection, fallback models)
│   ├── llms.py           # LLM initialisation, MODEL_REGISTRY, fallback chains
│   └── tools/            # One subdirectory per tool (pick_aoi/, pick_dataset/, etc.)
├── api/
│   ├── app.py            # ~80 lines: app creation, middleware, router registration only
│   ├── routers/          # One file per resource (chat.py, threads.py, users.py, etc.)
│   ├── services/         # Business logic separated from HTTP (chat.py, auth.py, quota.py)
│   ├── auth/             # FastAPI auth dependencies (require_auth, optional_auth)
│   ├── schemas.py        # All Pydantic request/response schemas
│   └── data_models.py    # SQLAlchemy ORM models
├── shared/
│   ├── database.py       # Global connection pool (lazy init, lifespan-managed)
│   ├── config.py         # SharedSettings
│   └── logging_config.py # structlog setup
└── ingest/               # One-off data ingestion scripts (GADM, KBA, WDPA, etc.)
```

### Key Design Decisions

**Separation of concerns in `src/api/`:** `app.py` is deliberately thin (~99 lines). Route logic belongs in `routers/`, business logic in `services/`. This was formalised in PR #609. If in doubt about where new code belongs, follow this pattern.

**State schema lives in `state.py` exclusively.** `AgentState` is the TypedDict that all tools write to and read from. When adding new state fields, add them here with appropriate annotated reducers. The preferred pattern is typed containers (e.g., `AOISelection`) rather than flat keys — note that `state.py` currently still contains some legacy flat keys (`aoi: dict`, `subtype: str`) alongside the newer `aoi_selection: AOISelection`. When working in this area, prefer adding to typed containers and do not add new flat keys. API streaming handlers in `services/chat.py` must be updated in sync whenever the state schema changes — this is a common source of drift. (See PR #554 — Soumya caught several old flat keys left in the streaming handler.)

**Middleware stack (graph.py):** `ModelRetryMiddleware → ModelFallbackMiddleware → handle_tool_errors`. Retry config (max retries, backoff) lives in the middleware, not on the model itself — set `max_retries=0` on model instances to avoid double-retrying. When retry exhausts, it must raise, not swallow, so the fallback middleware can trigger. Add a comment whenever middleware layers interact non-obviously. (See PR #602.)

**Checkpointer uses a separate connection pool** from the main SQLAlchemy pool, because LangGraph's checkpointer requires `psycopg` (async) while SQLAlchemy uses a different driver. This is intentional — don't consolidate them. (See `graph.py` comment.)

**Architectural decisions involving cross-team work** (WRI ↔ DevSeed) need a design discussion before implementation, even if the code change looks straightforward. Flag this early. (See PR #609 — Gary: "I recommend pausing on this until we have further design sessions".)

---

## Testing

### The Three-Tier Strategy

The team follows a deliberate pyramid. Before adding tests, ask yourself which tier fits:

**Tier 1 — Unit tests (no dependencies)** in `tests/unit/`
- No database, no LLM, no network.
- These are the priority. Write these first. They run in CI on every push.
- Test pure logic: argument parsing, SQL string construction, limit enforcement, state reducers.
- Use `monkeypatch` to replace any functions that would call DB or external services.

**Tier 2 — Tool tests (DB required)** in `tests/tools/`
- Hit the real test database (via `TEST_DATABASE_URL`).
- Use replay fixtures (`AOI_PICK_AOI_FIXTURES_MODE=replay`) where available to avoid requiring a live spatial DB in CI.
- These run on PRs that add the `run-tools-tests` label.

**Tier 3 — Evals**
- **In-repo** (`tests/evals/`): turn-based, fast evals testing individual LLM steps. Run locally when changing system prompts or tool instructions.
- **gnw-evals** (separate repo): task-based, end-to-end evals against staging. Run before major releases or after significant agent changes.

The goal is to push as much as possible into Tier 1. Only use LLM-dependent tests where the LLM is genuinely what's being tested.

### Test File Naming and Location

**Test file paths must mirror source file paths exactly.**

| Source file | Test file |
|---|---|
| `src/agent/tools/pick_aoi/tool.py` | `tests/unit/agent/tools/pick_aoi/test_tool.py` |
| `src/agent/tools/pick_dataset/tool.py` | `tests/unit/agent/tools/pick_dataset/test_tool.py` |
| `src/api/routers/chat.py` | `tests/api/test_chat.py` |

Do not create a new test file per bug or feature. Consolidate into the appropriate matching file. (Justin, PR #630: "I would also avoid making a test file just for every bug — FastAPI standard is test file path should match path of file it's testing".)

### Writing Good Unit Tests

**Override DB fixtures at the unit level.** `tests/unit/conftest.py` overrides the root `async_session_maker` fixture so unit tests never require a database. If your test starts requiring a DB to run, it belongs in `tests/tools/`, not `tests/unit/`.

**Do not test internal implementation details.** If you refactor the internals but the observable behaviour is the same, the test should still pass. Testing specific SQL strings (e.g., which PostGIS function is used internally) is usually wrong. Test the outputs and side-effects, not the mechanism. (Justin, PR #630: "I don't think you need to specifically test this since it was just an internal change".)

**Verify your test actually exercises the code path you think it does.** A test that silently falls through to the wrong code path and passes is worse than no test. Add an assertion that would fail if the key function were never called. (sunu, PR #610: "I don't think this test is calling `handle_global_request` at all. They're silently going through the normal AOI picking flow." — yellowcap: "Good catch. That is what you get for letting agents write your tests.")

**Test naming should describe the scenario, not the implementation.** Gary (PR #600) suggested refinements to test names — they should communicate intent, not mechanics. Use `test_global_query_returns_all_countries` not `test_handle_global_request_calls_query`.

### Write Failing Tests Before the Fix

When fixing a bug, commit the failing test first (before the fix) so the test demonstrably captures the problem. This makes the intent of the test clear and prevents the fix from accidentally making a flawed test pass vacuously. (See PR #621 — "Add failing tests" committed first, then the fix applied.) This also gives reviewers confidence that the test is actually exercising the bug.

### Common Testing Pitfalls

- **AI-generated tests need extra scrutiny.** They frequently exercise the wrong code path or mock at the wrong level. Always trace through the test manually to confirm it hits what you think.
- **Monkeypatch at the correct module.** If `pick_aoi/tool.py` imports `query_aoi_database` at the top, patch `src.agent.tools.pick_aoi.tool.query_aoi_database`, not `src.agent.tools.pick_aoi.global_queries.query_aoi_database`. Wrong patch target = test passes vacuously. (sunu, PR #610.)
- **Session-scoped fixtures + function-scoped cleanup.** The test client is session-scoped for efficiency; `clear_tables()` runs after each test to reset state.

---

## System Prompts and Agent Configuration

### Philosophy

The system prompt lives in `src/agent/graph.py` (`get_prompt()`) with wording guidance in `src/agent/prompts.py` (`WORDING_INSTRUCTIONS`).

Keep prompts **lean and focused**. The prompt is not a substitute for proper code handling. If a behaviour can be enforced in Python, enforce it in Python and omit it from the prompt.

Use examples sparingly. When you do use them, **every example must be verifiable against the current code**. If the prompt says `place="Global World"` but the code checks for `"global"` in `GLOBAL_TRIGGER_WORDS`, the example is wrong and will cause the LLM to produce inputs that silently fail the code-level check.

### Wording Instructions (`prompts.py`)

The `WORDING_INSTRUCTIONS` block enforces neutral scientific language:
- Avoid strong adjectives without scientific justification ("overwhelming", "critical", "significant").
- Use precise statistical terminology.
- Mirror the user's language — always respond in the language the user is writing in.
- When adding new datasets or capabilities, update wording guidance if the dataset has specific framing requirements.

### When to Update the System Prompt

Update the prompt when:
- A tool's parameter schema changes (examples must stay in sync).
- A new tool is added or removed from the agent.
- A capability boundary changes (e.g., "only supports country-level queries for global requests").
- The wording instructions need a new constraint based on user feedback.
- The LLM is exhibiting a behaviour problem that a prompt instruction can fix directly.

Do not update the prompt when the change can be handled in code.

### Fixing LLM Behaviour: Prompt First, Schema Last

When the LLM behaves incorrectly (wrong language, wrong field, wrong tone), the first question to ask is whether a prompt instruction can fix it. Adding a new Pydantic output field or restructuring a ToolMessage to work around an LLM tendency is usually the wrong move — it adds schema complexity without addressing the root cause.

Preferred pattern: add a targeted instruction to the relevant prompt step (e.g., "use the language of the query, not the language of any place mentioned in the query"). Only restructure schemas if the instruction approach genuinely cannot work. (See PR #621 — Dan: "the solution is not the right one in my opinion... this should stay as part of the pick reason, not an additional output field".)

### Preserve ToolMessage Content the Agent Depends On

Do not strip fields from ToolMessage output based on a hypothesis about what is causing a behaviour problem. The `reason` field in `pick_dataset` ToolMessage is intentional context for the downstream agent — removing it would leave the agent without selection rationale. If you suspect a field is causing issues (e.g., language pollution), fix the instruction for generating that field rather than removing it. (See PR #621.)

---

## Error Handling and Logging

### Logging

Uses `structlog` via `src/shared/logging_config.py`. Get a logger with:

```python
from src.shared.logging_config import get_logger
logger = get_logger(__name__)
```

Available levels: `debug`, `info`, `warning`, `error`, `exception`.

**Always use `logger.exception(...)` (or `logger.error(..., exc_info=True)`) when catching exceptions** — not bare `logger.error(...)`. Without `exc_info`, the traceback is lost and debugging becomes very hard. (sunu, PR #602: "let's include `exc_info=True` or use `logger.exception`, otherwise the traceback is lost".)

```python
# Wrong — loses the traceback
except Exception as e:
    logger.error(f"Model {model} failed: {e}")

# Right — preserves the traceback
except Exception as e:
    logger.exception(f"Model {model} failed")
```

### Fail Loudly

Unknown or invalid inputs should raise, not silently skip:

```python
# Wrong — silently ignores unknown model names
if name in MODEL_REGISTRY:
    models.append(MODEL_REGISTRY[name])

# Right — raise on unknown, or at minimum warn loudly
if name not in MODEL_REGISTRY:
    raise ValueError(f"Unknown model name: {name!r}")
```

If you intentionally want to skip with a warning, log at `warning` level with enough context to debug.

### Configuration Validation

Use Pydantic `@field_validator` on settings fields that accept constrained values (e.g., model names, log levels). This catches misconfiguration at startup rather than at runtime. (sunu, PR #602: "we should add validators for these config fields to make sure the model names are valid and in the expected format".)

### HTTP Error Handling

Raise `HTTPException` from FastAPI for all HTTP errors. Custom application exceptions wrap at the service layer, not the router layer.

---

## Code Style

### Formatting and Linting

- **Formatter:** ruff (enforced by pre-commit)
- **Line length:** 79 characters
- **Quotes:** double quotes
- **Import order:** stdlib → third-party → local (ruff `-I` flag)

Run `pre-commit run --all-files` before pushing. The CI will catch violations, but it's faster to catch them locally.

### Type Hints

Type hints are **mandatory** on all function signatures (parameters and return types). Use Pydantic v2 patterns throughout:

```python
# v2 style — use these
model_config = ConfigDict(from_attributes=True, alias_generator=alias_generators.to_camel)

@field_validator("field_name", mode="before")
@classmethod
def validate_field(cls, v): ...

# v1 style — do not use
class Config:
    orm_mode = True
```

### Naming Conventions

| Thing | Convention | Example |
|---|---|---|
| Functions | `snake_case` | `query_aoi_database` |
| Private functions | `_snake_case` | `_antimeridian_bbox_sql` |
| Classes | `PascalCase` | `AgentState`, `ChatRequest` |
| ORM models | `PascalCase` + `Orm` suffix | `UserOrm`, `ThreadOrm` |
| Constants | `UPPER_SNAKE_CASE` | `SUBREGION_LIMIT`, `MODEL` |
| DB tables | plural lowercase | `users`, `threads`, `daily_usage` |
| DB columns | `snake_case` | `created_at`, `user_id` |
| API endpoints | lowercase, underscores | `/api/custom_areas`, `/api/threads` |
| Env vars | `UPPER_SNAKE_CASE` | `DATABASE_URL`, `LOG_LEVEL` |
| Alembic migrations | `{revision_id}_{human_readable}.py` | `32753a3e09e0_add_user_profile_fields.py` |

### Use Constants, Not Magic Values

Hardcoded numbers or strings that appear in both code and user-facing messages should be named constants:

```python
# Wrong
"For optimal performance, please limit results to under 50 subregions"

# Right
SUBREGION_LIMIT = 50
f"For optimal performance, please limit results to under {SUBREGION_LIMIT} subregions"
```

Gary specifically flagged this in PR #600 and it was one of the cleanups accepted in that PR.

---

## Database and SQL Patterns

### PostGIS Queries

- **Centralise DB calls.** Tool functions should delegate spatial queries to dedicated query functions, not inline SQL. (Justin, PR #610: "we should keep our DB dependencies in one place".)
- **For GADM hierarchical lookups, use prefix matching** (`gadm_id LIKE 'RUS.%'`) rather than `ST_CoveredBy` against the full country geometry. `ST_CoveredBy` against Russia's geometry times out (5+ minutes for 83 oblasts). Non-GADM sources (KBA, WDPA, Landmark) still need `ST_CoveredBy` since they lack the hierarchical ID. (PR #630.)
- **Validate complex SQL changes in staging** before treating unit tests as sufficient. SQL correctness for edge-case geometries (antimeridian crossings, multi-polygon countries) is hard to cover with pure unit tests.
- **Antimeridian handling:** Use `ST_ClipByBox2D` against east/west half-planes to compute crossing bboxes. A naive `ST_XMin` / `ST_XMax` on geometries spanning the antimeridian returns a ~360° bbox. (PR #630.)

### Alembic Migrations

- One migration per logical change.
- Always implement `downgrade()`, not just `upgrade()`.
- Test your migration on a copy of production data before merging if it modifies existing rows.
- Alembic's env.py converts async PostgreSQL URLs to sync for migration execution — this is intentional.

### Connection Pools

- **Main pool:** SQLAlchemy async (`AsyncEngine` + `async_session_maker`), managed via `shared/database.py` with lifespan startup/shutdown.
- **Checkpointer pool:** Separate `AsyncConnectionPool` using `psycopg` directly — required by LangGraph's checkpointer. Do not consolidate with the main pool.
- Use `NullPool` in test fixtures to avoid connection leaks between tests.

---

## Agent Orchestration (LangGraph)

### Tool Definitions

Tools are defined with `@tool()` from `langchain_core.tools` and return `Command` objects for state updates. Registered as a list in `graph.py` and passed to `create_agent()`.

When adding a new tool:
1. Create a new subdirectory in `src/agent/tools/` with `tool.py` (and helpers as needed).
2. Add the tool to the tool list in `graph.py`.
3. Update the system prompt to describe the tool and its expected usage with a concrete example.
4. Ensure the example in the prompt exactly matches the tool's parameter schema.
5. Add unit tests in `tests/unit/agent/tools/<tool_name>/test_tool.py`.

### Sequential Tool Calls

The agent is configured for **sequential tool calls only** — never parallel. This is enforced in the system prompt. Do not change this without a design discussion; parallel tool calls introduce state consistency issues.

### Tool Prompt Instructions Must Not Assume Call Order

When a tool's prompt references data from a previous tool call (e.g., AOI bounding box passed into `pick_dataset`), make that input optional rather than required. Tools can be called in different orders depending on the user's query, and a tool that silently fails or behaves wrongly when upstream state is absent is harder to debug than one that degrades gracefully. (See PR #614 — Dan: "I would suggest that the additional instructions are only added to the pick dataset LLM call if the AOI is available, skip otherwise. Like this the user can just ask about some datasets and get them on screen without having to commit to a place.")

### State Management

`AgentState` (in `state.py`) is the authoritative schema. Key fields:
- `messages`: accumulates all messages via `add_messages` reducer
- `aoi_selection`: typed container for selected areas (not flat `aoi`, `aoi_name` keys)
- `statistics`: list with `operator.add` reducer to accumulate across tool calls

When modifying state schema:
1. Update `state.py` first.
2. Update any tools that read or write the changed fields.
3. Update the streaming handler in `services/chat.py` — this is the most common place to miss.
4. Ensure API backwards compatibility if the frontend consumes the field. (Soumya, PR #554: "stream_chat() still references the old state keys in a few places".)

---

## Dependencies and Tooling

### Package Management

Use `uv` for all package operations. All dependencies are pinned to exact versions in `pyproject.toml`. Python version is pinned to `==3.12.8`.

```bash
uv add <package>       # adds and updates uv.lock
uv sync                # installs from uv.lock
```

Do not use `pip install` directly in the project.

### Pinning Strategy

All production dependencies use exact version pins (`==`). This is intentional — it prevents surprise breakage from upstream changes. When upgrading a library (e.g., LangGraph, LangChain), create a dedicated PR with a clear description of what changed and why.

### Key Libraries to Know

| Library | Role | Notes |
|---|---|---|
| `langgraph` | Agent orchestration | Pin carefully — API changes frequently |
| `langchain-core` | Tool/message primitives | |
| `fastapi[standard]` | HTTP framework | Standard includes uvicorn, httpx |
| `pydantic v2` | Schemas and settings | Use v2 style throughout |
| `sqlalchemy 2.0` | ORM + async queries | Declarative style |
| `alembic` | DB migrations | Async URL converted to sync |
| `structlog` | Logging | Always use `get_logger(__name__)` |
| `langfuse` | LLM observability | Callback handler passed in graph config |
| `ruff` | Lint + format | 79 chars, double quotes, `E,F,W,Q,I` rules |
| `pytest` + `asyncio_mode=auto` | Test runner | Session-scoped async fixtures |

---

## Documentation and ADRs

### Current State

There are currently no formal ADRs in this repository. Design rationale is captured in PR descriptions, inline comments, and `docs/`:
- `docs/AGENT_ARCHITECTURE.md` — LangGraph architecture with Mermaid diagrams
- `docs/CLI.md` — User management CLI
- `docs/DEPLOYMENT_PHASES.md` — Deployment guidance

### When to Write an ADR

The team does not yet have a formal ADR process, but the following decisions warrant written rationale (in a PR description at minimum, ideally in `docs/adr/`):
- Choosing one external library over another
- Non-obvious architectural choices (e.g., why two separate DB pools)
- Performance trade-offs (e.g., why `gadm_id LIKE` prefix matching instead of `ST_CoveredBy`)
- Changes to the agent's evaluation strategy

### Inline Comments

Write comments that explain *why*, not *what*. The code itself explains what. Examples of good comments already in the codebase:

```python
# Use a separate connection pool for the checkpointer — LangGraph requires
# psycopg (async) which is a different driver from SQLAlchemy's asyncpg.
# Consolidating the pools would break one or the other.
```

This approach is especially important for future AI-assisted development sessions — without the "why", Claude Code will likely refactor away the decision.

---

## Common Review Feedback

### What tends to slow PRs down

**Tests hitting the DB when they don't need to.** Unit tests in `tests/unit/` must not require a database. If your test imports a function that internally uses `async_session_maker`, either monkeypatch the dependency or move the test to `tests/tools/`.

**Test file placed in the wrong location or with the wrong name.** Follow the mirror-path convention strictly. Reviewers will ask you to move the file.

**System prompt examples that don't match code.** Any example you add to the prompt will be taken literally by the LLM. If the example uses a value that doesn't appear in the code's trigger list or schema, the agent will produce inputs that silently fail downstream.

**Silent failures in error paths.** Using `logger.error` without `exc_info=True`, skipping unknown config values without logging them, or using `on_failure="continue"` in middleware without documenting what gets passed downstream. Reviewers will ask you to fail loudly or add a comment.

**Magic numbers and hardcoded strings.** If a value appears in both code logic and a user-facing message, make it a constant. Gary flagged this in PR #600.

**Scattered DB calls in tool functions.** Direct SQL or DB calls should be extracted to dedicated query functions and centralised. Justin flagged this in PR #610.

**Non-blocking UX feedback deferred to follow-up tickets.** When a PR introduces a change with UX or design implications (e.g., changes to chart output schema), flag it for design review but don't block the merge on it. De-scope non-blocking feedback into a follow-up Jira ticket. (See PR #622 — Gary: "Can we de-scope Fausto's feedback and the color issue? Or is that enough to hold this PR up?")

**PR titles for feature work should include the Jira ticket ID.** Use the format `PZB-NNN: Description` for feature PRs. Gary retroactively updated PR #622's title to add the ticket prefix — treat this as the expected convention.

**Draft PRs are fine for early feedback.** If tests or docs aren't ready, open as a draft and mark ready for review once they are. Note clearly in the PR description what is incomplete.

### What reviewers approve quickly

- PRs with a clear, structured description that explains *what changed*, *why*, and *what was tested*.
- Unit tests that are genuinely dependency-free.
- State schema changes that update all dependent code (tools, streaming handlers) atomically.
- Config changes that use Pydantic validators rather than relying on runtime failures.
- PRs that are scoped to one logical change — large PRs that bundle multiple concerns get more scrutiny.

---

## Maintenance Notes

- **Last updated:** 2026-04-23
- **PR scan window:** 2026-02-01 to 2026-04-23 (PRs #554–#633, all 39 merged PRs reviewed)
- **Key reviewers considered:** Gary Tempus (gtempus), Dan Wiesmann (yellowcap), Soumya Ranjan Mohanty (srmsoumya), Justin Terry (jterry64)
- **Next recommended update:** After the next sprint cycle, or after any significant change to the testing strategy, agent state schema, or system prompt philosophy.

Reference PRs that exemplify good patterns:
- [#600](https://github.com/wri/project-zeno/pull/600) — Test organisation, unit-first philosophy, constants for magic values
- [#609](https://github.com/wri/project-zeno/pull/609) — Splitting a monolithic module cleanly; good PR description structure
- [#602](https://github.com/wri/project-zeno/pull/602) — Middleware layering with clear interaction documentation
- [#621](https://github.com/wri/project-zeno/pull/621) — Prompt instruction fix preferred over schema change; failing tests before fix
- [#630](https://github.com/wri/project-zeno/pull/630) — Unit-first spatial SQL testing; GADM prefix matching over ST_CoveredBy