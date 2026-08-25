---
name: show-imagery
description: Display Planet or Sentinel-2 satellite imagery on the map for a place around a date.
when_to_use: User asks to see satellite imagery, a satellite view, Planet, or Sentinel-2 imagery of a place — optionally around a date. Not for data analysis or charts.
requires: pick_aoi, show_imagery
---

# Showing satellite imagery

1. `pick_aoi` — only if the AOI is not already in state. Imagery works for
   regional areas (up to ~50,000 km²); country-scale requests will be
   rejected — ask the user for a smaller region.
2. `show_imagery(target_date)` — pass the user's date (YYYY-MM-DD). When
   showing imagery alongside alert data, set `target_date` to the alert
   period's `end_date` so the imagery and alerts align. Only pass
   `target_date=null` when no alert period or imagery date was requested.
   For Amazon alert workflows with no requested date, prefer Planet and
   mention that it shows the previous complete monthly mosaic. For a dated
   alert period, keep `target_date` aligned with its `end_date` and let the
   tool select the available provider. Outside the Amazon, do not proactively
   suggest Planet.
   Always tell the user the selected imagery period from the returned
   `start_date` and `end_date`. Never describe a previous-month Planet mosaic
   as "latest" imagery.
   Otherwise, pass `provider="planet"` or `provider="sentinel-2"` only when
   the user explicitly asks for that provider. Sentinel-2 defaults to scenes
   within ±7 days of the target date, under 20% cloud cover.
3. **Stop.** Confirm the provider shown using the tool message. No dataset,
   pull or insights unless asked.

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
