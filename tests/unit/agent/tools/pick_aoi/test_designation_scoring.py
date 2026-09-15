"""The PZB-1392 designation cohort, scored against real production frames.

The local dev database holds GADM only, so the protected-area and landmark rows
this bug is about cannot be retrieved offline. `tests/fixtures/
aoi_designation_candidates_v1.json` therefore records what production retrieval
actually returns for each search term of the gnw-gold-evals
`cases/challenge/aoi/designations` cohort (see
`scripts/record_designation_candidates.py`). Scoring those frames here gives a
deterministic before/after for the fix, with no database, no LLM and no network.

Two limits of the instrument, both deliberate:

* The recorded terms are `[place, canonical]` only. The live geocoder also emits
  `alternatives`, so a case can pass in production on a native spelling this
  fixture does not carry. The fixture is the stricter instrument, which is what
  a unit test wants.
* `GET /api/aois` returns no `similarity_score` (`AOISearchResult`), so the
  merge here cannot reproduce production's score ordering. It does not need to:
  the scorer's tie-break is order-independent, which
  `test_the_selection_is_independent_of_frame_order` pins.
"""

import json
from pathlib import Path

import pandas as pd
import pytest

from src.agent.subagents.pick_aoi.scoring import best_candidate_row

_FIXTURE = (
    Path(__file__).resolve().parents[5]
    / "tests"
    / "fixtures"
    / "aoi_designation_candidates_v1.json"
)

_DATA = json.loads(_FIXTURE.read_text(encoding="utf-8"))
_FRAMES = _DATA["frames"]
_CASES = {case["case_id"]: case for case in _DATA["cases"]}

# Cases the shipped scorer gets wrong, with why. Every one is xfail(strict) so
# that a case flipping to correct fails the suite until it is moved out of here.
_KNOWN_BAD = {
    "ch-aoi-132": "PZB-1392: 'National Reserve' outweighs the leaf; picks Samburu KEN",
    "ch-aoi-133": "PZB-1392: 'National Park' outweighs the leaf; picks Yanga AUS",
    "ch-aoi-134": (
        "retrieval, not scoring: 37043 is in neither recorded frame. "
        "See test_the_okapi_case_is_retrieval_bound_not_scoring_bound and "
        "tests/api/test_aois_search_fallback.py"
    ),
    "ch-aoi-142": (
        "PZB-1392: loses to 'Maria, National Park, AUS' by 0.0013. Passes 3/3 "
        "on prod, where the geocoder's `alternatives` carry the native "
        "spelling this fixture does not record"
    ),
    "ch-aoi-143": "PZB-1392: 'National Park' outweighs the leaf; picks Yanga AUS",
    "ch-aoi-146": "PZB-1392: stored leaf is 'La Serranía de Chiribiquete'",
    "ch-aoi-149": "PZB-1392: native phrasing translates to the same English place",
    "ch-aoi-154": (
        "leaf-vs-leaf collision: the stored leaf 'Parque Nacional Montanhas Do "
        "Tumucumaque' competes with leaves that are themselves "
        "'<X> Mountains National Park'. Needs SPEC-PR8 alias data, not weights. "
        "Passes 3/3 on prod, where `alternatives` carry the native spelling"
    ),
}


def _candidates(case: dict) -> pd.DataFrame:
    """Every row this case's terms retrieved, merged as the geocoder merges.

    ``query_aoi_database_multiterm`` concatenates the per-term frames and
    deduplicates on ``(source, src_id)``. The recorded rows carry no score, so
    the surviving copy is arbitrary -- and identical, because the rows are the
    same row.
    """
    source = case.get("source", "wdpa")
    rows = [row for term in case["terms"] for row in _FRAMES[source][term]]
    if not rows:
        return pd.DataFrame()
    return (
        pd.DataFrame(rows)
        .drop_duplicates(subset=["source", "src_id"])
        .reset_index(drop=True)
    )


def _case_params():
    for case_id, case in _CASES.items():
        marks = []
        if case_id in _KNOWN_BAD:
            marks.append(
                pytest.mark.xfail(strict=True, reason=_KNOWN_BAD[case_id])
            )
        yield pytest.param(case_id, marks=marks, id=case_id)


@pytest.mark.parametrize("case_id", list(_case_params()))
def test_the_designation_cohort_resolves_to_the_right_area(case_id):
    """Each cohort prompt selects the area the cohort expects.

    The failure this pins: every candidate in a source-narrowed search shares
    its designation and ISO3 segments with the rest of the frame, so a scorer
    that compares whole names ranks on the designation and returns a
    same-designation area in another country.
    """
    case = _CASES[case_id]
    selected = best_candidate_row(_candidates(case), case["terms"])

    assert selected is not None, f"{case_id}: no candidate retrieved"
    assert selected["src_id"] == case["expected_src_id"], (
        f"{case_id} {case['query']!r} selected "
        f"{selected['src_id']} {selected['name']!r}, expected "
        f"{case['expected_src_id']}"
    )


def test_the_okapi_case_is_retrieval_bound_not_scoring_bound():
    """ch-aoi-134's answer is in neither frame, so no scorer can reach it.

    ``Okapi`` scores 0.1724 against ``Okapis, Réserve de Faune, COD`` under
    pg_trgm, below the 0.2 ``similarity_threshold``, so it retrieves nothing at
    all; and the ten rows ``Okapi Wildlife Reserve`` does retrieve are other
    ``Wildlife Reserve`` areas that crowd 37043 out of the limit. The fix is the
    word-similarity fallback, covered in tests/api/test_aois_search_fallback.py.

    ch-aoi-149 is the control: the same place asked for natively yields the
    canonical ``Okapis``, which does retrieve 37043 -- so that case is scoring
    bound and is expected to flip when the scorer is fixed.
    """
    okapi = _CASES["ch-aoi-134"]
    retrieved = {
        row["src_id"] for row in _candidates(okapi).to_dict("records")
    }

    assert _FRAMES["wdpa"]["Okapi"] == []
    assert "37043" not in retrieved

    native = _CASES["ch-aoi-149"]
    native_retrieved = {
        row["src_id"] for row in _candidates(native).to_dict("records")
    }
    assert "37043" in native_retrieved


def test_the_selection_is_independent_of_frame_order():
    """The merge order is arbitrary here, so the tie-break must not care.

    Recorded rows carry no ``similarity_score``, so this fixture cannot
    reproduce the order production's merge produces. The scorer breaks ties on
    ``(-score, name, source, src_id)``, which makes that irrelevant -- and this
    is what licenses the fixture to ignore the score column.
    """
    for case_id, case in _CASES.items():
        candidates = _candidates(case)
        if candidates.empty:
            continue
        forwards = best_candidate_row(candidates, case["terms"])
        backwards = best_candidate_row(
            candidates.iloc[::-1].reset_index(drop=True), case["terms"]
        )

        assert forwards["src_id"] == backwards["src_id"], case_id


def test_every_cohort_case_retrieved_at_least_one_candidate():
    """A case whose frames are both empty would xfail for the wrong reason."""
    empty = [
        case_id for case_id, case in _CASES.items() if _candidates(case).empty
    ]

    assert empty == []
