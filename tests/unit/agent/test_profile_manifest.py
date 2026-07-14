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
    DEFAULT_PROFILE,
    EXPERIMENTAL_PROFILE,
    default_registry,
)

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
  - pull-data (requires: pick_aoi, pick_dataset, pull_data)
subagents:
  - pick_aoi
  - pick_dataset
  - generate_insights
tools:
  - pull_data
  - read_skill"""

EXPERIMENTAL_MANIFEST = """\
profile: experimental
extends: default
skills:
  - analyze (requires: pick_aoi, pick_dataset, pull_data, generate_insights)
  - capabilities
  - dashboard (requires: create_dashboard, add_to_dashboard, add_map_widget)
  - explore (requires: search_blogs)
  - pull-data (requires: pick_aoi, pick_dataset, pull_data)
  - show-imagery (requires: pick_aoi, show_imagery)
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
  - search_insights
  - create_dashboard
  - add_to_dashboard
  - add_map_widget"""


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


def test_every_production_profile_has_a_manifest_snapshot():
    """A new profile registered without a snapshot here would ship with an
    unreviewed surface."""
    snapshotted = {BASE_PROFILE, DEFAULT_PROFILE, EXPERIMENTAL_PROFILE}
    registered = {config.name for config in default_registry.configs()}
    assert registered == snapshotted
