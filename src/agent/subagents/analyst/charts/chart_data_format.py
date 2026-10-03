from src.agent.datasets.curated_only import (
    CURATED_ONLY_DATA_WITHHELD,
    is_curated_only,
)
from src.agent.i18n import t
from src.agent.language import DEFAULT_LANGUAGE

# Rows at or below this get full data injected; above get per-column stats.
DATA_INJECT_THRESHOLD = 30
# Meta-columns that add no signal for stats and are skipped.
DATA_SKIP_COLUMNS = {"aoi_id", "aoi_type"}
# Secondary cap on full-table output; if the formatted table exceeds this,
# fall back to stats even if row count is below the threshold.
DATA_TABLE_CHAR_LIMIT = 4000


async def format_numeric_stats(
    values: list, language: str = DEFAULT_LANGUAGE
) -> str:
    """Min/max/mean for a list of numeric values, ignoring None/non-numeric."""
    nums = [v for v in values if isinstance(v, (int, float)) and v is not None]
    if not nums:
        return await t("analyst.chart_data_no_numeric", language)
    mn, mx = min(nums), max(nums)
    avg = sum(nums) / len(nums)
    # If avg is a whole number, drop decimal entirely; otherwise format to 2dp
    # and strip trailing zeros (2.50 -> 2.5).
    if avg == int(avg):
        mean = str(int(avg))
    else:
        mean = f"{avg:.2f}".rstrip("0").rstrip(".")
    return await t(
        "analyst.chart_data_stats", language, min=mn, max=mx, mean=mean
    )


async def format_chart_data(chart, language: str = DEFAULT_LANGUAGE) -> str:
    """Format chart data for the agent: full rows if small, stats if large.

    For series <= DATA_INJECT_THRESHOLD: a compact text table of the rows.
    For larger series: per-column min/max/mean (numeric) or distinct count +
    samples (string).

    Rows of a curated-only dataset are withheld: the agent must not
    interpret them, so it does not receive them.
    """
    if is_curated_only(getattr(chart, "dataset_id", None)):
        return f"  {CURATED_ONLY_DATA_WITHHELD}"
    data = chart.chart_data or []
    if not data:
        return await t("analyst.chart_data_none", language)

    rows_n = len(data)
    # Collect columns in first-seen order, skipping meta-columns.
    col_names = list(
        dict.fromkeys(
            k for row in data for k in row if k not in DATA_SKIP_COLUMNS
        )
    )
    if not col_names:
        return await t("analyst.chart_data_meta_only", language, rows=rows_n)

    if rows_n <= DATA_INJECT_THRESHOLD:
        # Small: render full table, but fall back to stats if it would be
        # too large (many columns or long values).
        header = await t(
            "analyst.chart_data_table_header",
            language,
            rows=rows_n,
            cols=len(col_names),
        )
        lines = [f"  {header}"]
        # Header.
        lines.append(f"    {''.join(f'{c:<18}' for c in col_names)}")
        for row in data:
            cells = [
                str(row.get(c, ""))[:16] if row.get(c) is not None else ""
                for c in col_names
            ]
            lines.append(f"    {''.join(f'{v:<18}' for v in cells)}")
        table_str = "\n".join(lines)
        if len(table_str) <= DATA_TABLE_CHAR_LIMIT:
            return table_str
        # Table too wide — fall through to stats.

    # Large: per-column stats.
    stats_header = await t(
        "analyst.chart_data_stats_header", language, rows=rows_n
    )
    lines = [f"  {stats_header}"]
    for col in col_names:
        values = [row.get(col) for row in data]
        nums = [
            v for v in values if isinstance(v, (int, float)) and v is not None
        ]
        if nums:
            stats = await format_numeric_stats(nums, language)
            lines.append(f"    {col}: {stats}")
        else:
            # dict.fromkeys preserves first-seen order (unlike set()), so
            # samples are stable across runs.
            distinct = list(
                dict.fromkeys(str(v) for v in values if v is not None)
            )
            samples = distinct[:4]
            samples_str = (
                ", ".join(samples) + "..." if len(distinct) > 4 else ""
            )
            distinct_str = await t(
                "analyst.chart_data_distinct",
                language,
                count=len(distinct),
                samples=samples_str,
            )
            lines.append(f"    {col}: {distinct_str}")
    return "\n".join(lines)
