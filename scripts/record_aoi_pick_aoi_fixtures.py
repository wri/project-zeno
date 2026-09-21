"""Record the AOI query replay fixtures for ``tests/tools/test_pick_aoi.py``.

CI runs that suite with ``AOI_PICK_AOI_FIXTURES_MODE=replay``, and
``tests/tools/conftest.py`` then answers ``query_aoi_database`` and
``query_subregion_database`` from the JSON this script writes, so the suite
needs no AOI corpus. Run it against a database built by ``build-aois`` (the
same code path production uses) whenever the search or the corpus changes,
then commit the JSON::

    uv run python scripts/record_aoi_pick_aoi_fixtures.py

The place names below are the ones the suite looks up. For a place the suite
expands into subregions, the subregion query is recorded for every GADM
candidate row, because which candidate the geocoder picks is not fixed here.
A non-GADM candidate gets an empty frame: the suite never selects one for
these places, and the real query for a non-GADM parent with an admin
subregion returns every admin unit in the world (a known defect), which would
make the fixture enormous.
"""

import asyncio
import json
import math
from pathlib import Path

import pandas as pd

from src.agent.subagents.pick_aoi.tool import (
    RESULT_LIMIT,
    query_aoi_database,
    query_subregion_database,
)
from src.shared import database
from src.shared.request_context import bound_user_id

OUTPUT = Path("tests/fixtures/aoi_pick_aoi_v2.json")

# (place name as the suite passes it, subregion the suite expands it into)
PLACES = [
    ("Puri", None),
    ("Ecuador", "state"),
    ("Bolivia", "state"),
    ("Para, Brazil", None),
    ("Indonesia", None),
    ("Castelo Branco, Portugal", None),
    ("Lisbon", None),
    ("Resex Catua-Ipixuna", None),
    ("Osceola, Research Natural Area, USA", None),
    ("Russia", "state"),
    ("Alabama, USA", "district"),
    ("Brazil", "state"),
]


def _entry(frame: pd.DataFrame) -> dict:
    records = json.loads(frame.to_json(orient="records"))
    # JSON has no NaN; the replay rebuilds a null as NaN where pandas would.
    for record in records:
        for key, value in record.items():
            if isinstance(value, float) and math.isnan(value):
                record[key] = None
    return {"columns": list(frame.columns), "records": records}


async def main() -> None:
    await database.initialize_global_pool()
    aoi_fixtures: dict[str, dict] = {}
    subregion_fixtures: dict[str, dict] = {}
    try:
        # The suite binds this user; custom areas are scoped to it and the
        # recorded database holds none, so the frames are reference rows only.
        with bound_user_id("test-user-123"):
            for place, subregion in PLACES:
                frame = await query_aoi_database(place, None, RESULT_LIMIT)
                aoi_fixtures[place] = _entry(frame)
                print(f"{place!r}: {len(frame)} candidate(s)")
                if subregion is None:
                    continue
                for row in frame.itertuples():
                    key = f"{subregion}|{row.source}|{row.src_id}"
                    if key in subregion_fixtures:
                        continue
                    if row.source == "gadm":
                        children = await query_subregion_database(
                            subregion, row.source, row.src_id
                        )
                    else:
                        children = pd.DataFrame(
                            columns=["name", "subtype", "source", "src_id"]
                        )
                    subregion_fixtures[key] = _entry(children)
                    print(f"  {key}: {len(children)} subregion(s)")
    finally:
        await database.close_global_pool()

    OUTPUT.write_text(
        json.dumps(
            {
                "version": 2,
                "query_aoi_database": aoi_fixtures,
                "query_subregion_database": subregion_fixtures,
            },
            ensure_ascii=False,
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    asyncio.run(main())
