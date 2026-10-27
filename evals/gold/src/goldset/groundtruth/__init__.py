"""Run-time ground truth: fetch a numeric case's expected values from the
analytics API instead of pinning them in the case file.

A numeric case that carries a hand-verified ``expected.answer`` is a snapshot of
a mutable dataset: when a new data vintage lands the row fails for reasons that
have nothing to do with the agent, and refreshing the figure mints a new ``uid``
(see ``canonical.py``) which resets that row's regression history. A case that
carries ``expected.ground_truth`` instead names *which figure* rather than *what
value*, so its uid survives every vintage.

The agent pulls from this same API, so comparing the two measures **retrieval
and usage fidelity** — did the agent build the right query and use the returned
numbers correctly — not the quality of the underlying data.
"""

from goldset.groundtruth.catalog import CatalogError, Dataset, datasets
from goldset.groundtruth.client import AnalyticsClient, AnalyticsError
from goldset.groundtruth.fetch import (
    GROUND_TRUTH_FIELD,
    GroundTruth,
    is_ground_truth,
    prefetch,
)
from goldset.groundtruth.request import RequestError, build_request
from goldset.groundtruth.selector import Selector, SelectorError, parse_selector

__all__ = [
    "GROUND_TRUTH_FIELD",
    "AnalyticsClient",
    "AnalyticsError",
    "CatalogError",
    "Dataset",
    "GroundTruth",
    "RequestError",
    "Selector",
    "SelectorError",
    "build_request",
    "datasets",
    "is_ground_truth",
    "parse_selector",
    "prefetch",
]
