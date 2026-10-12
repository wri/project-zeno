# ---------------------------------------------------------------------------
# Unit tests for check_aoi_selection (no DB, no LLM)
# ---------------------------------------------------------------------------


import pandas as pd

from src.agent.subagents.pick_aoi.tool import (
    SUBREGION_LIMIT,
    SUBREGION_LIMIT_ADMIN,
    AOIIndex,
    check_aoi_selection,
    check_concession_matches,
)


def _make_aois(source: str, n: int) -> list[AOIIndex]:
    return [
        AOIIndex(
            source=source,
            src_id=f"{source}_{i}",
            name=f"Area {i}",
            subtype="state-province",
        )
        for i in range(n)
    ]


async def test_check_aoi_selection_returns_none_when_gadm_within_limit():
    result = await check_aoi_selection(
        _make_aois("gadm", SUBREGION_LIMIT_ADMIN)
    )
    assert result is None


async def test_check_aoi_selection_returns_error_message_when_gadm_exceeds_limit():
    aois = _make_aois("gadm", SUBREGION_LIMIT_ADMIN + 1)
    result = await check_aoi_selection(aois)
    assert result is not None
    assert str(SUBREGION_LIMIT_ADMIN + 1) in result
    assert str(SUBREGION_LIMIT_ADMIN) in result


async def test_check_aoi_selection_kba_within_limit():
    result = await check_aoi_selection(_make_aois("kba", SUBREGION_LIMIT))
    assert result is None


async def test_check_aoi_selection_kba_exceeds_limit():
    aois = _make_aois("kba", SUBREGION_LIMIT + 1)
    result = await check_aoi_selection(aois)
    assert result is not None
    assert str(SUBREGION_LIMIT + 1) in result


async def test_check_aoi_selection_wdpa_exceeds_limit():
    aois = _make_aois("wdpa", SUBREGION_LIMIT + 1)
    result = await check_aoi_selection(aois)
    assert result is not None


async def test_check_aoi_selection_multiple_sources():
    aois = _make_aois("gadm", 1) + _make_aois("kba", 1)
    result = await check_aoi_selection(aois)
    assert result is not None
    assert "multiple sources" in result.lower()


# ---------------------------------------------------------------------------
# Unit tests for check_concession_matches (no DB, no LLM)
# ---------------------------------------------------------------------------


def _concession_frame(rows: list[tuple[str, str, bool]]) -> pd.DataFrame:
    """Candidate rows as ``(source, src_id, corrected)``."""
    return pd.DataFrame(
        [
            {
                "source": source,
                "src_id": src_id,
                "name": f"Palong 17, {src_id}, Oil palm concession, MYS",
                "leaf": "Palong 17",
                "subtype": "oil-palm-concession",
                "corrected": corrected,
            }
            for source, src_id, corrected in rows
        ]
    )


def _concession(src_id: str, source: str = "oil_palm") -> AOIIndex:
    return AOIIndex(
        source=source,
        src_id=src_id,
        name=f"Palong 17, {src_id}, Oil palm concession, MYS",
        subtype="oil-palm-concession",
    )


async def test_check_concession_matches_nudges_on_several_parcels():
    frame = _concession_frame(
        [("oil_palm", "1", False), ("oil_palm", "2", False)]
    )
    result = await check_concession_matches([_concession("1")], [frame])
    assert result is not None
    assert "Palong 17" in result
    assert "map" in result


async def test_check_concession_matches_none_for_a_single_match():
    frame = _concession_frame(
        [("oil_palm", "1", False), ("gadm", "MYS.1_1", False)]
    )
    assert await check_concession_matches([_concession("1")], [frame]) is None


async def test_check_concession_matches_ignores_corrected_rows():
    frame = _concession_frame(
        [("oil_palm", "1", False), ("oil_palm", "2", True)]
    )
    assert await check_concession_matches([_concession("1")], [frame]) is None


async def test_check_concession_matches_skips_other_sources():
    frame = _concession_frame([("wdpa", "1", False), ("wdpa", "2", False)])
    selected = _concession("1", source="wdpa")
    assert await check_concession_matches([selected], [frame]) is None
