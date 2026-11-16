"""Tests for the routing set format and its deterministic harness."""

import json

import pytest

from src.agent.datasets.handlers.analytics_handler import (
    GRASSLANDS_ID,
    TREE_COVER_GAIN_ID,
    TREE_COVER_LOSS_ID,
)
from tests.evals.routing.routing_set import (
    ENV_VAR,
    SEED_PATH,
    RoutingCase,
    load_routing_set,
    parse_case,
    routing_set_path,
    score,
    score_by_dataset,
    shown_route,
)


def _case(**fields):
    raw = {
        "id": "c1",
        "prompt": "tree cover loss in Pará",
        "dataset_id": TREE_COVER_LOSS_ID,
        "areas": 1,
        "route": "standard",
    } | fields
    return parse_case(raw)


def test_seed_set_loads():
    cases = load_routing_set(SEED_PATH)

    assert len(cases) >= 10
    assert {c.route for c in cases} == {"standard", "custom"}


@pytest.mark.parametrize(
    "fields, message",
    [
        ({"route": "maybe"}, "route must be"),
        ({"areas": 0}, "areas must be 1 or more"),
        ({"dataset_id": 999}, "unknown dataset_id"),
        ({"prompt": ""}, "missing fields"),
        ({"view": "no.such_view"}, "unknown view"),
        ({"view": "grasslands.by_year"}, "is not a view of dataset"),
        ({"route": "custom", "view": "tcl.annual_loss"}, "only a standard"),
    ],
)
def test_bad_rows_are_rejected(fields, message):
    with pytest.raises(ValueError, match=message):
        _case(**fields)


def test_an_external_csv_file_loads(tmp_path):
    path = tmp_path / "internal.csv"
    path.write_text(
        "id,prompt,dataset_id,areas,route,view,note\n"
        f"x1,loss in Pará,{TREE_COVER_LOSS_ID},1,standard,tcl.annual_loss,\n"
        f"x2,compare areas,{TREE_COVER_LOSS_ID},2,custom,,two areas\n",
        encoding="utf-8",
    )

    cases = load_routing_set(path)

    assert [c.id for c in cases] == ["x1", "x2"]
    assert cases[1].note == "two areas"


def test_the_environment_variable_names_the_file(tmp_path, monkeypatch):
    path = tmp_path / "internal.jsonl"
    row = {
        "id": "e1",
        "prompt": "p",
        "dataset_id": TREE_COVER_LOSS_ID,
        "areas": 1,
        "route": "standard",
    }
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    monkeypatch.setenv(ENV_VAR, str(path))

    assert routing_set_path() == path
    assert [c.id for c in load_routing_set()] == ["e1"]
    # An explicit path wins.
    assert routing_set_path(SEED_PATH) == SEED_PATH


def test_duplicate_ids_are_rejected(tmp_path):
    path = tmp_path / "dup.jsonl"
    row = json.dumps(
        {
            "id": "d",
            "prompt": "p",
            "dataset_id": TREE_COVER_LOSS_ID,
            "areas": 1,
            "route": "custom",
        }
    )
    path.write_text(f"{row}\n{row}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate"):
        load_routing_set(path)


def test_shown_route_needs_the_router_and_the_gate():
    one_area = _case()
    two_areas = _case(areas=2)
    gain = _case(dataset_id=TREE_COVER_GAIN_ID)

    assert shown_route(one_area, "standard") == "standard"
    assert shown_route(one_area, "custom") == "custom"
    assert shown_route(two_areas, "standard") == "custom"
    assert shown_route(gain, "standard") == "custom"


def test_score_counts_the_two_kinds_of_error():
    cases = [
        _case(id="ok-standard"),
        _case(id="ok-custom", route="custom", areas=3),
        # A one-area request that needs a custom chart: only the router
        # can send it to custom.
        _case(id="wrong-answer", route="custom"),
        # A curated chart can answer, but no view is enabled yet.
        _case(id="cost", dataset_id=TREE_COVER_GAIN_ID),
    ]

    result = score(cases)

    assert result.total == 4
    assert result.correct == 2
    assert result.wrong_answer == ["wrong-answer"]
    assert result.cost == ["cost"]
    assert result.summary() == "2/4 correct; wrong answer: 1; cost: 1"


def test_a_router_can_fix_a_wrong_answer():
    cases = [_case(id="wrong-answer", route="custom")]

    def router(case: RoutingCase):
        return "custom" if "running total" in case.prompt else "standard"

    assert score(cases).wrong_answer == ["wrong-answer"]
    fixed = [_case(id="w", route="custom", prompt="loss as a running total")]
    assert score(fixed, router).correct == 1


def test_score_by_dataset():
    cases = [_case(id="a"), _case(id="b", dataset_id=GRASSLANDS_ID)]

    result = score_by_dataset(cases)

    assert set(result) == {TREE_COVER_LOSS_ID, GRASSLANDS_ID}
    assert result[TREE_COVER_LOSS_ID].correct == 1
