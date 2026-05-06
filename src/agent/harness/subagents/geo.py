from src.agent.harness.protocol import AoiRef

_FIXTURES: dict[str, list[AoiRef]] = {
    "para": [
        {
            "name": "Para",
            "source": "gadm",
            "src_id": "BRA.14_1",
            "subtype": "state",
        }
    ],
    "brazil": [
        {
            "name": "Brazil",
            "source": "gadm",
            "src_id": "BRA",
            "subtype": "country",
        }
    ],
    "peru": [
        {
            "name": "Peru",
            "source": "gadm",
            "src_id": "PER",
            "subtype": "country",
        }
    ],
    "amazon": [
        {
            "name": "Amazon Basin",
            "source": "kba",
            "src_id": "amazon_basin",
            "subtype": "kba",
        }
    ],
}


class GeoAgent:
    """Stub geo subagent. Resolves a place query to AoiRefs.

    Returns hard-coded fixtures for known names; otherwise a single
    deterministic ref so downstream tools have something to work with.
    """

    async def resolve(self, query: str) -> list[AoiRef]:
        q = (query or "").strip().lower()
        for key, refs in _FIXTURES.items():
            if key in q:
                return refs
        slug = q.replace(" ", "_") or "unknown"
        return [
            {
                "name": query.strip() or "unknown",
                "source": "gadm",
                "src_id": slug.upper(),
                "subtype": None,
            }
        ]
