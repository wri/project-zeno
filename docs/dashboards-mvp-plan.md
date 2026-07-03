# Dashboards MVP — implementation plan (backend)

*Status: agreed design, ready to implement. Written 2026-07-02 after the insights
hardening on `feat/insights-musings` (commit 6d8b677). This document is
self-contained: a fresh session can implement from it without prior context.*

## Context

A **dashboard** is a persistent, curated collection of insights, layers and
AOIs — a complement to the map/explorer view. The design mock ("Paraná,
Brazil") shows: a dashboard titled by its area; widgets that each toggle
between map/chart/table views with "show params" / "view how this was
generated" / download; an "Add to dashboard" toggle on analyses in the chat
sidebar; dashboard-level Share/Export/Subscribe actions; and an AI-assistant
panel to "refine this dashboard".

**MVP is a single-area dashboard** (a country, a state, a protected area), but
the schema must extend to **multiple areas for portfolio monitoring** without
migration. Scope here is backend only: models, repositories, API, agent tools.

### Existing building blocks (do not rebuild these)

- **Insights are standalone artifacts**: `InsightOrm` + `InsightChartOrm`
  (`src/api/data_models.py`) persist charts, narrative and provenance
  (`statistics_ids`). A dashboard widget only *references* an insight.
- **AOIs have a canonical address**: `AreaOfInterest(source, src_id, subtype)`
  (`src/api/schemas.py`), sources `gadm|custom|wdpa|kba|landmark`. Custom areas
  are rows in `custom_areas` referenced as `source="custom"`. Dashboards store
  these references, never geometry.
- **Deterministic analysis**: `POST /api/analyze` (`src/api/routers/analyze.py`)
  turns (AOIs + dataset_id + dates) into a new insight via a background job.
  This is the future refresh/alerts mechanism — nothing to build now.
- **Access rules**: `src/api/repositories/insight_access.py` centralizes
  own+public read / owner-only edit. Dashboards get twin functions.
- **Agent harness**: everything is a tool on one agent (`src/agent/graph.py`);
  tools export `SPEC = ToolSpec(...)` (`src/agent/tool_spec.py`) and are added
  to profiles in `src/agent/agent_config.py` (`EXPERIMENTAL_SPECS` for new
  tools). Workflows live as markdown skills in
  `src/agent/skills/skills_md/*.md` with `requires:` frontmatter.
- **Frontend contract**: tools that change persisted artifacts attach
  `response_metadata={"msg_type": ..., "<id-field>": ...}` to their ToolMessage
  so the frontend refetches (see `search_insights.py` / `update_insight_display.py`
  using `msg_type: "insight_updated"`).

### Decisions already made (don't re-litigate)

1. **Multi-AOI join table from day one**; the single-area constraint is API
   validation (`max_length=1`), not schema.
2. **Access**: own + public read, owner-only edit — same as insights.
   **Publishing a dashboard cascades `is_public=True` to its referenced
   insights** (otherwise a public dashboard renders empty for viewers).
   Read-through access was considered and deferred.
3. **Agent = primitive tools + a skill, no subagent.** `create_dashboard` and
   `add_to_dashboard` are deterministic DB writes; orchestration ("build me a
   dashboard for X") is a markdown skill. A "dashboard composer" subagent is
   deferred until there is a real multi-stage LLM pipeline to hide (mirrors
   the insights split: primitives + Analyst).
4. Widgets don't store chart data, geometry, or tile URLs — only references
   plus presentation config. *Superseded for map widgets (2026-07-03):
   their config snapshots the resolved layer including tile URLs, mirroring
   the `dataset`/`imagery` state updates the explorer already renders.*

## 1. Data model + migration

Add to `src/api/data_models.py`, following `InsightOrm`/`InsightChartOrm`
conventions (UUID PK via `gen_random_uuid()`, `String` user FK, JSONB with
server defaults):

**`dashboards`** (`DashboardOrm`)
- `id` UUID PK
- `user_id` String FK→users, **NOT NULL** (dashboards are always owned)
- `name` String NOT NULL
- `description` String nullable
- `is_public` Boolean NOT NULL server_default false
- `created_at` / `updated_at` DateTime (`onupdate=datetime.now`, like
  `CustomAreaOrm`)
- relationships: `aois` → DashboardAoiOrm, `widgets` → DashboardWidgetOrm,
  both `cascade="all, delete-orphan"`, ordered by `position`

**`dashboard_aois`** (`DashboardAoiOrm`)
- `id` UUID PK, `dashboard_id` UUID FK→dashboards NOT NULL
- `source` String NOT NULL, `src_id` String NOT NULL, `subtype` String NOT NULL
- `name` String NOT NULL (display name, denormalized like
  `StatisticsOrm.aoi_names`)
- `position` Integer NOT NULL server_default 0
- UniqueConstraint(`dashboard_id`, `source`, `src_id`)

**`dashboard_widgets`** (`DashboardWidgetOrm`)
- `id` UUID PK, `dashboard_id` UUID FK→dashboards NOT NULL
- `position` Integer NOT NULL server_default 0
- `widget_type` String NOT NULL — `"insight"` | `"map"` (plain String like
  `JobOrm.type`; validate in Pydantic, not the DB)
- `insight_id` UUID FK→insights **nullable**, `ondelete="CASCADE"` — deleting
  an insight silently drops widgets that reference it
- `config` JSONB NOT NULL server_default `'{}'` — presentation only:
  `default_view` ("map"|"chart"|"table"), optional `title` override; for map
  widgets: `dataset_id`, `start_date`/`end_date`, optional viewport. Leave room
  for a future `refresh` key (relative date window) — do not implement it.
- `created_at` DateTime

Migration: new revision in `db/alembic/versions/` (alembic config at
`db/alembic.ini`, run alembic from the `db/` directory). Follow the style of a
recent revision file there.

## 2. Access rules — `src/api/repositories/dashboard_access.py`

Twin of `insight_access.py` (same docstring discipline, same semantics):
`visible_dashboards_clause(user_id)`, `is_visible_to_user(row, user_id)`,
`is_editable_by_user(row, user_id)`. Missing/unset user id ⇒ only public rows
visible, nothing editable. Unit-test as pure functions (copy
`tests/unit/api/test_insight_access.py`).

## 3. Repository — `src/api/repositories/dashboard_writer.py`

Follow `insight_writer.py` conventions (`get_session_from_pool`, structlog
`logger.info` events, malformed UUIDs return None/False rather than raise):

- `create_dashboard(*, user_id, name, description=None, aois: list[dict]) -> str`
- `get_dashboard(dashboard_id) -> Optional[DashboardOrm]` (selectinload aois +
  widgets; caller applies access check)
- `add_widget(dashboard_id, *, widget_type, insight_id=None, config=None, position=None) -> Optional[str]`
  (position defaults to max+1)
- `update_widget(widget_id, *, position=None, config=None) -> bool`
- `remove_widget(widget_id) -> bool`
- `update_dashboard(dashboard_id, *, name=None, description=None) -> bool`
- `delete_dashboard(dashboard_id) -> bool`
- `set_dashboard_public(dashboard_id, is_public) -> bool` — when setting True,
  also set `is_public=True` on all insights referenced by its widgets
  (decision 2), in the same transaction.

Ownership checks live in the callers (router/tools) via `dashboard_access`,
same split as insights.

## 4. API — `src/api/routers/dashboards.py`

Mirror `src/api/routers/insights.py` (auth dependencies from
`src/api/auth/dependencies.py`, `_row_to_response` mapping helpers, 404 for
not-found *and* not-owned). Register the router wherever the others are
included (`src/api/app.py`).

- `POST /api/dashboards` — `require_auth`. Body: `name?` (defaults to the
  first AOI's name), `description?`, `aois: List[DashboardAoi]` with
  **`min_length=1, max_length=1`** (the MVP single-area constraint — lift
  later by raising max_length). `DashboardAoi` = `AreaOfInterest` + `name`.
- `GET /api/dashboards` — own dashboards, newest first.
- `GET /api/dashboards/{id}` — `optional_auth`; own or public (mirror
  `get_insight`, including admin/superuser override). Response expands widgets
  with their insight payloads reusing the insights `_row_to_response` shape so
  the frontend renders widgets like insights.
- `PATCH /api/dashboards/{id}` — rename/description, owner only.
- `PATCH /api/dashboards/{id}/public` — mirror
  `PATCH /api/insights/{id}/public`; cascades to insights per decision 2.
  Response should list the insight ids it publicized.
- `POST /api/dashboards/{id}/widgets` — body: `widget_type`,
  `insight_id?`, `config?`, `position?`. Validate: insight widgets need an
  `insight_id` the user can see (`insight_access.is_visible_to_user`).
- `PATCH /api/dashboards/{id}/widgets/{widget_id}` — reorder/config.
- `DELETE /api/dashboards/{id}/widgets/{widget_id}` and
  `DELETE /api/dashboards/{id}` — owner only.

Schemas in `src/api/schemas.py` next to the insight response models.

## 5. Agent integration (experimental profile only)

**Tools** — copy the structure of `src/agent/tools/search_insights.py`
(module docstring, private DB helpers, pure helpers separated, `Command` +
ToolMessage return, `SPEC` at the bottom, user id from
`structlog.contextvars.get_contextvars().get("user_id")`):

- `src/agent/tools/create_dashboard.py` —
  `create_dashboard(name?, tool_call_id)`: AOIs default from
  `state["aoi_selection"]` (`AOISelection` in `src/agent/state.py`: `{name,
  aois: list[dict]}`); error ToolMessage if no AOI in state. Returns success
  ToolMessage with `response_metadata={"msg_type": "dashboard_updated",
  "dashboard_id": ...}` and puts `dashboard_id` into state (add the key to
  `AgentState`).
- `src/agent/tools/add_to_dashboard.py` —
  `add_to_dashboard(insight_id?, dashboard_id?, tool_call_id)`: insight
  defaults to `state["insight_id"]`; dashboard defaults to
  `state["dashboard_id"]` or `view_context["dashboard_id"]`. Owner-only via
  `dashboard_access.is_editable_by_user`; referenced insight must be visible
  via `insight_access.is_visible_to_user`. Same `dashboard_updated` metadata.

Register both in `EXPERIMENTAL_SPECS` (`src/agent/agent_config.py`).

**Skill** — `src/agent/skills/skills_md/dashboard.md` with frontmatter
`requires: create_dashboard, add_to_dashboard` (skills are only advertised
when their tools are in the profile — see `src/agent/skills/loader.py`).
Content: when to create vs. reuse the dashboard in view/state; the compose
loop (per topic: `pick_aoi` if needed → analyze pipeline → `generate_insights`
→ `add_to_dashboard`); recall flow (`search_insights` → `add_to_dashboard`);
stop conditions (don't keep adding widgets unprompted). Look at
`skills_md/show-imagery.md` and `analyze.md` for tone/format.

**view_context** — extend the comment on `ChatRequest.view_context`
(`src/api/schemas.py`) with `"dashboard_id": "<uuid>"` and `page: "dashboard"`.
Extend `src/agent/tools/inspect_view_context.py`: when `dashboard_id` is
present, load the dashboard (visibility via `dashboard_access`), print name,
area(s) and its widgets — reuse `format_insights` for the insight content.

**Routing** — add one line to the routing table in the `graph.py` system
prompt for "add this to my dashboard / build a dashboard for X" → read skill
`dashboard`.

## 6. Tests

Follow the two established patterns:

- **Pure/unit**: `tests/unit/api/test_dashboard_access.py` (copy
  `test_insight_access.py` parametrization).
- **Tool unit tests**: `tests/agent/test_create_dashboard.py`,
  `test_add_to_dashboard.py` — SimpleNamespace fakes + `AsyncMock`-patch the
  repository functions, invoke `tool.coroutine(...)`, assert ToolMessage
  content/status/`response_metadata` and state updates (copy
  `tests/agent/test_search_insights.py` style).
- **DB integration**: `tests/agent/test_dashboards_db.py` — the autouse
  `test_db_pool` fixture in `tests/conftest.py` points
  `get_session_from_pool()` at the test DB; bind the user with
  `structlog.contextvars.bound_contextvars(user_id=user.id)` (see
  `tests/agent/test_insights_db.py` for the whole pattern, incl. `user` /
  `user_ds` fixtures). Cover: create + single-area enforcement happens in API
  (not repo); widget add/reorder/remove; owner-only edit; publish cascades
  `is_public` to referenced insights; deleting an insight cascades widget
  removal; deleting a dashboard leaves insights intact.
- **API tests**: `tests/api/test_dashboards.py` using `client` +
  `auth_override` fixtures (copy `tests/api/test_insights.py`): 401/404
  semantics, public read, single-area validation (2 AOIs → 422), widget
  endpoints.

## 7. Verification

1. `uv run pytest tests/unit tests/agent tests/api/test_dashboards.py tests/api/test_insights.py`
   (test DB via docker compose service `test-db`, port 5434, env in `.env`).
   Note: `tests/agent/test_graph.py::test_agent_for_disturbance_alerts_for_brazil`
   is a known-flaky live-LLM test — rerun before blaming a change.
2. Pre-commit hooks run ruff/ruff-format/mypy and bump the CalVer version in
   `pyproject.toml` on commit; if the first commit attempt fails with
   "files were modified", `git add` the hook changes and commit again.
3. Manual smoke via the agent CLI (`src/agent/cli.py`) on the experimental
   profile: run an analysis, then "create a dashboard for this area", then
   "add this insight to the dashboard"; verify rows and
   `GET /api/dashboards/{id}`.

## Out of scope (deliberately)

- Refresh / relative date windows (future `config.refresh` + re-run
  `POST /api/analyze`, swap `insight_id`).
- Subscribe-to-alerts, PDF export.
- Portfolio UX (schema already supports multiple `dashboard_aois` rows).
- Read-through access for private insights on public dashboards.
- A dashboard-composer subagent.
