"""Tests for the view-page registry and its two renderings.

Covers: page-aware session lines through format_session_block (Layer 1),
the "# Current surface" prompt section through get_prompt (Layer 2), and
the graceful fallback for unknown/absent pages.
"""

from src.agent.middleware import format_session_block
from src.agent.view_pages import get_page, prompt_section

MAP_STATE = {
    "view_context": {
        "page": "map",
        "viewport": {"bbox": [-74, -34, -34, 5], "zoom": 5},
        "visible_layers": [{"id": "tree-cover", "name": "Tree cover"}],
        "visible_aois": [
            {"source": "gadm", "src_id": "BRA.24_1", "name": "São Paulo"}
        ],
    }
}

DASHBOARD_STATE = {
    "view_context": {
        "page": "dashboard",
        "dashboard_id": "5c9f7dd8-0000-0000-0000-000000000000",
        "dashboard_name": "Paraná",
    }
}


# ---------------------------------------------------------------------------
# Registry resolution
# ---------------------------------------------------------------------------
def test_get_page_resolves_registered_pages():
    assert get_page(MAP_STATE["view_context"]).name == "map"
    assert get_page(DASHBOARD_STATE["view_context"]).name == "dashboard"


def test_get_page_unknown_or_malformed():
    assert get_page(None) is None
    assert get_page({}) is None
    assert get_page({"page": "report"}) is None  # unregistered page
    assert get_page({"page": {"nested": "junk"}}) is None  # not a string


# ---------------------------------------------------------------------------
# Layer 1: session-block lines
# ---------------------------------------------------------------------------
def test_map_session_line_carries_scope_semantics():
    block = format_session_block(MAP_STATE)
    assert "View: map explorer" in block
    assert "1 layer(s)" in block and "1 AOI(s) visible" in block
    assert "'this area'" in block.lower() or "'Here'" in block
    # Bulky detail stays behind the tool.
    assert "BRA.24_1" not in block
    assert "inspect_view_context" in block


def test_dashboard_session_line_names_the_dashboard():
    block = format_session_block(DASHBOARD_STATE)
    assert "View: dashboard 'Paraná'" in block
    assert "5c9f7dd8" in block
    assert "add_to_dashboard targets it by default" in block


def test_dashboard_session_line_without_name_or_id():
    no_name = {
        "view_context": {"page": "dashboard", "dashboard_id": "abc-123"}
    }
    assert "View: dashboard abc-123" in format_session_block(no_name)

    bare = {"view_context": {"page": "dashboard"}}
    assert "(id not reported)" in format_session_block(bare)


def test_unregistered_page_falls_back_to_generic_breadcrumb():
    state = {
        "view_context": {
            "page": "report",
            "visible_insights": [{}, {}],
        }
    }
    block = format_session_block(state)
    assert "View: report page · 2 insight(s) on screen" in block
    assert "call inspect_view_context for details" in block


# ---------------------------------------------------------------------------
# Layer 2: system-prompt surface section
# ---------------------------------------------------------------------------
def test_prompt_section_for_registered_pages():
    assert "map explorer" in prompt_section("map")
    dashboard = prompt_section("dashboard", frozenset({"dashboard"}))
    assert "add_to_dashboard" in dashboard
    assert "dashboard's area" in dashboard
    assert "skill `dashboard`" in dashboard


def test_prompt_section_unknown_is_none():
    assert prompt_section(None) is None
    assert prompt_section("report") is None
    assert prompt_section("") is None


def test_prompt_section_drops_skill_mention_when_unavailable():
    """A profile without the dashboard skill (its required tools aren't all
    bound) must not be told to read it — read_skill would just refuse."""
    dashboard = prompt_section("dashboard", frozenset())
    # The page-level orientation stays; only the skill pointer is gated.
    assert "add_to_dashboard" in dashboard
    assert "dashboard's area" in dashboard
    assert "skill `dashboard`" not in dashboard


def test_prompt_section_defaults_to_no_available_skills():
    assert "skill `dashboard`" not in prompt_section("dashboard")


def test_get_prompt_includes_surface_section_only_for_known_pages():
    from src.agent.graph import get_prompt

    plain = get_prompt()
    assert "# Current surface" not in plain

    dashboard = get_prompt(page="dashboard")
    assert "# Current surface" in dashboard
    assert "add_to_dashboard, which defaults to the dashboard" in dashboard
    # The rest of the prompt is unchanged.
    assert "# Routing" in dashboard
    # The default profile has no dashboard tools, so the dashboard skill
    # is unavailable — the surface section must not point at it.
    assert "skill `dashboard`" not in dashboard

    assert "# Current surface" not in get_prompt(page="report")


def test_get_prompt_dashboard_surface_names_the_skill_when_available():
    from src.agent.agent_config import EXPERIMENTAL_PROFILE, default_registry
    from src.agent.graph import get_prompt

    config = default_registry.resolve(EXPERIMENTAL_PROFILE)
    dashboard = get_prompt(config=config, page="dashboard")
    assert "skill `dashboard`" in dashboard
