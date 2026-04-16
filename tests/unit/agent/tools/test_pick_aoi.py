# ---------------------------------------------------------------------------
# Unit tests for check_aoi_selection (no DB, no LLM)
# ---------------------------------------------------------------------------


from src.agent.tools.pick_aoi.tool import (
    SUBREGION_LIMIT,
    SUBREGION_LIMIT_ADMIN,
    AOIIndex,
    check_aoi_selection,
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
