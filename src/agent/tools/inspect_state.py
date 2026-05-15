import json
from typing import Annotated, Any, Dict, Optional

from langchain_core.messages import BaseMessage
from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

STATE_FIELD_NAMES = frozenset(
    {
        "messages",
        "user_persona",
        "aoi_selection",
        "dataset",
        "start_date",
        "end_date",
        "statistics",
        "insight",
        "follow_up_suggestions",
        "insight_id",
        "charts_data",
        "codeact_parts",
    }
)

MAX_STR_LEN = 500
MAX_CODEACT_LEN = 200
MAX_MESSAGE_CONTENT = 300
MAX_MESSAGES_SHOWN = 5
MAX_LIST_ITEMS = 20
MAX_DICT_KEYS = 30


def _truncate(value: str, limit: int = MAX_STR_LEN) -> str:
    if len(value) <= limit:
        return value
    return f"{value[:limit]}… ({len(value)} chars total)"


def _summarize_tabular_dict(data: dict) -> dict:
    columns = list(data.keys())
    row_counts = {
        key: len(values)
        for key, values in data.items()
        if isinstance(values, list)
    }
    summary: dict[str, Any] = {"columns": columns}
    if row_counts:
        summary["row_count"] = max(row_counts.values())
    return summary


def _summarize_list_records(data: list) -> dict:
    if not data:
        return {"row_count": 0}
    first = data[0]
    if isinstance(first, dict):
        return {
            "row_count": len(data),
            "columns": list(first.keys()),
        }
    return {"row_count": len(data), "item_type": type(first).__name__}


def _summarize_heavy_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _truncate(value)
    if isinstance(value, list):
        if not value:
            return []
        if all(isinstance(item, dict) for item in value):
            summary = _summarize_list_records(value)
            if len(value) > MAX_LIST_ITEMS:
                summary["truncated"] = True
                summary["shown"] = MAX_LIST_ITEMS
            return summary
        if len(value) > MAX_LIST_ITEMS:
            return {
                "length": len(value),
                "preview": [
                    _summarize_heavy_value(item)
                    for item in value[:MAX_LIST_ITEMS]
                ],
                "truncated": True,
            }
        return [_summarize_heavy_value(item) for item in value]
    if isinstance(value, dict):
        if all(isinstance(v, list) for v in value.values()):
            return _summarize_tabular_dict(value)
        if len(value) > MAX_DICT_KEYS:
            keys = list(value.keys())[:MAX_DICT_KEYS]
            return {
                "keys": keys,
                "key_count": len(value),
                "truncated": True,
            }
        return {
            key: _summarize_heavy_value(item) for key, item in value.items()
        }
    return _truncate(str(value))


def _summarize_aoi(aoi: dict) -> dict:
    return {
        "name": aoi.get("name"),
        "subtype": aoi.get("subtype"),
        "source": aoi.get("source"),
        "src_id": aoi.get("src_id"),
    }


def _summarize_aoi_selection(selection: dict | None) -> dict | None:
    if not selection:
        return selection
    aois = selection.get("aois") or []
    return {
        "name": selection.get("name"),
        "aoi_count": len(aois),
        "aois": [_summarize_aoi(aoi) for aoi in aois],
    }


def _summarize_statistics_entry(stat: dict) -> dict:
    summary = {
        key: value
        for key, value in stat.items()
        if key not in {"data", "aoi_id_to_name"}
    }
    data = stat.get("data")
    if data:
        summary["data"] = _summarize_heavy_value(data)
    elif stat.get("source_url"):
        summary["data"] = "(empty — use source_url to fetch full result)"
    else:
        summary["data"] = "(empty)"
    mapping = stat.get("aoi_id_to_name")
    if mapping:
        summary["aoi_id_to_name"] = {
            "mapping_count": len(mapping),
            "sample": dict(list(mapping.items())[:5]),
        }
    return summary


def _summarize_statistics(statistics: list | None) -> list | None:
    if statistics is None:
        return None
    return [_summarize_statistics_entry(stat) for stat in statistics]


def _summarize_chart(chart: dict) -> dict:
    summary = {key: value for key, value in chart.items() if key != "data"}
    data = chart.get("data")
    if data is not None:
        summary["data"] = _summarize_heavy_value(data)
    return summary


def _summarize_charts_data(charts: list | None) -> list | None:
    if charts is None:
        return None
    return [_summarize_chart(chart) for chart in charts]


def _summarize_codeact_parts(parts: list | None) -> list | None:
    if parts is None:
        return None
    summarized = []
    for part in parts:
        content = part.get("content", "")
        summarized.append(
            {
                "type": part.get("type"),
                "content": _truncate(str(content), MAX_CODEACT_LEN),
            }
        )
    return summarized


def _summarize_message(message: BaseMessage) -> dict:
    content = message.content
    if isinstance(content, list):
        content = json.dumps(content, default=str)
    else:
        content = str(content)
    return {
        "type": message.type,
        "content": _truncate(content, MAX_MESSAGE_CONTENT),
    }


def _summarize_messages(messages: list | None) -> dict | None:
    if messages is None:
        return None
    total = len(messages)
    recent = messages[-MAX_MESSAGES_SHOWN:]
    return {
        "count": total,
        "recent": [_summarize_message(message) for message in recent],
    }


def _summarize_value(key: str, value: Any) -> Any:
    if value is None:
        return None
    if key == "messages":
        return _summarize_messages(list(value))
    if key == "aoi_selection":
        return _summarize_aoi_selection(value)
    if key == "statistics":
        return _summarize_statistics(value)
    if key == "charts_data":
        return _summarize_charts_data(value)
    if key == "codeact_parts":
        return _summarize_codeact_parts(value)
    return _summarize_heavy_value(value)


def build_state_inspection(
    state: Dict,
    fields: Optional[list[str]] = None,
) -> dict:
    unknown = []
    selected = list(STATE_FIELD_NAMES)
    if fields:
        selected = []
        for field in fields:
            if field in STATE_FIELD_NAMES:
                selected.append(field)
            else:
                unknown.append(field)

    inspection: dict[str, Any] = {}
    if unknown:
        inspection["_unknown_fields"] = unknown

    for key in selected:
        if key not in state:
            continue
        inspection[key] = _summarize_value(key, state[key])

    return inspection


@tool("inspect_state")
def inspect_state(
    state: Annotated[Dict, InjectedState],
    fields: Optional[list[str]] = None,
) -> str:
    """Return a compact JSON snapshot of the current agent state.

    Use optional `fields` to request specific top-level keys only
    (e.g. ["aoi_selection", "dataset", "statistics"]).
    Large values (messages, AOI geometries, pull-data tables, chart rows)
    are summarized rather than dumped in full.
    """
    inspection = build_state_inspection(state, fields)
    return json.dumps(inspection, indent=2, default=str)
