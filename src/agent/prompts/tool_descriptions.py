"""The schema descriptions of the tools.

The system prompt (src/agent/prompts/) has no tool list, so the schema
description is the one description of a tool. These texts replace the
docstrings of the tools named here (agent_config.ALL_SPECS); a tool not
named here keeps its docstring.
"""

_DEFAULT_DASHBOARD = (
    "`dashboard_id` defaults to the dashboard in state or on screen. "
    "Only the user's own dashboards can be edited."
)

TOOL_DESCRIPTIONS: dict[str, str] = {
    "pick_aoi": (
        "Resolve the place in the request to the area of interest (AOI) in "
        "state (geocoding subagent). Pass the user's full request about the "
        'area to analyze, not only the place name, for example "tree cover '
        'loss in Pará, Brazil", "which province of the DRC had the most '
        'alerts", "forest loss worldwide". The words around the place ("each '
        'state", "the provinces of", "Indigenous territories in") tell it to '
        'select the subregions: with only "DRC" it selects the country. When '
        "the message does not name the place, add it from the earlier turns "
        '("which states lost the most?" after a question about Brazil becomes '
        '"which states of Brazil lost the most?"). Leave out places that are '
        "not part of the area to analyze. It extracts, "
        "translates and resolves the place and any subregions itself. Set "
        "`area_of_interest` when the type of area is obvious. Returns a "
        "clarifying question when the place is ambiguous or missing. A zone "
        'with no boundary (a "belt", a "frontier") resolves to its country '
        "or to the country's units: say in the answer that the figures are "
        "for the country, not the zone."
    ),
    "pick_dataset": (
        "Select the dataset, context layer and date range that best answer "
        "the request (dataset-selection subagent). The subagent reads the "
        "user's latest message. In `query`, give the data request with what "
        "that message does not say, for example a place or a dataset of an "
        "earlier turn. Do not name a dataset that the user did not name. "
        "`start_date`/`end_date` (YYYY-MM-DD) are optional; the "
        "closest valid range of the dataset is used. Call it again before "
        "`pull_data` when the user changes the dataset, the context layer "
        "(drivers, land cover change and so on) or a parameter. A "
        'dataset-only request ("use tree cover loss by driver") needs no '
        "AOI: do not ask for a place. Can return no dataset, or only "
        "alternatives."
    ),
    "inspect_view_context": (
        "Return what the user sees in the app: the page, the map viewport, "
        "the visible layers and AOIs, and the content of each insight on "
        "screen (summary, chart titles, variables). On a dashboard page "
        "also the dashboard's name, areas, sections and widgets with their "
        'ids. Call it when the user refers to "this", "here", the current '
        "view, the report, the dashboard or an insight on screen, and you "
        "need those details to answer."
    ),
    "show_imagery": (
        "Show Sentinel-2 imagery on the map for the AOI in state (pick_aoi "
        "first). Global, any date. `target_date` (YYYY-MM-DD) is the centre "
        "of the search window; null shows about the previous two weeks. "
        "The least cloudy scenes of the window are shown on top. "
        "`window_days` (default 7, max 183) and `max_cloud_cover` (default "
        "50 percent) widen the search: raise them only when the defaults "
        "find no scenes and the user agrees. The map searches the scenes "
        "after the call; their count and dates come with the next message. "
        "Regional areas only."
    ),
    "show_planet_imagery": (
        "Show Planet's high-resolution monthly mosaic for the AOI in state "
        "(pick_aoi first), to inspect Integrated Disturbance Alerts in the "
        "Amazon biome. It renders only within 500 m of alerts from the past "
        "2 years, so it is blank elsewhere and is not a basemap. Mosaics "
        "start in September 2020; a month is published about the 15th of "
        "the next month. `target_date` (YYYY-MM-DD) selects the month; null "
        "gives the latest month (tell the user that it is the most recent "
        'available Planet imagery). For other places or for "latest" or '
        '"recent" imagery, use show_imagery. Outside its footprint the tool '
        "falls back to Sentinel-2 by itself and says so. Regional areas "
        "only."
    ),
    "search_blogs": (
        "Research subagent: searches the WRI and LCL Insights articles and "
        "returns a short answer with inline [N](url) citation markers. Use "
        "it only when no dataset can answer the question, when the user "
        "asks for WRI research or citations, or for an open interest with "
        "no place and no dataset topic. Never for a question that "
        "pick_dataset can answer. When your reply uses the findings, keep the "
        "markers on the statements you use, numbered by first appearance "
        "(the app shows each as a citation icon). Never remove markers or "
        "invent URLs. `query`: the topic or question; a place or a theme "
        "helps."
    ),
    "update_insight_display": (
        "Restyle an existing insight without new data: reword the summary "
        "or the follow-up suggestions, rename a chart, change a chart type, "
        "or map a chart to other columns that it already has. It cannot add "
        "data or make charts: use generate_insights for that (it always "
        "makes a new insight). Default target: the most recent insight; "
        "pass `insight_id` for another one. If it is not clear whether the "
        "user wants a restyle or a new insight, first call "
        'send_nudge(nudge_type="insight_choice", options=["Create a new '
        'insight", "Update the current insight"]).'
    ),
    "search_insights": (
        "Find an insight made earlier (in any conversation of the user, or "
        "a public one) by its description and show it again with its chart, "
        "without computing anything. Use it when the user refers to an "
        'earlier finding ("show that tree-cover insight again").'
    ),
    "send_nudge": (
        "Offer the user 2 to 4 clickable options instead of an open "
        "question. `nudge_type`: a free label for the kind of choice (for "
        'example "confirm", "clarify"). `options`: the exact button texts; '
        "a click sends the text as the user's next message, so each option "
        "must be short and clear by itself."
    ),
    "create_dashboard": (
        "Create an empty dashboard for the AOI in state (pick_aoi first). "
        "`name` defaults to the area's name. Add widgets with "
        "add_to_dashboard."
    ),
    "add_to_dashboard": (
        "Add an insight to a dashboard as a widget. `insight_id` defaults to "
        "the current insight in state. `section` (a section title or id) "
        "puts it in a section; without it the widget is ungrouped. The "
        "insight must be one that the user can see. " + _DEFAULT_DASHBOARD
    ),
    "add_map_widget": (
        'Add a map widget to a dashboard. `layer="dataset"`: the selected '
        'dataset layer (pick_dataset first). `layer="imagery"`: the '
        "Sentinel-2 imagery from show_imagery. `title` overrides the header; "
        "`section` (a section title or id) groups it. " + _DEFAULT_DASHBOARD
    ),
    "add_text_widget": (
        "Add a markdown note to a dashboard. Write `text` yourself: a short "
        "note, summary or section intro, with any heading in the markdown "
        "(there is no title field), and no raw data. `section` (a section "
        "title or id) groups it; `position` places it in that container "
        "(default: last). " + _DEFAULT_DASHBOARD
    ),
    "edit_text_widget": (
        "Replace all the markdown of a text widget with `text`. `widget_id` "
        "defaults to the only text widget; when there are several, the "
        "error lists their ids. " + _DEFAULT_DASHBOARD
    ),
    "add_dashboard_section": (
        "Create a section (a titled group of widgets) on a dashboard. "
        '`title`: short and topical, for example "Deforestation". '
        "`description`: optional, one or two lines on its purpose. "
        "`position`: default last. The section starts empty: pass `section` "
        "to add_to_dashboard, add_text_widget or add_map_widget. "
        + _DEFAULT_DASHBOARD
    ),
    "edit_dashboard_section": (
        "Change the title or the description of a section, or both (each a "
        "full replacement). `section` (a section title or id) defaults to "
        "the only section; when there are several, the error lists them. "
        + _DEFAULT_DASHBOARD
    ),
    "move_dashboard_widget": (
        "Move a widget into a section (`section`, a section title or id) or "
        "back to the top level (`ungroup=True`): exactly one of the two. "
        "`position` sets the slot (default: last); to reorder only, name "
        "the container that it is in and a position. Get `widget_id` from "
        "inspect_view_context. Only the user's own dashboards can be edited."
    ),
}
