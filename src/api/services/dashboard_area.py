from typing import Optional

from src.api.data_models import DashboardOrm


def dashboard_aoi(dashboard: DashboardOrm) -> Optional[dict]:
    """The area a dashboard covers: its first AOI. Portfolios are not in
    v1."""
    if not dashboard.aois:
        return None
    aoi = min(dashboard.aois, key=lambda a: a.position)
    return {
        "source": aoi.source,
        "src_id": aoi.src_id,
        "subtype": aoi.subtype,
        "name": aoi.name,
    }
