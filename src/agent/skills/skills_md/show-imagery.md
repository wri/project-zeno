---
name: show-imagery
description: Display Sentinel-2 satellite imagery on the map for a place around a date.
when_to_use: User asks to see satellite imagery, a satellite view, or Sentinel-2 of a place — optionally around a date. Not for data analysis or charts.
requires: pick_aoi, show_imagery
---

# Showing satellite imagery

1. `pick_aoi` — only if the AOI is not already in state. Imagery works for
   regional areas (up to ~50,000 km²); country-scale requests will be
   rejected — ask the user for a smaller region.
2. `show_imagery(target_date)` — pass the user's date (YYYY-MM-DD) or omit
   for the most recent imagery. Defaults: scenes within ±7 days of the
   target date, under 20% cloud cover.
3. **Stop.** Confirm what is shown (scene count and date span from the tool
   message). No dataset, pull or insights unless asked.

# When no scenes are found

The defaults are strict on purpose (recent + clear). If the tool reports no
scenes, do **not** silently retry. Tell the user what was searched and offer
the two levers:

- **Widen the date window**: `window_days=30` (or 60 for cloudy regions) —
  imagery may be further from the requested date.
- **Allow cloudier scenes**: `max_cloud_cover=50` (or 80 as a last resort) —
  imagery may be partly obscured.
- A different `target_date` (e.g. dry season) is often the best fix.

Once the user picks an option, call `show_imagery` again with that parameter.
If they just say "try again" or "whatever works", retry once with
`window_days=30, max_cloud_cover=50` and say you loosened both.
