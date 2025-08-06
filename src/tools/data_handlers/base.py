"""
Base classes and shared components for data handlers.

This module contains the abstract base classes and shared utilities
that are used by both the orchestrator and individual handlers,
preventing circular imports.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List

from pydantic import BaseModel

DATASET_NAMES = {
    "Tree cover loss": "tree_cover_loss",
    "DIST-ALERT": "DIST-ALERT",
    "Natural lands": "natural_lands",
    "Grasslands": "grasslands",
    "Land cover change": "land_cover_change",
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
