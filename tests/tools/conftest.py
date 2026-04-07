"""Test-only AOI query replay.

The `pick_aoi` tool queries a spatial database via SQL (PostGIS).
For CI, we want to avoid building/loading the heavy AOI geometry DB, while
still using "real" query outputs.

When `AOI_PICK_AOI_FIXTURES_MODE=replay`, this module patches:
- `src.agent.tools.pick_aoi.tool.query_aoi_database`
- `src.agent.tools.pick_aoi.tool.query_subregion_database`

to return DataFrames reconstructed from JSON fixtures recorded once from the
real database.
"""

from __future__ import annotations

import json
import os
from importlib import import_module
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pandas as pd
import pytest

from src.shared.logging_config import get_logger

logger = get_logger(__name__)


def _df_entry_to_dataframe(entry: dict[str, Any]) -> pd.DataFrame:
    columns = entry.get("columns") or []
    records = entry.get("records") or []
    # Preserve columns for empty frames so downstream code that expects
    # specific headers (e.g. `to_csv`) behaves consistently.
    return pd.DataFrame(records, columns=columns)


def _load_fixtures(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="session", autouse=True)
def replay_aoi_queries_for_tools_tests() -> Any:
    mode = os.getenv("AOI_PICK_AOI_FIXTURES_MODE", "live").lower()
    if mode != "replay":
        yield
        return

    fixtures_path = Path(
        os.getenv(
            "AOI_PICK_AOI_FIXTURES_PATH",
            "tests/fixtures/aoi_pick_aoi_v1.json",
        )
    )
    if not fixtures_path.exists():
        raise RuntimeError(
            "AOI fixtures file not found for replay mode: "
            f"{fixtures_path}. "
            "Run `uv run python scripts/record_aoi_pick_aoi_fixtures.py` "
            "to generate it from the real AOI database, then commit the JSON."
        )

    fixtures = _load_fixtures(fixtures_path)
    query_aoi_db_fixtures: dict[str, Any] = fixtures.get(
        "query_aoi_database", {}
    )
    query_subregion_db_fixtures: dict[str, Any] = fixtures.get(
        "query_subregion_database", {}
    )

    # The `tests/tools/test_pick_aoi.py` suite uses these place names.
    required_place_names = {
        "Puri",
        "Ecuador",
        "Bolivia",
        "Para, Brazil",
        "Indonesia",
        "Castelo Branco, Portugal",
        "Lisbon",
        "Resex Catua-Ipixuna",
        "Osceola, Research Natural Area, USA",
    }
    missing = sorted(required_place_names - set(query_aoi_db_fixtures.keys()))
    if missing:
        raise RuntimeError(
            "AOI fixtures are missing required query_aoi_database entries "
            f"for: {missing}. "
            "Re-record fixtures with the record script."
        )

    # `import src.agent.tools.pick_aoi as m` can bind `m` to the StructuredTool
    # re-exported on `src.agent.tools` (same final name), not the submodule.
    pick_aoi_py = import_module("src.agent.tools.pick_aoi.tool")
    live_query_aoi_database = pick_aoi_py.query_aoi_database

    async def query_aoi_database_replay(
        place_name: str, result_limit: int = 10
    ) -> pd.DataFrame:
        if place_name in query_aoi_db_fixtures:
            entry = query_aoi_db_fixtures[place_name]
            return _df_entry_to_dataframe(entry)
        # Custom areas are created dynamically by tests (DB-backed),
        # so allow live fallback when no fixture exists for that place.
        logger.warning(
            "AOI fixtures replay miss for place_name=%r; falling back to "
            "live DB query.",
            place_name,
        )
        return await live_query_aoi_database(place_name, result_limit)

    async def query_subregion_database_replay(
        subregion_name: str, source: str, src_id: Any
    ) -> pd.DataFrame:
        key = f"{subregion_name}|{source}|{str(src_id)}"
        if key in query_subregion_db_fixtures:
            entry = query_subregion_db_fixtures[key]
            return _df_entry_to_dataframe(entry)

        # If we reach here in replay mode, it means the recorded fixture
        # set doesn't cover the selected AOI candidates (depends on LLM
        # selection). Fail loudly and point to the key we need.
        raise RuntimeError(
            "Missing AOI subregion fixture in replay mode. "
            f"key={key}. "
            "Re-record fixtures (or extend `record_aoi_pick_aoi_fixtures.py`) "
            "to cover the selected AOI candidates."
        )

    with (
        patch(
            "src.agent.tools.pick_aoi.tool.query_aoi_database",
            new=query_aoi_database_replay,
        ),
        patch(
            "src.agent.tools.pick_aoi.tool.query_subregion_database",
            new=query_subregion_database_replay,
        ),
    ):
        yield
