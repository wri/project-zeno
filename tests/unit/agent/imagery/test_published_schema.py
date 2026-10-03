import json
from pathlib import Path

from src.shared.imagery.wire import json_schema

SNAPSHOT = (
    Path(__file__).resolve().parents[4] / "docs/imagery/imagery.schema.json"
)


def test_the_published_schema_matches_its_snapshot():
    assert json_schema() == json.loads(SNAPSHOT.read_text())
