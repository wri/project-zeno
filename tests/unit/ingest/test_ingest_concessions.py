"""Unit tests for the concession ingest's cleaning and naming (no DB, no S3).

The values are rows of the GFW v2025 concession files.
"""

import pandas as pd
import pytest

from src.ingest.ingest_concessions import (
    CONCESSION_DATASETS,
    clean_text,
    concession_name,
    prepare,
    strip_shares,
)


@pytest.mark.parametrize(
    "company, expected",
    [
        ("IDM Mining Ltd - 100%", "IDM Mining Ltd"),
        (
            "18526 Yukon Inc. - 70%, Anthill Resources Ltd. - 30%",
            "18526 Yukon Inc., Anthill Resources Ltd.",
        ),
        ("Desai Miyoba (100%)", "Desai Miyoba"),
        ("JOSE G. GUTIERREZ MONARREZ 67%", "JOSE G. GUTIERREZ MONARREZ"),
        (
            "Glencore Canada Corporation (92528) 100 % (responsable)",
            "Glencore Canada Corporation",
        ),
        (
            "Archer, Cathro & Associates (1981) Limited - 100%",
            "Archer, Cathro & Associates (1981) Limited",
        ),
        (
            "FELDA Global Ventures Holdings Berhad",
            "FELDA Global Ventures Holdings Berhad",
        ),
        (None, None),
    ],
)
def test_strip_shares(company, expected):
    assert strip_shares(company) == expected


@pytest.mark.parametrize(
    "value", [None, float("nan"), "", "  ", "NA", "No group", "No Data"]
)
def test_clean_text_drops_no_data(value):
    assert clean_text(value) is None


def test_clean_text_drops_dataset_markers_only_when_given():
    markers = CONCESSION_DATASETS["mining"].name_markers
    assert clean_text("Yukon Territory", markers) is None
    assert clean_text("Yukon Territory") == "Yukon Territory"
    assert clean_text(" Palong 17 ") == "Palong 17"


def _row(**values) -> pd.Series:
    return pd.Series(
        {
            "conc_name": None,
            "company": None,
            "comp_group": None,
            "conc_type": "Oil palm concession",
            "cont_id": None,
            "iso3": "MYS",
            **values,
        }
    )


def test_concession_name_named_parcel():
    row = _row(conc_name="Palong 17", company="FELDA")
    assert concession_name(row) == "Palong 17, FELDA, Oil palm concession, MYS"


def test_concession_name_falls_back_to_company_once():
    row = _row(company="Sime Darby Plantation (Liberia) Inc.", iso3="LBR")
    assert concession_name(row) == (
        "Sime Darby Plantation (Liberia) Inc., Oil palm concession, LBR"
    )


def test_concession_name_carries_the_contract_id():
    row = _row(
        conc_name="UFA ABANGA",
        cont_id="UFA ABANGA",
        conc_type="Logging concession",
        iso3="GAB",
    )
    assert concession_name(row) == (
        "UFA ABANGA (UFA ABANGA), Logging concession, GAB"
    )


def test_concession_name_without_any_name_uses_the_type():
    row = _row(conc_type="Logging concession", iso3="CAN")
    assert concession_name(row) == "Logging concession, CAN"
    row = _row(conc_type="Mining concession", iso3="CAN", cont_id="P 42344")
    assert concession_name(row) == "Mining concession (P 42344), CAN"


def test_prepare_cleans_before_naming():
    chunk = pd.DataFrame(
        [
            {
                "gfw_fid": 7,
                "iso3": "CAN",
                "conc_type": "Mining concession",
                "conc_name": "Yukon Territory",
                "company": "IDM Mining Ltd - 100%",
                "cont_id": "P 42344",
                "mineral": None,
            }
        ]
    )
    out = prepare(chunk, CONCESSION_DATASETS["mining"])
    row = out.iloc[0]
    assert row.conc_name is None
    assert row.company == "IDM Mining Ltd"
    assert row["name"] == ("IDM Mining Ltd (P 42344), Mining concession, CAN")
    assert row.subtype == "mining-concession"


def test_rspo_names_leave_out_the_membership_number():
    chunk = pd.DataFrame(
        [
            {
                "gfw_fid": 4477,
                "iso3": "MYS",
                "conc_type": "Oil palm concession (RSPO)",
                "conc_name": None,
                "company": "TDM Plantation Sdn Bhd",
                "comp_group": "TDM Plantation Sdn Bhd",
                "cont_id": "1-0095-11-000-00",
            }
        ]
    )
    out = prepare(chunk, CONCESSION_DATASETS["rspo_oil_palm"])
    assert out.iloc[0]["name"] == (
        "TDM Plantation Sdn Bhd, Oil palm concession (RSPO), MYS"
    )
    assert out.iloc[0].subtype == "rspo-oil-palm-concession"


def test_other_unknown_is_no_data():
    assert clean_text("Other / Unknown") is None
