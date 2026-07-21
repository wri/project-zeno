from datetime import date
from typing import Optional

from src.agent.datasets.config import DATASETS


async def revise_date_range(
    start_date: Optional[str],
    end_date: Optional[str],
    dataset_id: int,
    context_layer: Optional[str] = None,
) -> tuple[str, str, bool]:
    """
    Revise the input date range to the dataset/context layer's available range.

    When no dates are provided and the dataset opts in via
    `default_to_latest_year` (sparse, discrete snapshot years rather than a
    continuous annual series — e.g. Global land cover's 2015/2024 snapshots),
    default to just the latest available year instead of the full span. Every
    other dataset (including continuous annual series) uses the full available
    range as before, whether or not `content_date_fixed` is set.
    """
    ds_original = next(
        (ds for ds in DATASETS if ds["dataset_id"] == dataset_id),
        None,
    )
    if not ds_original:
        raise ValueError(f"Dataset not found: {dataset_id}")

    ds_start_original: Optional[str] = ds_original.get("start_date")
    ds_end_original: Optional[str] = ds_original.get("end_date")
    if ds_end_original is None:
        ds_end_original = str(
            date.today()
        )  # e.g. DIST-ALERT: ongoing, no fixed end
    if ds_start_original is None:
        raise ValueError(f"Dataset {dataset_id} has no start_date configured")

    available_start: str = ds_start_original
    available_end: str = ds_end_original

    if context_layer:
        selected_context_layer = next(
            (
                layer
                for layer in ds_original.get("context_layers") or []
                if layer.get("value") == context_layer
            ),
            None,
        )

        if selected_context_layer:
            layer_start: str = (
                selected_context_layer.get("start_date") or ds_start_original
            )
            layer_end: str = (
                selected_context_layer.get("end_date") or ds_end_original
            )
            available_start = max(ds_start_original, layer_start)
            available_end = min(ds_end_original, layer_end)

    # When no dates are given and the dataset explicitly opts in, narrow to
    # the latest available year instead of the full span (see docstring).
    # range_clamped stays False because the user didn't provide dates to clamp.
    if (
        start_date is None
        and end_date is None
        and ds_original.get("default_to_latest_year")
    ):
        end_year = available_end[:4]
        effective_start = f"{end_year}-01-01"
        effective_end = f"{end_year}-12-31"
        return (
            max(effective_start, available_start),
            min(effective_end, available_end),
            False,
        )

    if start_date is None:
        start_date = available_start
    if end_date is None:
        end_date = available_end

    if ds_original.get("content_date_fixed"):
        effective_start = available_start
        effective_end = available_end
    else:
        effective_start = max(start_date, available_start)
        effective_end = min(end_date, available_end)

    range_clamped = effective_start != start_date or effective_end != end_date

    return effective_start, effective_end, range_clamped
