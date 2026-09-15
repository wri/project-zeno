"""The word-similarity fallback in ``search_aois``, against the real database.

This is SQL behaviour, so it is tested against Postgres rather than mocked:
pg_trgm's ``%`` and ``%>`` operators and their two session thresholds are the
whole subject. ``test_aoi_lookup.py`` is the precedent for calling
``geocoding_helpers`` directly here instead of going through the router.

The rows are the real ones from the PZB-1392 cohort and from the recorded
"Para, Brazil" frame, so the two cases the fallback has to get right are the
two it actually meets in production: a term that retrieves nothing because an
inflected leaf falls under the similarity threshold, and a term that already
fills the limit and must not move.
"""

import pytest

from src.shared.geocoding_helpers import search_aois
from tests.conftest import seed_reference_aoi

AUTH = {"Authorization": "Bearer abc123"}

# Real WDPA rows. "Okapi" is the canonical name the geocoder extracts from
# "Show me the Okapi Wildlife Reserve"; the stored leaf is "Okapis".
_WDPA = [
    ("37043", "Okapis, Réserve de Faune, COD"),
    ("1445", "Ajai, Wildlife Reserve, UGA"),
    ("555512073", "Bomu, Réserve de Faune, COD"),
]

# The four rows of the recorded "Para, Brazil" frame, plus enough more real
# trigram matches to take the term over a limit of 10. Twelve rows clear
# `name % 'Para, Brazil'`, so the first pass fills the limit and the fallback
# must not fire.
_GADM = [
    ("BRA.16_1", "Paraná, Brazil", "state-province"),
    ("BRA.14_1", "Pará, Brazil", "state-province"),
    ("BRA.15_1", "Paraíba, Brazil", "state-province"),
    ("BRA.15.12_2", "Arara, Paraíba, Brazil", "district-county"),
    ("BRA", "Brazil", "country"),
    ("BRA.15.133_2", "Parari, Paraíba, Brazil", "district-county"),
    ("BRA.16.266_2", "Piên, Paraná, Brazil", "district-county"),
    ("BRA.16.48_2", "Cafeara, Paraná, Brazil", "district-county"),
    ("BRA.16.130_2", "Guaíra, Paraná, Brazil", "district-county"),
    ("BRA.15.84_2", "Ibiara, Paraíba, Brazil", "district-county"),
    ("BRA.16.174_2", "Japira, Paraná, Brazil", "district-county"),
    ("BRA.16.183_2", "Jussara, Paraná, Brazil", "district-county"),
]


@pytest.fixture
async def seeded_wdpa():
    for src_id, name in _WDPA:
        await seed_reference_aoi("wdpa", src_id, name, "protected-area")


@pytest.fixture
async def seeded_gadm():
    for src_id, name, subtype in _GADM:
        await seed_reference_aoi("gadm", src_id, name, subtype)


def _ids(frame):
    return list(frame["src_id"])


@pytest.mark.asyncio
async def test_a_term_below_the_trigram_threshold_finds_nothing_by_default(
    seeded_wdpa,
):
    """The PZB-1392 retrieval half, reproduced.

    ``similarity('Okapis, Réserve de Faune, COD', 'Okapi')`` is 0.1724, under
    the 0.2 ``pg_trgm.similarity_threshold``, so the ``%`` operator rejects the
    row outright. One trailing "s" is the whole difference.
    """
    found = await search_aois(
        name="Okapi", sources=["wdpa"], user_id=None, limit=10
    )

    assert _ids(found) == []


@pytest.mark.asyncio
async def test_the_word_similarity_fallback_finds_the_inflected_leaf(
    seeded_wdpa,
):
    """``word_similarity('Okapi', 'Okapis, …')`` is 0.8333, so containment finds it.

    And it stays discriminating: "Ajai" shares no trigram with "Okapi", so the
    row that the whole-name scorer used to pick is not dragged in with it.
    """
    found = await search_aois(
        name="Okapi",
        sources=["wdpa"],
        user_id=None,
        limit=10,
        word_similarity_fallback=True,
    )

    assert "37043" in _ids(found)
    assert "1445" not in _ids(found)


@pytest.mark.asyncio
async def test_the_fallback_does_not_fire_when_the_first_pass_fills_the_limit(
    seeded_gadm,
):
    """The saturated frame must come back byte-identical.

    Twelve seeded rows clear ``name % 'Para, Brazil'``, so the first pass
    already returns ten. Every row the fallback could add scores below the
    similarity threshold and so sorts below all ten under the unchanged
    ``ORDER BY similarity_score DESC``: it cannot displace anything, and the
    fallback is not even issued.
    """
    without = await search_aois(
        name="Para, Brazil", sources=["gadm"], user_id=None, limit=10
    )
    with_fallback = await search_aois(
        name="Para, Brazil",
        sources=["gadm"],
        user_id=None,
        limit=10,
        word_similarity_fallback=True,
    )

    assert len(without) == 10
    assert _ids(with_fallback) == _ids(without)
    assert list(with_fallback["name"]) == list(without["name"])


@pytest.mark.asyncio
async def test_the_fallback_never_outranks_the_rows_the_first_pass_found(
    seeded_wdpa,
):
    """An under-filled frame keeps its own rows on top and appends the rest."""
    found = await search_aois(
        name="Réserve de Faune",
        sources=["wdpa"],
        user_id=None,
        limit=10,
        word_similarity_fallback=True,
    )
    baseline = await search_aois(
        name="Réserve de Faune", sources=["wdpa"], user_id=None, limit=10
    )

    assert _ids(found)[: len(baseline)] == _ids(baseline)


@pytest.mark.asyncio
async def test_the_search_endpoint_does_not_opt_into_the_fallback(
    auth_override, client, seeded_wdpa
):
    """``GET /api/aois`` keeps exactly today's behaviour.

    The fallback is opt-in and only the geocoder passes it, so the endpoint the
    frontend calls is unchanged until that is reviewed on its own terms.
    """
    auth_override("test-user-wri")

    res = await client.get("/api/aois?name=Okapi&source=wdpa", headers=AUTH)

    assert res.status_code == 200, res.text
    assert res.json() == []
