---
name: pick-dataset
description: Pick or change dataset and context layer; dataset-only requests need no AOI.
when_to_use: User asks to pick/select a dataset, before `pull_data`, or when changing dataset, drivers, land cover context, or time framing.
---

# Dataset-only requests

When the user only wants a dataset chosen (e.g. "pick tcl by driver", "use tree cover loss by driver"):

1. Call `pick_dataset` with their query. AOI is not required.
2. Briefly confirm the selection. Do not ask for a country or region.
3. Do not call `pick_aoi`, `pull_data`, or `generate_insights` unless the user asks for more.

# Re-pick dataset

Call `pick_dataset` again before `pull_data` if:

1. The user requests a different dataset, or
2. The user changes context for a layer (drivers, land cover change, time dynamics, parameters, etc.)

# Dates

Warn if there is no exact date match for the dataset, but proceed with the closest valid range when reasonable.
