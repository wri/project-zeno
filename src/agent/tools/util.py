from datetime import date
from typing import Optional

from src.agent.tools.datasets_config import DATASETS


async def revise_date_range(
    start_date: Optional[str],
    end_date: Optional[str],
    dataset_id: int,
    context_layer: Optional[str] = None,
) -> tuple[str, str, bool]:
    """
    Revise the input date range to the dataset/context layer's available range.
    """
    ds_original = next(
        (ds for ds in DATASETS if ds["dataset_id"] == dataset_id),
        None,
    )
    if not ds_original:
        raise ValueError(f"Dataset not found: {dataset_id}")

    ds_start_original = ds_original.get("start_date")
    ds_end_original = ds_original.get("end_date")
    if ds_end_original is None:
        ds_end_original = str(
            date.today()
        )  # e.g. DIST-ALERT: ongoing, no fixed end

    available_start = ds_start_original
    available_end = ds_end_original

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
            layer_start = (
                selected_context_layer.get("start_date") or ds_start_original
            )
            layer_end = (
                selected_context_layer.get("end_date") or ds_end_original
            )
            available_start = max(ds_start_original, layer_start)
            available_end = min(ds_end_original, layer_end)

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
