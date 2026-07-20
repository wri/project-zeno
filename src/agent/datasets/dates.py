import re
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

    When no dates are provided and the dataset's content_date describes a
    multi-year range (e.g. "2015-2024"), default to just the end year instead
    of the full span. For datasets with a single content year or ongoing data,
    the full available range is used as before.
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

    # When user provided no dates and content_date is a multi-year range
    # (e.g. "2015-2024"), narrow to the end year instead of the full span.
    # range_clamped stays False because the user didn't provide dates to clamp.
    if start_date is None and end_date is None:
        content_date = ds_original.get("content_date")
        if content_date:
            years = re.findall(r"\b(?:19|20)\d{2}\b", str(content_date))
            if len(years) >= 2:
                end_year = years[-1]
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
