"""Helpers for chart generator tests.

`fixtures/*.json` are recorded analytics API responses (captured 2026-07-22
against production, small admin AOIs) — the source of truth for real column
names, which drift from other in-repo fixtures.
"""

import json
from pathlib import Path
from typing import List

from src.api.services.charts import column_to_rows

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture_rows(slug: str) -> List[dict]:
    """Row dicts from a recorded analytics response fixture."""
    record = json.loads((FIXTURES_DIR / f"{slug}.json").read_text())
    return column_to_rows(record["data"])
