"""The routing set: labelled chart requests for curated charts first.

Each case is a request of a user for a chart and the route that it must
take (docs/curated-charts-first-plan.md, "Evals"):

- ``standard``: a curated chart answers the request.
- ``custom``: the request needs a chart from the code executor.

The harness is deterministic. A router selects ``standard`` or ``custom``
for a case, as the orchestrator does with the ``chart`` argument of
``generate_insights``. The code gate (src/api/services/charts/gate.py) then
decides if a curated chart is shown. The score counts two kinds of error
separately:

- wrong answer: a curated chart is shown for a request that needs a custom
  chart;
- cost: the code executor runs for a request that a curated chart answers.

The seed file (``seed.jsonl``) holds a small set of invented prompts. The
real prompts of the demand analysis are internal to WRI: keep them out of
this repository, and give their file to the loader with a path or with the
``ZENO_ROUTING_SET`` environment variable.

File format: JSON Lines (``.jsonl``) or CSV (``.csv``) with these fields:

- ``id``: a unique name of the case.
- ``prompt``: the request of the user.
- ``dataset_id``: the dataset of the pull (src/agent/datasets/catalog).
- ``areas``: the number of areas in the pull, 1 or more.
- ``route``: ``standard`` or ``custom``.
- ``view`` (optional): the id of the view that answers a ``standard`` case.
- ``note`` (optional): free text.

Run the score of the default router (always ``standard``, the default of
the tool) with::

    uv run python -m tests.evals.routing.routing_set [path]
"""

import csv
import json
import os
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Literal, Optional, get_args

from src.agent.datasets.config import DATASETS
from src.api.services.charts.gate import view_gate
from src.api.services.charts.views import get_view

Route = Literal["standard", "custom"]
ROUTES: tuple[str, ...] = get_args(Route)

SEED_PATH = Path(__file__).with_name("seed.jsonl")
ENV_VAR = "ZENO_ROUTING_SET"

_DATASET_IDS = frozenset(entry["dataset_id"] for entry in DATASETS)


@dataclass(frozen=True)
class RoutingCase:
    id: str
    prompt: str
    dataset_id: int
    areas: int
    route: Route
    view: Optional[str] = None
    note: str = ""


def parse_case(raw: dict, where: str = "") -> RoutingCase:
    """One case from a row of the file. Raises ValueError for a bad row."""
    prefix = f"{where}: " if where else ""
    missing = [
        key
        for key in ("id", "prompt", "dataset_id", "areas", "route")
        if raw.get(key) in (None, "")
    ]
    if missing:
        raise ValueError(f"{prefix}missing fields {missing}")
    try:
        dataset_id = int(raw["dataset_id"])
        areas = int(raw["areas"])
    except (TypeError, ValueError) as error:
        raise ValueError(
            f"{prefix}dataset_id and areas are numbers"
        ) from error
    if dataset_id not in _DATASET_IDS:
        raise ValueError(f"{prefix}unknown dataset_id {dataset_id}")
    if areas < 1:
        raise ValueError(f"{prefix}areas must be 1 or more, not {areas}")
    route = str(raw["route"]).strip()
    if route not in ROUTES:
        raise ValueError(f"{prefix}route must be one of {ROUTES}")
    view_id = (raw.get("view") or "").strip() or None
    if view_id is not None:
        view = get_view(view_id)
        if view is None:
            raise ValueError(f"{prefix}unknown view {view_id!r}")
        if view.dataset_id != dataset_id:
            raise ValueError(
                f"{prefix}view {view_id!r} is not a view of dataset "
                f"{dataset_id}"
            )
        if route != "standard":
            raise ValueError(f"{prefix}only a standard case names a view")
    return RoutingCase(
        id=str(raw["id"]).strip(),
        prompt=str(raw["prompt"]),
        dataset_id=dataset_id,
        areas=areas,
        route=route,  # type: ignore[arg-type]
        view=view_id,
        note=str(raw.get("note") or ""),
    )


def routing_set_path(path: Optional[str | Path] = None) -> Path:
    """The file to load: `path`, else the environment variable, else the
    seed file."""
    if path:
        return Path(path)
    if os.environ.get(ENV_VAR):
        return Path(os.environ[ENV_VAR])
    return SEED_PATH


def _rows(path: Path) -> Iterable[tuple[str, dict]]:
    if path.suffix == ".csv":
        with path.open(newline="", encoding="utf-8") as handle:
            for number, row in enumerate(csv.DictReader(handle), 2):
                yield f"{path.name}:{number}", row
        return
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            if line.strip():
                yield f"{path.name}:{number}", json.loads(line)


def load_routing_set(path: Optional[str | Path] = None) -> list[RoutingCase]:
    """The cases of a routing set file (see `routing_set_path`)."""
    cases = [
        parse_case(raw, where) for where, raw in _rows(routing_set_path(path))
    ]
    duplicates = [i for i, n in Counter(c.id for c in cases).items() if n > 1]
    if duplicates:
        raise ValueError(f"duplicate case ids {duplicates}")
    return cases


def shown_route(case: RoutingCase, choice: Route) -> Route:
    """The route that the user gets: a curated chart only when the router
    selects ``standard`` and the code gate passes."""
    if choice == "standard" and view_gate(case.dataset_id, case.areas).passed:
        return "standard"
    return "custom"


@dataclass
class RoutingScore:
    total: int = 0
    correct: int = 0
    # Case ids of each kind of error.
    wrong_answer: list[str] = field(default_factory=list)
    cost: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"{self.correct}/{self.total} correct; "
            f"wrong answer: {len(self.wrong_answer)}; "
            f"cost: {len(self.cost)}"
        )


def score(
    cases: Iterable[RoutingCase],
    router: Callable[[RoutingCase], Route] = lambda case: "standard",
) -> RoutingScore:
    """The score of `router` on the cases. The default router selects
    ``standard`` for each case, as the tool does when the orchestrator
    gives no ``chart``: it measures the code gate alone."""
    result = RoutingScore()
    for case in cases:
        result.total += 1
        shown = shown_route(case, router(case))
        if shown == case.route:
            result.correct += 1
        elif shown == "standard":
            result.wrong_answer.append(case.id)
        else:
            result.cost.append(case.id)
    return result


def score_by_dataset(
    cases: Iterable[RoutingCase],
    router: Callable[[RoutingCase], Route] = lambda case: "standard",
) -> dict[int, RoutingScore]:
    by_dataset: dict[int, list[RoutingCase]] = {}
    for case in cases:
        by_dataset.setdefault(case.dataset_id, []).append(case)
    return {
        dataset_id: score(group, router)
        for dataset_id, group in sorted(by_dataset.items())
    }


def main(argv: list[str]) -> None:
    cases = load_routing_set(argv[1] if len(argv) > 1 else None)
    print(f"all datasets: {score(cases).summary()}")
    for dataset_id, result in score_by_dataset(cases).items():
        print(f"dataset {dataset_id}: {result.summary()}")
        if result.wrong_answer:
            print(f"  wrong answer: {', '.join(result.wrong_answer)}")


if __name__ == "__main__":
    main(sys.argv)
