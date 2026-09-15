"""The probes the 22-case cohort is blind to, and the baseline `main` sets.

`test_designation_scoring.py` gives every case BOTH search terms and a
source-narrowed frame. Real traffic does neither reliably, and a scorer tuned
only against that fixture passed it while regressing five separate things. This
module is the wider instrument, one probe per blind spot:

* **exact full-name round trip** -- hand the scorer a row's own stored name and
  it must return that row. This is the `_format_aoi_candidate` contract: an
  `aoi_choice` option carries the full stored name and is resubmitted verbatim,
  so a user clicking an option must land on what they clicked.
* **single term** -- only the user's own wording, no canonical spelling. The
  geocoder emits a canonical name, but it can be wrong, absent, or identical,
  and `ExtractedPlace` allows a bare `place`.
* **un-narrowed frames** -- what the geocoder searches when a narrowed search
  comes back empty and it retries every source. Only here do admin units and
  sites compete, so only here is the hierarchy term exercised against a site's
  own name.
* **native-order terms** -- the designation before the name, as most languages
  other than English write it.

Each probe records what `main`'s scorer does, because "better than the fixture
said" is not the bar; "no worse than what shipped" is. Two kinds of xfail live
here and they mean different things: a REGRESSION is something `main` gets
right and this branch does not, and it must go green before the branch is
mergeable; a pre-existing failure is one `main` gets wrong too, kept as a
target rather than a gate.

Two probes still fail, under every shape tried and under `main` too. They are
targets, not noise, and neither belongs to another ticket:

* **"Salonga" un-narrowed** selects the country Tonga (0.7667) over the park
  (0.7012). The name evidence is right -- "salonga" matches the park's leaf
  exactly and Tonga's only 0.77 -- but a country outranks a named site by 0.24
  of hierarchy, which is more than the name can recover. The hierarchy term
  exists for genuinely identical names ("Lisbon"); it should probably taper
  once the names differ, which is a change to `_HIERARCHY_SCORES`, not to the
  leaf comparison, and wants its own before/after.
* **"Parc National de l'Ivindo"** selects "Parc National de Toubkal" (0.6217)
  over "Ivindo, Parc National, GAB" (0.4120). Toubkal's stored LEAF is itself
  mostly designation words, so it covers three of the term's four words while
  the correct row's leaf is the single word "Ivindo". Separating these needs to
  know that "parc national de" is a designation, which no comparison of two
  strings can: it needs the designation held in its own column, which is
  SPEC-PR8's `designation_local` / `designation_en`.

Baseline, measured 2026-09-15 against `main` @ 65f0d8a4:

===========================  ============  ==============
probe                        main          this branch
===========================  ============  ==============
exact full-name round trip   0/150 wrong   0/150 wrong
single term, user wording    7/22          13/22
un-narrowed frames           3/4           3/4
native-order terms           0/3           2/3
Niger > Nigeria              yes           yes
bare "Para" > Parana         yes           yes
===========================  ============  ==============
"""

import json
from pathlib import Path

import pandas as pd
import pytest

from src.agent.subagents.pick_aoi.scoring import (
    _score_candidate,
    best_candidate_row,
)

_FIXTURES = Path(__file__).resolve().parents[5] / "tests" / "fixtures"

_ROUNDTRIP = json.loads(
    (_FIXTURES / "aoi_exact_name_roundtrip_v1.json").read_text(
        encoding="utf-8"
    )
)
_COHORT = json.loads(
    (_FIXTURES / "aoi_designation_candidates_v1.json").read_text(
        encoding="utf-8"
    )
)
_FRAMES = _COHORT["frames"]
_UNNARROWED = _FRAMES["(all sources)"]


def _frame(rows):
    return (
        pd.DataFrame(rows)
        .drop_duplicates(subset=["source", "src_id"])
        .reset_index(drop=True)
    )


# ---------------------------------------------------------------------------
# Exact full-name round trip
# ---------------------------------------------------------------------------


def test_a_rows_own_name_resolves_back_to_that_row():
    """150 real GADM rows, each searched under its own stored name.

    `main` gets all 150 right, because its whole-name similarity carried
    weight 0.5 and an exact string scored all of it. Every failure seen while
    developing this branch was a child whose leaf repeats its parent's
    ("Senga, Senga, Butezi, Ruyigi, Burundi"), where the leaf comparison ties
    and the hierarchy term hands it to the parent -- so the user clicking a
    municipality would get the district containing it.
    """
    wrong = []
    for probe in _ROUNDTRIP["probes"]:
        selected = best_candidate_row(
            _frame(probe["candidates"]), [probe["name"]]
        )
        if selected["src_id"] != probe["src_id"]:
            wrong.append((probe["name"], selected["name"]))

    assert wrong == [], (
        f"{len(wrong)} of {len(_ROUNDTRIP['probes'])} rows did not resolve to "
        f"themselves (main: 0). First: {wrong[:3]}"
    )


# ---------------------------------------------------------------------------
# Single term: the user's wording alone
# ---------------------------------------------------------------------------

# What each cohort case resolves to on `main` when only the user's own wording
# is searched. main scores 7 of 22; the numbers are here so a change that
# trades one of these away is visible rather than silent.
_PLACE_ONLY_MAIN_BASELINE = 7


def _place_only_hits():
    hits = []
    for case in _COHORT["cases"]:
        source = case.get("source", "wdpa")
        rows = _FRAMES[source][case["terms"][0]]
        if not rows:
            continue
        selected = best_candidate_row(_frame(rows), [case["terms"][0]])
        if selected["src_id"] == case["expected_src_id"]:
            hits.append(case["case_id"])
    return hits


def test_the_users_own_wording_alone_beats_the_main_baseline():
    """A canonical spelling must be extra recall, never the only thing working.

    The geocoder emits one, but it can be absent, wrong, or identical to the
    place name, and `ExtractedPlace` is valid with a bare `place`. Anything
    that only works because two terms disagree is a coincidence, not a fix.
    """
    hits = _place_only_hits()

    assert len(hits) >= _PLACE_ONLY_MAIN_BASELINE, (
        f"single-term accuracy {len(hits)}/22 is below main's "
        f"{_PLACE_ONLY_MAIN_BASELINE}/22"
    )


# ---------------------------------------------------------------------------
# Un-narrowed frames: a site's own name against an admin unit's
# ---------------------------------------------------------------------------


_PREEXISTING = "main fails this too; not a regression, a Part B target"


@pytest.mark.parametrize(
    "term,expected_src_id",
    [
        ("Kahuzi-Biega", "1082"),
        ("Odzala-Kokoua", "643"),
        ("Virunga", "166889"),
        pytest.param(
            "Salonga",
            "555697863",
            marks=pytest.mark.xfail(
                strict=True,
                reason=_PREEXISTING + ': main selects "Tonga" as well',
            ),
        ),
    ],
)
def test_an_exactly_named_site_beats_a_differently_named_admin_unit(
    term, expected_src_id
):
    """Reached whenever a narrowed search is empty and every source is retried.

    The hierarchy term exists so that a bare "Lisbon" prefers the Portuguese
    district to a small "Lisbon Forest Preserve" -- two places with the SAME
    name, where nothing else can separate them. It must not also overrule the
    name itself: "Kahuzi-Biega" names the park exactly and only half-matches
    the province "Kahuzi", so the park has to win.
    """
    selected = best_candidate_row(_frame(_UNNARROWED[term]), [term])

    assert (
        selected["src_id"] == expected_src_id
    ), f"{term!r} selected {selected['name']!r}"


# ---------------------------------------------------------------------------
# Native-order terms: designation first
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "term,expected_src_id",
    [
        ("Parque Nacional Yasuni", "186"),
        # This one the leaf comparison already fixed: main selects "Bomu,
        # Réserve de Faune, COD" and this branch selects the right row.
        ("Reserve de faune a Okapis", "37043"),
        pytest.param(
            "Parc National de l'Ivindo",
            "303873",
            marks=pytest.mark.xfail(
                strict=True,
                reason=_PREEXISTING + ": main selects Mohéli as well",
            ),
        ),
    ],
    ids=["yasuni-es", "okapis-fr", "ivindo-fr"],
)
def test_a_native_order_term_resolves_as_well_as_an_english_one(
    term, expected_src_id
):
    """English puts the designation last; most other languages do not.

    GEOCODER_PROMPT translates into English, so this is not the common path --
    but the `alternatives` field exists precisely to carry native spellings,
    and scoring takes the best score per candidate across terms. A term that
    scores the correct row near zero cannot help, and can only ever raise a
    decoy, so word order must not be load-bearing.
    """
    selected = best_candidate_row(_frame(_FRAMES["wdpa"][term]), [term])

    assert (
        selected["src_id"] == expected_src_id
    ), f"{term!r} selected {selected['name']!r}"


# ---------------------------------------------------------------------------
# Pairwise invariants the frames above cannot state
# ---------------------------------------------------------------------------


def test_an_exact_name_outscores_a_longer_name_that_contains_it():
    """ "Niger" is not "Nigeria", and a bare term is the case that proves it.

    The Pará test cannot: its term carries a parent, so the candidate never
    starts with the term and the prefix branch is never taken.
    """
    exact = _score_candidate("Niger", "Niger", "country")
    longer = _score_candidate("Niger", "Nigeria", "country")

    assert exact > longer, f"exact {exact:.4f} vs longer {longer:.4f}"


def test_a_bare_accented_leaf_still_prefers_its_own_row():
    """The PZB-1272 case with no parent to lean on."""
    para = _score_candidate("Para", "Pará, Brazil", "state-province")
    parana = _score_candidate("Para", "Paraná, Brazil", "state-province")

    assert para > parana, f"Pará {para:.4f} vs Paraná {parana:.4f}"


def test_a_short_leaf_does_not_match_a_longer_one_perfectly():
    """ "Rio" must not tie "Río Puré" for a term naming Río Puré.

    A comparison that takes the best score over the term's leading words with
    no coverage requirement scores both a perfect 1.0, which is how a
    one-word decoy reaches the top of a frame.
    """
    exact = _score_candidate(
        "Rio Pure National Park",
        "Río Puré, Parque Nacional Natural, COL",
        "protected-area",
    )
    decoy = _score_candidate(
        "Rio Pure National Park", "Rio, Nature Park, USA", "protected-area"
    )

    assert exact > decoy, f"Río Puré {exact:.4f} vs Rio {decoy:.4f}"
