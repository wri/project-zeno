"""Snapshot the full derived surface of every production profile.

Profiles declare deltas (``extends`` plus their own skills and tools), so
the complete bound surface — which subagents and tools a skill pulled in —
is never visible at the declaration site. These snapshots make it visible
and reviewable: adding a skill to a profile shows up in the diff as exactly
the subagents/tools it brought along.

When one of these fails after an intentional change, update the expected
manifest to the new ``describe()`` output — the point is that the change is
seen, not that the surface is frozen forever.
"""

from src.agent.agent_config import (
    BASE_PROFILE,
    CONCISE_PROFILE,
    CURATED_CHARTS_PROFILE,
    DEFAULT_PROFILE,
    EXPERIMENTAL_PROFILE,
    LGMS_PROFILE,
    default_registry,
)
from src.agent.graph import REPLY_STYLE_DEFAULT, get_prompt

BASE_MANIFEST = """\
profile: base
skills:
  (none)
subagents:
  - pick_aoi
  - pick_dataset
  - generate_insights
tools:
  - pull_data"""

DEFAULT_MANIFEST = """\
profile: default
extends: base
skills:
  - analyze (requires: pick_aoi, pick_dataset, pull_data, generate_insights)
  - capabilities
  - dashboard (requires: create_dashboard, add_to_dashboard, add_map_widget, add_text_widget, edit_text_widget, add_dashboard_section, edit_dashboard_section, move_dashboard_widget, inspect_view_context, send_nudge, search_insights)
  - explore (requires: search_blogs)
  - pull-data (requires: pick_aoi, pick_dataset, pull_data)
  - show-imagery (requires: pick_aoi, show_imagery, show_planet_imagery)
  - wri-insights (requires: search_blogs)
subagents:
  - pick_aoi
  - pick_dataset
  - generate_insights
  - search_blogs
  - update_insight_display
tools:
  - pull_data
  - read_skill
  - inspect_view_context
  - show_imagery
  - show_planet_imagery
  - search_insights
  - create_dashboard
  - add_to_dashboard
  - add_map_widget
  - add_text_widget
  - edit_text_widget
  - add_dashboard_section
  - edit_dashboard_section
  - move_dashboard_widget
  - send_nudge"""

EXPERIMENTAL_MANIFEST = """\
profile: experimental
skills:
  - analyze (requires: pick_aoi, pick_dataset, pull_data, generate_insights)
  - capabilities
  - dashboard (requires: create_dashboard, add_to_dashboard, add_map_widget, add_text_widget, edit_text_widget, add_dashboard_section, edit_dashboard_section, move_dashboard_widget, inspect_view_context, send_nudge, search_insights)
  - explore (requires: search_blogs)
  - pull-data (requires: pick_aoi, pick_dataset, pull_data)
  - show-imagery (requires: pick_aoi, show_imagery, show_planet_imagery)
  - wri-insights (requires: search_blogs)
subagents:
  - pick_aoi
  - pick_dataset
  - generate_insights
  - search_blogs
  - update_insight_display
tools:
  - pull_data
  - read_skill
  - inspect_view_context
  - show_imagery
  - show_planet_imagery
  - search_insights
  - create_dashboard
  - add_to_dashboard
  - add_map_widget
  - add_text_widget
  - edit_text_widget
  - add_dashboard_section
  - add_template_section
  - edit_dashboard_section
  - move_dashboard_widget
  - send_nudge"""


def test_base_profile_manifest():
    assert default_registry.resolve(BASE_PROFILE).describe() == BASE_MANIFEST


def test_default_profile_manifest():
    assert (
        default_registry.resolve(DEFAULT_PROFILE).describe()
        == DEFAULT_MANIFEST
    )


def test_experimental_profile_manifest():
    assert (
        default_registry.resolve(EXPERIMENTAL_PROFILE).describe()
        == EXPERIMENTAL_MANIFEST
    )


def test_lgms_profile_manifest():
    # The lgms profile only reveals a dataset: its skills and tools must stay
    # exactly the default surface.
    expected = DEFAULT_MANIFEST.replace(
        "profile: default\nextends: base\n",
        "profile: lgms\nextends: default\n",
        1,
    )
    assert default_registry.resolve(LGMS_PROFILE).describe() == expected


def test_curated_charts_profile_manifest():
    # The curated-charts profile only sets a flag: its skills and tools must
    # stay exactly the default surface (the flag swaps the generate_insights
    # spec for a variant of the same name).
    expected = DEFAULT_MANIFEST.replace(
        "profile: default\nextends: base\n",
        "profile: curated-charts\nextends: default\n"
        "flags: curated-charts-first\n",
        1,
    )
    assert (
        default_registry.resolve(CURATED_CHARTS_PROFILE).describe() == expected
    )


def test_concise_profile_manifest():
    # The concise profile only sets a flag. Its skills are the default
    # skills; the flag swaps the reply-style prompt text and puts two
    # dashboard tools in place of seven (FLAG_TOOL_MERGES).
    replaced = (
        "add_to_dashboard, add_map_widget, add_text_widget, "
        "edit_text_widget, add_dashboard_section, edit_dashboard_section, "
        "move_dashboard_widget"
    )
    expected = DEFAULT_MANIFEST.replace(
        "profile: default\nextends: base\n",
        "profile: concise\nextends: default\n"
        "flags: concise-replies, curated-charts-first\n",
        1,
    ).replace(replaced, "add_dashboard_item, edit_dashboard_item", 1)
    tool_lines = (
        "  - add_to_dashboard\n  - add_map_widget\n  - add_text_widget\n"
        "  - edit_text_widget\n  - add_dashboard_section\n"
        "  - edit_dashboard_section\n  - move_dashboard_widget\n"
    )
    assert tool_lines in expected
    expected = expected.replace(
        tool_lines, "  - add_dashboard_item\n  - edit_dashboard_item\n", 1
    )
    assert default_registry.resolve(CONCISE_PROFILE).describe() == expected


def test_concise_flag_uses_the_prompt_sections():
    default = get_prompt(default_registry.resolve(DEFAULT_PROFILE))
    concise = get_prompt(default_registry.resolve(CONCISE_PROFILE))
    assert REPLY_STYLE_DEFAULT in default
    assert REPLY_STYLE_DEFAULT not in concise
    assert concise.startswith("# 1. Role")


def test_every_production_profile_has_a_manifest_snapshot():
    """A new profile registered without a snapshot here would ship with an
    unreviewed surface."""
    snapshotted = {
        BASE_PROFILE,
        DEFAULT_PROFILE,
        EXPERIMENTAL_PROFILE,
        LGMS_PROFILE,
        CURATED_CHARTS_PROFILE,
        CONCISE_PROFILE,
    }
    registered = {config.name for config in default_registry.configs()}
    assert registered == snapshotted
