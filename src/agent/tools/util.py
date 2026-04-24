from datetime import date
from typing import Optional

from src.agent.tools.datasets_config import DATASETS


async def revise_date_range(
    start_date: Optional[str], end_date: Optional[str], dataset_id: int
) -> tuple[str, str, bool]:
    """
    Revise the input date range to the dataset's available range
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

    if start_date is None:
        start_date = ds_start_original
    if end_date is None:
        end_date = ds_end_original
    
    if ds_original.get("content_date_fixed"):
        effective_start = ds_start_original
        effective_end = ds_end_original
    else:
        effective_start = max(start_date, ds_start_original)
        effective_end = min(end_date, ds_end_original)

    range_clamped = effective_start != start_date or effective_end != end_date

    return effective_start, effective_end, range_clamped
