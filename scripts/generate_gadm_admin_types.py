"""Generate the GADM admin-type fixture used by the pick_aoi subregion resolver.

GADM's own ``TYPE_N``/``ENGTYPE_N`` columns record what each country calls its
own administrative levels locally (Province, Region, Department, Canton,
Constituent Country, ...). The same English word can name different depths in
different countries -- Spain's "provinces" are ADM2, Canada's are ADM1 -- so a
single global word-to-depth table (which is what the geocoder prompt used
before this) is necessarily wrong for some country. This script reads that
data straight from the GADM GeoPackage (no database required) and writes a
small fixture that lets the resolver look up the correct depth per country.

GADM hierarchies only change on a GADM version bump (years apart, not our
deploy cycle), so this fixture is generated once and checked in -- re-run this
script only after re-ingesting a new GADM version.

Usage:
    uv run python scripts/generate_gadm_admin_types.py [path/to/gadm_410-levels.gpkg]
"""

import json
import sys
from pathlib import Path

import pandas as pd
import pyogrio

DEFAULT_GPKG = Path("data/gadm_410-levels.gpkg")
OUT_PATH = Path("src/shared/fixtures/gadm_admin_types.json")

# GADM's own layer name -> the admin depth it holds.
LAYERS = {"ADM_1": 1, "ADM_2": 2, "ADM_3": 3, "ADM_4": 4, "ADM_5": 5}

# Typos and truncations found in GADM 4.1's own ENGTYPE_N columns. Fixed here
# instead of silently kept, so they don't fragment the canonical vocabulary.
MANUAL_FIX = {
    "Distict": "District",
    "Autononous Region": "Autonomous Region",
    "Captial City District": "Capital City District",
    "Municipiality": "Municipality",
    "Metropolian Region": "Metropolitan Region",
    "Area Outside Territorial Authori": "Area Outside Territorial Authority",
    "Districts of Republican Subordin": "Districts of Republican Subordination",
    "Subdivision of County Municipali": "Subdivision of County Municipality",
    "Atol": "Atoll",
    "?": "Unknown",
}

# Real-world terms worth keeping in the LLM-facing enum even though GADM
# assigns them to only one country -- they are still the natural word a user
# would use for that country's units (the UK's "constituent countries", the
# UAE's "emirates", ...).
ALLOWLIST_SINGLE_COUNTRY = {
    "Constituent Country",
    "Emirate",
    "Autonomous Community",
    "Free State",
    "Comarca",
    "Voivodeship",
    "Regency",
    "Canton",
    "Governorate",
}

# GADM values that name a data artifact, not an administrative unit a user
# would ever ask for.
NOT_REAL_ADMIN_TERMS = {
    "Unknown",
    "Water body",
    "Waterbody",
    "Not Classified",
    "Other",
}


def read_layer(gpkg: Path, layer: str, level: int) -> pd.DataFrame:
    df = pyogrio.read_dataframe(
        gpkg,
        layer=layer,
        columns=["GID_0", f"ENGTYPE_{level}"],
        read_geometry=False,
        use_arrow=True,
    )
    df = df.rename(columns={"GID_0": "gid0", f"ENGTYPE_{level}": "engtype"})
    df["level"] = level
    df["engtype"] = df["engtype"].str.strip().str.strip("'").str.strip()
    return df[~df["engtype"].isin(["", "NA"])]


def build_fixture(gpkg: Path) -> dict:
    df = pd.concat(
        [read_layer(gpkg, layer, level) for layer, level in LAYERS.items()],
        ignore_index=True,
    )
    df["engtype"] = df["engtype"].replace(MANUAL_FIX)

    # Fold case-only duplicates ("City council" / "City Council") onto
    # whichever spelling is more common in the raw data.
    counts = df.groupby("engtype").size()
    lower_to_canonical = counts.groupby(counts.index.str.lower()).apply(
        lambda s: s.idxmax()
    )
    df["canonical"] = df["engtype"].str.lower().map(lower_to_canonical)

    by_country_count = df.groupby("canonical")["gid0"].nunique()
    candidates = set(by_country_count[by_country_count >= 2].index) | (
        ALLOWLIST_SINGLE_COUNTRY & set(by_country_count.index)
    )
    canonical_terms = sorted(
        t for t in candidates if t not in NOT_REAL_ADMIN_TERMS and "|" not in t
    )

    by_country: dict = {}
    for (gid0, level), group in df.groupby(["gid0", "level"]):
        by_country.setdefault(gid0, {})[str(level)] = sorted(
            group["canonical"].unique().tolist()
        )

    return {"canonical_terms": canonical_terms, "by_country": by_country}


def main() -> None:
    gpkg = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_GPKG
    if not gpkg.exists():
        raise FileNotFoundError(
            f"{gpkg} not found. Run ingest_gadm.py first, or pass the path "
            "to gadm_410-levels.gpkg explicitly."
        )

    fixture = build_fixture(gpkg)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump(fixture, f, indent=1, sort_keys=True)
        f.write("\n")

    print(
        f"✓ Wrote {OUT_PATH}: {len(fixture['canonical_terms'])} canonical "
        f"terms, {len(fixture['by_country'])} countries"
    )


if __name__ == "__main__":
    main()
