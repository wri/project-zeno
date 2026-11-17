"""Short tool descriptions for the ``concise-replies`` flag.

The concise prompt (src/agent/prompts/) has no tool list, so the schema
description is the one description of a tool. These texts replace the
docstrings for the flagged profile only, so the default profile stays the
same during the comparison (docs/concise-agent-plan.md, iteration 2).

Temporary: when the concise profile is accepted, each text becomes the
docstring of its tool and this module is deleted. The two dashboard tools
that replace seven have their texts in src/agent/tools/dashboard_items.py.
"""

_DEFAULT_DASHBOARD = (
    "`dashboard_id` defaults to the dashboard in state or on screen. "
    "Only the user's own dashboards can be edited."
)

CONCISE_TOOL_DESCRIPTIONS: dict[str, str] = {
    "pick_aoi": (
        "Resolve the place in the request to the area of interest (AOI) in "
        "state (geocoding subagent). Pass the user's words about the place "
        'verbatim, for example "tree cover loss in Pará, Brazil", "the '
        'districts of Odisha", "forest loss worldwide". It extracts, '
        "translates and resolves the place and any subregions itself. Set "
        "`area_of_interest` when the type of area is obvious. Returns a "
        "clarifying question when the place is ambiguous or missing."
    ),
    "pick_dataset": (
        "Select the dataset, context layer and date range that best answer "
        "the request (dataset-selection subagent). Pass the user's request "
        "as `query`. `start_date`/`end_date` (YYYY-MM-DD) are optional; the "
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
        "first). Global, any date. `target_date` (YYYY-MM-DD) is the date to "
        "be closest to; null shows about the previous two weeks. "
        "`window_days` (default 7, max 183) and `max_cloud_cover` (default "
        "20 percent) widen the search: raise them only when the defaults "
        "find no scenes and the user agrees. Regional areas only."
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
        "it to ground an answer in published research or to explore a topic "
        "before analysis. When your reply uses the findings, keep the "
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
        "add_dashboard_item."
    ),
}
