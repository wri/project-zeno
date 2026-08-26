---
name: show-imagery
description: Display Planet or Sentinel-2 satellite imagery on the map for a place around a date.
when_to_use: User asks to see satellite imagery, a satellite view, Planet, or Sentinel-2 imagery of a place — optionally around a date. Can be called in conjunction with request for alerts, but not for independent data analysis or charts.
requires: pick_aoi, show_imagery
---

# Showing satellite imagery

There two separate options for displaying recent and past Satellite imagery around an AOI or limited area.

## Planet — monthly mosaics, masked to integrated alerts

Planet imagery is **only rendered in a buffer around integrated deforestation
alerts**, inside a limited Amazon footprint. Away from an alert the tiles are
empty. That makes Planet a tool for *inspecting alerts up close*, not a
general basemap — if the user is not looking at integrated alerts in the
Amazon, Planet will look blank and Sentinel-2 is the right answer.

It publishes one mosaic per calendar month, and only through the **last
complete month**. There is never a current-month or "latest" Planet mosaic —
never describe one as latest imagery.

## Sentinel-2 — global, continuous

Global coverage, any date, no dependence on alerts. Use it for recent
imagery, anywhere outside Planet's footprint, and any request not tied to
alerts. Defaults to scenes within ±7 days of the target date under 20% cloud
cover.

# Steps

1. `pick_aoi` — only if the AOI is not already in state. Imagery works for
   regional areas (up to ~50,000 km²); country-scale requests will be
   rejected — ask the user for a smaller region.
2. `show_imagery` — let the tool pick the provider unless the user named one.
   - Pass `target_date` (YYYY-MM-DD) when the user gave a date.
   - When showing imagery alongside alert data, set `target_date` to the
     alert period's `end_date` so the imagery and alerts align.
   - Pass `target_date=null` only when no alert period or imagery date was
     requested.
   - Use Planet if the user is requesting imagery in the Amazon and not explicitly asking for imagery in the past few weeks.
   - Only pass `provider` otherwise when the user explicitly asked for one.
3. **Stop.** Confirm the provider actually shown from the tool message. No
   dataset, pull or insights unless asked.

Always report the period shown from the returned `start_date` and `end_date`.
The tool may fall back to a different provider than the one implied by the
request — read the tool message rather than assuming.

# When no scenes are found

The Sentinel-2 defaults are strict on purpose (recent + clear). If the tool
reports no scenes, do **not** silently retry. Tell the user what was searched
and offer the levers:

- **Widen the date window**: `window_days=30` (or 60 for cloudy regions) —
  imagery may be further from the requested date.
- **Allow cloudier scenes**: `max_cloud_cover=50` (or 80 as a last resort) —
  imagery may be partly obscured.
- A different `target_date` (e.g. dry season) is often the best fix.

Once the user picks an option, call `show_imagery` again with that parameter.
If they just say "try again" or "whatever works", retry once with
`window_days=30, max_cloud_cover=50` and say you loosened both.
