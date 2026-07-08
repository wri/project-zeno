# View pages — how the agent knows which surface the user is on

*Status: implemented 2026-07-03 on `feat/dashboards-mvp`, as a follow-up to
`docs/dashboards-mvp-plan.md`. The app is growing a second surface (the
dashboard page, toggled in the top bar, next to the map explorer); this
records how page scope is communicated to the agent and where to add the
next page.*

## The problem

The frontend sends an ambient view snapshot with every chat request
(`ChatRequest.view_context`), including a `page` value. Before this change
the backend treated `page` as an opaque string: the session block echoed
"`map page`" and `inspect_view_context` dumped the snapshot, but nothing
told the agent what a page *means* — what the user can do there, what
"this" / "here" refer to, or which tools are the natural defaults. Each new
surface (dashboard, and whatever comes next) would have made that gap wider.

## The design: one registry, two renderings

**`src/agent/view_pages.py`** is the single place page semantics live. Each
registered page (`map`, `dashboard`) defines the same knowledge in two
shapes, matching the two channels the agent already has:

1. **Session line (every model call).** `SessionContextMiddleware` prepends
   a `[Session — date]` block before each model call; its `View:` line is
   now rendered by the page's `session_line`. This is the cheap, ambient
   layer — the agent always knows where the user is without a tool call.

   ```
   View: dashboard 'Paraná' (5c9f…) — a persistent collection of insight
   widgets for one area. 'This dashboard' = the one on screen;
   add_to_dashboard targets it by default (call inspect_view_context for
   its area and widgets).
   ```

2. **`# Current surface` prompt section (per request).** `stream_chat`
   passes `view_context["page"]` to `fetch_zeno(page=...)` →
   `get_prompt(config, page=...)`, which inserts the page's
   `prompt_section` — the behavioral/routing hints ("'add this' means
   add_to_dashboard", "new analyses default to the dashboard's area").
   The agent is rebuilt per request, so switching pages mid-thread simply
   produces the matching prompt on the next request.

Deep content stays where it was: the full snapshot (viewport, layer lists,
widget contents) is only returned by the `inspect_view_context` tool, which
loads and formats dashboards and insights from the DB on demand.

## The frontend contract

`view_context` remains frontend-owned and free-form. The parts the backend
assigns meaning to:

- `page`: `"map"` | `"dashboard"` (`"report"` is sent today but has no
  registered semantics yet). Unknown values degrade gracefully — generic
  breadcrumb, no prompt section.
- On the dashboard page: `dashboard_id` (used by `add_to_dashboard` as the
  default target and by `inspect_view_context` to load the dashboard) and
  optionally `dashboard_name` (lets the session line name the dashboard
  without a DB read; omitted → the line falls back to the id).

## Deliberately not done: eager scope hydration

We do **not** pre-fill agent selections from the view (e.g. setting
`aoi_selection` from the dashboard's area before the agent runs). The
`ChatRequest.view_context` comment records this ADR: ambient view state is
reference material, unlike `ui_context` (deliberate user actions), and is
never turned into a message or merged into selections. Eager merging breaks
down as soon as a user browses one dashboard while chatting about something
else. Scope becomes *actionable* through tool defaulting on explicit intent
instead: `add_to_dashboard` already defaults to `view_context["dashboard_id"]`;
if "analyze deforestation" on a dashboard page proves to need it, `pick_aoi`
could similarly learn to consult the dashboard's area — revisit then.

## Adding the next page

1. Register a `ViewPage` in `src/agent/view_pages.py`: a `session_line`
   renderer (one line — what the surface is + what "this/here" means) and a
   `prompt_section` (2–4 sentences of routing hints). Keep both terse; bulky
   content belongs in `inspect_view_context`.
2. If the page anchors on an entity (like `dashboard_id`), document the id
   field in the `ChatRequest.view_context` comment, teach
   `inspect_view_context` to load/format it, and let the relevant tools
   default from it.
3. Tests: `tests/unit/agent/test_view_pages.py` covers session lines, prompt
   sections and the unknown-page fallback — extend the same file.
