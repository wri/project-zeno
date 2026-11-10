---
name: concessions-layer
description: Show a concessions boundary layer on the map so the user can click a concession to select and analyse it.
when_to_use: User asks to show, see or display concessions (oil palm, RSPO oil palm, logging, mining, wood fiber) on the map, optionally in a named place — e.g. "Show me oil palm concessions", "Show me logging concessions in Brazil". Also when the user wants to pick one concession. Not when the user asks for figures, charts or analysis of the concessions in a place — use skill `analyze`.
requires: pick_aoi, show_boundary_layer
---

# Showing a concessions layer

The concessions boundary layer shows every concession of one type. The user
clicks a concession on the layer to select it as the area to analyse.
Showing the layer does not select an area.

## Concession types

| User says | `layer` |
|---|---|
| oil palm, palm oil | `oil_palm` |
| RSPO, RSPO-certified oil palm | `rspo_oil_palm` |
| logging, managed forest, timber | `logging` |
| mining, mines | `mining` |
| wood fiber, pulpwood, plantation for pulp | `wood_fiber` |

Plain "oil palm" is `oil_palm`. Use `rspo_oil_palm` only when the user says
RSPO.

# Steps

1. If the user names a place, call `pick_aoi` with the place only (e.g.
   "Brazil", not "logging concessions in Brazil"). `pick_aoi` selects the
   place as the AOI and zooms the map to it. If you send the concessions
   in the question, `pick_aoi` selects every concession in the place
   instead. Skip this step when the user names no place.
2. Call `show_boundary_layer`:
   - With the matching `layer` when the user gives a type.
   - With `layer=null` when the user says "concessions" with no type. The
     tool offers the types to the user. Ask which type to show, list the
     types it returned, and stop.
3. **Stop.** Reply in one or two sentences: say which layer is on the map
   (and which place is selected, if step 1 ran), and tell the user to click
   a concession on the map to select it and analyse it. Do not pick a
   dataset, pull data or give figures.

When the user picks a type from the offered list, call
`show_boundary_layer` with that type. Do not call `pick_aoi` again for a
place already in the session block.

# One named concession

`pick_aoi` cannot find a concession by its name. When it says so, and you
know the concession type, call `show_boundary_layer` with that type, and
tell the user to find the concession on the map and click it.
