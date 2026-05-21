"""Dataset domain — the shared catalog and analytics data layer.

`config` loads the dataset catalog (the YAML files in `catalog/`) into
`DATASETS`. `handlers` fetch analytics data for a dataset. `dates` clamps a
requested date range to a dataset's real coverage. Used by the `pull_data`
tool, the `pick_dataset` and `analyst` subagents, and the ingest pipeline —
shared infrastructure, owned by no single tool.
"""
