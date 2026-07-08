"""What each frontend surface (``view_context["page"]``) means to the agent.

The frontend reports which page the user is on with every chat request
(``ChatRequest.view_context``), but the page value alone is an opaque string.
This module is the single place page *semantics* live — for each known
surface, two renderings of the same knowledge:

- ``session_line``: the one-line scope hint injected into the per-turn
  session block (``SessionContextMiddleware``), so the agent always knows
  where the user is and what "this"/"here" refers to without a tool call.
- ``prompt_section``: a short "# Current surface" block for the system
  prompt (``get_prompt``), carrying the behavioral/routing hints for that
  surface.

Both stay terse on purpose: the bulky view snapshot (viewport, layer lists,
widget contents) remains behind the ``inspect_view_context`` tool. Pages not
registered here degrade to the generic breadcrumb — the frontend owns the
``view_context`` shape and may ship new pages before the backend knows them.

Deliberately NOT done here: eagerly merging view scope into agent selections
(e.g. pre-filling ``aoi_selection`` from the dashboard's area). Ambient view
state stays reference material; tools *default* from it on explicit intent
(``add_to_dashboard`` reads ``view_context["dashboard_id"]``). See
docs/view-context-pages.md for the full design.
"""

from dataclasses import dataclass
from typing import Callable, Optional


def on_screen_counts(view: dict) -> list[str]:
    """The on-screen item counts shared by the breadcrumb renderings."""
    parts = []
    layers = view.get("visible_layers") or []
    if layers:
        parts.append(f"{len(layers)} layer(s)")
    aois = view.get("visible_aois") or []
    if aois:
        parts.append(f"{len(aois)} AOI(s) visible")
    insights = view.get("visible_insights") or []
    if insights:
        parts.append(f"{len(insights)} insight(s) on screen")
    return parts


def _map_session_line(view: dict) -> str:
    parts = on_screen_counts(view)
    detail = " · ".join(parts) if parts else "nothing reported on screen"
    return (
        f"View: map explorer — free exploration; {detail}. "
        "'Here' / 'this area' = what is on the map "
        "(call inspect_view_context for details)."
    )


def _dashboard_session_line(view: dict) -> str:
    dashboard_id = view.get("dashboard_id")
    name = view.get("dashboard_name")
    if name and dashboard_id:
        label = f"'{name}' ({dashboard_id})"
    elif dashboard_id:
        label = str(dashboard_id)
    else:
        label = "(id not reported)"
    return (
        f"View: dashboard {label} — a persistent collection of insight "
        "widgets for one area. 'This dashboard' = the one on screen; "
        "add_to_dashboard targets it by default "
        "(call inspect_view_context for its area and widgets)."
    )


@dataclass(frozen=True)
class ViewPage:
    """One frontend surface: its session-line and system-prompt renderings."""

    name: str
    session_line: Callable[[dict], str]
    # Takes the calling profile's available skill/tool names so it can drop
    # any "read skill `x`" mention the profile can't actually serve — the
    # same rule read_skill enforces at call time, applied here so the model
    # is never routed toward a skill it will just be told "not found" for.
    prompt_section: Callable[[frozenset[str]], str]


def _map_prompt(available: frozenset[str]) -> str:
    return (
        "The user is on the map explorer — free exploration of areas and "
        "layers. 'This area', 'here' or 'what I'm looking at' refer to what "
        "is on the map: check the session block or call "
        "inspect_view_context before asking the user for a location."
    )


def _dashboard_prompt(available: frozenset[str]) -> str:
    base = (
        "The user is viewing a dashboard — a persistent collection of "
        "insight widgets for one area. 'Add this' / 'add it to my "
        "dashboard' means add_to_dashboard, which defaults to the "
        "dashboard on screen. New analyses should use the dashboard's area "
        "unless the user names another place. Call inspect_view_context to "
        "see the dashboard's area and widgets"
    )
    if "dashboard" in available:
        return base + "; read skill `dashboard` for the compose workflow."
    return base + "."


PAGES: dict[str, ViewPage] = {
    page.name: page
    for page in (
        ViewPage(
            name="map",
            session_line=_map_session_line,
            prompt_section=_map_prompt,
        ),
        ViewPage(
            name="dashboard",
            session_line=_dashboard_session_line,
            prompt_section=_dashboard_prompt,
        ),
    )
}


def get_page(view: Optional[dict]) -> Optional[ViewPage]:
    """Resolve the registered page for a view snapshot, if any."""
    if not view:
        return None
    page = view.get("page")
    if not isinstance(page, str):
        return None
    return PAGES.get(page)


def prompt_section(
    page_name: Optional[str], available: frozenset[str] = frozenset()
) -> Optional[str]:
    """System-prompt surface hints for a page name; None when unknown.

    ``available`` is the calling profile's skill and tool names (see
    ``AgentConfig.skills()`` / ``.tool_names()``) — pages use it to drop any
    skill mention the profile can't actually serve.
    """
    if not isinstance(page_name, str):
        return None
    page = PAGES.get(page_name)
    return page.prompt_section(available) if page else None
