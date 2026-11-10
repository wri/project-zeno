"""Build an analytics API request from a case's own expectations.

**Deterministic only.** A GOLD case already asserts which query the agent should
build (``aoi_ids``, ``aoi_source``, ``dataset_id``, ``context_layer``,
``dataset_parameters``, dates), so the request is a deterministic function of
fields the case already carries. That is what makes the resulting check a
measure of the agent's retrieval fidelity rather than two models agreeing.

Every failure here is loud. A case that cannot be turned into a request must
abort the run  rather than silently score against nothing — an inferred AOI type
or a guessed dataset would re-introduce exactly the nondeterminism this mechanism
exists to remove.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from goldset.groundtruth.catalog import (
    AOI_TYPES,
    DEFAULT_CANOPY_COVER,
    Dataset,
    dataset_for,
)

# strip the `_1` at the end of gadm ids
_GADM_SUFFIX = re.compile(r"_[1-5]$")

# sLUC (9) is refused by zeno for anything but GADM levels 0-2; LGMS (12)
# documents the same restriction. Recorded so a future case fails at build
# time rather than returning a confusing API error.
_GADM_ONLY = {"9", "12"}

_FOREST_FILTERS = {
    "loss": frozenset({"primary_forest", "intact_forest"}),
    "gain": frozenset({"primary_forest"}),
    "extent": frozenset({"primary_forest"}),
}


class RequestError(Exception):
    """A case cannot be turned into an analytics request."""


@dataclass(frozen=True)
class AnalyticsRequest:
    endpoint: str
    payload: dict[str, Any]
    dataset: Dataset

    def describe(self) -> str:
        return f"POST {self.endpoint} {json.dumps(self.payload, sort_keys=True)}"


def _split(value: str | None) -> list[str]:
    return [part.strip() for part in (value or "").split(";") if part.strip()]


def normalise_aoi_id(raw: str, aoi_type: str) -> str:
    """Strip the GADM admin-level suffix; other sources pass through."""
    return _GADM_SUFFIX.sub("", raw) if aoi_type == "admin" else raw


def canopy_cover(expected: dict[str, str]) -> int:
    """The canopy threshold to send, from ``dataset_parameters``.

    Zeno takes ``int(max(param["values"]))`` off the agent's *narrowed*
    selection and otherwise defaults to 30. A case that does not pin
    ``dataset_parameters`` therefore relies on that default matching what the
    agent chose — true for 1-076, but a coincidence rather than a guarantee,
    which is why pinning it is recommended when authoring.
    """
    raw = (expected.get("dataset_parameters") or "").strip()
    if not raw:
        return DEFAULT_CANOPY_COVER
    try:
        for param in json.loads(raw):
            if param.get("name") == "canopy_cover" and param.get("values"):
                return int(max(param["values"]))
    except (ValueError, TypeError, KeyError) as exc:
        raise RequestError(f"unparseable dataset_parameters: {raw!r} ({exc})")
    return DEFAULT_CANOPY_COVER


def _years(expected: dict[str, str], dataset: Dataset) -> tuple[str, str]:
    """The analysis window, as years.

    ``cases/README.md`` forbids date expectations on annual datasets — the agent
    pulls the full range and slices in code — so most cases carry no dates and
    the window comes from the dataset's own coverage. The case's own temporal
    intent then lives in the ``ground_truth`` selector
    (``... WHERE tree_cover_loss_year=2019``), not in the request.
    """
    start = (expected.get("start_date") or dataset.start_date)[:4]
    end_raw = expected.get("end_date") or dataset.end_date
    if not end_raw:
        from datetime import UTC, datetime

        end_raw = datetime.now(UTC).strftime("%Y-%m-%d")
    return start, end_raw[:4]


def _dates(expected: dict[str, str], dataset: Dataset) -> tuple[str, str]:
    start = expected.get("start_date") or dataset.start_date
    end = expected.get("end_date") or dataset.end_date
    if not end:
        from datetime import UTC, datetime

        end = datetime.now(UTC).strftime("%Y-%m-%d")
    return start, end


def _snap(year: str, floor: int) -> str:
    """Tree cover gain reports in 5-year buckets; zeno snaps the request."""
    value = int(year)
    return str(max(floor, value - value % 5))


def forest_filter(layer: str | None, style: str) -> str | None:
    """The ``forest_filter`` this dataset accepts for a case's context layer.

    ``None`` when the dataset has no filter for that layer — the same as the
    agent sends.
    """
    return layer if layer in _FOREST_FILTERS.get(style, frozenset()) else None


def build_request(case: Any, dataset_id: str | None = None) -> AnalyticsRequest:
    """Build the analytics request a ground-truth case implies.

    ``dataset_id`` selects one alternative when the case offers several
    (``dataset_id: "0;11"``); it defaults to the case's first.
    """
    expected: dict[str, str] = dict(getattr(case, "expected", {}) or {})
    label = getattr(case, "id", "?")

    ids = _split(expected.get("aoi_ids"))
    if not ids:
        raise RequestError(
            f"{label}: no aoi_ids — the area exists only as prose in the query, "
            "which the harness must not geocode (that would redo the agent's own "
            "AOI resolution). Add an explicit area id."
        )

    source = (expected.get("aoi_source") or "").strip().lower()
    if not source:
        raise RequestError(
            f"{label}: no aoi_source — cannot determine the analytics aoi.type. "
            f"Expected one of {sorted(AOI_TYPES)}."
        )
    aoi_type = AOI_TYPES.get(source)
    if aoi_type is None:
        raise RequestError(f"{label}: unknown aoi_source {source!r}")

    alternatives = _split(expected.get("dataset_id"))
    chosen = (
        str(dataset_id).strip()
        if dataset_id
        else (alternatives[0] if alternatives else "")
    )
    if not chosen:
        raise RequestError(f"{label}: no dataset_id")
    dataset = dataset_for(chosen)
    if dataset is None:
        raise RequestError(f"{label}: unknown dataset_id {chosen!r}")
    if dataset.style == "unsupported":
        raise RequestError(
            f"{label}: dataset {chosen} ({dataset.name}) has no request builder yet"
        )
    if chosen in _GADM_ONLY and aoi_type != "admin":
        raise RequestError(
            f"{label}: dataset {chosen} accepts GADM areas only, got {source!r}"
        )

    payload: dict[str, Any] = {
        "aoi": {"type": aoi_type, "ids": [normalise_aoi_id(i, aoi_type) for i in ids]},
    }
    layer = (expected.get("context_layer") or "").strip() or None

    if dataset.style == "date":
        # Dates only, matching zeno's Integrated Alerts payload. The API rejects
        # unknown fields with a 422, so no `intersections` key is sent, not even
        # an empty one. A context layer on the case is ignored, as zeno ignores
        # it, so the harness sends the same request as the agent.
        start, end = _dates(expected, dataset)
        payload |= {"start_date": start, "end_date": end}
    elif dataset.style == "year":
        start, end = _years(expected, dataset)
        payload |= {"start_year": start, "end_year": end}
    elif dataset.style == "loss":
        start, end = _years(expected, dataset)
        payload |= {
            "start_year": start,
            "end_year": end,
            "forest_filter": forest_filter(layer, dataset.style),
            "intersections": list(dataset.intersections),
            "canopy_cover": canopy_cover(expected),
        }
    elif dataset.style == "gain":
        start, end = _years(expected, dataset)
        payload |= {
            "start_year": _snap(start, 2000),
            "end_year": _snap(end, 2005),
            "forest_filter": forest_filter(layer, dataset.style),
        }
    elif dataset.style == "canopy":
        payload |= {"canopy_cover": canopy_cover(expected)}
    elif dataset.style == "extent":
        payload |= {
            "forest_filter": forest_filter(layer, dataset.style),
            "canopy_cover": canopy_cover(expected),
        }
    # "none": AOI only.

    return AnalyticsRequest(dataset.endpoint, payload, dataset)
