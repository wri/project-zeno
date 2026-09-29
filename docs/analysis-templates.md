# Analysis templates

An analysis template is a named spec for a dashboard section. One API call
applies a template to a dashboard. The call gets the data, makes the widgets
and writes one new section.

The section is a normal section. The user can edit it, move its widgets and
delete it. The agent can apply a template too (see "Agent").

The design and the decisions are in `analysis-templates-plan.md`.

## Templates

| Name | Widgets | Args |
|---|---|---|
| `nrt-monitoring` | Integrated alerts chart (daily), integrated alerts map layer, Sentinel-2 imagery | `days`: length of the period, counted back from today. Default 14, maximum 365. |

A template uses the first area of the dashboard. Each template has its own
arguments (`args`). The arguments set the period of the widgets.

## API

### List the templates

`GET /api/analysis-templates` (authentication required)

```json
[
  {
    "name": "nrt-monitoring",
    "label": "Near-real-time monitoring",
    "args_schema": {
      "type": "object",
      "title": "NrtMonitoringArgs",
      "additionalProperties": false,
      "properties": {
        "days": {
          "type": "integer",
          "title": "Days",
          "description": "Length of the period in days, counted back from today.",
          "default": 14,
          "minimum": 1,
          "maximum": 365
        }
      }
    },
    "widgets": ["chart", "layer", "imagery"]
  }
]
```

The `label` is in the user's language. `args_schema` is the JSON schema of
the template arguments. Use it to make the form: it gives each argument, its
default and its limits.

### Apply a template

`POST /api/dashboards/{dashboard_id}/sections/from-template` (owner only)

```json
{ "template": "nrt-monitoring", "args": { "days": 30 } }
```

`args` is optional. An argument that you do not send gets its default. An
unknown argument gives 422.

Response `201`:

```json
{
  "section_id": "…",
  "widget_ids": ["…", "…", "…"],
  "warnings": [],
  "dashboard": { "...": "the same body as GET /api/dashboards/{id}" }
}
```

The request is synchronous. It takes tens of seconds, because it pulls
analytics data, searches for imagery and calls a model for the text. Show a
progress indicator and disable the button during the request. Two calls make
two sections.

| Condition | Status |
|---|---|
| Unknown template, or `args` do not agree with `args_schema` | 422 |
| The dashboard has no area | 422 |
| The dashboard does not exist, or the user does not own it | 404 |
| A required widget failed (for example, the analytics pull) | 502. Nothing is written. |
| The dashboard was deleted during the build | 404 |

An optional widget can fail. For example, there is no cloud-free imagery in
the period. Then the section does not have that widget, and `warnings` gives
the reason. Show each warning to the user.

### The section record

Each section in the dashboard response has a `template` field:

```json
{
  "name": "nrt-monitoring",
  "args": { "days": 14 },
  "start_date": "2026-09-09",
  "end_date": "2026-09-23",
  "built_at": "2026-09-23T10:15:02"
}
```

`args` has all the arguments, also the defaults. The field is `null` for a section that a user or the agent composed. It tells
how the section started, not what it contains now. An edited section keeps
it. You can use it to show, for example, "Built from Near-real-time
monitoring, 2026-09-09 to 2026-09-23".

### Title and description

A small model writes the title and the description from the data. The title
has a maximum of 60 characters. The description has one to three sentences.
If the model fails, the template's fixed text applies. The text is in the
user's language.

### Access

The new chart insights belong to the dashboard owner. They are public if the
dashboard is public.

## Change to the alerts chart

The default integrated alerts chart now shows one point per day per
confidence level. Before, it showed one point per month. This change applies
to every default alerts chart, also to `POST /api/analyze`:

- `x_axis` is `alert_date` (`YYYY-MM-DD`). It was `month` (`YYYY-MM`).
- A day with no alerts has no row.
- Insights that are already in the database do not change.

## Agent

The `add_template_section(template, template_args?, dashboard_id?)` tool applies a
registered template. It runs the same code as the API. The tool description
gives the arguments of each template, from `args_schema`. The tool is in the
`experimental` profile. The `dashboard` skill tells the agent to use a
template when the request matches the purpose of one, and to compose the
section by hand for all other requests.

## Add a template

1. In `src/api/services/analysis_templates/registry.py`, add a
   `TemplateArgs` subclass with the template arguments. Give each field a
   default, limits and a description. Implement `period(today)`: it returns
   the start and end dates of the widgets.
2. Add an `AnalysisTemplate` entry to `TEMPLATES` in the same file. Set
   `args_model` to the new class.
3. Add the three i18n keys (label, fallback title, fallback description) to
   `src/agent/i18n.py`. The fallback text can use `{aoi_name}`,
   `{start_date}` and `{end_date}`.
4. Run `tests/unit/api/analysis_templates/test_templates.py`. It checks that
   each chart dataset has a curated chart generator, that each layer dataset
   has a tile layer, that the i18n keys exist and that the default arguments
   are valid.

You do not have to write code if the template uses the widget kinds `chart`,
`layer` and `imagery`. For a new widget kind, add a spec class to
`models.py` and a builder function to `builder.py`.

## Limits

- There is no refresh. To show a different period, apply the template again
  and delete the old section.
- A template uses only the first area of the dashboard.
- The new insights have no `statistics_ids`. The insight filters
  (`?dataset_id=`, `?aoi_source=`) do not find them. `POST /api/analyze` has
  the same gap.
