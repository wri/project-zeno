"""Tests for the ranking builder of the ranked bar chart."""

import pytest

from src.api.services.charts.ranking import (
    RankedArea,
    build_ranked_areas,
    build_ranking,
    shares_allowed,
    split_name,
)


def _area(area_id, name=None, parent=None, source="gadm"):
    return RankedArea(area_id, name or area_id, parent, source)


def _row(area_id, value, year=2020, column="area_ha"):
    return {"aoi_id": area_id, column: value, "tree_cover_loss_year": year}


def test_a_name_with_one_part_has_no_parent():
    assert split_name("Kenya") == ("Kenya", None)
    assert split_name("Bom Jesus, Piauí, Brazil") == ("Bom Jesus", "Piauí")


def test_the_areas_come_from_the_parallel_lists_of_the_pull():
    areas = build_ranked_areas(
        ["BOL.3.1_2", "KEN.33"],
        ["Cercado, Beni, Bolivia", "Narok, Kenya"],
        ["gadm", "gadm"],
        {"BOL.3.1": "Cercado", "KEN.33": "Narok"},
    )

    assert areas == [
        RankedArea("BOL.3.1", "Cercado", "Beni", "gadm"),
        RankedArea("KEN.33", "Narok", "Kenya", "gadm"),
    ]


def test_the_name_falls_back_to_the_first_part_of_the_full_name():
    (area,) = build_ranked_areas(["KEN.33_1"], ["Narok, Kenya"], ["gadm"])

    assert area.name == "Narok"
    assert area.id == "KEN.33"


def test_lists_that_differ_in_length_raise():
    with pytest.raises(ValueError, match="do not agree"):
        build_ranked_areas(["A.1"], ["A", "B"], ["gadm"])


def test_an_area_twice_in_the_pull_raises():
    with pytest.raises(ValueError, match="twice"):
        build_ranked_areas(["A.1_1", "A.1"], ["A", "A"], ["gadm", "gadm"])


def test_values_are_summed_per_area_and_sorted_largest_first():
    areas = [_area("K.1", "One"), _area("K.2", "Two"), _area("K.3", "Three")]
    rows = [
        _row("K.1", 10, 2020),
        _row("K.2", 70.5, 2020),
        _row("K.1", 15, 2021),
        _row("K.3", 5, 2020),
    ]

    ranking = build_ranking(rows, areas, "area_ha")

    assert [(r["rank"], r["aoi_id"], r["area_ha"]) for r in ranking] == [
        (1, "K.2", 70.5),
        (2, "K.1", 25),
        (3, "K.3", 5),
    ]
    # Only the ranking columns, no year.
    assert set(ranking[0]) == {
        "rank",
        "aoi_id",
        "name",
        "parent",
        "area_ha",
        "share_pct",
    }


def test_an_area_with_no_rows_is_a_row_of_zero():
    areas = [_area("K.1"), _area("K.2", "Zed"), _area("K.3", "Alpha")]

    ranking = build_ranking([_row("K.1", 8)], areas, "area_ha")

    assert [(r["aoi_id"], r["area_ha"], r["rank"]) for r in ranking] == [
        ("K.1", 8, 1),
        ("K.3", 0, 2),
        ("K.2", 0, 2),
    ]


def test_ties_share_a_rank_and_are_sorted_by_name():
    areas = [_area(f"K.{i}", name) for i, name in enumerate("DCBAEF", 1)]
    values = dict(
        zip(["K.1", "K.2", "K.3", "K.4", "K.5", "K.6"], [9, 5, 5, 5, 3, 1])
    )
    rows = [_row(area_id, value) for area_id, value in values.items()]

    ranking = build_ranking(rows, areas, "area_ha")

    assert [(r["name"], r["rank"]) for r in ranking] == [
        ("D", 1),
        ("A", 2),
        ("B", 2),
        ("C", 2),
        ("E", 5),
        ("F", 6),
    ]


def test_a_repeated_name_keeps_both_areas_with_their_parent():
    areas = [
        _area("BRA.1.1", "Bom Jesus", "Piauí"),
        _area("BRA.2.1", "Bom Jesus", "Rio Grande do Sul"),
    ]
    rows = [_row("BRA.1.1", 3), _row("BRA.2.1", 4)]

    ranking = build_ranking(rows, areas, "area_ha")

    assert [(r["aoi_id"], r["parent"]) for r in ranking] == [
        ("BRA.2.1", "Rio Grande do Sul"),
        ("BRA.1.1", "Piauí"),
    ]


def test_level_2_ids_with_a_suffix_match_the_rows():
    (area,) = build_ranked_areas(
        ["BOL.3.1_2"], ["Cercado, Beni, Bolivia"], ["gadm"]
    )
    other = build_ranked_areas(
        ["BOL.3.2_2"], ["Loreto, Beni, Bolivia"], ["gadm"]
    )[0]

    ranking = build_ranking(
        [_row("BOL.3.1", 4), _row("BOL.3.2", 6)], [area, other], "area_ha"
    )

    assert [r["name"] for r in ranking] == ["Loreto", "Cercado"]


def test_a_row_for_an_area_not_in_the_pull_raises():
    with pytest.raises(ValueError, match="not in the pull"):
        build_ranking([_row("X.9", 1)], [_area("K.1")], "area_ha")


def test_shares_are_of_the_total_of_the_areas():
    areas = [_area("K.1"), _area("K.2"), _area("K.3")]
    rows = [_row("K.1", 50), _row("K.2", 30), _row("K.3", 20)]

    ranking = build_ranking(rows, areas, "area_ha")

    assert [r["share_pct"] for r in ranking] == [50, 30, 20]
    assert sum(r["share_pct"] for r in ranking) == pytest.approx(100)


def test_no_row_has_a_share_when_the_areas_may_overlap():
    areas = [_area("BRA"), _area("BRA.14")]

    ranking = build_ranking(
        [_row("BRA", 9), _row("BRA.14", 3)], areas, "area_ha"
    )

    assert all("share_pct" not in row for row in ranking)


def test_shares_rules():
    gadm = lambda *ids: [_area(i) for i in ids]  # noqa: E731
    assert shares_allowed(gadm("KEN.1", "KEN.2"))
    assert shares_allowed(
        gadm("BRA.1", "BRA.14")
    )  # BRA.1 does not hold BRA.14
    assert shares_allowed(gadm("BOL.3.1", "BOL.4.2"))
    assert not shares_allowed(gadm("BRA", "BRA.14"))
    assert not shares_allowed(gadm("BOL.3", "BOL.3.1"))
    assert not shares_allowed(gadm("BOL.3", "BOL.4", "BOL.3.2.1"))
    assert not shares_allowed(
        [_area("1", source="wdpa"), _area("2", source="wdpa")]
    )
    assert not shares_allowed([_area("K.1"), _area("2", source="wdpa")])


def test_an_all_zero_pull_has_no_ranking():
    areas = [_area("K.1"), _area("K.2")]

    assert build_ranking([_row("K.1", 0)], areas, "area_ha") == []
    assert build_ranking([], areas, "area_ha") == []


def test_a_measure_that_is_null_everywhere_has_no_ranking():
    areas = [_area("K.1"), _area("K.2")]
    rows = [
        {"aoi_id": "K.1", "carbon_emissions_MgCO2e": None},
        {"aoi_id": "K.2", "carbon_emissions_MgCO2e": None},
    ]

    assert build_ranking(rows, areas, "carbon_emissions_MgCO2e") == []


def test_an_area_with_only_nulls_while_others_have_numbers_raises():
    areas = [_area("K.1"), _area("K.2")]
    rows = [
        {"aoi_id": "K.1", "carbon_emissions_MgCO2e": 5.0},
        {"aoi_id": "K.2", "carbon_emissions_MgCO2e": None},
    ]

    with pytest.raises(ValueError, match="other areas have it"):
        build_ranking(rows, areas, "carbon_emissions_MgCO2e")


def test_a_null_next_to_a_number_in_one_area_is_skipped():
    areas = [_area("K.1"), _area("K.2")]
    rows = [
        {"aoi_id": "K.1", "carbon_emissions_MgCO2e": 5.0},
        {"aoi_id": "K.1", "carbon_emissions_MgCO2e": None},
        {"aoi_id": "K.2", "carbon_emissions_MgCO2e": 2.0},
    ]

    ranking = build_ranking(rows, areas, "carbon_emissions_MgCO2e")

    assert [r["carbon_emissions_MgCO2e"] for r in ranking] == [5.0, 2.0]


def test_the_input_rows_are_not_changed():
    rows = [_row("K.1", 1)]

    build_ranking(rows, [_area("K.1")], "area_ha")

    assert rows == [_row("K.1", 1)]
