"""
Base classes and shared components for data handlers.

This module contains the abstract base classes and shared utilities
that are used by both the orchestrator and individual handlers,
preventing circular imports.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List

from pydantic import BaseModel

TN_TCL = "tree_cover_loss"
TN_DIST_ALERT = "DIST-ALERT"
TN_NATURAL_LANDS = "natural_lands"
TN_GRASSLANDS = "grasslands"
TN_LAND_COVER_CHANGE = "land_cover_change"

DS_TCL = "Tree cover loss"
DS_DIST_ALERT = "Ecosystem disturbance alerts"
DS_NATURAL_LANDS = "Natural lands"
DS_GRASSLANDS = "Grassland"
DS_LAND_COVER_CHANGE = "Global land cover"

DATASET_NAMES = {
    DS_TCL: TN_TCL,
    DS_DIST_ALERT: TN_DIST_ALERT,
    DS_NATURAL_LANDS: TN_NATURAL_LANDS,
    DS_GRASSLANDS: TN_GRASSLANDS,
    DS_LAND_COVER_CHANGE: TN_LAND_COVER_CHANGE,
}


class DataPullResult(BaseModel):
    """Result of a data pull operation"""

    success: bool
    data: Any
    message: str
    data_points_count: int = 0


class DataSourceHandler(ABC):
    """Abstract base class for data source handlers"""

    @abstractmethod
    def can_handle(self, dataset: Any, table_name: str) -> bool:
        """Check if this handler can process the given dataset and table"""
        pass

    @abstractmethod
    def pull_data(
        self,
        query: str,
        aoi: Dict,
        subregion_aois: List[Dict],
        subregion: str,
        subtype: str,
        dataset: Dict,
        start_date: str,
        end_date: str,
    ) -> DataPullResult:
        """Pull data from the source"""
        pass
