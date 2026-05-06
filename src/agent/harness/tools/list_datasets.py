from pathlib import Path

import yaml
from langchain_core.tools import tool

_DATASETS_DIR = (
    Path(__file__).resolve().parents[3] / "agent" / "tools" / "datasets"
)


def _load_catalog() -> list[dict]:
    catalog: list[dict] = []
    if not _DATASETS_DIR.exists():
        return catalog
    for path in sorted(_DATASETS_DIR.glob("*.yml")):
        try:
            doc = yaml.safe_load(path.read_text()) or {}
        except yaml.YAMLError:
            continue
        catalog.append(
            {
                "id": path.stem,
                "name": doc.get("dataset_name") or path.stem,
                "description": (doc.get("prompt_instructions") or "")[:240],
                "keywords": doc.get("keywords") or [],
                "start_date": str(doc.get("start_date") or ""),
                "end_date": str(doc.get("end_date") or ""),
            }
        )
    return catalog


_CATALOG = _load_catalog()


def _score(item: dict, query: str) -> int:
    q = query.lower()
    score = 0
    if q in item["name"].lower():
        score += 5
    if q in item["description"].lower():
        score += 2
    for kw in item["keywords"]:
        if q in str(kw).lower():
            score += 3
    return score


@tool
def list_datasets(query: str = "", limit: int = 5) -> list[dict]:
    """Search the dataset catalog. Pass a free-text query (e.g. "tree cover
    loss") or empty string to list everything. Returns up to `limit`
    matches with id, name, description and date range."""
    if not query.strip():
        items = _CATALOG[:limit]
    else:
        ranked = sorted(
            _CATALOG, key=lambda d: _score(d, query), reverse=True
        )
        items = [d for d in ranked if _score(d, query) > 0][:limit]
        if not items:
            items = ranked[:limit]
    return [
        {
            "id": d["id"],
            "name": d["name"],
            "description": d["description"],
            "date_range": [d["start_date"], d["end_date"]],
        }
        for d in items
    ]
