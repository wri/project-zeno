# Highlight markup in text blocks

*Status: implemented. Scope: backend (`wri/project-zeno`) and the app that
renders a dashboard. Related: `insight-chart-colors-plan.md`,
`nrt-monitoring-section-plan.md`.*

## 1. What it is

A text block states figures — an area, a percentage, a change against the
period before. A reader must find those figures without reading the whole
block. To make that possible, the model that writes the block puts each
figure in a span, and the app gives the span a colour.

The backend writes the markup. The app owns the colours.

## 2. The markup

```html
As of 2020, <span data-highlight="value">27%</span> of the area was natural
forest. Alerts rose by <span data-highlight="increase">12%</span> against
the year before, and tree cover loss fell to
<span data-highlight="decrease">4,200 ha</span>.
```

One tag, one attribute, three values:

| `data-highlight` | Use for |
|---|---|
| `value` | A figure that states a quantity. |
| `increase` | A figure that states a rise between two periods or two areas. |
| `decrease` | A figure that states a fall between two periods or two areas. |

`increase` and `decrease` give the direction of the change. They do not say
whether the change is good news: more tree cover loss is bad news, more
tree cover is good news, and only the app knows which dataset it shows. Map
the colours per dataset, not per direction.

## 3. Where it appears

| Text block | Field | Written by |
|---|---|---|
| Text widget on a dashboard | `widget.config.text` | The agent, through `add_text_widget` / `edit_text_widget` |
| Section description | `section.description` | The agent, through `add_dashboard_section` / `edit_dashboard_section` |
| Monitoring section description | `section.description` | `nrt_summary.generate_section_summary` |
| Insight narrative | `insight.insight_text` (`primary_insight`) | `InsightTextGenerator`, `InsightDisplayReviser` |

The markup does **not** appear in:

- a title or a heading — a section title, a dashboard name, a chart title;
- a chart label, an axis label or a legend entry;
- a follow-up suggestion;
- a chat message. The backend removes the spans from every text block it
  quotes back into the conversation, so the model does not copy them into a
  reply.

## 4. What the backend guarantees

- The tag is always `span`. The attribute is always `data-highlight`.
- A span holds a figure and its unit, and the word that carries the
  direction when the wording needs one ("up 12%"). It never holds a whole
  sentence.
- Spans do not nest.
- No other HTML and no other attribute. No `class`, no `style`.
- The text reads correctly when the spans are removed.

A model writes the markup, so treat the guarantees as intent, not as proof.
Sanitize the HTML: keep `span` with `data-highlight`, and drop the rest.

## 5. What the app has to do

1. Render the text block as markdown with inline HTML enabled.
2. Colour a span by its `data-highlight` value.
3. Render an unknown value as plain text. The list of values can grow.
4. Keep the same colours as the chart legend of the same dataset, so a
   figure in the text and its series in the chart read as one thing. See
   `insight-chart-colors-plan.md`.

## 6. Where the contract lives in code

`src/agent/text_highlights.py` holds all of it:

- `HIGHLIGHT_GUIDE` — the rules, for a text-generation system prompt. It is
  composed into `WORDING_GUIDE` (insight text and the display reviser), into
  the `nrt_summary` prompt, and into the `dashboard` skill through the
  `{{HIGHLIGHT_GUIDE}}` placeholder that `skills/loader.py` resolves.
- `HIGHLIGHT_RULE` — the same rules in one paragraph, for the tool fragments
  in the agent's system prompt.
- `strip_highlights` — the markup removed again, for the tool messages and
  summaries that go back into the conversation.

To add a kind, add it to `HIGHLIGHT_KINDS` and to `HIGHLIGHT_GUIDE`, then add
its colour in the app. Old text keeps working, because the app renders an
unknown kind as plain text.
