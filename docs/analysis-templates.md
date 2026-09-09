# Analysis templates

*Scope: backend (`wri/project-zeno`). Related: `dashboards-mvp-plan.md`,
`AGENT_ARCHITECTURE.md`.*

An **analysis template** answers a standing question about an area — "what
has been disturbed here in the last two weeks?" — by writing a whole
dashboard section at once: a chart, the map layers that belong with it, and
a title and description written from the data.

It is not a chat workflow. Nothing is picked by a model along the way, so
the same request always produces the same section. The only model call
writes the words.

Today the agent is the only caller, behind the experimental profile. The
system is built so an HTTP route can be added later without changing a
template.

## The parts

| Where | What |
|---|---|
| `analysis_templates/registry.py` | the templates, as metadata only |
| `analysis_templates/base.py` | the interface, the result and error types, the shared helpers |
| `analysis_templates/writer.py` | the two transactional writes, and the `config` shape |
| `analysis_templates/<name>/` | one template |
| `agent/tools/analysis_sections.py` | the two generic agent tools |
| `skills_md/analysis-templates.md` | the workflow the model follows |

The registry imports nothing else, and must stay that way. Two callers need
to know a template exists without paying for what it does:
`dashboard_writer` reads `SEALED_SECTION_TYPES` on every dashboard write,
and the agent's tool prompt lists the templates at import time.
`get_template()` imports a template's module on first use.

A template's `name` is also the value stored in `dashboard_sections.type`,
so there is one list of template names rather than two.

## Sealed sections

A section a template wrote is **read-only**. Its content is a record of one
build — one area, one period, the data as it was — so editing it would make
its own title and description untrue.

`dashboard_writer` refuses every write that would change a sealed section or
its widgets' content: retitling, restating, adding a widget, removing one,
moving one in or out, replacing a widget's config. The API returns 409; the
agent tools return an error that says what to do instead.

Three details worth knowing:

- **Layout is exempt.** `position`, and a config replacement whose only
  differing keys are `size`/`sizes`. The check is a diff, not a field
  allowlist, because PATCH replaces a config wholesale.
- **Deleting a sealed section always takes its widgets**, whatever
  `delete_widgets` says. Ungrouping would leave loose, editable copies of
  content that is only meaningful inside its own section.
- **`update_insight_display` refuses an insight a sealed widget shows.** It
  is the one path that could rewrite a section's content without touching a
  dashboard row.

A template never meets the seal: it writes its section in one transaction
(`add_section_with_widgets`) and replaces it in another
(`replace_section_widgets`), neither of which is guarded.

## Adding a template

1. **Write the module.** `analysis_templates/<your_name>/` with a `recipe.py`
   exporting `TEMPLATE` and a parameter model, and a `summary.py` if it
   generates its own words. Copy the shape of `nrt_monitoring`.

   - `build(dashboard, *, user_id, params, language)` and
     `refresh(section, dashboard, ...)` both gather content and hand it to
     `writer`. Sharing one gather step means a refreshed section is
     assembled exactly like a new one.
   - The template takes the loaded `DashboardOrm`, so it picks its own area
     (`base.first_aoi`) and runs its own "already built" check.
   - Its parameter model states its defaults and its bounds, and sets
     `extra="forbid"` so a parameter it does not take is refused rather
     than ignored.
   - Everything it raises is a `TemplateError`, whose message is shown to
     the user as written.
   - It writes its own one-line `summary`, so no caller has to know what
     the section contains.
   - Record `start_date` and `end_date` in `SectionContent.config` if the
     section covers a period; `base.describe_window` reads them back.

2. **Register it.** One `TemplateEntry` in `registry.py`. `label`,
   `when_to_use` and `params_help` are read by a model, so keep them to one
   line each. `sealed=True` unless the section is genuinely editable
   afterwards.

3. **Document it for the model.** One `##` section in
   `skills_md/analysis-templates.md`: what it builds, what its parameters
   mean, and any caveat the model must pass on rather than apologise for.

Nothing else changes: no new tool, no `agent_config` change, no
`dashboard_writer` change, no migration, no router change. The tests in
`tests/unit/api/analysis_templates/test_registry.py` cover every registered
template, so a new one is covered by them the day it is added.

Reuse what is already there: `resolve_dataset_layer` for a renderable tile
URL, `widget_configs` for a map widget's config, `DETERMINISTIC_GENERATORS`
for a curated chart, `AnalyzeService` for the pull, `persist_insight` for a
chart widget's insight.

## Known limits

- **One area.** A template covers the dashboard's first AOI
  (`base.first_aoi`). Portfolios of areas are a dashboard-level question,
  and that is the one place it will change.
- **One shared parameter in the agent's tools.** Both tools pass `days`. A
  template needing another input adds a field to its parameter model and a
  line to `params_help`, and the tools gain that argument once — not once
  per template.
- **Synchronous.** A build runs to completion before it answers, which
  takes tens of seconds. When a route is added, that decision gets made
  again.
