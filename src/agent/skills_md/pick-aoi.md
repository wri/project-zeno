---
name: pick-aoi
description: Rules for resolving places to AOIs, including subregions and English normalization.
when_to_use: User names a place, asks to pick/resolve an AOI, or wants to compare units within a parent area — not for dataset-only requests.
---

# Translation

Always pass **English** place names: translate other languages, normalize accents (é→e, ã→a, ç→c), use common English spellings.

Examples: Odémire → Odemira; São Paulo → Sao Paulo; México → Mexico; Köln → Cologne; Bern, Schweiz → Bern, Switzerland; Lisboa em Portugal → Lisbon, Portugal.

Keep paired places in one string: "Lisbon in Portugal" → `Lisbon, Portugal` (not separate `Lisbon` and `Portugal`).

# Subregion parameter

Use `subregion` **only** when the user wants to analyze or **compare across** multiple administrative units inside a parent area.

Types: `country`, `state`, `district`, `municipality`, `locality`, `neighbourhood`, `kba`, `wdpa`, `landmark`.

**Use subregion:**
- "Which countries have the most deforestation globally?" → place=`Global World`, subregion=`country`
- "Compare forest loss across provinces in Canada" → place=`Canada`, subregion=`state`
- "Which districts in Odisha have tiger threats?" → place=`Odisha`, subregion=`district`
- "Which KBAs in Brazil have highest biodiversity loss?" → place=`Brazil`, subregion=`kba`

**Do not use subregion:**
- "Deforestation in Ontario" → place=`Ontario` only
- "Forest data for Mumbai" → place=`Mumbai` only
- "Tree cover in Yellowstone National Park" → single protected area

# Global queries

For whole-world questions ("globally", "worldwide", "all countries"), pass a global synonym as place (e.g. `global`) with `subregion=country`. Global queries only support `subregion=country`.
