"""Flash-powered place name normalizer and geographic concept reasoner.

Uses Gemini Flash Lite to:
1. Normalize raw place names into canonical English + alternatives (always runs)
2. Expand geographic concepts into concrete admin unit approximations (fallback only)
"""

import asyncio
from typing import Literal, Optional

import cachetools
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from src.agent.llms import GEMINI_FLASH_LITE
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# 1. Name Normalizer
# ---------------------------------------------------------------------------


class NormalizedPlaceName(BaseModel):
    """Normalized place name with alternative spellings for search."""

    primary: str = Field(
        description=(
            "The most likely English name as it appears in a geographic database "
            "(GADM format). Remove diacritics/accents (é→e, ã→a, ç→c, ñ→n). "
            "Keep hierarchical qualifiers: 'Para, Brazil' not separate."
        )
    )
    alternatives: list[str] = Field(
        default_factory=list,
        description=(
            "Up to 3 alternative spellings, transliterations, or historical names. "
            "Include the accented/original form if primary is de-accented."
        ),
    )
    iso_country_code: Optional[str] = Field(
        default=None,
        description="ISO 3166-1 alpha-3 country code if confidently identified.",
    )


_NORMALIZE_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "user",
            """You are a geographic name normalizer. Given a place name (possibly in any language,
with abbreviations, colloquial names, or historical names), produce the most likely
English name as it would appear in the GADM geographic database.

GADM stores names as: "Place, Parent, Country" (e.g., "Pará, Brazil", "Lisbon, Portugal").

Rules:
1. PRIMARY: Canonical English name with diacritics REMOVED (e→e, not é).
   If the input includes a parent region or country, keep it: "Para, Brazil" not just "Para".
2. ALTERNATIVES: Include the accented version, plus any common alternative spellings.
3. ISO CODE: Only provide if you are confident about the country.
4. Expand abbreviations fully: "DRC" → "Democratic Republic of the Congo".
5. Map colloquial names: "The Big Apple" → "New York".
6. Map historical names: "Burma" → "Myanmar", "Rhodesia" → "Zimbabwe".
7. Transliterate non-Latin scripts: "Москва" → "Moscow" (primary), "Moskva" (alternative).
8. If the input is already clean English with no accent issues, return it as-is with empty alternatives.

Place name: {place_name}""",
        )
    ]
)


async def normalize_place_name(raw_place: str) -> NormalizedPlaceName:
    """Normalize a place name via Flash Lite. Returns search-optimized terms."""
    try:
        chain = _NORMALIZE_PROMPT | GEMINI_FLASH_LITE.with_structured_output(
            NormalizedPlaceName
        )
        result = await asyncio.wait_for(
            chain.ainvoke({"place_name": raw_place}),
            timeout=2.0,
        )
        logger.debug(f"Normalized '{raw_place}' -> {result}")
        return result
    except Exception:
        logger.warning(
            f"Name normalization failed for '{raw_place}', using as-is",
            exc_info=True,
        )
        return NormalizedPlaceName(primary=raw_place)


# ---------------------------------------------------------------------------
# 2. Geographic Concept Reasoner (with spatial approximation)
# ---------------------------------------------------------------------------


class ConceptExpansion(BaseModel):
    """Result of expanding a geographic concept into concrete place names."""

    is_concept: bool = Field(
        description=(
            "True if the input refers to a geographic concept, biome, basin, "
            "informal region, or natural feature rather than a specific named place."
        )
    )
    places: list[str] = Field(
        default_factory=list,
        description=(
            "Specific admin unit names that best approximate the concept. "
            "Use standard English names as they appear in GADM."
        ),
    )
    admin_level: Literal["country", "state", "district"] = Field(
        default="country",
        description=(
            "Admin level giving the best spatial approximation. "
            "Country for multi-country features, state for within-country features."
        ),
    )
    coverage_note: str = Field(
        default="",
        description=(
            "Brief note on approximation quality: 'exact' if admin units map perfectly, "
            "or describe the approximation (e.g., 'these states overlap ~85% with the biome')."
        ),
    )
    source_hint: Optional[Literal["gadm", "wdpa", "kba", "landmark"]] = Field(
        default=None,
        description=(
            "If the concept implies a specific source type "
            "(e.g., 'protected areas' -> wdpa), specify it here."
        ),
    )


_CONCEPT_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "user",
            """You are a geographic knowledge expert. The user's query mentions a geographic
term that could not be found in our administrative boundaries database (GADM).

Your job: determine if this is a geographic CONCEPT (biome, basin, region, island,
geopolitical grouping, natural feature) and expand it into concrete administrative
units that best approximate its spatial extent.

User's question: {question}
Unresolved term: {term}

Rules:
1. If this is a specific named place that's just misspelled or in another language,
   set is_concept=False and places=[].
2. If this IS a geographic concept, find the admin units that best approximate it:
   - For biomes/ecosystems (Amazon, Cerrado, Sahel): list the states/provinces
     that overlap with the biome. Prefer state level for within-country features.
   - For multi-country regions (Southeast Asia, BRICS): list countries.
   - For natural features (Borneo, Patagonia): list states/provinces spanning
     the feature across relevant countries.
   - For informal regions (The UK, Scandinavia): list constituent countries or
     their top-level admin units.
3. Choose admin_level that gives >70% coverage without too many units (under 30).
4. In coverage_note, describe the approximation quality honestly.
5. If the concept implies a data source (protected areas→wdpa, indigenous lands→landmark,
   KBAs→kba), set source_hint.
6. Use standard English names as they appear in GADM.
7. Keep the list under 30 entries. If it would be larger, suggest narrowing down.""",
        )
    ]
)

# Cache concept expansions for 24 hours (concepts are stable)
_concept_cache: cachetools.TTLCache = cachetools.TTLCache(
    maxsize=256, ttl=60 * 60 * 24
)


async def expand_geographic_concept(
    term: str, question: str
) -> ConceptExpansion:
    """Use Flash to expand a geographic concept into concrete place names.

    Only called as a fallback when the database returns no results for a term.
    Results are cached for 24 hours.
    """
    cache_key = term.strip().lower()
    if cache_key in _concept_cache:
        logger.debug(f"Concept cache hit for '{term}'")
        return _concept_cache[cache_key]

    try:
        chain = _CONCEPT_PROMPT | GEMINI_FLASH_LITE.with_structured_output(
            ConceptExpansion
        )
        result = await asyncio.wait_for(
            chain.ainvoke({"term": term, "question": question}),
            timeout=5.0,
        )
        logger.info(
            f"Concept expansion for '{term}': {len(result.places)} places, "
            f"level={result.admin_level}, coverage={result.coverage_note}"
        )
        if result.is_concept:
            _concept_cache[cache_key] = result
        return result
    except Exception:
        logger.warning(
            f"Concept expansion failed for '{term}'", exc_info=True
        )
        return ConceptExpansion(is_concept=False)
