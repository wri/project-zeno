"""The Sentinel-2 imagery recipe and its token.

A recipe is everything that defines one Sentinel-2 imagery request: the AOI
references, the target date and the search parameters. Its token (base64url
of the key-sorted, compact recipe JSON) is deterministic and
self-describing:

- the agent's show_imagery writes it as ``mosaic_id``; the frontend decodes
  it to search earth-search and render the scenes in the browser, and builds
  the same token for the same request (project-zeno-next
  ``src/features/imagery/model/request.ts``), so both name one capture
  identically;
- the legacy S3 mosaics (``src/api/services/mosaic.py``) are keyed by it.

Keep the encoding byte-stable: persisted dashboard widgets and chat threads
hold these tokens.
"""

import base64
import json
from dataclasses import dataclass
from datetime import date
from typing import Optional


class InvalidRecipeError(ValueError):
    pass


@dataclass(frozen=True)
class MosaicRecipe:
    """Everything needed to (re)build a mosaic deterministically.

    target_date is always a resolved date, never an implicit "today", so a
    token rebuilt later yields the same imagery. user_id is only set when a
    custom area is referenced (its geometry lookup is scoped to the owner).
    """

    aois: tuple[tuple[str, str], ...]  # (source, src_id) pairs
    target_date: date
    window_days: int = 7
    max_cloud_cover: int = 20
    max_items: int = 50
    user_id: Optional[str] = None


def encode_recipe(recipe: MosaicRecipe) -> str:
    payload = {
        "a": [list(pair) for pair in recipe.aois],
        "d": recipe.target_date.isoformat(),
        "w": recipe.window_days,
        "c": recipe.max_cloud_cover,
        "n": recipe.max_items,
    }
    if recipe.user_id:
        payload["u"] = recipe.user_id
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_recipe(token: str) -> MosaicRecipe:
    """Decode a recipe token; raise InvalidRecipeError if malformed."""
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
        payload = json.loads(raw)
        return MosaicRecipe(
            aois=tuple((source, src_id) for source, src_id in payload["a"]),
            target_date=date.fromisoformat(payload["d"]),
            window_days=max(1, min(int(payload["w"]), 183)),
            max_cloud_cover=max(1, min(int(payload["c"]), 100)),
            max_items=max(1, min(int(payload["n"]), 100)),
            user_id=payload.get("u"),
        )
    except (KeyError, ValueError, TypeError):
        raise InvalidRecipeError("Invalid recipe token")
