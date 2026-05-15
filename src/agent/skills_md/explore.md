---
name: explore
description: Answer questions about agent capabilities, datasets, and example queries.
when_to_use: User asks what you can do, what data exists, limitations, or how to get started — not a specific analysis yet.
---

# Workflow

Call `get_capabilities` once, then answer from that output in your own words. Do not run `pick_aoi` / `pull_data` unless the user then asks for a concrete analysis.

# Typical analysis pipeline (for orientation only)

1. Area of interest from the user's place
2. Dataset matching the topic
3. `pull_data` for the date range
4. `generate_insights` for one chart + follow-ups

To run that pipeline, use skill `analyze` instead.
