"""Dashboard evaluator: dashboard creation, key AOI, and widget checks."""

from collections import Counter
from typing import Any

from goldset.evaluators.aoi_evaluator import _normalize_aoi_ids


def evaluate_dashboard_created(
    agent_state: dict[str, Any],
    expected_dashboard_created: bool | None,
) -> dict[str, Any]:
    """Check whether a dashboard was created in this turn.

    Tri-state scoring, mirroring evaluate_clarification's table:
        expected=True,  actual=True  -> 1.0 (correct)
        expected=True,  actual=False -> 0.0 (wrong: expected but not created)
        expected=False, actual=False -> 1.0 (correct)
        expected=False, actual=True  -> 0.0 (guardrail: unwanted dashboard)
        expected=None,  actual=True  -> 0.0 (unsolicited dashboard creation)
        expected=None,  actual=False -> None (not evaluated)

    Args:
        agent_state: Final agent state after execution
        expected_dashboard_created: Expected dashboard-creation behaviour
            (True/False/None, None meaning "no expectation")

    Returns:
        Dict with dashboard_created_score (0/1/None), actual_dashboard_created,
        actual_dashboard_id

    """
    dashboard_id = agent_state.get("dashboard_id")
    actual_dashboard_created = bool(dashboard_id)

    if expected_dashboard_created is None:
        score = 0.0 if actual_dashboard_created else None
    else:
        score = 1.0 if actual_dashboard_created == expected_dashboard_created else 0.0

    return {
        "dashboard_created_score": score,
        "actual_dashboard_created": actual_dashboard_created,
        "actual_dashboard_id": dashboard_id or None,
    }


def evaluate_dashboard_aoi(
    dashboard: dict[str, Any] | None,
    expected_aoi_ids: list[str] | None,
    expected_aoi_source: str = "",
) -> dict[str, Any]:
    """Check the dashboard has exactly one AOI, matching the expected AOI.

    Reuses the case's aoi_ids and aoi_source expectations rather than adding new
    ones: the dashboard's AOI should be the AOI the case already tests.

    Args:
        dashboard: Fetched dashboard payload (GET /api/dashboards/{id}), or None
            if no dashboard was created / the fetch failed
        expected_aoi_ids: Expected AOI IDs (reused from the AOI-selection check)
        expected_aoi_source: Expected AOI source (e.g. "gadm", "kba", "wdpa")

    Returns:
        Dict with dashboard_aoi_match_score (0/1/None), actual_dashboard_aoi_count,
        actual_dashboard_aoi_id, actual_dashboard_aoi_source

    """
    result: dict[str, Any] = {
        "dashboard_aoi_match_score": None,
        "actual_dashboard_aoi_count": None,
        "actual_dashboard_aoi_id": None,
        "actual_dashboard_aoi_source": None,
    }

    if dashboard is None:
        return result

    aois = dashboard.get("aois") or []
    result["actual_dashboard_aoi_count"] = len(aois)
    if aois:
        result["actual_dashboard_aoi_id"] = str([aoi.get("src_id", "") for aoi in aois])
        result["actual_dashboard_aoi_source"] = str(
            [aoi.get("source", "") for aoi in aois],
        )

    if not expected_aoi_ids:
        return result

    if len(aois) != 1:
        result["dashboard_aoi_match_score"] = 0.0
        return result

    aoi = aois[0]
    actual_source = aoi.get("source", "")
    normalized_actual, normalized_expected = _normalize_aoi_ids(
        [aoi.get("src_id", "")],
        expected_aoi_ids,
        actual_source,
    )
    id_match = set(normalized_actual) == set(normalized_expected)
    source_match = (
        not expected_aoi_source or actual_source.lower() == expected_aoi_source.lower()
    )
    result["dashboard_aoi_match_score"] = 1.0 if (id_match and source_match) else 0.0
    return result


def _widget_is_valid(widget: dict[str, Any]) -> bool:
    """Sanity-check a single widget's content resolved correctly."""
    widget_type = widget.get("widget_type")
    if widget_type == "insight":
        return widget.get("insight") is not None
    if widget_type == "text":
        # The API nests the markdown at config.text; the flat key is a
        # fallback for older payloads.
        config = widget.get("config") or {}
        return config.get("text") is not None or widget.get("text") is not None
    if widget_type == "map":
        config = widget.get("config") or {}
        snapshot = config.get("dataset") or config.get("imagery") or {}
        return bool(snapshot.get("tile_url"))
    if widget_type == "alerts":
        # The live alerts list (project-zeno PZB-1468, Stage 1): the widget
        # persists its area and a map-layer snapshot, never rows. Valid when
        # both are there to render from.
        config = widget.get("config") or {}
        aoi = (config.get("alerts") or {}).get("aoi") or {}
        snapshot = config.get("dataset") or {}
        return bool(aoi.get("src_id")) and bool(snapshot.get("tile_url"))
    return False


def evaluate_dashboard_widgets(
    dashboard: dict[str, Any] | None,
    expected_dashboard_widgets: list[str] | None,
) -> dict[str, Any]:
    """Check widget composition (multiset) and structural validity of widget content.

    Args:
        dashboard: Fetched dashboard payload (GET /api/dashboards/{id}), or None
            if no dashboard was created / the fetch failed
        expected_dashboard_widgets: Expected widget types, e.g. ["insight", "map"].
            Compared as a multiset (order doesn't matter, but counts do).

    Returns:
        Dict with dashboard_widgets_match_score (0/1/None): multiset match against
        expected; dashboard_widgets_valid_score (0/1/None): independent content
        sanity check, None when there are no widgets and none were expected; and
        actual_dashboard_widget_types (str of the actual widget_type list).

    """
    result: dict[str, Any] = {
        "dashboard_widgets_match_score": None,
        "dashboard_widgets_valid_score": None,
        "actual_dashboard_widget_types": None,
    }

    if dashboard is None:
        return result

    widgets = dashboard.get("widgets") or []
    actual_types = [w.get("widget_type", "") for w in widgets]
    result["actual_dashboard_widget_types"] = str(actual_types)

    if expected_dashboard_widgets:
        match = Counter(actual_types) == Counter(expected_dashboard_widgets)
        result["dashboard_widgets_match_score"] = 1.0 if match else 0.0

    if widgets:
        all_valid = all(_widget_is_valid(w) for w in widgets)
        result["dashboard_widgets_valid_score"] = 1.0 if all_valid else 0.0
    elif expected_dashboard_widgets:
        # Widgets were expected and there are none.
        result["dashboard_widgets_valid_score"] = 0.0
    else:
        # No widgets and none expected: nothing to validate. An empty dashboard
        # fails only when widgets were asked for. A case cannot say "expect zero
        # widgets" (an empty value means no expectation), so failing here would
        # penalise cases that never asked for content. If an empty dashboard
        # should always fail, that needs its own check.
        result["dashboard_widgets_valid_score"] = None

    return result
