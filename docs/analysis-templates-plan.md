# Analysis templates: plan

*Scope: backend (`wri/project-zeno`). Branch: `feat/analysis-templates`, from
`main`. Replaces #822 (draft) and #813 (closed). Related:
`dashboards-mvp-plan.md`, `curated-charts-in-agent-plan.md`.*

## 1. Goal

An **analysis template** is a named spec for a dashboard section. One API call
applies a template to a dashboard. The call pulls the data, makes the widgets
and writes one new section.

The section is a normal section. The user can edit it, move its widgets and
delete it. This is the main change from #822: **there is no seal**.

The primary deliverable is the API endpoint. The agent also gets one tool that
applies a template (section 8).

## 2. What we keep from #822 and #813

| Idea | Source | Keep? | Note |
|---|---|---|---|
| Write the section and its widgets in one transaction | `dashboard_writer.add_section_with_widgets` | Yes | Also write the insight in the same transaction (fixes the orphan insight, see 9, item 1). |
| Record on the section how it was built | migration `type` + `config` | Changed | One nullable JSONB column `template`. No `type` column. |
| Curated chart from the analytics pull | `AnalyzeService` + `DETERMINISTIC_GENERATORS` | Yes | `main` now has `charts/curated.py` (#827). Use it. |
| Map layer snapshot, same as `add_map_widget` | `widget_configs.py` | Yes | Extract again from `main`, because #803 changed `add_map_widget`. |
| Imagery is best effort, with a warning | NRT recipe | Yes | Generic: each widget has `required`. |
| Clamp the period to the dataset range, once | `resolve_period` | Yes | Resolve "today" one time per request (reviewer finding). |
| Give each consumer its own copy of the AOI | NRT recipe | Yes | `AnalyticsHandler.pull_data` changes its input. |
| Sealed sections | #813/#822 | **No** | About 200 lines over 8 files. Not needed. |
| `refresh` and `reconfigure` verbs, confirmation gate | #822 | **No** | See 7. |
| "Already built" check | #822 | **No** | An editable section cannot be "the same" as a new one. |
| Registry that imports nothing, lazy module import | #822 | **No** | Needed only for the seal. |
| One Python module per template (`build`/`refresh`/`describe`) | #822 | **No** | Templates become data. See 3. |
| `resolve_dataset_layer` refactor of `pick_dataset` | #822 `b31394fc` | **No** | Highest regression risk, and it conflicts with #803. See 4.3. |
| Model-written title and description | `nrt_monitoring/summary.py` | Yes | Made generic for all templates. See 4.5. |
| Daily alerts chart | #813 `charts/integrated_alerts.py` | Yes | Changes every default alerts chart, not only templates. See 5. |

Size target: about 1,600 lines with tests, including the agent tool and the text call. #822 is 4,455.

## 3. Templates are data

A template is a Pydantic object, not a module with methods. One generic
builder runs every template.

```python
class ChartWidgetSpec(BaseModel):
    kind: Literal["chart"] = "chart"
    dataset_id: int
    required: bool = True          # failure stops the build

class LayerWidgetSpec(BaseModel):
    kind: Literal["layer"] = "layer"
    dataset_id: int
    required: bool = True

class ImageryWidgetSpec(BaseModel):
    kind: Literal["imagery"] = "imagery"
    window_days: int = 7
    max_cloud_cover: int = 20
    required: bool = False         # failure adds a warning

WidgetSpec = Annotated[
    ChartWidgetSpec | LayerWidgetSpec | ImageryWidgetSpec,
    Field(discriminator="kind"),
]

class AnalysisTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str                      # "nrt-monitoring"
    label_key: str                 # i18n key, for the template list
    purpose: str                   # one sentence for the text model: what the section is for
    fallback_title_key: str        # i18n key, used when the text model fails;
    fallback_description_key: str  #   placeholders {aoi_name}, {start_date}, {end_date}
    default_days: int              # rolling period, counted back from today
    max_days: int
    widgets: tuple[WidgetSpec, ...]
```

The registry is a tuple of these objects in one file:

```python
TEMPLATES = (
    AnalysisTemplate(
        name="nrt-monitoring",
        label_key="analysis_template.nrt_monitoring.label",
        purpose="Show recent forest disturbance in the area, day by day.",
        fallback_title_key="analysis_template.nrt_monitoring.title",
        fallback_description_key="analysis_template.nrt_monitoring.description",
        default_days=14,
        max_days=365,
        widgets=(
            ChartWidgetSpec(dataset_id=INTEGRATED_ALERTS_ID),
            LayerWidgetSpec(dataset_id=INTEGRATED_ALERTS_ID),
            ImageryWidgetSpec(),
        ),
    ),
)
```

**A new template is one entry and three i18n strings.** There is no new code if
the template uses the three widget kinds. A new widget kind (for example a text
widget, or a chart with a canopy threshold) is one new spec class and one
builder function.

A unit test checks each template when it is added:

- each `chart` widget has a curated generator for its dataset;
- each `layer` widget has a dataset with a `tile_url` or `layers`;
- the i18n keys exist in each supported language;
- `default_days <= max_days`.

### Parameters

The only parameter in v1 is `days`, the length of the rolling period. The
request can change it inside `1..max_days`.

#822 made parameters an untyped dict so that a future template could take a
threshold. We do not do that now. All known templates are "datasets over a
period". Add typed fields to `AnalysisTemplate` when a template needs them.

## 4. Build

### 4.1 Flow

`src/api/services/analysis_templates/builder.py`:

```text
apply_template(dashboard, template, days, user_id, language)
  1. aoi   = first AOI of the dashboard, else error "no area"
  2. today = date.today()                  # one time
  3. for each widget spec, concurrently (asyncio.gather):
       clamp the period to the dataset range (revise_date_range)
       run the builder for its kind, with its own copy of the AOI
  4. a required widget failed -> raise TemplateError, write nothing
     an optional widget failed -> add a warning, drop the widget
  5. title, description = generate_section_text(...)   # 4.5; never raises
  6. write the section, its widgets and new insights in one transaction
  7. return section_id, widget_ids, warnings
```

### 4.2 Widget builders

| Kind | Calls | Output |
|---|---|---|
| `chart` | `AnalyzeService.analyze()` → curated charts | an insight payload (not yet written) and a widget that points at it |
| `layer` | tile resolution (4.3) → map widget config projection | a map widget config |
| `imagery` | `Sentinel2ImageryProvider.get_imagery()` → imagery projection | a map widget config |

A builder returns data. It does not write to the database. Only step 6 writes.

### 4.3 Tile URL resolution without the `pick_dataset` refactor

`get_tile_services_for_dataset(selection_result, selected_row, start, end)`
already resolves a catalog `tile_url`. It reads only `dataset_id`,
`context_layer` and `parameters` from `selection_result`. The layer builder
calls it with:

- a small stub selection: `dataset_id`, `context_layer=None`,
  `parameters=None`;
- the catalog row as a `pd.Series` (the same shape `pick_dataset` passes).

This gives the same URL as the chat path (the default canopy threshold of 30,
the date suffix). It does not change `pick_dataset`.

The map widget config projection (`_dataset_config`, `_imagery_config`,
`_widget_config` in `add_map_widget.py`) moves to
`src/api/services/widget_configs.py`. The move does not change behaviour.
`add_map_widget` imports from there. This keeps a template layer and a chat
layer identical.

### 4.4 The write

Extend the #822 `add_section_with_widgets` so that a widget spec can carry an
`insight` payload instead of an `insight_id`. The function writes the insight
rows, the section and the widgets in one session and one commit.

- A failure writes nothing. There is no orphan insight.
- Each new insight gets `is_public = dashboard.is_public`. A public dashboard
  keeps showing its charts.
- The new section goes after the last section (`max(position) + 1`).
- The section row gets `template = {"name", "days", "start_date",
  "end_date", "built_at"}`.

Move the insight row construction out of `persist_insight` into a helper that
takes a session. `persist_insight` then calls that helper. This is a small
refactor with no change in behaviour.

### 4.5 Title and description

The title and description are dynamic. One small model call writes both from
the data, for every template. Start from #813's `nrt_monitoring/summary.py`
and make it generic: `src/api/services/analysis_templates/text.py`.

Input to the model:

- the area name and the period;
- the template `purpose`;
- the widgets the section has after step 4 (for example "no imagery");
- the chart data of each chart widget, with numbers rounded for the prompt
  (the stored chart keeps full precision);
- the `presentation_instructions` of each dataset in the template.

Instructions to the model:

- **Title:** name the area and the subject. At most 60 characters. No
  trailing period. No markup.
- **Description:** one to three short sentences. Say what the section shows,
  then give the one or two figures that matter most. Take each figure from
  the chart data. Do not compute new figures. Give the unit with each area.
- Be short, descriptive and to the point. No filler, no advice, no
  speculation about causes.
- Obey the dataset presentation rules (for example: alerts show possible
  disturbance, not confirmed deforestation).
- Write in the user's language.

Rules:

- Use `SMALL_MODEL` with structured output (`title`, `description`).
- The call never raises. If the model fails or returns empty text, use the
  template's fallback i18n text. A build must not fail after its data is
  ready.
- Cut the title to 60 characters in code, not only in the prompt.

This adds one model call to the API path. It adds a few seconds to a request
that already takes tens of seconds.

### 4.6 Schema

One migration: `dashboard_sections.template JSONB NULL`.

- `NULL` = a section composed by hand or by the agent.
- Not `NULL` = the provenance of a template section. The API returns it. The
  frontend can show "Built from *Near-real-time monitoring*, 2026-09-09 to
  2026-09-23".
- No code reads it for access or edit rules. An edited section keeps it. The
  field says how the section started, not what it contains now.

## 5. Daily alerts chart

`IntegratedAlertsChartGenerator` now groups alerts by month. The analytics API
returns daily rows. A 14-day period gives one or two points, which is not a
useful line.

Change the generator to one point per day per `alert_confidence`. Take the
code from #813 (`charts/integrated_alerts.py`):

- `x_axis` changes from `month` to `alert_date` (`YYYY-MM-DD`).
- Rows with the same day and confidence are summed. The API returns one row
  per intersecting geometry.
- A day with no alerts has no row. Do not add zeros.
- Update the class docstring and
  `tests/unit/api/services/test_chart_generators.py` (the `month` asserts).

**This change affects every default alerts chart, not only the template.**

| Caller | Effect |
|---|---|
| `POST /api/analyze` (default insights, #806) | New alerts charts are daily. The chart spec has `x_axis: "alert_date"` in place of `month`. |
| Analysis templates | Daily, as intended. |
| Agent `generate_insights` | No effect. It uses curated charts only for `curated_only` datasets (LGMS). Alerts use the code executor. |
| Insights already in the database | No effect. They keep their monthly data. |

Before merge:

- Check that the frontend reads the axis name from the chart spec and shows a
  date axis correctly. Do not assume that it has `month` hard-coded.
- Check a long period. Two years of daily data for three confidence levels
  is about 2,000 points. The chart must stay readable, and
  `inspect_view_context` must still limit the size (#778).
- Put this change in its own commit, first on the branch. Name it in the PR
  description as a visible change for `/api/analyze` clients.

## 6. API

### 6.1 List the templates

`GET /api/analysis-templates` (authenticated, no dashboard needed)

```json
[
  {
    "name": "nrt-monitoring",
    "label": "Near-real-time monitoring",
    "default_days": 14,
    "max_days": 365,
    "widgets": ["chart", "layer", "imagery"]
  }
]
```

`label` is translated to the user's language.

### 6.2 Apply a template

`POST /api/dashboards/{dashboard_id}/sections/from-template` (owner only)

Request:

```json
{ "template": "nrt-monitoring", "days": 30 }
```

`days` is optional. The template default applies.

Response `201`:

```json
{
  "section_id": "…",
  "widget_ids": ["…", "…", "…"],
  "warnings": ["No cloud-free imagery in the period."],
  "dashboard": { "...": "the same body as GET /api/dashboards/{id}" }
}
```

| Condition | Status |
|---|---|
| Unknown template, `days` out of range | 422 |
| Dashboard has no AOI | 422 |
| Not the owner, or no dashboard | 404 (same as other owner-only dashboard routes) |
| A required widget failed (for example the analytics pull) | 502, nothing written |
| Dashboard deleted during the build | 404 |

### 6.3 Synchronous

The request runs to completion. It takes tens of seconds (analytics pull,
mosaic search, the text call). We do not use a background job:

- The review of the #762–766 stack found that a background task is not
  durable across a container restart.
- A synchronous call with one transaction has no half-built state to recover.
- The frontend shows a spinner and disables the button during the request.

If the time becomes a problem, change to the `JobRepository` pattern of
`POST /api/analyze`. The builder does not change.

## 7. What is not in v1

- **Refresh.** The user can edit a template section, so a refresh in place
  would delete their edits. When we add refresh, it makes a **new** section
  from the stored `template` record. The user then deletes the old section.
  There is no replace path and no confirmation gate.
- **Portfolios.** A template uses the dashboard's first AOI, as in #822.
- **Idempotency.** Two calls make two sections. The frontend prevents a double
  click.
- **Parameters other than `days`.**
- **`statistics_ids` on the insight.** `AnalyzeService` does not write
  `StatisticsOrm` rows. The insight filters (`?dataset_id=`, `?aoi_source=`)
  do not find these insights. `/api/analyze` has the same gap. The section's
  `template` field records the dataset and the area.

## 8. Agent access

The agent gets one tool that applies a registered template. It runs the same
`apply_template` as the API. The agent does not write its own specs (8.4).

### 8.1 The tool

`src/agent/tools/add_template_section.py`, in the `experimental` profile. Add
its `SPEC` to `ALL_SPECS` in `agent_config.py`, after
`add_dashboard_section_spec`.

```python
@tool("add_template_section")
async def add_template_section(
    template: TemplateName,            # Literal built from the registry names
    days: Optional[int] = None,        # template default when omitted
    dashboard_id: Optional[str] = None,
    state: Annotated[Dict, InjectedState] | None = None,
    tool_call_id: Annotated[Optional[str], InjectedToolCallId] = None,
) -> Command:
```

The tool:

1. gets the user with `require_current_user_id`;
2. gets the dashboard with `resolve_dashboard_id` (argument, then state, then
   `view_context`) and `load_editable_dashboard` (owner check);
3. refuses a `days` value outside `1..max_days` of the template, with the
   bounds in the message;
4. calls `apply_template(dashboard, template, days, user_id, language)`, with
   the language from state;
5. catches `TemplateError` and returns `error_command` with its message;
6. returns `dashboard_updated_command`, so the frontend reloads the dashboard.

The tool message gives the section id, the generated title and description,
the widget count and each warning. It does not give chart rows. The model can
report the section without more data.

`template` is a `Literal` of the registry names, not a free string. The model
sees the valid names in the tool schema. #822 had an untyped `params` dict;
this tool has one typed argument, `days`, because `days` is the only
parameter.

The `prompt_fragment` lists each template with its name, `purpose`,
`default_days` and `max_days`. It is made from the registry, so a new
template appears in the prompt with no tool change.

### 8.2 Skill

Add one section, "Sections from a template", to
`src/agent/skills/skills_md/dashboard.md`:

- Use a template when the request matches the `purpose` of one (for example
  "monitor this area", "what was disturbed here recently"). Compose a section
  by hand (`add_dashboard_section` + widget tools) for all other requests.
- The dashboard must have an area. If there is no dashboard, create one first
  with `create_dashboard`.
- Tell the user that the build takes some seconds.
- Give each warning to the user as written (for example "no cloud-free
  imagery").
- The new section is a normal section. Use the normal tools to change it
  (`edit_dashboard_section`, `move_dashboard_widget`, the widget tools).
- To show a different period, apply the template again with a new `days`
  value. Offer to delete the old section. There is no refresh.

### 8.3 Size and risk

| Work | Size |
|---|---|
| Tool and `SPEC` | ~100 lines |
| Skill section | ~30 lines |
| Profile registration, manifest test | ~10 lines |
| Unit tests with a mocked `apply_template` | ~150 lines |

**Cost: low.** #822's tool file was 453 lines. Most of that was the seal and
the three verbs (refresh, reconfigure, confirmation). None of these exist
now.

The only behaviour risk is routing: the model must choose between a template
and hand composition. The skill text controls this. Check it with one live
test in `tests/agent` ("monitor deforestation in <area> on my dashboard" →
`add_template_section`). Run only that test.

### 8.4 Not included: the agent writes its own spec

In this option the tool takes a list of widget specs (`chart`/`layer`/
`imagery` with `dataset_id`s), and the builder runs it as a one-off template.
Because templates are data (section 3), the code cost is small: about 150
lines. The real cost is behaviour:

- The model must choose `dataset_id`s without `pick_dataset`. That drops the
  context layer and parameters (canopy threshold). This is the "wrong answer"
  gap in `curated-charts-in-agent-plan.md`.
- It overlaps with hand composition (`generate_insights` + `add_map_widget`),
  which does the same work with correct dataset selection.
- It needs evals to prove that it is better than hand composition.

The spec format keeps it possible. Revisit when a request comes that no
registered template answers and hand composition answers badly.

## 9. Findings from the #822 review, and where they go

1. Orphan insight when a later step fails → fixed by 4.4 (one transaction).
2. Refresh on a public dashboard makes a private insight → fixed by 4.4
   (`is_public` from the dashboard). No refresh in v1.
3. Delete of a sealed section leaves an insight → gone. No seal. A normal
   section delete ungroups its widgets and keeps the insights.
4. `ValidationError` from stored parameters on refresh → gone. No refresh.
5. `assert` in the registry → gone. No lazy import.
6. Template config overwrites reserved keys → gone. `template` is its own
   column, written only by the builder.
7. No `statistics_ids` → known gap (7).
8. `resolve_period` called twice → fixed by 4.1 (one `today`).
9. `confirmed` is only a prompt guard → gone.
10. `resolve_section` message for a sealed section → gone.
11. Model text is not deterministic → accepted. The data and the widgets are
    deterministic. The fallback text is deterministic.

## 10. Decisions (2026-09-23)

1. **Alerts chart is daily**, for every caller of the default alerts chart
   (section 5). NRT keeps the 14-day default.
2. **Title and description are dynamic**: one model call, short, descriptive
   and to the point, with a fixed i18n fallback (4.5).
3. **Endpoint path** is `POST /api/dashboards/{dashboard_id}/sections/from-template`.
4. **Agent access (8)** is in this branch: apply a registered template only.

## 11. Commits

1. `feat(charts): show integrated alerts by day`
2. `refactor(dashboards): move map widget config projections to a shared module`
3. `feat(dashboards): record the template a section was built from` (migration, ORM, response field)
4. `feat(dashboards): write a section, its widgets and insights in one transaction`
5. `feat(dashboards): add analysis templates and the section builder`
6. `feat(dashboards): write the title and description of a template section`
7. `feat(dashboards): add the analysis template endpoints`
8. `feat(agent): let the agent apply an analysis template`
9. `docs: describe analysis templates`

## 12. Tests

- `tests/unit/api/services/test_chart_generators.py` — daily points, sum per
  day and confidence, no zero rows, `x_axis == "alert_date"`.
- `tests/unit/api/analysis_templates/test_templates.py` — the registry checks
  in 3, for each template.
- `tests/unit/api/analysis_templates/test_builder.py` — mocked analytics,
  imagery and catalog: a required failure writes nothing; an optional failure
  gives a warning; each builder gets its own AOI copy; one `today`.
- `tests/unit/api/analysis_templates/test_text.py` — rounded numbers in the
  prompt; fallback on a model error and on empty output; title cut to 60
  characters.
- `tests/api/test_analysis_templates.py` — the two routes: 201 body, 422
  cases, 404 for a non-owner, 502 with no rows written, `is_public`
  inheritance, and the section is editable after the build (PATCH title,
  move a widget, delete the section).
- `tests/unit/agent/tools/test_widget_configs.py` — the moved projections
  give the same output as before.
- `tests/unit/agent/tools/test_add_template_section.py` — dashboard
  resolution, owner check, `days` bounds, `TemplateError` to an error
  message, `dashboard_updated` command.
- `tests/unit/agent/test_profile_manifest.py` — the tool is in
  `experimental` only.
- One live routing test in `tests/agent` (8.3).

Run only these files and `tests/unit` + `tests/api`. Do not run the full
`tests/agent` or `tests/tools` suites.
